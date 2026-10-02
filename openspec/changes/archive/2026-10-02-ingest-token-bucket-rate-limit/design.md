## Context

**Estado actual — el limitador.** `_RateLimiter` (`backend/app/modules/events/consumer.py:143-227`)
es un log de ventana deslizante: por cada `agent_id` guarda un `deque[float]` con las marcas
`time.monotonic()` de los eventos admitidos, purga las que quedaron fuera de la ventana y rechaza
cuando quedan `limit` marcas adentro (`check`, `:186-196`). `seconds_until_available` (`:198-220`)
deriva el `retry_after` del `event_nack` como el remanente hasta que la marca más vieja salga de la
ventana, con el piso `_MIN_RETRY_AFTER_S = 0.5` (`:175`). Un `threading.Lock` envuelve los tres
métodos desde D75/RN-169, porque `check()` corre en un hilo del executor (vía
`accept_new=lambda: _rate_limiter.check(agent_id)`, `:523`) y `seconds_until_available()` en el
event loop (vía `_reject`, `:618-619`). La instancia de módulo `_rate_limiter` (`:227`) y
`reset_rate_limiter()` (`:230-232`) son la interfaz que usan los tests.

**Estado actual — la configuración.** `rate_limit_ingest_events: int = 100` y
`rate_limit_ingest_window_seconds: float = 60.0` (`backend/app/core/config.py:100-101`). `Settings`
usa `extra="ignore"` y `env_file=".env"` (`:39-43`): una variable que ya no es un campo se ignora en
silencio. `docker-compose.yml:290-291` reenvía `RATE_LIMIT_INGEST_EVENTS` y
`RATE_LIMIT_INGEST_WINDOW_SECONDS` con defaults `100` y `60`; `.env.example:118,121` las documenta.
`lab/docker-compose.exp.yml:8-9` las eleva a `100000`/`60` para las baterías, y ocho scripts de
`lab/` aplican ese override y registran `printenv RATE_LIMIT_INGEST_EVENTS` como procedencia.

**Estado actual — el lado del agente (no cambia).** `Publisher._apply_backpressure`
(`agent/publisher.py:267-284`) acota el `retry_after` recibido a `(0, max_retry_after_s = 60 s]`
(`agent/config.py:54`) y pausa **todas** las transmisiones del agente hasta que vence. Un valor
`≤ 0` se reemplaza por `_MIN_RETRY_AFTER_S = 1.0` (`agent/publisher.py:66`); un `0,6` se respeta tal
cual. `_retry_loop` (`:604-650`) despierta cada 5 s y reenvía los eventos sin ack con más de 60 s
desde su último envío, con techo `max_publish_attempts`.

**Decisión normativa que gobierna esta change** — cerrada, no se re-decide acá: D85/RN-179
(`docs/reglas_de_negocio.md`, «D85 / RN-179: El límite de ingesta es un token bucket por agente»;
fila D85 en `docs/arquitectura_stack.md:2725`). Fija el régimen (100 ev/min), la ráfaga (3.000), su
base (el replay de la batería 5, con la cola como cota superior), los nombres de los settings, la
eliminación de los anteriores con advertencia al arrancar y la consecuencia sobre `retry_after`.

**Restricciones.** Backend single-instance (RN-76): el estado del limitador vive en memoria del
proceso y se pierde al reiniciar, como hoy. D37/RN-131: el exceso de presupuesto produce un
`event_nack` retenible con `retry_after` positivo; el evento nunca se destruye. D75/RN-169: el
limitador se toca desde dos hilos. D38/RN-132: el límite efectivo de una corrida se declara junto a
su resultado.

## Goals / Non-Goals

**Goals:**

- Admitir sin rechazos una ráfaga de hasta 3.000 eventos nuevos de un agente con balde lleno, y
  limitar el régimen sostenido a 100 ev/min.
