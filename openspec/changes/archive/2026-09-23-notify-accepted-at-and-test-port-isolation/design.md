## Context

Esta change corrige dos defectos de **instrumentación**. Ninguno de los dos impide que el sistema
funcione; los dos impiden que una medición sobre el sistema sea creíble. Por eso viajan juntos: el
capítulo de evaluación los declara en la misma página, y corregir uno solo deja el capítulo igual de
indefendible.

### Defecto 1 — el estado actual, con anclas

La Change 59 (D76/RN-170) dejó `notify_event` con la forma sobre la que esta change apoya. El camino
de éxito de n8n es (`backend/app/modules/alerts/service.py:428-432`):

```python
if await send_n8n(payload, settings.n8n_webhook_url):
    await loop.run_in_executor(
        get_notify_executor(), _mark_delivered, alert.id, AlertChannel.n8n, attempt, attempt + 1
    )
    log.info("notify.delivered", alert_id=alert.id, channel=AlertChannel.n8n, attempt=attempt)
```

Y el de la cascada de fallbacks (`:447-457`) tiene la misma forma con `_try_fallbacks` en lugar de
`send_n8n`. `_mark_delivered` (`:467-492`) es una función sync que corre en el executor de
notificación y escribe:

```python
db_alert.delivered_at = datetime.now(timezone.utc)
```

Ese `now()` **se evalúa dentro del hilo del executor**, es decir después de tres cosas que el
protocolo de medición excluye explícitamente: el retorno del `await`, el despacho de la corrutina al
executor —que bajo carga espera en la cola FIFO del pool— y el `Session` + `add` + `commit`.

El instante verdadero de aceptación sí se observa, pero sólo en el log:
`backend/app/modules/alerts/notifier.py:47-48` hace `response.raise_for_status()` y a la línea
siguiente `log.info("notifier.n8n_sent", status_code=response.status_code)`. La línea **no lleva
identidad de alerta**: `send_n8n(payload, url, timeout) -> bool` no la recibe ni la devuelve, y nada
la liga en el camino de entrega en segundo plano.

La tabla `alerts` (`models.py:25-41`) no tiene dónde guardarlo. Las dos columnas que un lector podría
confundir con la marca buscada no lo son: `created_at` (`:41`) se evalúa al construir la fila, antes
de cualquier red; `delivered_at` (`:32`) es la marca de persistencia descrita arriba.

**La distancia entre las dos magnitudes está medida.** Medianas de `delivered_at − received_at` para
el candidato actual: **13,170 s**, **11,671 s**, **10,537 s** en los tres escenarios de la Batería 4.
La Fuente A del protocolo (`tesis/plan_medicion_cap5.md:222-230`) calcula exactamente eso, y la
definición del intervalo (`:202-204`) pide otra cosa: *"recepción del evento por el backend → emisión
exitosa del webhook"*, *"no incluye la entrega en n8n ni en el canal final"*, *"solo camino feliz /
primer intento"*.

Conviene notar que el protocolo **ya había previsto** la fuente correcta: su Fuente B
(`:233-237`) dice *"correlacionar por `event_id`: `consumer.event_persisted` (recepción),
`notify.delivered` (emisión exitosa)"*. Pero `notify.delivered` (`service.py:432`, `:457`) se emite
**después** del `run_in_executor` de `_mark_delivered`, de modo que tampoco marca la emisión: marca
lo mismo que `delivered_at`, con una línea de log en vez de una columna. Las dos fuentes que el
protocolo ofrece miden la magnitud que el protocolo dice no querer.

### Defecto 2 — el estado actual, con anclas

**Caso A, el puerto.** `backend/app/core/pki.py:638-645`:

```python
def start_mtls_server(
    app: object,
    ca_cert_path: str,
    cert_path: str,
    key_path: str,
    host: str = "0.0.0.0",
    port: int = 8443,
) -> "uvicorn.Server | None":
```

