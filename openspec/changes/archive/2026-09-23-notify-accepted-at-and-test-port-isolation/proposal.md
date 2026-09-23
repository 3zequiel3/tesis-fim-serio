## Why

Esta change agrupa **dos defectos independientes que comparten un único propósito: que una medición
sea creíble**. Ninguno de los dos es un defecto de producto en funcionamiento —el sistema notifica y
el sistema se testea—; los dos son defectos de **instrumentación**, y los dos producen números que la
tesis no puede informar sin una nota al pie que los anule.

No se agrupan por conveniencia. Se agrupan porque el capítulo de evaluación los declara juntos: uno
dice que el intervalo medido no es el intervalo definido, y el otro dice que el conteo de fallas de
la suite no describe el producto. Corregir uno y dejar el otro deja el capítulo igual de indefendible.

---

### Defecto 1 — el intervalo de notificación que la tesis define no se registra en ninguna parte

El protocolo de medición (`tesis/plan_medicion_cap5.md`, Batería 4, `:202-204`) define el intervalo
con tres frases sin ambigüedad:

> **Intervalo**: recepción del evento por el backend → **emisión exitosa del webhook**.
> **No incluye** la entrega en n8n ni en el canal final.
> **Solo camino feliz / primer intento** — los reintentos (5/30/120 s) harían infalsable el umbral de 5 s.

Lo que se mide hoy es otra cosa. La Fuente A del mismo protocolo (`:222-230`) calcula
`EXTRACT(EPOCH FROM (a.delivered_at - e.received_at))`, y **ese intervalo es estrictamente mayor que
el definido**, porque `delivered_at` no marca la aceptación del canal.

**Lo que hay en la tabla `alerts`, con anclas.** `backend/app/modules/alerts/models.py:25-41` declara
las columnas `id, event_id, severity, channel, delivered_at, failed_at, last_error, retry_count,
notification_id, attempt_count, next_retry_at, created_at`. **Ninguna registra el instante en que un
canal aceptó la notificación.** Las dos que podrían confundirse con ella no lo son:

- `created_at` (`:41`) es un `default_factory` que se evalúa al construir la fila, **antes de
  cualquier intento de red**.
- `delivered_at` lo escribe `_mark_delivered` (`alerts/service.py:483`) con un
  `datetime.now(timezone.utc)` que se evalúa **dentro del hilo del executor**, es decir después de que
  `await send_n8n(...)` devolvió `True` (`:428`), después de que la corrutina despachó un
  `run_in_executor` (`:429-431`) y después de que ese hilo abrió una `Session`, hizo el `add` y llegó
  al `commit`.

**Lo que hay en el log, y por qué no alcanza.** `alerts/notifier.py:48` emite
`log.info("notifier.n8n_sent", status_code=response.status_code)` inmediatamente después de que
`response.raise_for_status()` no levantó (`:47`). **Ése es estructuralmente el instante verdadero de
aceptación.** Pero la línea **no lleva `alert_id`, ni `event_id`, ni `notification_id`**, y nada los
liga en el camino de entrega en segundo plano: `send_n8n` recibe `payload` y `url`, y devuelve `bool`.
Tampoco sirve un join por proximidad temporal, porque bajo la concurrencia acotada que introdujo
D76/RN-170 (`notify_max_concurrent_deliveries`, default 32) hay hasta 32 entregas en vuelo
simultáneas y la correspondencia entre una línea de log y una alerta deja de ser una función.

**La brecha está medida, no supuesta.** Las medianas de `delivered_at − received_at` para este
candidato son **13,170 s**, **11,671 s** y **10,537 s** en los tres escenarios de la Batería 4. Ese
número absorbe, además del tiempo de red del webhook, la espera por un permiso del cupo de entregas
concurrentes y el viaje de ida y vuelta al executor. La cifra que el protocolo pide —emisión exitosa
del webhook— es **otra magnitud, mucho menor**, y hoy no existe registro alguno del que derivarla.

> **Lo que esta change NO hace con `delivered_at`.** No redefine su semántica. **Agrega una marca, no
> reinterpreta una.** Hay mediciones ya publicadas que dependen de que `delivered_at` signifique
> exactamente lo que significa hoy —la persistencia del éxito después de la confirmación del canal—;
> cambiarle el sentido invalidaría retroactivamente esos números en vez de corregir la brecha, y
> convertiría una corrección en una reescritura de la evidencia.

---

### Defecto 2 — la suite de tests colisiona consigo misma sobre recursos ambientales compartidos