- Que el estado de un agente no afecte a otro.
- Que `retry_after` sea el tiempo real hasta que el agente vuelve a tener cupo.
- Que un entorno con los settings viejos lo sepa al arrancar, en lugar de perder el ajuste en
  silencio.
- Que las baterías de evaluación midan el producto con sus defaults.
- Tests deterministas: sin `sleep`, con reloj inyectado.

**Non-Goals:**

- **No** se cambia el rendimiento de la ingesta ni el tiempo de drenaje (Change 69, D87/RN-181).
- **No** se cambia el agente: ni la pausa por backpressure, ni el `_retry_loop`, ni
  `max_publish_attempts`.
- **No** se persiste el estado del limitador en Valkey ni se comparte entre procesos.
- **No** se toca la evidencia histórica bajo `tesis/cierre/` ni `docs/implementaciones/`: registra
  lo que se corrió con los nombres de entonces.
- **No** se redefine el umbral de recuperación de 30 s (D38/RN-132) ni se re-corre el arnés.

## Derivación de la ráfaga

D85/RN-179 fija `burst = 3.000` por la carga medida, no por la capacidad de la cola. Este cálculo
documenta las dos cifras y la relación entre ellas.

**1. Base: el replay de la batería 5.** Las tres repeticiones de resiliencia encolaron 2.672, 2.671
y 2.672 eventos sobre 3.000 operaciones generadas, y los drenaron en 34,050 s, 35,044 s y 35,257 s
(`tesis/cierre/RESPUESTAS_PENDIENTES_V22.md:118-125`). Esas corridas usaron el límite elevado
100000/60, declarado según D38/RN-132.

- Margen de 3.000 sobre el máximo encolado: 3.000 − 2.672 = 328 eventos, es decir **12,3 %**.
- 3.000 coincide además con las operaciones **generadas** por la batería: aun si el agente encolara
  todas, la ráfaga las cubre.

**2. Lo que realmente admite el balde durante un drenaje.** El balde se rellena mientras se consume.
Si el backend ingiere a `v` ev/s, un replay de `N` eventos dura `N / v` s y en ese lapso entran
`r · N / v` tokens, con `r = 100/60 ≈ 1,667` tokens/s. El replay pasa sin un solo rechazo si
`N ≤ B + r · N / v`, es decir:

```
N_max = B / (1 − r / v)
```

Con la tasa de ingesta medida, `v ≈ 2.672 / 35,044 s ≈ 76,2 ev/s` (CHANGES.md, nota de Change 69):

```
N_max = 3.000 / (1 − 1,667 / 76,2) = 3.000 / 0,9781 ≈ 3.067 eventos
```

La cota conservadora para el contrato y para el test es `N = B = 3.000`, que se cumple aun con
`v → ∞` (sin relleno).

**3. Cota superior: la cola local del agente.** `_MAX_BYTES = 100 * 1024 * 1024 = 104.857.600 B`
(`agent/queue.py:62`), medido sobre el tamaño del blob cifrado (`agent/queue.py:427-430`). Un
evento sin diff, con los campos de `DetectedChange` (`agent/detector.py:75-110`) más los que agrega
`_build_payload` (`agent/publisher.py:288-299`), serializado como sobre
`{"payload", "attempts", "first_attempt_at"}` con `sort_keys` y separadores compactos, ocupa
**728 B** de JSON. El cifrado agrega `_MIN_BLOB_LEN` = 6 (magic `FIMQE\x01`) + 12 (nonce) + 16 (tag
GCM) = **34 B** (`agent/queue.py:73-75`). Total: **~762 B por evento**.

```
104.857.600 B / 762 B ≈ 137.608 eventos
```

La cola puede acumular unas **46 veces** la ráfaga. Por eso la cola **no** es la base del valor:
derivar la ráfaga de la cola daría un balde de ~137.600 eventos, que equivale a no tener límite para
cualquier ráfaga realista. Un evento con `diff_text` pesa más (hasta 1 MiB, `agent/detector.py:34`),
y la cola admite entonces menos eventos; ~137.600 es la cota para el caso sin diff.