`port` **ya es un parámetro**. El problema no es que no se pueda mover: es que nadie lo mueve.
`backend/app/main.py:92-97` lo invoca sin `port`, dentro del lifespan, y toma el default. Los 41
`with TestClient(app)` de la suite ejecutan ese lifespan de verdad —`conftest.py:4-7` documenta que
`AsyncClient` + `ASGITransport` **no** lo ejecuta, y eso es precisamente lo que hace que los que sí lo
ejecutan sean los que colisionan—, y todos piden el mismo 8443.

El modo de falla es desagradable porque **no nombra la causa**: el bind levanta
`OSError: [Errno 98] address already in use` dentro del arranque del lifespan, el portal anyio del
`TestClient` muere, y el teardown reporta `RuntimeError: This portal is not running`. Y cascada: los
tests hermanos de la misma sesión heredan el portal roto. 13 de las 15 fallas del backend son esto,
repartidas 7 en `test_notifications` y 6 en `test_sse_alerts`.

**Caso B, el entorno de configuración.** `backend/app/core/config.py:39-43`:

```python
model_config = SettingsConfigDict(
    env_file=".env",
    extra="ignore",
    case_sensitive=False,
)
```

`env_file=".env"` es una **ruta relativa**, y pydantic-settings la resuelve contra el **directorio de
trabajo del proceso**. `backend/tests/core/test_notification_settings.py:23-39` sanea el entorno con
`monkeypatch.delenv` sobre las seis claves relevantes y recarga el módulo:

```python
for key in ("N8N_WEBHOOK_URL", "N8N_HEALTH_URL", "SMTP_HOST", "SMTP_STARTTLS", "SMTP_SSL", "WEBHOOK_FALLBACK_URL"):
    monkeypatch.delenv(key, raising=False)
```

**Ese saneamiento es correcto, y no alcanza.** `delenv` neutraliza `os.environ`; no neutraliza el
archivo. El arnés corre pytest desde la raíz del repositorio
(`scripts/correr_suites_candidato.sh:40`, `:93-99`), donde vive un `.env` real que define
`N8N_WEBHOOK_URL` y `N8N_HEALTH_URL` entre otras claves. Pydantic lo lee igual.

> **Esta precisión importa y cambia el arreglo.** Una lectura razonable del síntoma es "el test hereda
> variables de entorno exportadas". Si fuera eso, el `delenv` que el test ya hace las habría borrado, y
> en particular la aserción sobre `n8n_health_url` —una clave que `delenv` sí borra del proceso— no
> podría fallar. Falla porque el valor no vino del proceso: **vino del archivo**. Un arreglo que se
> limite a limpiar `os.environ` deja el defecto exactamente donde está.

### Restricciones vigentes que no se negocian acá

- **`_build_payload` se invoca exactamente una vez por entrega, fuera del bucle de reintentos**
  (`service.py:321`, dentro de `_prepare_notification`). Es la única razón por la que
  `notification_id` es estable a lo largo de la escalera, y esa estabilidad es la única razón por la
  que sirve como clave de deduplicación (D40/RN-134, D41/RN-135).
- **El permiso del cupo de entregas concurrentes se adquiere una sola vez, antes de
  `_prepare_notification`** (`service.py:399-406`), y se sostiene hasta que la entrega termina por
  cualquier salida (D76/RN-170).
- **Entrega al-menos-una-vez**, y **cascada de canales** n8n → `smtp_fallback` → `webhook_fallback` →
  `log_only` con `RETRY_DELAYS = [5, 30, 120]`.
- **Backend single-instance** (RN-76). Sin escalado horizontal, sin `AsyncSession`.
- **Timestamps con zona** (D39/RN-133): toda columna de tiempo de `alerts` usa `TIMESTAMPTZ`.

## Goals / Non-Goals

**Goals:**

1. Que exista un registro **durable y joineable** del instante en que un canal aceptó la
   notificación, del que la Batería 4 pueda derivar el intervalo que define.
2. Que ese registro se obtenga **sin degradar ni reinterpretar** ninguna marca existente, y en
   particular sin tocar la semántica de `delivered_at`.
