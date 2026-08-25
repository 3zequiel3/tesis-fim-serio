# Cambios de código — Bloque A (A.1, A.2, A.3)

Rama base: `devel` · Commit revisado: `075427c`

Este documento cubre **solo lo que hay que tocar en el repositorio**. Las
correcciones de redacción del documento de tesis van por separado.

---

## A.1 — Anti-replay: NO TOCAR NADA

**El código ya está correcto.** El cambio D37 / RN-131 dejó la ventana de
`clock_skew` sobre `sent_at` y sacó a `detected_at` de toda ventana. Es
exactamente lo que hacía falta.

Referencias, por si alguien duda:

- `backend/app/modules/events/consumer.py:283-341` — la ventana se evalúa
  sobre `sent_at`; `detected_at` solo debe ser parseable.
- `agent/publisher.py:229-233` — `sent_at` se sella justo antes de cada
  transmisión y queda cubierto por el HMAC.
- `backend/tests/test_stream_ack_durability_consumer.py:5` — caso 14.1,
  "detected_at viejo + sent_at reciente se acepta".

**Lo que estaba mal era el §4.5 de la tesis**, que describe la RN-90 anterior
a la enmienda. Es corrección documental pura. **No hay que re-ejecutar la
Batería 5**: sus números son coherentes con este código.

> Si alguien propone agregar un contador de secuencia monotónico por agente:
> no hace falta. La combinación HMAC sobre `sent_at` + ventana de tránsito +
> dedup por `event_id` ya cubre el vector.

---

## A.2 — Atribución de proceso: el `uid = 0` silencioso

### El problema

`agent/detector.py:98`

```python
def _get_uid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0          # ← BUG
```

El caso de fallo es que el proceso causante ya terminó (vida breve, que es el
perfil adversario). El sistema atribuye entonces el evento a **uid 0 = root**.
Un evento sin atribución posible queda registrado como si lo hubiera causado
el usuario más privilegiado del anfitrión. Es una atribución falsa, no una
imprecisión.

### Los cambios

**1. `agent/detector.py:98` — `_get_uid` devuelve `None` en el fallo**

```python
def _get_uid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None
```

(`_get_exe` ya devuelve `None` correctamente — no se toca.)

**2. `agent/detector.py:55` — tipo en la dataclass `FanotifyEvent`**

```python
uid: int | None
```

**3. `agent/detector.py:72` — tipo en la dataclass `DetectedChange`**

```python
process_uid: int | None
```

**4. `agent/decision.py:151` — payload de rehidratación del journal**

```python
"process_uid": None,      # antes: 0
"process_exe": None,      # ya estaba bien
```

En ese camino el proceso original no existe por definición (se rehidrata al
arrancar), así que `None` es el valor correcto, no `0`.

### Lo que NO hay que tocar

- **Backend**: `Event.process_uid` ya es `int | None`
  (`backend/app/modules/events/models.py:58`). **No hace falta migración.**
- **Frontend**: ya maneja el nulo en los tres puntos donde muestra atribución
  (`EventsTable.tsx:30-36`, `EventDetail.tsx:199-218`). No se toca.

### Tests

Hay 47 apariciones de `uid=0` / `process_uid=0` en `agent/tests/`. **La gran
mayoría son fixtures que construyen eventos de un proceso root real y siguen
siendo válidas** — no las cambien en masa.

**Corrección: la lista de tests que estaba acá era incorrecta.** Los tres archivos
que se listaban —`test_decision.py:73`, `test_restore_metadata.py:77`,
`test_symlink_hardening.py:565`— **no** cubren el camino de rehidratación. Son
helpers tipo `_make_change()` que devuelven un `MagicMock` con `process_pid: 100`
(un proceso real) y cuyo `to_event_data()` alimenta `engine.evaluate_and_act()`.
Ninguno pasa jamás por `engine.rehydrate()`. Son exactamente las fixtures que este
mismo apartado dice **no** tocar. Dejarlos como están.

