## Context

El agente restaura archivos por dos caminos que comparten la misma secuencia de escritura atómica:

| Camino | Sitio | Disparador | Canal de la falla |
|---|---|---|---|
| Automático | `DecisionEngine._auto_restore` (`agent/decision.py:226`) | regla `auto_restore`; también la rehidratación del journal (`:176`) | evento con `action_failed` + `action_error` |
| Operador | `handle_restore_file` (`agent/commands.py:300`) | comando firmado `restore_file` | `event_ack` con `status=error` + `error` |

Ambos abren `<path>.fim_restore_tmp` con `O_EXCL` (`decision.py:261`, `commands.py:371`),
escriben con `os.write` descartando el valor de retorno (`decision.py:266`, `commands.py:376`),
hacen `fsync`, `fchown` y `fchmod` sobre el descriptor (D36/RN-130), y reemplazan con `os.replace`
(`decision.py:287`, `commands.py:392`). La duplicación es deliberada y está documentada
(`commands.py:340-343`; spec `agent-approve-reject-handler`, requisito «An operator-initiated
restore does not report its own write as a detection»).

Después del reemplazo, los dos caminos «verifican» así:

```python
restored_hash = _hash_bytes(content)            # decision.py:295
if expected_hash and restored_hash != expected_hash:
    raise _ActionFailed("hash_mismatch_after_restore")
```

`content` es el buffer que se acaba de escribir. La comprobación no observa el disco, así que el
único caso que detecta es que el baseline guarde contenido y hash inconsistentes entre sí; una
escritura corta, un `fsync` que miente o una sobrescritura concurrente pasan como éxito. Con
`expected_hash` vacío —`select_restorable_content` (`agent/baseline.py:218`) devuelve
`entry.hash or ""`— ni siquiera eso se compara.

Restricciones relevantes:

- **D81/RN-175** (`docs/arquitectura_stack.md:2721`, `docs/reglas_de_negocio.md:2717-2725`, en su
  versión de `7306ecc`): helper único compartido, relectura con `O_NOFOLLOW` tras `os.replace`,
  comparación contra el hash esperado o, sin él, contra el de los bytes escritos; `OSError` →
  `verify_failed`; hash distinto → `hash_mismatch_after_restore`.
- **D36/RN-130**: vocabulario cerrado de causas, sin interpolar path ni mensaje del sistema
  operativo; orden `fchown`→`fchmod`; `O_EXCL` del temporal. Nada de eso cambia.
- **Detector**: la máscara de fanotify se arma con `FAN_CLOSE_WRITE` y eventos de entradas de
  directorio (`agent/detector.py:466`, `:508`); no incluye `FAN_OPEN`, `FAN_ACCESS` ni
  `FAN_CLOSE_NOWRITE`. Una apertura de sólo lectura del agente no produce eventos.
- El backend persiste `action_error` sin validar contra enum (`008_add_event_action_error.sql`) y
  el frontend muestra un literal desconocido tal cual (`frontend/src/utils/actionError.ts`).

## Goals / Non-Goals

**Goals:**

- Que la verificación posterior a la restauración observe el archivo en disco en los dos caminos.
- Que la lógica de verificación exista una sola vez.
- Que una escritura truncada, una sobrescritura posterior al reemplazo y un symlink en el path
  restaurado se reporten como falla, con un test por caso en cada camino donde aplique.
- Que la verificación no se omita cuando el baseline no tiene hash esperado.
- Retirar el residual §1 de `docs/residuales_declarados.md`.

**Non-Goals:**

- **Unificar la secuencia de escritura** (temporal, `fsync`, `fchown`/`fchmod`, `os.replace`) de
  los dos caminos. D81 pide un helper de verificación, no de escritura; la duplicación de la
  escritura está documentada y protegida por un test, y la unificación de los caminos de acción es
  materia de la Change 64 para la cuarentena.
- **Tratar las escrituras cortas** con un bucle sobre `os.write`. La verificación es el mecanismo
  que las detecta; corregirlas en origen cambiaría el camino de escritura y haría inobservable el
  caso que el test obligatorio provoca. Queda como observación en Open Questions.
- **Revertir o reintentar** ante una falla de verificación. El archivo queda como quedó y la falla
  se reporta, igual que hoy con `hash_mismatch_after_restore`
  (`docs/implementaciones/cuarentena-y-diff-arreglos-como-implementar.md:403`).
- **Etiqueta legible de `verify_failed` en el frontend.** Fuera de alcance por decisión del
  coordinador; el fallback del mapper la muestra como `Causa: verify_failed`.