3. Que la suite de backend deje de fallar por colisión de recursos ambientales, **sin que ninguna ruta
   de código de producción cambie de comportamiento**.
4. Que el arreglo del arnés sea **centralizado**: una vez, en un lugar, no 41 veces.
5. Que el protocolo de medición diga de dónde sale cada número, y que la serie anterior quede
   **declarada, no borrada**.

**Non-Goals:**

1. **Reducir el intervalo medido.** Esta change no optimiza nada. Mide bien lo que hoy se mide mal. Si
   el número nuevo resulta mejor o peor, se registra tal cual (D-10).
2. **Redefinir `delivered_at`.** Excluido de forma dura (D-2).
3. **Extender el contrato de la API de alertas ni el payload de notificación.** La marca es
   instrumentación, no superficie de producto (D-4).
4. **Backfill de la columna sobre filas históricas.** No hay dato del que derivarla (D-3).
5. **Convertir el puerto mTLS en un parámetro de despliegue.** El agente conoce el 8443; eso es otra
   change con su propia decisión (D-6).
6. **Ligar `notifier.n8n_sent` a la alerta.** La columna vuelve innecesario el join (D-1, alternativa
   B).
7. **Reescribir los 41 call sites de `TestClient`.** Excluido por D-5.
8. Reabrir D76/RN-170, D75/RN-169, D40/RN-134, D41/RN-135, D38/RN-132 ni RN-76.

## Decisions

### D-1 — La marca se captura en la corrutina, en el punto de éxito del envío, y se persiste en el `commit` que ya existe

**Decisión.** En los dos puntos de éxito de `notify_event` —`:428` cuando `await send_n8n(...)`
devuelve `True`, y `:447` cuando `await _try_fallbacks(payload)` devuelve `success`— la corrutina
evalúa `datetime.now(timezone.utc)` **antes de despachar nada al executor**, y pasa ese valor como
argumento a `_mark_delivered`, que lo escribe en la columna nueva dentro del **mismo `commit`** que
ya escribe `delivered_at`.

**Por qué acá y no en otro lado.** El punto de éxito de la corrutina es el primer instante del proceso
en que se sabe, con identidad de alerta a la vista (`alert.id` está en alcance), que un canal aceptó.
Todo lo que viene después —el despacho al executor, la espera en la cola FIFO del pool, el `Session`,
el `commit`— es exactamente lo que el protocolo excluye. Capturar acá y persistir después separa
**cuándo ocurrió** de **cuándo se escribió**, que es la distinción entera de esta change.

**Alternativas evaluadas y descartadas:**

- **(A) Que `send_n8n` devuelva el instante.** Es el punto estructuralmente más exacto: el
  `raise_for_status()` de `notifier.py:47`. Pero cambia el tipo de retorno de `bool` a algo compuesto,
  y con él las firmas de `send_smtp`, `send_webhook_fallback` y `send_log_only` para que la cascada
  sea homogénea, más sus call sites y sus tests. **Es una refactorización de la capa de transporte
  para ganar la latencia de un retorno de corrutina.** Descartada por desproporción, no por
  incorrección.

- **(B) Ligar el log `notifier.n8n_sent` a la alerta y joinear.** Requiere atravesar contexto por la
  firma de `send_n8n` —es decir, el mismo costo de (A) sin la marca durable— y produce evidencia en
  el log en vez de en la base. Y no resuelve el problema de raíz: bajo D76/RN-170 hay hasta 32
  entregas en vuelo, de modo que **ningún** join por proximidad temporal es una función. Descartada.

- **(C) Un `commit` propio, inmediatamente después del éxito.** Agrega un viaje al executor y una
  transacción por entrega en el camino caliente, para escribir un dato que ya va a viajar en el
  `commit` siguiente. Empeora exactamente la magnitud que se quiere medir. Descartada.