**4. Costo en el peor caso (agente comprometido o en bucle).** En una ventana de `t` segundos desde
un balde lleno, un agente puede inyectar como máximo `B + r · t` eventos nuevos:

| Ventana | Ventana deslizante 100/60 (hoy) | Token bucket 100/min + 3.000 |
|---|---|---|
| 1 min | 100 | 3.100 |
| 10 min | 1.000 | 4.000 |
| 60 min | 6.000 | 9.000 |
| Régimen (por hora, balde vacío) | 6.000 | 6.000 |

El régimen sostenido no cambia; la ráfaga agrega una vez 3.000 eventos. Después de vaciar el balde,
recuperarlo entero lleva `B / r = 3.000 / 1,667 = 1.800 s = 30 min` de silencio del agente.

**5. Comparación con el modelo actual.** Con 100/60 deslizante, 2.672 eventos exigen al menos
`2.672 / 100 = 26,72` ventanas de 60 s, es decir **26,7 min** (D85/RN-179, «Motivo»). Con el balde
lleno, el mismo replay queda limitado sólo por la tasa de ingesta.

## Decisions

### D-1: Token bucket con relleno perezoso y estado `(tokens, updated_at)` por agente

Cada `agent_id` tiene un registro con `tokens: float` y `updated_at: float` (marca de reloj
monótono). Cada operación primero rellena: `tokens = min(burst, tokens + (now − updated_at) · rate)`
y `updated_at = now`. `check()` admite si `tokens ≥ 1` y descuenta uno.

**Alternativas consideradas:**

- *GCRA (un solo «theoretical arrival time» por agente).* Matemáticamente equivalente y con un float
  menos. Se descarta por legibilidad: el texto de la tesis y D85/RN-179 hablan de tokens y ráfaga, y
  el código debe leerse con el mismo vocabulario.
- *Ventana deslizante con límite mayor (p. ej. 3.000 por 30 min).* Mismo promedio, pero permite
  3.000 eventos al comienzo de **cada** ventana y obliga a guardar hasta 3.000 marcas por agente. No
  es lo que D85/RN-179 decide.
- *Estado en Valkey.* Sobra para un backend single-instance (RN-76) y contradice el requisito
  vigente de que el contador se reinicia con el backend.

### D-2: Un agente nunca visto arranca con el balde lleno

El primer acceso a una clave crea el registro con `tokens = burst`. Es lo que permite que el replay
inmediatamente posterior a una reconexión pase sin rechazos. **Consecuencia:** reiniciar el backend
devuelve el balde lleno a todos los agentes. Hoy ocurre lo equivalente (la ventana se vacía al
reiniciar) y el requisito vigente ya lo establece.

### D-3: Settings `rate_limit_ingest_rate_per_s: float` y `rate_limit_ingest_burst: int`

- `rate_limit_ingest_rate_per_s: float = Field(default=100 / 60, gt=0)`: la unidad por segundo es la
  que nombra D85/RN-179 y la natural del relleno.
- `rate_limit_ingest_burst: int = Field(default=3000, ge=1)`: con `burst < 1` ningún evento pasaría
  nunca.
- Validación fail-fast al importar `settings` (D-CHANGE-04, `config.py:4-7`).
- El compose reenvía `RATE_LIMIT_INGEST_RATE_PER_S` con default `1.6666666666666667` (el
  `repr` de `100/60`) y `RATE_LIMIT_INGEST_BURST` con default `3000`, siguiendo el patrón actual de
  defaults explícitos en `docker-compose.yml`. Un test compara esos literales con los defaults de
  `Settings` para que no se separen.

**Alternativa considerada:** expresar la tasa por minuto (`RATE_LIMIT_INGEST_EVENTS_PER_MIN=100`)
evitaría el decimal periódico. Se descarta porque D85/RN-179 fija los nombres.

### D-4: Reloj inyectable en el constructor