Dos casos hermanos, **no un caso y una nota al pie**. Los dos son la misma clase de problema: *una
prueba acoplada a un recurso ambiental compartido*, sea un puerto TCP o un archivo de configuración
del entorno. Los dos producen fallas que no dicen nada del producto.

#### Caso A — el puerto 8443, fijo en el código

`backend/app/core/pki.py:638-645` declara `start_mtls_server(..., host: str = "0.0.0.0", port: int = 8443)`:
un default **cableado, sin ningún setting que lo mueva**. `backend/app/main.py:92-97` lo invoca de
verdad dentro del lifespan de FastAPI.

`backend/tests/conftest.py:4-7` documenta que `httpx.AsyncClient` + `ASGITransport` **no ejecuta** el
lifespan. Pero `with TestClient(app) as client:` **sí lo ejecuta, de verdad**, y hay **41** call sites
así repartidos en cuatro módulos: `test_notifications.py` (16), `test_sse_alerts.py` (14),
`test_sse_stream_ticket.py` (10) y `test_logging_sanitize.py` (1).

Cuando dos de esos tests coinciden sobre un 8443 ocupado, el bind levanta
`OSError: [Errno 98] address already in use`, que aflora en el teardown como
`RuntimeError: This portal is not running`, **y cascada**: una vez que el portal anyio compartido se
rompe, los tests hermanos de la misma sesión heredan el estado roto. El propio arnés de suites lo
documenta y lo esquiva bajando el backend del laboratorio antes de correr
(`scripts/correr_suites_candidato.sh:83-91`), con el comentario *"8443 is fixed in pki.py, so the port
has to be freed rather than moved"*. **Esta change hace que se pueda mover.**

El patrón correcto ya existe en este repositorio y no hay que inventarlo:
`backend/tests/test_mtls_transport.py:111-118` define `_free_port()` con
`socket.bind(("127.0.0.1", 0))`, y `:143-151` pasa `port=port` explícito;
`backend/tests/test_agent_cert_renewal_e2e.py` usa el mismo helper.

#### Caso B — las variables de configuración del entorno, heredadas del proceso que invoca

`backend/tests/core/test_notification_settings.py` falla con dos aserciones distintas de las del
caso A:

```
AssertionError: assert 'http://n8n:5678/webhook/fim-alert' == ''
AssertionError: n8n_health_url must stay empty when unset
```

El test construye su entorno con `_fresh_settings` (`:23-39`), que hace
`monkeypatch.delenv` sobre las seis claves relevantes y recarga `app.core.config`. **Ese saneamiento
es correcto y no es el problema.**

La fuga entra por otro lado, y conviene decirlo con precisión porque determina el arreglo:
`backend/app/core/config.py:39-43` declara `model_config = SettingsConfigDict(env_file=".env", ...)`.
`env_file` es una **ruta relativa**, y pydantic-settings la resuelve contra el **directorio de trabajo
del proceso**, no contra el paquete. El arnés corre pytest desde la raíz del repositorio
(`scripts/correr_suites_candidato.sh:40`, `:93-99`), donde vive un `.env` real que define
`N8N_WEBHOOK_URL` y `N8N_HEALTH_URL`. `monkeypatch.delenv` neutraliza `os.environ`; **no neutraliza el
archivo dotenv**, que pydantic lee igual. De ahí que la segunda aserción falle sobre
`n8n_health_url`, una clave que `delenv` sí borró del proceso: el valor no vino del proceso, vino del
archivo.

Es el mismo acoplamiento del caso A con otro recurso: la suite depende de qué hay en el directorio
desde el que se la invoca.

#### Impacto medido, sobre el artefacto sellado

Corrida sobre el candidato `v3.0-tesis` (`22f393d`), paquete
`tesis/cierre/evidencia/v2-eval-20260923T010103Z/suites/`, procedencia con
`candidate_tag=v3.0-tesis`:

| Suite | Tests | Fallas | Omitidos |
|---|---|---|---|
| agente | 642 | 0 | 1 |
| backend | 864 | **15** | 4 |
| frontend | 260 | 0 | 0 |

Desglose de las 15 fallas del backend, por mensaje, leídas de `backend.xml`:

| Clase | Fallas | Reparto |
|---|---|---|
| `RuntimeError: This portal is not running` (caso A) | **13** | `tests.test_notifications` 7 · `tests.test_sse_alerts` 6 |
| `AssertionError` de configuración heredada (caso B) | **2** | `tests.core.test_notification_settings` |