**Error residual, declarado.** Entre el `raise_for_status()` de `notifier.py:47` y el
`datetime.now(...)` de `service.py:428` hay: la emisión de una línea de log, el cierre del
`AsyncClient` de httpx (`notifier.py:45`) y el retorno de la corrutina. Es del orden de los
microsegundos a un milisegundo, contra una magnitud objetivo que el protocolo acota en segundos. **Se
declara como error conocido y acotado, no se oculta**, y se anota en el protocolo de medición. La
alternativa exacta es (A), y su costo está dicho arriba.

**Para la cascada de fallbacks vale lo mismo, con una aclaración.** `_try_fallbacks` (`:494-523`)
puede terminar en `smtp_fallback`, `webhook_fallback` o `log_only`. El instante capturado en `:447`
es el de aceptación del canal que haya ganado, con el mismo error residual. Para `log_only` la
"aceptación" es la escritura del log (`:520`), que es lo que ese canal significa; la marca sigue
siendo verdadera bajo la definición "el canal aceptó la notificación".

### D-2 — El nombre de la columna: `channel_accepted_at`

**Decisión.** La columna se llama **`channel_accepted_at`**.

**Fundamento.** El nombre tiene que hacer imposible una lectura que la confunda con `delivered_at`,
porque esa confusión es el defecto que esta change corrige y volvería a producirse en la primera
consulta SQL que alguien escriba de memoria. `channel_accepted_at` nombra **el actor** (el canal) y
**el acto** (la aceptación), y ninguno de los dos aparece en `delivered_at`.

**Alternativas evaluadas:**

- **`accepted_at`**: correcto pero peligroso. En una tabla que ya tiene `delivered_at` y `failed_at`,
  un `accepted_at` desnudo se lee como sinónimo de `delivered_at` —"aceptada" y "entregada" son
  intercambiables en castellano corriente— y la pregunta "¿cuál de las dos uso?" no tiene respuesta
  en el nombre. Descartada.
- **`emitted_at` / `dispatched_at`**: nombran el acto del **emisor**, no la respuesta del receptor. La
  marca existe precisamente porque el receptor confirmó; un nombre que sugiere "lo mandamos" la
  vuelve indistinguible de `backend_dispatched_at` (`notifier.py:41-44`), que es otra cosa y ya
  existe. Descartadas.
- **`webhook_accepted_at`**: correcto para n8n y falso para `smtp_fallback` y `log_only`, que también
  la escriben. Descartada por no cubrir la cascada.

**Léxico.** `snake_case` minúsculas, RN-71.

### D-3 — Columna anulable, sin backfill, sin índice

**Anulable.** Una alerta que todavía no fue entregada no tiene instante de aceptación, y una que
falló en todos los canales tampoco. `NULL` es la representación correcta de "no ocurrió", igual que en
`delivered_at` y `failed_at`.

**Sin backfill.** Las filas anteriores a la migración 022 **no tienen el dato y no se lo inventa**. El
único valor derivable sería `delivered_at`, que es precisamente la magnitud equivocada: escribirlo
ahí produciría una columna que parece medir lo que el protocolo pide y mide lo de siempre, con el
agravante de parecer verificada. Una alerta vieja tiene `channel_accepted_at IS NULL`, que es la
verdad.

**Sin índice.** La columna es material de análisis —un `COPY ... TO` sobre una ventana temporal— y no
predicado de ninguna consulta caliente. Los índices que la tabla necesita ya existen
(`ux_alerts_notification_id` e `ix_alerts_pending_delivery`, migración 014). Agregar uno acá sería
costo de escritura en el camino caliente por un beneficio que nadie pidió.

**Migración 022.** Número libre verificado contra `backend/db/migrations/`, cuyo máximo actual es
`021_add_agent_queue_pressure_high.sql`. Estilo idempotente (`ADD COLUMN IF NOT EXISTS`), mismo que
`014_add_alert_delivery_state.sql`. Tipo `TIMESTAMPTZ` por D39/RN-133.

### D-4 — `delivered_at` no cambia, y el contrato de la API tampoco