`_RateLimiter(rate_per_s: float | None = None, burst: int | None = None, clock: Callable[[], float] =
time.monotonic)`. Los argumentos `None` leen `settings`, como hoy. Los tests pasan un reloj falso y
avanzan el tiempo explícitamente: el test de ventana actual (`test_event_consumer_c11.py:107-115`)
usa `time.sleep(0.1)`, que es lento y sensible a la carga de la máquina. Con un reloj inyectado, la
admisión de 3.000 eventos y el régimen sostenido se verifican en milisegundos y sin flakiness.

### D-5: `retry_after = max((1 − tokens) / rate_per_s, _MIN_RETRY_AFTER_S)`

`seconds_until_available(key)` rellena, y si `tokens ≥ 1` devuelve `0.0`; si no, devuelve el tiempo
hasta acumular el token que falta, con el piso existente de 0,5 s. Para un agente nunca visto
devuelve `0.0` sin crear registro. A 100 ev/min, el valor queda en `[0,5 s; 0,6 s]`. Sigue siendo el
único punto por el que el consumer conoce el estado del limitador (el consumer no lee los campos
internos).

**Consecuencia aceptada (D85/RN-179):** el agente pasa de pausas de hasta ~60 s a pausas de ~0,6 s.
Es compatible con D37/RN-131: el valor es positivo, derivado del estado vivo y menor que el techo de
60 s que aplica el agente.

### D-6: Settings viejos eliminados; advertencia al arrancar si siguen definidos

Se eliminan los dos campos. Una función pura en `backend/app/core/config.py`,
`legacy_ingest_rate_limit_vars(environ: Mapping[str, str], env_file_values: Mapping[str, str | None])
-> list[str]`, devuelve los nombres heredados (`RATE_LIMIT_INGEST_EVENTS`,
`RATE_LIMIT_INGEST_WINDOW_SECONDS`, comparando sin distinguir mayúsculas, como `Settings`) que tengan
valor **no vacío** en el entorno del proceso o en el `.env` que `Settings` lee. El `lifespan`
(`backend/app/main.py:78`) la invoca al arrancar y, si la lista no está vacía, registra **un**
`log.warning("config.legacy_ingest_rate_limit_ignored", variables=[...],
replacements=["RATE_LIMIT_INGEST_RATE_PER_S", "RATE_LIMIT_INGEST_BURST"])`. El arranque continúa.

El compose sigue reenviando `RATE_LIMIT_INGEST_EVENTS: ${RATE_LIMIT_INGEST_EVENTS:-}` y
`RATE_LIMIT_INGEST_WINDOW_SECONDS: ${RATE_LIMIT_INGEST_WINDOW_SECONDS:-}` **sólo** para la
detección. Sin ese reenvío, el caso más común —un operador que actualiza el repositorio y conserva su
`.env` con `RATE_LIMIT_INGEST_EVENTS=100000`— no llegaría nunca al contenedor y la advertencia
jamás se dispararía. Un valor vacío cuenta como «no definido».

**Alternativas consideradas:** *mapear* los valores viejos a los nuevos y *fallar* al arrancar.
D85/RN-179 resuelve eliminar con advertencia. Además, mapear dejaría que
`lab/docker-compose.exp.yml` siguiera elevando el límite sin que nadie lo note, que es justamente lo
que la decisión busca terminar.

### D-7: Mismo lock, mismo cruce de hilos

Se mantiene un único `threading.Lock` alrededor de `check`, `seconds_until_available` y `reset`,
con el fundamento de D75/RN-169. El relleno es lectura-modificación-escritura de dos campos, así que
la protección sigue siendo necesaria. El test de concurrencia existente
(`test_ingest_offload_blocking_db.py:454-476`) se reescribe: 500 `check()` desde 20 hilos con reloj
congelado sobre un balde de capacidad 100 admiten exactamente 100.

### D-8: Laboratorio con los defaults del producto

