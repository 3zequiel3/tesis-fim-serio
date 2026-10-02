## MODIFIED Requirements

### Requirement: Handler restore_file — restauración desde baseline con journal

El handler de `restore_file` SHALL: escribir un journal pre-acción en `/var/lib/fim-agent/journal/` antes de ejecutar; descifrar el contenido baseline del archivo indicado en `path`; sobrescribir el archivo en el filesystem con el contenido descifrado; verificar, releyendo el archivo desde disco después de `os.replace`, que su SHA-256 coincide con el hash almacenado en el baseline (o, si no lo hay, con el de los bytes escritos); escribir un journal post-acción con resultado; publicar `event_ack`.

El handler MUST verificar con el mismo helper que `DecisionEngine._auto_restore` (`agent/decision.py`), definido por el requisito «La verificación posterior a la restauración relee el archivo desde disco» de `agent-decision-engine`, y MUST NOT mantener una comparación propia. Un `OSError` en la relectura SHALL publicarse como `verify_failed` y una discrepancia como `hash_mismatch_after_restore`, los mismos literales que el camino de eventos (D81/RN-175, D36/RN-130).

#### Scenario: Restore exitoso
- **WHEN** el agente recibe `{"type": "restore_file", "path": "/etc/passwd", ...}` y existe baseline para ese path
- **THEN** el archivo en `/etc/passwd` contiene el contenido del baseline
- **AND** el SHA-256 del archivo releído desde disco coincide con el hash del baseline
- **AND** existe una entrada en el journal con `action=restore`, `status=success`
- **AND** se publicó `event_ack`

#### Scenario: Restore fallido — no existe baseline para el path
- **WHEN** el agente recibe `restore_file` para un `path` sin baseline
- **THEN** el restore no se ejecuta
- **AND** se escribe journal con `status=error` y razón `no_baseline`
- **AND** se publica `event_ack` con `status=error`

#### Scenario: Journal pre-acción escrito antes de ejecutar
- **WHEN** el handler de restore recibe el comando
- **THEN** el archivo de journal para esa acción existe en disco antes de que el archivo sea sobrescrito

#### Scenario: Restore con escritura truncada — ack de error
- **WHEN** el agente recibe un `restore_file` válido y `os.write` escribe sólo la mitad del contenido antes de un `os.replace` exitoso
- **THEN** el journal queda `failed` con razón `hash_mismatch_after_restore`
- **AND** se publica `event_ack` con `status=error` y `error="hash_mismatch_after_restore"`

#### Scenario: Restore con relectura fallida — ack de error
- **WHEN** el agente recibe un `restore_file` válido, la escritura y el `os.replace` tienen éxito y la apertura del path restaurado para verificarlo levanta `OSError`
- **THEN** el journal queda `failed` con razón `verify_failed`
- **AND** se publica `event_ack` con `status=error` y `error="verify_failed"`