**`delivered_at`.** Sigue siendo el `datetime.now(timezone.utc)` evaluado dentro de `_mark_delivered`
(`:483`), en el hilo del executor. **No** se lo reemplaza por el valor capturado, **no** se lo deriva
de él y **no** se lo documenta como si hubiera significado otra cosa. Hay mediciones publicadas que
dependen de que signifique lo que significa; redefinirlo no corregiría la brecha, **invalidaría
retroactivamente evidencia ya emitida** y convertiría una corrección en una reescritura del registro.
Esta change **agrega una marca; no reinterpreta una**.

**La API.** `backend/app/modules/alerts/router.py:64` enumera los campos de su modelo de respuesta de
forma explícita, de modo que agregar una columna al modelo ORM no cambia ninguna respuesta por sí
sola — y **no se la agrega**. El estado derivado (`delivered` / `failed` / `pending`, `:82-83`) sigue
derivándose **sólo** de `delivered_at` y `failed_at`. Que `channel_accepted_at` quede fuera es
deliberado: es instrumentación de medición, y la superficie de producto no crece para acompañarla. Si
alguna vez la UI necesita el dato, eso es una decisión de producto propia.

**El payload.** No viaja en el payload canónico (D40/RN-134). `backend_dispatched_at`
(`notifier.py:41-44`) sigue siendo evidencia de transporte del lado del emisor, sellada
inmediatamente antes del request y explícitamente distinta de `received_at`; no se toca.

### D-5 — El arnés se arregla con una fixture centralizada, no editando 41 call sites

**Decisión.** Una única fixture en `backend/tests/conftest.py`, de aplicación automática, que
neutraliza el arranque del servidor mTLS del lifespan para todo test que lo ejecute. Los 41
`with TestClient(app)` **no se tocan**.

**Fundamento.** Los tres criterios apuntan al mismo lado:

1. **Cobertura por construcción.** Una fixture cubre los 41 call sites de hoy y **los que se escriban
   mañana**. Editar 41 sitios cubre 41 sitios; el 42.º vuelve a colisionar, y el modo de falla no
   nombra la causa (`RuntimeError: This portal is not running`), de modo que el próximo que lo sufra
   vuelve a diagnosticarlo desde cero.
2. **Superficie de revisión.** 41 ediciones mecánicas en cuatro archivos de test producen un diff en
   el que un cambio de comportamiento accidental pasa desapercibido. Una fixture es una unidad
   revisable.
3. **Precedente establecido.** El proyecto ya neutraliza exactamente esta función para tests que no
   necesitan un listener real: `backend/tests/test_rejected_events_retention.py:299-300` y
   `backend/tests/test_notify_isolate_executor_lifespan.py:46-47` hacen
   `monkeypatch.setattr(main_module, "start_mtls_server", lambda *a, **k: None)`. El mecanismo está
   probado en esta suite.

**Qué hace la fixture, exactamente.** La inmensa mayoría de esos 41 tests **no necesita un servidor
mTLS**: necesitan que el lifespan corra para que se abran los consumers y el resto del arranque. Para
ellos, neutralizar el arranque del servidor es suficiente y es lo más barato. Para el caso en que un
test **sí** necesita un listener real, el patrón correcto ya existe y no hay que inventarlo:
`backend/tests/test_mtls_transport.py:111-118` define

```python
def _free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    except PermissionError:
        pytest.skip("sandbox does not permit local TCP sockets")
```

y `:143-151` pasa `port=port` explícito. `backend/tests/test_agent_cert_renewal_e2e.py` usa el mismo
helper. Ese helper se promueve al conftest para que deje de estar duplicado, y los tests que necesitan
un listener lo piden explícitamente en vez de heredar un default global.

**Lo que la fixture NO hace: tocar producción.** `pki.py:638-645` conserva su firma y su default
`8443`; `main.py:92-97` conserva su invocación sin `port`. **Ninguna ruta de producción cambia de
comportamiento.** Es una obligación dura de esta change, no una preferencia: un arreglo de la suite
que altere producción convierte un defecto de instrumentación en un riesgo de producto, que es
exactamente el intercambio que esta change existe para no hacer.