Se elimina `lab/docker-compose.exp.yml`. Los scripts que lo aplicaban (`DCX`, `DC_OVERRIDE`) usan el
compose nominal; las líneas de procedencia pasan a
`printenv RATE_LIMIT_INGEST_RATE_PER_S RATE_LIMIT_INGEST_BURST`, más una línea que registra la
ausencia de las variables heredadas. El segundo argumento de `lab/bateria5.sh` (`LIMIT`, hoy sólo una
etiqueta en `:33`) deja de recibir `100000` y el encabezado del log pasa a imprimir los valores
efectivos leídos del contenedor. `corrida_unificada.sh:177` deja de copiar el override a la
evidencia.

D38/RN-132 sigue vigente: una corrida **puede** elevar el límite si lo declara. Esta change sólo
quita del arnés versionado el override que lo hacía por defecto.

### D-9: Cada medición arranca con el balde lleno; el backend nunca se recrea durante un corte

Cerrado en D85/RN-179 («Protocolo de medición», opción (a)): el arnés SHALL recrear el contenedor
del backend antes de cada batería y de cada repetición, dentro de `reset_lab`, y MUST NOT
reiniciarlo durante un corte de Valkey.

**Contexto que lo vuelve necesario.** El arnés unificado publica las tres series de la batería de
notificación (`lab/corrida_unificada.sh:304-306`, 3 × 1.000 eventos) con el `agent_id` `fim-vm`
(`lab/bateria4_publicador.py:20`), el mismo de la VM, y luego corre las tres repeticiones de
resiliencia (`:319-329`, ~2.672 eventos cada una). `reset_lab` (`:207-216`) limpia la base, la cola
del agente y el stream, pero hoy **no** toca el backend. El contenedor se recreaba de hecho porque el
arnés alternaba `DC` y `DCX`. Sin el override, `up -d backend` deja de recrearlo, y la repetición 2
empezaría con el balde vaciado por la 1 (~27 min para recuperarlo a 100 ev/min).
`bateria4_publicador.py` no reintenta los `event_nack`, así que un evento limitado sería una muestra
perdida.

**Implementación.**

- `reset_lab` termina con `"${DC[@]}" --profile app up -d --force-recreate backend` **después** de
  vaciar la base, la cola de la VM y el stream, y espera a que el backend consuma de nuevo antes de
  devolver el control. La espera reemplaza los `sleep` fijos posteriores a los `up -d backend` que
  hoy siguen a `reset_lab`.
- La batería de notificación (`:283-306`) hoy no llama a `reset_lab`: pasa a llamarlo una vez al
  comenzar, en lugar de su `"${DCX[@]}" --profile app up -d backend` (`:285`). Las tres series son
  partes de una misma batería, no repeticiones: no se recrea entre ellas. Suman 3.000 eventos más el
  relleno de los minutos de espera entre series, dentro de la ráfaga. La evidencia registra el
  conteo de `rate_limited` en `rejected_events_audit` después de cada serie; si no es cero, el
  resultado se reporta, no se corrige recreando a mitad de batería.
- Los otros scripts que definen `reset_lab` (`lab/cierre_cap5.sh:15`, `lab/repetir_cap5.sh:18`,
  `lab/rehacer_notif_resil.sh:29`) reciben el mismo cambio. Los que corren una batería sin
  `reset_lab` (`lab/corte_valkey.sh`, `lab/b5_post_d75.sh`) recrean el backend antes de invocarla.
- **Nunca durante un corte.** `lab/bateria5.sh` restaura con
  `"${DC[@]}" --profile app up -d valkey backend` (`:50`). Compose recrea cualquier servicio cuya
  configuración efectiva difiere de la del contenedor en marcha. `bateria5.sh` arma su propio `DC`
  (base + TLS + a lo sumo **un** `DC_OVERRIDE`, `:11-19`), mientras que `corrida_unificada.sh`
  levanta el backend con base + TLS + `docker-compose.mailpit.yml`, que modifica el `environment`
  del backend. La restauración del corte puede entonces **recrear el backend en plena medición**.
  Se corrigen las dos cosas:
  - la fase 3 restaura sólo Valkey (`up -d --no-recreate valkey`);
  - `bateria5.sh` recibe del llamador la lista completa de archivos compose (variable
    `DC_FILES` o equivalente) en lugar de un único `DC_OVERRIDE`, de modo que el conjunto es el
    mismo en todo el arnés.

  Si esta recreación explica el retraso de 33,5 s observado en run-03 (nota de Change 69) es una
  hipótesis de esa change, no de esta.