> **El matiz que la tesis debe informar sin adornos.** La misma suite contra contenedores efímeros,
> donde el puerto está libre y el directorio de invocación no tiene `.env`, reporta **0 fallas**. Eso
> **no significa que estén corregidas**: significa que ese entorno evita el conflicto. La cifra de
> referencia del capítulo son las **15 de arriba**, sobre el artefacto sellado. "Se evitan cambiando
> el entorno" no es una corrección, y presentarlo como tal sería exactamente la clase de lectura
> conveniente que esta change existe para cerrar.

---

### El principio que esta change existe para honrar

**Una medición es creíble cuando el número que se informa es el número que se definió, y cuando una
falla reportada dice algo del producto.** Hoy ninguna de las dos condiciones se cumple: el intervalo
informado es mayor que el definido y no hay de dónde derivar el definido; y 15 fallas de la suite no
hablan del producto sino del entorno que la invoca.

## What Changes

- **Marca durable del instante de aceptación del canal.** Se agrega a `alerts` una columna de
  timestamp **anulable** que registra el instante en que un canal aceptó la notificación. Se captura
  en la corrutina, **inmediatamente después** de que el envío devolvió éxito —en los dos puntos de
  éxito de `notify_event`: `:428` para n8n y `:447` para la cascada de fallbacks— y se **persiste
  junto con las marcas existentes, en el mismo `commit`** que ya escribe `_mark_delivered`. Sin
  `commit` adicional, sin viaje adicional al executor y sin depender de ningún join por proximidad
  temporal. El nombre de la columna y su fundamento están en D-1 del design.

- **`delivered_at` conserva su semántica, sin excepción.** Sigue siendo el `datetime.now(timezone.utc)`
  evaluado dentro del hilo del executor, en `_mark_delivered`. Esta change **agrega** una marca; no
  redefine ninguna. Es un requisito duro, no una preferencia: las mediciones publicadas dependen de
  ello.

- **El contrato de la API no se extiende.** El modelo de respuesta de `alerts/router.py:64` enumera
  sus campos de forma explícita, de modo que agregar una columna al modelo ORM **no** cambia ninguna
  respuesta. El estado derivado (`delivered` / `failed` / `pending`, `router.py:82-83`) sigue
  derivándose **solo** de `delivered_at` y `failed_at`. La marca nueva es instrumentación de medición,
  no superficie de producto.

- **Migración `022`.** Siguiente número libre verificado contra `backend/db/migrations/`, cuyo máximo
  actual es `021_add_agent_queue_pressure_high.sql`. Columna anulable, sin backfill: las filas
  anteriores a la migración no tienen el dato y **no se inventa uno**; una alerta entregada antes de
  esta change tiene la marca en `NULL`, que es la verdad.

- **El puerto del servidor mTLS deja de estar cableado para los tests, sin cambiar producción.** La
  solución es **exclusivamente del arnés de pruebas**: ninguna ruta de código de producción cambia de
  comportamiento. Se prefiere **una fixture centralizada** antes que editar los 41 call sites
  (fundamento en D-5 del design). El default `8443` de `pki.py:644` y la invocación real del lifespan
  en `main.py:92-97` **no se tocan**.

- **La suite parte de un entorno determinado.** El arnés deja de heredar las variables de
  configuración del proceso y del directorio que lo invoca —incluido el archivo dotenv que
  `config.py:40` resuelve contra el CWD—. Se hace **una sola vez** en `backend/tests/conftest.py`,
  que ya es el lugar donde el proyecto fija el entorno canónico antes del primer import de la
  aplicación (`conftest.py:51-66`), y no test por test.

- **Todos los invariantes vigentes se preservan, y se verifican explícitamente.** En particular, y
  declarados acá porque esta change toca el mismo camino que D76/RN-170:
  - **`notification_id` estable a lo largo de toda la escalera de reintentos** (D40/RN-134,
    D41/RN-135), que se sostiene únicamente porque `_build_payload` se invoca **exactamente una vez**,
    dentro de `_prepare_notification` (`:321`) y **fuera** del bucle de reintentos.
  - **Entrega al-menos-una-vez**, tal como la declara el docstring de `notify_event`.
  - **La cascada de canales** n8n → `smtp_fallback` → `webhook_fallback` → `log_only` y sus
    `RETRY_DELAYS = [5, 30, 120]`.
  - **El permiso del cupo de entregas concurrentes se adquiere UNA sola vez, ANTES de
    `_prepare_notification`** (D76/RN-170, `service.py:399-406`), y se sostiene hasta que la entrega
    termina por cualquier salida.