### D-6 — El entorno de configuración se determina una sola vez, en el conftest, y se ataca el dotenv

**Decisión.** El conftest raíz garantiza que la suite parte de un entorno de configuración
**determinado**: ni las variables exportadas por el proceso que la invoca ni el archivo dotenv que
`config.py:40` resuelve contra el CWD pueden decidir el valor de una opción que un test afirma vacía.

**Por qué en el conftest.** Es donde el proyecto **ya** fija el entorno canónico, con el comentario
que explica por qué tiene que ser antes del primer import de la aplicación
(`backend/tests/conftest.py:51-66`):

> `Settings()` is instantiated at import time; these must be in the environment before the first
> import of `app.core.config`. Use direct assignment (not setdefault) so our values always win.

El defecto del caso B es el mismo problema con una fuente que ese bloque no contempla. El arreglo
pertenece al mismo lugar y al mismo momento.

**Por qué el `delenv` del test no alcanza, y qué se agrega.** `test_notification_settings.py:23-39`
ya borra las seis claves de `os.environ`, correctamente. Lo que ninguna limpieza de `os.environ`
puede hacer es impedir que pydantic-settings lea el archivo: `env_file` es una ruta relativa al CWD,
y el CWD de la corrida del arnés es la raíz del repositorio, que tiene un `.env` real. El saneamiento
que falta es el del **archivo**, y se hace una vez para toda la suite.

**Criterio de fail-fast heredado.** El conftest ya prefiere fallar temprano y fuerte antes que
degradar en silencio: `pytest_sessionstart` (`:37-49`) aborta la sesión si falta `psycopg`, con el
argumento de que 354 tests salteados en silencio reportan cero fallos y un lector concluye que la
suite está sana. **El mismo criterio aplica acá**: una suite cuyo resultado depende del directorio
desde el que se la invoca reporta un número que no describe el producto, y eso es peor que fallar.

**Lo que NO se hace.** No se cambia `config.py:39-43`. `env_file=".env"` es correcto y necesario para
el despliegue; el defecto no es que la aplicación lea su `.env`, es que la **suite** lo herede. El
arreglo es del arnés, igual que en D-5.

### D-7 — Las dos correcciones del defecto 2 son la misma regla, y se especifican juntas

**Decisión.** El puerto y el dotenv se especifican como **dos obligaciones de un único requisito** en
`backend-test-harness`, no como dos requisitos independientes.

**Fundamento.** Son el mismo enunciado: *una prueba no debe depender de un recurso ambiental
compartido con el sistema que la aloja*. Un puerto TCP y un archivo en el CWD son dos instancias de
"recurso ambiental compartido", y las dos producen la misma patología —fallas que no dicen nada del
producto, que aparecen y desaparecen según dónde y cuándo se corra la suite—. Escribirlas como dos
requisitos sin relación deja al lector del spec sin la regla, sólo con dos casos; y la próxima
instancia —un archivo temporal de ruta fija, un socket Unix, una variable de un `pytest.ini` heredado—
no queda cubierta por ninguno de los dos.

### D-8 — El protocolo de medición declara la serie anterior, no la reemplaza

**Decisión.** La Batería 4 de `tesis/plan_medicion_cap5.md` pasa a derivar sus ítems 11-22 de
`channel_accepted_at − received_at`, y **agrega una nota que declara explícitamente** qué eran los
números anteriores.

**Por qué explícito.** Las medianas de `delivered_at − received_at` —**13,170 s**, **11,671 s**,
**10,537 s**— **no son erróneas**: miden correctamente el intervalo recepción → persistencia del
éxito, que es una magnitud legítima y que bajo D76/RN-170 incluye la espera por un permiso del cupo.
Lo que era erróneo es haberlas presentado como si midieran lo que la Batería 4 define. Borrarlas y
poner otras en su lugar sin decir nada sería sustituir una tergiversación por un silencio. Quedan
declaradas como la serie de un intervalo distinto, con su nombre.