## Risks / Trade-offs

- **[Riesgo] Un `.env` heredado con `RATE_LIMIT_INGEST_EVENTS=100000` pierde su efecto.** →
  Advertencia al arrancar (D-6), con el nombre de los reemplazos. Es el comportamiento que decide
  D85/RN-179.
- **[Riesgo] Más eventos en la primera hora de un agente comprometido** (9.000 contra 6.000, tabla
  de la derivación). → El régimen sostenido no cambia y la ráfaga se recupera en 30 min de silencio.
  La amplificación sobre notificaciones está acotada por `notify_max_concurrent_deliveries`
  (`config.py:199-210`), cuyo comentario se actualiza.
- **[Trade-off] Tormenta de `event_nack` después de vaciar el balde.** El `_retry_loop` del agente
  reenvía en bloque todos los eventos sin ack con más de 60 s; con el balde vacío, unos 100 pasan y
  el resto genera un `event_nack` y una fila en `rejected_events_audit` por ronda. Es comportamiento
  **preexistente** (hoy pasa a partir del evento 101) y esta change lo desplaza al evento 3.001. No
  se corrige acá porque es del agente.
- **[Trade-off] Descartes por `max_attempts_exceeded` en ráfagas muy grandes.** Con 100 admisiones
  por ronda de 60 s y 20 intentos por evento, un backlog que supere la ráfaga en más de unas
  ~2.000 posiciones agota intentos antes de entrar. Es una estimación de orden de magnitud sobre el
  comportamiento actual del agente, que esta change mejora sin eliminarlo. No se re-mide acá.
- **[Riesgo] El arnés deja de recrear el backend entre baterías** al desaparecer el override, y el
  balde de `fim-vm` pasaría de una medición a la siguiente. → D-9: `reset_lab` lo recrea antes de
  cada batería y repetición.
- **[Riesgo] Recreación accidental del backend durante el corte de Valkey.** → D-9: la fase 3 de
  `bateria5.sh` restaura sólo Valkey y el conjunto de archivos compose es único para todo el arnés.
- **[Riesgo] Defaults duplicados entre `Settings` y `docker-compose.yml`.** → Test que compara los
  literales (D-3).
- **[Riesgo] `.env.example` lo bloquea una regla de permisos en el entorno del asistente.** Hubo que
  ubicar sus líneas con `rg`. → La tarea correspondiente indica editarlo a mano si el agente de
  apply tampoco puede leerlo.

## Migration Plan

1. Despliegue normal (`docker compose up -d --build backend`). No hay migración de datos ni de
   esquema.
2. Un `.env` que conserve los nombres viejos produce
   `config.legacy_ingest_rate_limit_ignored` en el log del backend. El operador los borra y, si
   necesita otro régimen, define `RATE_LIMIT_INGEST_RATE_PER_S` / `RATE_LIMIT_INGEST_BURST`.
3. **Rollback:** revertir el commit. Los nombres viejos vuelven a ser campos y, si seguían en el
   `.env`, retoman su efecto.

## Open Questions

Ninguna. OQ-1 (estado del balde entre mediciones) quedó cerrada en D85/RN-179 con la opción (a) y
se resuelve en D-9.

El reenvío de los nombres heredados desde el compose (D-6) **no** es una pregunta abierta: es una
decisión de implementación que hace efectiva la advertencia que D85/RN-179 exige, y no cambia el
comportamiento observable fuera de esa advertencia.