- Cambios en backend, base de datos o contrato de streams.

## Decisions

### D-1 — El helper vive en `agent/decision.py` y devuelve un literal, no lanza

Firma propuesta:

```python
def verify_restored_file(path: str, written: bytes, expected_hash: str) -> str | None
```

Devuelve `None` si la verificación pasa, o `"verify_failed"` / `"hash_mismatch_after_restore"`.
Cada caller traduce el literal a su propio mecanismo de falla: `_auto_restore` lanza
`_ActionFailed(err)`, `handle_restore_file` lanza `ValueError(err)` (su `except Exception`
convierte `str(exc)` en la razón del journal y del ack, `commands.py:407-409`).

**Por qué en `decision.py`:** es donde ya viven las otras dos funciones puras que comparten los dos
caminos (`parse_baseline_mode`, `action_error_from_oserror`), y `commands.py` ya las importa en
`:348`. Un módulo nuevo para una función agregaría una superficie de import sin beneficio.

**Por qué devolver y no lanzar:** los dos caminos tienen excepciones distintas y ninguna de las dos
es pública en el otro módulo. Hacer que el helper lance `_ActionFailed` obligaría a
`commands.py` a importar un tipo privado y a reenvolver; devolver el literal mantiene al helper
puro y testeable sin depender de ninguno de los dos callers.

**Alternativa descartada:** un helper `restore_atomically(path, content, uid, gid, mode, expected)`
que absorba escritura, reemplazo y verificación. Elimina la duplicación entera, pero excede D81 y
choca con la Change 64, que reorganiza los caminos de acción del agente.

### D-2 — Relectura por descriptor con `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`, hash por bloques

El helper abre el path con `os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)`, lee en
bloques de tamaño fijo (por ejemplo 1 MiB) alimentando `hashlib.sha256` y cierra el descriptor en
un `finally`.

- **`O_NOFOLLOW`** (D81): si entre `os.replace` y la relectura alguien reemplaza el path por un
  symlink, la apertura falla con `ELOOP` y eso es `verify_failed`. Sin el flag, la verificación
  podría leer un archivo arbitrario que casualmente coincida con el baseline y declarar éxito sobre
  un path que no contiene lo restaurado.
- **Por bloques**: el contenido ya está en memoria y su tamaño está acotado por el baseline, así
  que leer el archivo entero no sería un problema de memoria; leer por bloques evita duplicar el
  pico y no cuesta complejidad.
- **`O_CLOEXEC`**: higiene; el agente no hace `fork`/`exec` en este camino, pero no hay motivo para
  heredar el descriptor.

**Alternativa descartada:** verificar por el descriptor del temporal antes de `os.replace`. Prueba
que el temporal es correcto, pero no lo que quedó en el path final, que es lo que D81 exige.

### D-3 — Sin hash esperado, se compara contra el hash de los bytes escritos

`expected = expected_hash or _hash_bytes(written)`. La relectura se compara siempre contra algo.

Con hash esperado presente, el helper compara contra él y no contra `written`: así un baseline cuyo
contenido no coincide con su propio hash sigue fallando con `hash_mismatch_after_restore`, como
hoy (lo fija `test_decision_auto_restore_hash_mismatch`, `agent/tests/test_decision.py:140`).

Comparar el disco contra el hash de `written` **no** es la tautología que RN-175 prohíbe: la
tautología es comparar el buffer consigo mismo; acá una de las dos partes viene del disco.

### D-4 — `OSError` en la relectura → `verify_failed`, sin `action_error_from_oserror`

Cualquier `OSError` en `os.open` o `os.read` del helper produce `verify_failed`, también `EACCES`,
`EPERM` y `EROFS`. `action_error_from_oserror` (`agent/decision.py:56-69`) clasifica fallas de
**escritura** como barreras de despliegue; en la relectura la escritura ya tuvo éxito, y
reportarla como `permission_denied` o `read_only_mount` llevaría al operador a corregir un
despliegue que no está roto. El `errno` va al log estructurado (`restore.verify_failed`, con
`errno` y el path como campos), nunca a la causa publicada.

### D-5 — `verify_failed` se agrega a la lista cerrada de la spec

El requisito «Action failures carry a closed-vocabulary cause…» de `agent-decision-engine`
enumera la lista cerrada; se modifica para incluir `verify_failed` y para declarar que la relectura
no pasa por el mapeo de errores de escritura. No se toca backend ni migraciones: la columna
`action_error` es `VARCHAR(64)` sin restricción de enum por diseño.