- **Sin cambio del payload canónico de notificación** (D40/RN-134). La marca es durable en la fila
  `Alert`; **no** viaja en el payload. `backend_dispatched_at` (`notifier.py:41-44`) sigue siendo
  evidencia de transporte del lado del emisor y no se toca.

- **Actualización del protocolo de medición.** La Batería 4 de `tesis/plan_medicion_cap5.md` pasa a
  derivar sus ítems 11-22 de la columna nueva, y **declara la relación con la serie anterior** en vez
  de reemplazarla en silencio: los números de `delivered_at − received_at` siguen siendo válidos para
  lo que miden, y dejan de presentarse como si midieran lo que la Batería 4 define.

- **Re-medición obligatoria.** Esta change **invalida el candidato congelado `v3.0-tesis`**. Se
  re-corre el arnés unificado `~/fim-lab/corrida_unificada.sh` con `TAG=<tag-nuevo>` y se emite un tag
  nuevo. **No se declara mejora anticipada**: primero se implementa, después se mide, y el número
  medido se registra sea cual sea.

### Fuera de alcance — dirección declarada, no omisión

- **Ligar `notifier.n8n_sent` a la alerta.** Agregar `alert_id` / `notification_id` a la línea de log
  de `notifier.py:48` tendría valor operativo propio, pero exigiría atravesar contexto por la firma de
  `send_n8n` y de los tres fallbacks, y **la columna durable vuelve innecesario el join**. Queda
  nombrada acá para que la decisión esté en el registro.

- **Mover el puerto mTLS a un setting de producción.** Esta change lo hace inyectable **para el
  arnés**. Convertirlo en un parámetro de despliegue toca el contrato de conexión del agente
  (`agent/` conoce el 8443) y es otra magnitud de cambio, con su propia decisión.

- **Un barrido que complete la marca nueva sobre filas históricas.** No hay dato del que derivarla.
  Un backfill sería inventar evidencia.

## Capabilities

### New Capabilities

- _Ninguna._ Esta change no introduce capabilities: modifica dos que ya existen.

### Modified Capabilities

- `backend-notifications`: el requisito **"Notificación asincrónica post-ingesta de eventos críticos o
  altos"** (`openspec/specs/backend-notifications/spec.md:3`) gobierna hoy el camino de entrega
  completo —aislamiento de recursos, cota de concurrencia, cascada, `notification_id` estable— pero
  **no exige registro alguno del instante en que un canal aceptó la notificación**, y la única marca
  de éxito que define (`delivered_at`) se escribe después del despacho al executor y del `commit`. Se
  amplía para exigir una marca durable de aceptación del canal, capturada en el momento del éxito del
  envío, persistida junto a las marcas existentes y **explícitamente distinta** de `delivered_at`,
  cuya semántica se ratifica sin cambio.

- `backend-test-harness`: el requisito **"Test harness owns schema, seeding, and isolation"**
  (`openspec/specs/backend-test-harness/spec.md:8`) hace responsable al conftest raíz del esquema, del
  sembrado y del aislamiento **por test de la base de datos**, y del entorno canónico previo al primer
  import. No dice nada sobre **recursos ambientales compartidos fuera de la base**: ni puertos TCP ni
  el archivo de configuración del entorno que la aplicación resuelve contra el directorio de trabajo.
  Se amplía para exigir que la suite no dependa de ningún recurso ambiental compartido, con las dos
  obligaciones concretas —puerto de escucha efímero por test y entorno de configuración determinado,
  sin herencia del proceso ni del CWD— y con la restricción de que se satisfagan **sin cambiar
  ninguna ruta de código de producción**.

## Impact

**Backend — modelo y migración**:
- `backend/app/modules/alerts/models.py:25-41` — columna nueva anulable en `Alert`, con `sa_type`
  `TIMESTAMPTZ` por el mismo criterio de D39/RN-133 que ya aplica a `delivered_at`, `failed_at`,
  `next_retry_at` y `created_at` (`:8`).
- `backend/db/migrations/022_*.sql` — `ALTER TABLE alerts ADD COLUMN IF NOT EXISTS ...`, idempotente,
  mismo estilo que `014_add_alert_delivery_state.sql`. Sin backfill, sin índice: la columna es
  material de análisis, no de predicado de consulta caliente.

**Backend — camino de notificación** (`backend/app/modules/alerts/service.py`):
- `:428-432` (éxito de n8n) y `:447-457` (éxito de la cascada) — captura del instante de aceptación en
  la corrutina, inmediatamente después del `await` que devolvió éxito.