Los tests que sí ejercen `rehydrate()` son `test_rehydrate_action_error_propagates`
(`test_decision.py:220`), `test_rehydrate_auto_restore_pending` (:364),
`test_rehydrate_manual_review_pending` (:399) y `test_rehydrate_no_pending` (:419).
Construyen el estado vía `journal.write_pending(...)` y **ninguno assertea nada
sobre `process_uid`**.

Consecuencia práctica: si se cambia `decision.py:151` a `None` tal como se propone,
**ningún test existente detectaría una regresión**. Lo que hay que hacer es agregar
la aserción que falta a uno de esos cuatro, p. ej. en
`test_rehydrate_auto_restore_pending`:

```python
assert payload["process_uid"] is None
```

**Test nuevo a agregar** (es el que sostiene la afirmación de la tesis):

```
_get_uid sobre un pid inexistente devuelve None, no 0
```

Sin ese test, la frase del §2.6 que dice que el agente "no sustituye el dato
ausente por un valor por defecto" no tiene respaldo verificable.

### Regla de negocio

Hay que dar de alta o enmendar la regla del catálogo que cubre la atribución
de proceso, para que diga que la no-resolución se registra como ausencia. El
identificador tiene que quedar citado en el código y en el test, según la
cadena de tres eslabones del §3.8.

---

## A.2 bis — Los docstrings fantasma de `pyfanotify`

**Prioridad alta, esfuerzo nulo.** El §2.6 de la tesis dedica tres párrafos a
justificar por qué se descartó `pyfanotify`, y el §6.2 pone el binding propio
como **primera contribución original del trabajo**. Pero `agent/detector.py`
tiene cinco referencias residuales:

| Línea | Texto actual |
|-------|--------------|
| 2   | `Detector reactivo de cambios en el filesystem usando pyfanotify (C09, ...)` |
| 52  | `"""Evento raw recibido de pyfanotify (interno al detector)."""` |
| 242 | `Corre un hilo daemon que lee eventos pyfanotify (bloqueante) y los ...` |
| 279 | `"pyfanotify no disponible — requiere Linux con CAP_SYS_ADMIN"` |
| 363 | `"""Lee eventos de pyfanotify (bloqueante). Retorna lista de eventos."""` |

`agent/requirements.txt:6` aclara correctamente que no se depende de
`pyfanotify`, y el import real es `from agent import _fanotify as _fan_mod`.
Son docstrings viejos nomás.

Cambiar las cinco por referencias al binding propio (`agent/_fanotify.py`).
El A.7 nos obliga a invitar al jurado a abrir el repo, y lo primero que se lee
al abrir `detector.py` contradice hoy la contribución más destacada de la tesis.

---

## A.3 — Evasión por escritura mapeada en memoria

### Contexto para entender el cambio

`agent/detector.py:293` — la máscara registrada es:

```python
FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE
```

No hay `FAN_MODIFY`. La detección de modificación de contenido se dispara al
cerrar un descriptor abierto para escritura, y el hash se computa ahí.
`FAN_CLOSE_WRITE` se emite al cerrar, **haya habido escritura o no**. Por lo
tanto:

```c
fd = open(path, O_RDWR);
addr = mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
close(fd);              // CLOSE_WRITE se emite acá, sin modificación
memcpy(addr, evil, n);  // la modificación real: ningún evento
msync(...); munmap(...);
```

El agente hashea contenido íntegro, concluye que no hay violación, y lo que
viene después es invisible. La evasión ocurre **de forma consistente** bajo ese
orden. Si el descriptor se cierra *después* de escribir sobre el mapeo, sí se detecta.

> **No decir "determinística".** El desenlace del caso A depende de una carrera
> entre la secuencia in-process (escribir sobre el mapeo → `msync` → `munmap`, sin
> syscalls de por medio) y el pipeline cross-thread del agente (hilo lector de
> fanotify → `call_soon_threadsafe` → `asyncio.Queue` → hash asincrónico,
> `agent/detector.py:265,400-406,769-778`). La batería no mide ese margen. La
> afirmación defendible es "consistente en las N repeticiones"; "determinística"
> es una afirmación más fuerte que no se puede sostener si la piden en sala.