**La Fuente B también se corrige.** `:233-237` ofrece `notify.delivered` como *"emisión exitosa"*, y
no lo es: se emite después del `run_in_executor` de `_mark_delivered` (`service.py:432`, `:457`), de
modo que marca lo mismo que `delivered_at`. Dejarla como está mantendría en pie una segunda fuente
igual de equivocada, presentada como validación cruzada de la primera — es decir, dos errores que se
confirman entre sí.

### D-9 — El orden de implementación es una restricción, no una preferencia

La columna y la migración van **antes** que la captura; la captura **antes** que la actualización del
protocolo; y la re-medición **al final, con todo lo demás completo**.

Escribir la captura contra una columna que no existe produce un `ProgrammingError` en el primer evento
`high`. Actualizar el protocolo antes de que la columna tenga datos deja una batería que consulta
`NULL` en todas las filas y produce un CSV vacío, que es indistinguible de "el sistema no notificó".
Y medir sobre una implementación parcial produce un número que no corresponde a nada.

Las dos mitades de esta change —defecto 1 y defecto 2— son **independientes entre sí** y pueden
implementarse en cualquier orden relativo. Lo que no se puede es medir antes de que las dos estén.

### D-10 — La re-medición es obligatoria y no anticipa su resultado

Esta change **invalida el candidato congelado `v3.0-tesis`** por dos motivos distintos: cambia el
esquema y el camino de notificación (defecto 1), y cambia lo que la suite reporta (defecto 2). El
paquete `tesis/cierre/evidencia/v2-eval-20260923T010103Z/` deja de describir el binario.

Se re-corre el arnés unificado completo `~/fim-lab/corrida_unificada.sh` con `TAG=<tag-nuevo>` y se
emite un tag nuevo. El arnés de suites toma ahora `CAND`, `CAND_TAG` y `SUITES_OUT`
(`scripts/correr_suites_candidato.sh:22`), de modo que el paquete queda archivado bajo el candidato
que realmente se evaluó — el defecto que ese mismo script documenta en `:15-20` y que ya produjo una
vez artefactos de `v1.0-tesis` etiquetados como `v3.0-tesis`.

**No se declara ninguna mejora por anticipado.** Es esperable que el intervalo nuevo sea menor que
13,170 s, porque mide un subconjunto estricto de lo que medía el anterior — pero *"es esperable"* no
es un resultado, y esta change no existe para producir un número más chico sino para producir **el
número correcto**. Se implementa, se mide, y se registra lo que salga.

## Risks / Trade-offs

**El error residual de D-1 es real y hay que declararlo, no minimizarlo.** La marca se captura en el
retorno de la corrutina, no en el `raise_for_status()`. La alternativa exacta existe (D-1, alternativa
A) y se descartó por desproporción. Si en algún momento la magnitud objetivo bajara al orden del
milisegundo, ese descarte habría que reconsiderarlo — y en ese caso el número ya no sería defendible
sin (A). **Mitigación**: el error queda escrito en el protocolo de medición, con su cota y su causa,
en vez de vivir en la cabeza de quien implementó.

**Dos marcas de éxito en la misma fila invitan a la confusión que esta change corrige.** A partir de
ahora `alerts` tiene `channel_accepted_at` y `delivered_at`, y la próxima consulta que alguien escriba
de memoria puede tomar la equivocada — que es exactamente lo que pasó. **Mitigación**: el nombre elegido
las hace no intercambiables (D-2); el comentario de la migración y el del modelo dicen cuál es cuál y
para qué sirve cada una; y el protocolo de medición nombra la columna explícitamente en su SQL.