- `_mark_delivered` (`:467-492`) — **un parámetro más**; el cuerpo sigue escribiendo `delivered_at`
  con su propio `datetime.now(timezone.utc)` dentro del executor, **sin cambio de semántica**. Sigue
  siendo una función sync invocada por `run_in_executor` con el executor de notificación referenciado
  explícitamente (D76/RN-170).
- `notify_event` (`:383-465`) — **sin cambio estructural**: no se toca el bucle de reintentos, ni la
  cascada, ni `RETRY_DELAYS`, ni el `async with _delivery_slot()` ni el punto en que se adquiere el
  permiso.
- `_build_payload`, `_prepare_notification`, `_record_retry_attempt`, `_record_all_attempts_failed`,
  `_try_fallbacks`, `recover_pending_notifications` — **firmas y cuerpos sin cambios**.

**Backend — API**: `backend/app/modules/alerts/router.py` — **sin cambios**. Se verifica que el
modelo de respuesta (`:64`) y el estado derivado (`:82-83`) no incorporan la columna nueva.

**Backend — PKI**: `backend/app/core/pki.py:638-645` — `start_mtls_server` ya acepta `port`; el
default y el comportamiento **no cambian**. `backend/app/main.py:92-97` **no cambia**.

**Backend — arnés de pruebas** (`backend/tests/conftest.py`): fixture centralizada que provee a los
tests con lifespan un puerto de escucha efímero, siguiendo el patrón ya establecido por
`test_mtls_transport.py:111-118` y el de neutralización por `monkeypatch` ya establecido por
`test_rejected_events_retention.py:294-312` y `test_notify_isolate_executor_lifespan.py:41-52`; y
saneamiento de una sola vez del entorno de configuración, incluido el dotenv que `config.py:40`
resuelve contra el CWD.

**Backend — tests**: que la marca de aceptación se escribe en el éxito de n8n y en el de cada canal de
la cascada; que **no** se escribe cuando toda la cascada falla; que `delivered_at` conserva su
semántica; que la marca precede o iguala a `delivered_at` en la misma fila; que `notification_id` no
se altera; que los 41 call sites con lifespan ya no colisionan; que los tests de configuración parten
de un entorno determinado con un `.env` presente en el CWD.

**Documentación canónica**: appendix "Decisiones de implementación — Abril 2026" de
`docs/reglas_de_negocio.md` (**D77/RN-171** y **D78/RN-172**) y sus filas en `docs/arquitectura_stack.md`;
`CHANGES.md` (Change 60).

**Medición**: `tesis/plan_medicion_cap5.md` (Batería 4, `:200-240`) y re-corrida completa de
`~/fim-lab/corrida_unificada.sh` con tag nuevo; el paquete `v2-eval-20260923T010103Z` queda como línea
de base de comparación, tanto para los 13,170 / 11,671 / 10,537 s como para las 15 fallas.

**Sin impacto**: `agent/`, `frontend/`, contrato del stream `events`, payload canónico de notificación
(D40/RN-134), cascada de canales, `RETRY_DELAYS`, cupo de entregas concurrentes y su desborde
(D76/RN-170), presupuesto de conexiones (D75/RN-169), default de producción del rate limit
(D38/RN-132), respuesta de la API de alertas.

Reglas cubiertas: **RN-171** (nueva, marca de aceptación del canal), **RN-172** (nueva, aislamiento de
la suite de recursos ambientales), **RN-134** y **RN-135** (contrato y deduplicación de notificación,
ratificadas sin cambio), **RN-170** (concurrencia acotada, ratificada sin cambio), **RN-133**
(timestamps con zona), **RN-86** y **RN-102** (lifecycle de `alerts`, ratificadas sin cambio),
**RN-141** (integridad de specs), **RN-71** (léxico snake_case). Decisiones aplicadas: **D77/RN-171** y
**D78/RN-172** (nuevas); **D76/RN-170**, **D75/RN-169**, **D40/RN-134**, **D41/RN-135** y **D39/RN-133**
(preservadas, no reabiertas); **D43/RN-137** (el test que el caso B rompe la defiende, y la defensa se
conserva intacta).

**Dependencias del DAG** (CHANGES.md, Change 60): change 59 `notify-isolate-executor-lane` —archivada
en `openspec/changes/archive/2026-09-23-notify-isolate-executor-lane/` ✔—, dueña de D76/RN-170, del
cupo de entregas concurrentes y de la forma actual de `notify_event`, sobre la que esta change apoya
la captura del instante de aceptación. Change 58 `ingest-offload-blocking-db` —archivada ✔—, dueña de
D75/RN-169 y del despacho de `_mark_delivered` al executor.
