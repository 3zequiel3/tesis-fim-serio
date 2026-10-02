## Why

La única comprobación que afirma «la restauración quedó bien escrita» no puede fallar. Tras
`os.replace`, `DecisionEngine._auto_restore` calcula `restored_hash = _hash_bytes(content)`
(`agent/decision.py:295`) y compara ese hash —el del **buffer en memoria** que acaba de escribir—
contra `expected_hash` (`:296-297`). Nunca relee el archivo del disco. `handle_restore_file`
(`agent/commands.py:300`), el camino de restauración que dispara el operador mediante un comando
firmado, replica el mismo bloque de forma deliberada (`agent/commands.py:340-343`, comentario de
duplicación) y comete el mismo error en `:400-402`.

La consecuencia es que una escritura truncada, un `fsync` que falla silenciosamente, un filesystem
lleno o una modificación concurrente del path entre `os.replace` y la comprobación producen un
archivo distinto del baseline, y el agente reporta éxito igual. Es el modo de falla más caro del
agente porque miente en la dirección peligrosa: afirma que el sistema remedió cuando no lo hizo. El
caso de la escritura parcial es concreto, no teórico: el valor de retorno de `os.write`
(`agent/decision.py:266`, `agent/commands.py:376`) se descarta, de modo que una escritura corta
deja en disco un archivo truncado sin ninguna señal.

El defecto ya estaba declarado como residual en `docs/residuales_declarados.md` §1, que además cita
líneas desactualizadas (`agent/decision.py:184-186`). Esta change lo cierra.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9), verificada contra `devel`; base para
el candidato `v5.0-tesis` (Change 61). La decisión que la gobierna está cerrada: **D81/RN-175**
(`docs/arquitectura_stack.md:2721`, `docs/reglas_de_negocio.md:2717-2725`), extendida al camino del
operador en `7306ecc`. No se abre ninguna suposición nueva. Dependencias del DAG: ninguna
(`CHANGES.md:1306`).

## What Changes

- **Helper único de verificación desde disco (D81/RN-175).** Se agrega en `agent/decision.py`,
  junto a `action_error_from_oserror` y `parse_baseline_mode` —que `agent/commands.py` ya importa—,
  una función pura de verificación que, tras `os.replace`, abre el path restaurado con
  `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`, calcula su SHA-256 leyendo desde disco y lo compara contra
  el hash esperado o, si el baseline no lo tiene, contra el hash de los bytes escritos. Devuelve el
  literal de falla o nada.
- **Ambos caminos de restauración usan el helper.** `_auto_restore` (`agent/decision.py:295-297`)
  y `handle_restore_file` (`agent/commands.py:400-402`) reemplazan su comparación tautológica por la
  llamada al helper. El camino de rehidratación del journal (`agent/decision.py:176`) hereda el
  cambio porque invoca `_auto_restore`.
- **Dos causas de falla, ambas en el vocabulario cerrado.** Cualquier `OSError` en la relectura
  produce `verify_failed` —sin pasar por `action_error_from_oserror`: un `EACCES` en la relectura no
  es una barrera de despliegue sobre la escritura, que ya tuvo éxito—; un hash distinto produce
  `hash_mismatch_after_restore`, que ya existía. `verify_failed` se agrega a la lista cerrada de
  causas de la spec.
- **La verificación nunca se omite.** Hoy, con `expected_hash` vacío
  (`select_restorable_content`, `agent/baseline.py:218`, devuelve `entry.hash or ""`), la
  comparación se saltea por completo (`if expected_hash and ...`). Con esta change se compara contra
  el hash de los bytes escritos.
- **Tests de filesystem nuevos**, en ambos caminos: escritura truncada (monkeypatch de `os.write`
  que escribe la mitad) → `hash_mismatch_after_restore`; archivo corrompido después de `os.replace`
  → `hash_mismatch_after_restore`; `OSError` inyectado en la relectura → `verify_failed`; path
  convertido en symlink después de `os.replace` → `verify_failed`; baseline sin hash con escritura
  truncada → `hash_mismatch_after_restore`.
- **Se retira el residual** `docs/residuales_declarados.md` §1, sin renumerar las entradas
  restantes (§9 se cita por número desde `CHANGES.md`, D82/RN-176 y `tesis/cierre/`).

No hay cambios **BREAKING**. `verify_failed` es un literal nuevo que el backend ya persiste sin
validar contra enum (`backend/db/migrations/008_add_event_action_error.sql`,
`backend/app/modules/events/service.py:320-324`) y que el frontend muestra como literal crudo
(`frontend/src/utils/actionError.ts`, fallback de `getActionErrorMeta`).

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `agent-decision-engine`: la restauración automática verifica releyendo el archivo desde disco
  (requisito nuevo que fija el contrato del helper compartido); el requisito de `auto_restore` deja
  de describir una verificación contra `entry.hash` sin decir sobre qué bytes; la lista cerrada de
  causas de falla incorpora `verify_failed`.
- `agent-approve-reject-handler`: el handler `restore_file` verifica con el mismo helper y publica
  en el `event_ack` las mismas dos causas; se corrige la referencia obsoleta a `agent/actions.py`,
  módulo que no existe.

## Impact

- **Código del agente**: `agent/decision.py` (helper nuevo; `_auto_restore`), `agent/commands.py`
  (`handle_restore_file`).
- **Tests del agente**: `agent/tests/test_decision.py`, `agent/tests/test_commands.py` (o un
  archivo nuevo dedicado a la verificación). `test_decision_auto_restore_hash_mismatch`
  (`agent/tests/test_decision.py:140`) sigue pasando sin cambios: el hash leído del disco es el de
  los bytes escritos y sigue difiriendo del `expected_hash` incorrecto del fixture.
- **Documentación**: `docs/residuales_declarados.md` (se retira §1).
- **Sin cambios** en backend, frontend, base de datos, contrato de streams ni configuración. La
  etiqueta legible de `verify_failed` en `frontend/src/utils/actionError.ts` queda fuera de alcance
  (decisión del coordinador): el fallback del mapper muestra `Causa: verify_failed`.
- **Rendimiento**: una lectura adicional del archivo restaurado por restauración. El contenido ya
  está en memoria, de modo que el tamaño está acotado por lo que el baseline guarda; la restauración
  no es un camino de alta frecuencia.
- **Reglas y decisiones**: aplica D81/RN-175; preserva D36/RN-130 (vocabulario cerrado, orden
  `fchown`→`fchmod`, `O_EXCL` del temporal) y RN-30–33 (restauración desde baseline); RN-71 (léxico
  snake_case del literal nuevo).
- **Re-medición**: única, sobre `v5.0-tesis` (Change 61).