**Una fixture de aplicación automática puede alterar tests que hoy dependen del listener real.**
Neutralizar el arranque del servidor mTLS para todos los tests con lifespan podría romper alguno que
lo necesite. **Mitigación**: los que lo necesitan ya no dependen del default —`test_mtls_transport.py`
y `test_agent_cert_renewal_e2e.py` invocan `start_mtls_server` **directamente**, con `_free_port()` y
`port=` explícito, fuera del lifespan (`test_mtls_transport.py:143-151`)—, de modo que la fixture no
los toca. La verificación de que esto es así es una tarea, no un supuesto.

**Determinar el entorno de configuración puede romper tests que sin saberlo dependían del `.env`.** Si
algún test pasa hoy porque una variable del archivo le da el valor que espera, aislarlo lo hará
fallar. **Eso es el resultado correcto** —un test que pasa por el `.env` del desarrollador no estaba
probando nada—, pero puede aparecer como un aumento de fallas antes de convertirse en una reducción.
**Mitigación**: se corre la suite completa después del cambio y se clasifica cada falla nueva antes de
tocarla; ninguna se "arregla" devolviéndole la variable.

**El conteo de fallas de referencia cambia de sentido.** Hoy el capítulo informa 15 fallas de backend
sobre 864 tests. Después de esta change el número esperado es 0, pero **el número que se informe será
el que mida la corrida nueva**, no el esperado. **Mitigación**: D-10; y la corrida nueva se sella con
su procedencia igual que la anterior.

**El alcance combinado es mayor que el de una change de un solo defecto.** Toca esquema, camino de
notificación, arnés de pruebas, protocolo de medición y documentación canónica. **Mitigación**: las dos
mitades son independientes (D-9) y sus tareas están separadas por grupo, de modo que un problema en
una no bloquea a la otra; sólo la re-medición final las espera a las dos.

## Migration Plan

1. **Migración 022** (`ALTER TABLE alerts ADD COLUMN IF NOT EXISTS channel_accepted_at TIMESTAMPTZ`),
   idempotente y sin backfill. Se aplica antes de desplegar el código que la escribe.
2. **Compatibilidad hacia atrás.** Una columna anulable sin índice y sin constraint: un backend de la
   versión anterior corriendo contra el esquema nuevo funciona sin cambios —nunca la escribe y nunca
   la lee—. No hay ventana de incompatibilidad.
3. **Filas históricas.** Quedan con `NULL`. Toda consulta de la Batería 4 debe filtrar
   `channel_accepted_at IS NOT NULL`, y el protocolo lo dice explícitamente: una ventana temporal que
   incluya alertas anteriores a la migración produciría un `n` menor que el esperado, y hay que poder
   distinguir eso de "el sistema no notificó".
4. **Sin cambios de configuración.** Esta change no agrega ninguna variable de entorno ni cambia
   ningún default. Un despliegue existente no necesita tocar su `.env`.
5. **Rollback.** Revertir el código es suficiente; la columna puede quedar. Dropearla sólo sería
   necesario si se decidiera que el dato no debe existir, que no es el caso.

## Open Questions

**Ninguna suposición abierta que esta change necesite cerrar para avanzar.** Los dos defectos están
diagnosticados contra código leído y contra evidencia sellada, y las decisiones que toman —nombre de
columna, punto de captura, mecanismo del arnés— se cierran en D-1 a D-8 de este design y se elevan a
los appendices canónicos como **D77/RN-171** y **D78/RN-172**.

Se dejan anotadas dos cuestiones que **no bloquean** esta change y que quedan nombradas para que la
decisión esté en el registro:

- **Si la UI o la API deberían exponer `channel_accepted_at`.** D-4 decide que no, por ahora, con el
  argumento de que es instrumentación y no superficie de producto. Si el capítulo de evaluación
  terminara necesitando mostrarlo en pantalla, eso es una decisión de producto con su propia change.

- **Si el puerto del servidor mTLS debería ser un parámetro de despliegue.** Esta change lo hace
  inyectable para el arnés y deja producción intacta (D-5). Convertirlo en configuración real toca lo
  que el agente sabe del backend y excede el alcance.