### D-6 — El residual §1 se elimina sin renumerar

`docs/residuales_declarados.md` §1 se elimina entero. Las entradas restantes conservan su número:
§9 se cita por número desde `CHANGES.md` (Change 64), D82/RN-176 y
`tesis/cierre/PARA_LA_V22_estado_real.md:108`, y renumerar rompería esas referencias. Si el
documento necesita indicarlo, se agrega una línea en su introducción explicando que las entradas
retiradas se eliminan sin renumerar.

### D-7 — Tests: monkeypatch acotado de `os.write`, y casos post-reemplazo por envoltura de `os.replace`

- **Escritura truncada (obligatorio):** `monkeypatch.setattr(os, "write", half_write)` donde
  `half_write(fd, data)` escribe `data[: len(data) // 2]` y devuelve esa longitud **sólo cuando
  `data` es el contenido del baseline**, y delega en el `os.write` original en cualquier otro caso
  —para no afectar escrituras del journal ni del logging—. Se espera
  `_ActionFailed("hash_mismatch_after_restore")` en `_auto_restore` (y el literal en el payload y el
  journal vía `evaluate_and_act`), y `error="hash_mismatch_after_restore"` en el ack de
  `handle_restore_file`.
- **Alteración tras el reemplazo:** se envuelve `os.replace` para que, después del reemplazo real,
  sobrescriba el path con otros bytes. Esperado: `hash_mismatch_after_restore`.
- **Symlink tras el reemplazo:** la envoltura de `os.replace` sustituye el path por un symlink a un
  archivo con el contenido correcto. Esperado: `verify_failed`.
- **`OSError` en la relectura:** se envuelve `os.open` para que levante `OSError(errno.EIO, ...)`
  sólo cuando las flags incluyen `O_NOFOLLOW` y no `O_WRONLY` (la apertura de verificación), y con
  `errno.EACCES` en un segundo caso para fijar que no se mapea a `permission_denied`.
- **Sin hash esperado:** entry con `hash=None` más escritura truncada → `hash_mismatch_after_restore`;
  entry con `hash=None` sin truncar → éxito.
- **Unitarios del helper:** archivo correcto → `None`; contenido distinto → mismatch; path
  inexistente → `verify_failed`; symlink → `verify_failed`.

## Risks / Trade-offs

- **[Falso negativo por concurrencia legítima]** Un proceso del host que escriba el path justo
  después de `os.replace` hace fallar la verificación aunque la restauración en sí haya sido
  correcta. → Es el comportamiento correcto: el archivo en disco no es el baseline y el agente no
  debe afirmar lo contrario. La modificación concurrente además produce su propio evento por el
  detector.
- **[Costo de lectura]** Una lectura completa adicional por restauración. → Acotada por el tamaño
  del contenido restaurable que el baseline guarda; la restauración no es un camino caliente en
  frecuencia.
- **[Divergencia futura de los dos caminos de escritura]** El helper unifica sólo la verificación.
  → La spec del handler ya exige un test que fija la equivalencia de la escritura; esta change
  agrega tests de verificación sobre ambos caminos.
- **[Monkeypatch global de `os.write`]** Un parche sobre el módulo `os` afecta a todo el proceso de
  test. → La envoltura sólo trunca cuando `data` es el contenido del fixture y delega en el resto.
- **[Literal nuevo sin etiqueta en la UI]** El operador ve `Causa: verify_failed` sin texto
  explicativo. → Fallback ya previsto por el mapper; la etiqueta queda fuera de alcance por
  decisión explícita.

## Migration Plan

Sin migración de datos ni de esquema. El cambio se despliega con el código del agente; un agente
anterior nunca emite `verify_failed` y un backend o frontend anterior lo aceptan y muestran como
literal. Rollback: revertir el commit del agente; no deja estado persistente nuevo.

## Open Questions

- **Escrituras cortas en origen.** `os.write` sigue sin bucle de escritura completa en los dos
  caminos (`decision.py:266`, `commands.py:376`). Con esta change una escritura corta deja de
  reportarse como éxito, pero sigue produciendo un archivo truncado en disco. Corregirla en origen
  es un cambio de comportamiento del camino de escritura que D81 no cubre; si se quiere, requiere
  una decisión propia.
- **Citas de línea de D81/RN-175.** El texto cerrado cita `agent/commands.py:398-400`; en `devel`
  la comparación está en `:400-402` (`:398-399` es el `except` del `os.replace`). No cambia el
  alcance; se cita la línea vigente en los artefactos.