> **No agregar `FAN_MODIFY` a la máscara pensando que resuelve esto.** El
> núcleo tampoco lo emite para escrituras sobre mapeos. No arregla nada y
> agrega ruido de eventos.

### Cambio 1 — agregar el script de la Batería 8

> **Numeración: es la 8, no la 7.** `docs/plan_medicion_cap5.md:380` ya usa
> "Batería 7" para el grupo de control, y `scripts/control_hashing.py:5,310`
> escribe `bateria7_control.csv`. Correr esta batería con el número 7 pisaría el
> directorio de salida del grupo de control. Además, la tesis dice "seis baterías
> secuenciales" en §3.7 cuando el plan interno ya tiene siete: con esta van ocho,
> y ese número hay que actualizarlo en el §3.7.

Archivos nuevos, ya en el repo: `scripts/bateria_mmap.py` (la batería) y
`scripts/analisis_mmap.py` (el correlacionador contra la tabla `events`).

Ejercita tres casos, 10 repeticiones cada uno por defecto:

| Caso | Orden de operaciones | Eventos emitidos | Detección |
|------|----------------------|------------------|-----------|
| A | `open → mmap → close(fd) → escribir → msync → munmap` | 1 (`CLOSE_WRITE`) | **ninguna** (evasión) |
| B | `open → mmap → escribir → msync → munmap → close(fd)` | 1 | 1 |
| C | `open/write/close` convencional, sin mapeo | 1 | 1 |

> **Las dos columnas van separadas a propósito.** En el caso A el agente **sí
> emite** un evento —el `CLOSE_WRITE` del descriptor— pero con el hash del
> contenido todavía íntegro. Contar eventos a secas da "detectado" y es falso: el
> evento existe, la detección de la modificación no. Por eso `analisis_mmap.py`
> exige que `hash_detected` coincida con `hash_despues` y clasifica en tres
> estados: `detectada`, `evento_sin_cambio` (esta es la evasión, y es el hallazgo
> fino) y `sin_evento`.

Emite `bateria8_cambios.jsonl` y `bateria8_manifiesto.json` con el mismo
esquema de campos que `generador_carga.py`, para reutilizar el correlacionador
contra la tabla `events` sin tocarlo.

**El caso C es el testigo de validez de la corrida.** Si C no produce eventos,
el resultado de A no prueba evasión: prueba que el agente no estaba mirando ese
directorio. Sin ese control la batería no vale.

Uso:

```bash
# 1. Correr la batería contra el laboratorio, con el agente andando
sudo ./scripts/bateria_mmap.py \
    --dir /var/fim-lab \
    --agent-prefix /var/fim-lab \
    --repeticiones 10 \
    --salida ./resultados/bateria8

# 2. Esperar ~30 s a que drene la ingesta

# 3. Cruzar contra la tabla events
export DATABASE_URL='postgresql://fim:...@localhost:5432/fim'
python3 scripts/analisis_mmap.py \
    --jsonl resultados/bateria8/bateria8_cambios.jsonl \
    --salida resultados/bateria8/bateria8_correlacion.csv
```

**Corte de validez.** Si el caso C no detecta 10/10, `analisis_mmap.py` devuelve
código 1 y avisa que la corrida no vale. Un cero en el caso A no prueba evasión
mientras el testigo no dé 100 %: prueba que el agente no estaba mirando. No
reportar la Tabla 17 si ese chequeo falla.

### Cambio 2 — decidir qué hacer con `run_scan` (decisión, no tarea)

`agent/baseline.py:481` — `run_scan` **sobreescribe (upsert)** cualquier entry
existente sin comparar contra la baseline vigente ni emitir eventos. Y
`rescan_baseline` es el único camino que podría sacar a la superficie una
modificación por mapeo, porque no hay re-escaneo periódico.

Resultado: el único mecanismo que detectaría la evasión, la **incorpora como
estado legítimo**.

Dos opciones, hay que elegir una y documentarla:

1. **Dejarlo como está** y declarar el comportamiento en la tesis (§4.3 o
   §6.6): `rescan_baseline` es una operación de re-línea-base explícita y
   deliberada, no un control de detección. Costo: cero.
2. **Hacer que `run_scan` compare antes de sobreescribir** y emita evento por
   cada divergencia encontrada. Es lo correcto de seguridad y convierte el
   comando en un control real, pero es trabajo y toca el flujo de comandos.

Mi lectura: si el tiempo aprieta, la opción 1 es defendible siempre que esté
declarada. Lo indefendible es que no esté escrito en ningún lado.

---

## Bonus — hallazgos sueltos que conviene anotar

- **`§5.6.3` no existe.** La tesis lo referencia cuatro veces (§6.1, §6.6,
  §7.6 y §8) para remitir a que la caída de Valkey inhabilita toda la
  superficie autenticada del backend. El apartado 5.6 solo tiene 5.6.1. O se
  escribe ese subapartado o se redirigen las cuatro referencias. (Documental,
  no de código, pero afecta a quien escriba el Cap. 5.)

- **`docs/dataset_cap5.md`, sección "Salvedades", punto 1.** El análisis de
  los 7 falsos negativos que está ahí es mejor que el que quedó en el
  Capítulo 5 y hay que subirlo a la tesis: la hipótesis de "reversión al
  contenido previo" queda contradicha por la Batería 5 (210 cambios repiten
  hash previo pero solo 12 quedaron sin evento). **`mmap` no explica los 7**:
  `generador_carga.py:339` escribe con un solo `open/write/close`, y no hay
  `mmap` en ningún lado del repo. Los 7 siguen sin explicación verificada y
  así hay que reportarlos.

---

- **`FAN_Q_OVERFLOW` no se maneja en ningún lado.** El plan de correcciones pide
  (M-17) "corregir el adjetivo *silenciosa*" porque el núcleo emite
  `FAN_Q_OVERFLOW`. Está al revés: el adjetivo es correcto. La constante `0x4000`
  no está definida en `agent/_fanotify.py` ni se chequea en `_parse_events`
  (`agent/_fanotify.py:241-258`). El contador `_event_drops`
  (`agent/detector.py:402-411`, expuesto en el heartbeat) mide la `asyncio.Queue`
  interna, que es un punto de pérdida **posterior**: el evento ya salió del núcleo.
  Lo que hay que corregir es la otra mitad de la frase de la tesis, la que afirma
  que el agente detecta la condición. Hoy no la detecta.

- **`docs/arquitectura_stack.md:1509` etiqueta mal `queue_pressure`.** Dice que el
  agente "monitorea activamente el nivel de backpressure [de `fanotify`] y lo
  reporta como anomalía en el heartbeat (`queue_pressure`)". Pero `queue_pressure`
  es la **cola de disco offline** de 100 MB (`agent/queue.py:1-27`,
  `agent/heartbeat.py:100`), que no tiene relación con la saturación de fanotify.
  El doc canónico afirma una capacidad que el código no tiene.

---

## Orden sugerido

1. Docstrings de `pyfanotify` (5 min, sin riesgo).
2. `_get_uid` → `None` + tipos + `decision.py` + **el assert que falta** (medio día).
   Ver la sección **Tests** más arriba: los tres archivos que se listaban no
   cubren el camino de rehidratación y no hay que tocarlos; falta el assert.
3. Correr la Batería 8 contra el laboratorio (los scripts ya están en `scripts/`).
4. Decidir lo de `run_scan` y dejarlo escrito.
5. A.7: **sacar `resultados/` del `.gitignore`** (línea 46). Los datos crudos de
   las baterías ya existen ahí —CSV por evento, manifiestos JSONL, `.pcap`,
   `.strace`— y los agregados de `docs/dataset_cap5.md` se recomputan exacto
   contra ellos. El problema no es que falten: es que un tercero que clona el
   repo no recibe ninguno. Con la Batería 8 son ocho baterías, no siete.
