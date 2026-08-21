# n8n — qué debe hacer, qué hace hoy, y qué falta

**Propósito de este documento.** Reunir en un solo lugar (a) lo que la tesis compromete sobre la
orquestación de notificaciones, (b) el estado real del código y del despliegue, y (c) la lista
concreta de lo que falta. Está escrito para que otro agente pueda analizarlo y trabajar sobre él sin
tener que releer la tesis ni auditar el repositorio de cero.

**Estado en una línea:** la integración con n8n **no existe funcionalmente**. Hay tres archivos JSON,
una variable de entorno y un cliente HTTP que no se conocen entre sí, y un contenedor apagado.

Fuentes: `docs/Tesis.pdf` §2.7 (p. 14), §4.7 (pp. 38-40, Figura 6, Tabla 8), Anexo D (p. 79);
`docs/reglas_de_negocio.md` RN-52 a RN-54, RN-86, RN-87, RN-101, RN-102, RN-107, D23/RN-120;
auditoría del backend del 2026-08-20.

---

## 1. Lo que la tesis compromete

### 1.1 El componente

> «La integración con el motor de notificaciones se realiza mediante un componente interno
> denominado **NotificationDispatcher**, que desacopla al código de negocio del mecanismo concreto de
> entrega. Este componente opera con un **motor principal configurable, por defecto n8n**, y una
> cadena ordenada de alternativas de respaldo que se activan automáticamente ante indisponibilidad
> del principal.» — §4.7, p. 38

### 1.2 El flujo operativo, textual

> «Cuando un evento con severidad crítica o alta requiere notificación, el dispatcher primero
> verifica la salud del motor principal. Si n8n responde saludable, el dispatcher envía el webhook
> HTTP con payload JSON hacia el endpoint configurado de n8n, **que ejecuta el flujo de trabajo y
> reencamina la notificación hacia los canales configurados por el administrador**. Si n8n no
> responde saludable, o si el envío al endpoint falla, el dispatcher recorre la cadena de
> alternativas en orden preestablecido.» — §4.7, p. 39

La frase en negrita es el requisito central y el que hoy no tiene ninguna implementación: **n8n es un
enrutador**. Recibe un payload y lo abanica hacia los canales que el administrador configuró.

### 1.3 La cadena de precedencia (Tabla 8, p. 40)

| Prioridad | Mecanismo | Activación |
|---|---|---|
| Principal | Webhook HTTP hacia n8n | n8n saludable según healthcheck de 10 s |
| Alternativa 1 | SMTP directo (`aiosmtplib`) | n8n indisponible o envío fallido tras reintentos |
| Alternativa 2 | Webhook directo a plataforma de mensajería | Alternativa 1 no configurada o fallida |
| Alternativa 3 | Log estructurado con nivel crítico | Último esfuerzo previo a persistencia en DLQ |
| Persistencia final | Tabla `failed_notifications` | Todas las alternativas anteriores fallaron |

### 1.4 El healthcheck (Figura 6, p. 39)

- `GET /healthz` cada **10 s**.
- Caché del resultado durante **10 s**, para evitar sobrecarga.
- **Timeout corto (1 s)** para evitar bloquear.
- «n8n es pieza principal pero no crítica. **Su indisponibilidad no detiene el servicio de
  alertado.**»

### 1.5 Reintentos y DLQ

> «Las notificaciones hacia n8n emplean internamente un esquema de reintento exponencial de tres
> intentos con retardos de **cinco, treinta y ciento veinte segundos** antes de activar la cadena de
> fallbacks.» — §4.7, p. 40

Persistencia final en `failed_notifications` con: identificador del evento, payload, último error
registrado, timestamp de fallo y cantidad de reintentos. La interfaz muestra **banner persistente**
mientras la tabla contenga al menos una fila con **al menos tres reintentos fallidos**, y una vista
dedicada permite reintentar individualmente, descartar, o reintentar en lote.

### 1.6 Despliegue

Anexo D (p. 79): n8n con **volumen persistente** y **puerto administrativo restringido a la red
interna**.

---

## 2. Qué hace hoy

### 2.1 El contenedor está apagado

```
tesis-fim-serio-n8n-1   n8nio/n8n:2.16.1   Exited (0) 7 semanas
```

El servicio existe en `docker-compose.yml` pero **nadie lo levanta ni lo vigila**: ningún
`depends_on` del backend lo referencia y no tiene healthcheck. El puerto 5678 no se publica —
deliberado por D-04 — y **no hay ningún camino documentado para completar el setup de owner de
n8n 2.x**, que es obligatorio en el primer arranque antes de poder activar un workflow.

### 2.2 El webhook apunta a un endpoint de salud

```yaml
# docker-compose.yml:138
N8N_WEBHOOK_URL: ${N8N_WEBHOOK_URL:-http://n8n:5678/healthz}
```

`/healthz` responde 200 a cualquier POST, así que `send_n8n` retorna `True` y la alerta se marca
`delivered` con `channel="n8n"`. **Ese es el mecanismo que produjo 3.885 filas marcadas como
entregadas con n8n apagado hace siete semanas.**

El comentario del propio compose lo admite: *"DEMO PLACEHOLDER (no es la integración real)"*.

### 2.3 Sin canales configurados, todo se marca entregado

`.env` y `.env.example` **no declaran** `N8N_WEBHOOK_URL`, `SMTP_*` ni `WEBHOOK_FALLBACK_URL`. Un
despliegue limpio arranca con cero canales, y `_try_cascade` toma la rama
`any_primary_configured = False` y devuelve `(True, log_only)`: **todo se entrega, nada se envía, la
DLQ nunca se puebla y la escalera de reintentos nunca corre.**

D23/RN-120 razona esa rama como intencionada para dev/CI. El problema es que, al ser el estado por
defecto del producto, deja el mecanismo de garantía de entrega inactivo en el caso base.

### 2.4 Lo que sí está bien implementado

No todo falta. La cascada está correctamente escrita en `backend/app/modules/alerts/service.py`
(~líneas 170-206) y respeta el orden de RN-52/RN-86 y la semántica de D23/RN-120. La escalera
`RETRY_DELAYS = [5, 30, 120]` es correcta en forma. La DLQ tiene modelo, listado (`GET
/alerts/failed`), reintento y descarte. El healthcheck existe en `backend/app/core/health.py`.

Lo que falta es todo lo que está **fuera** del proceso del backend.

---

## 3. Los tres workflows: por qué ninguno funcionaría

`n8n/workflows/` contiene `email_alert.json`, `slack_alert.json` y `ticketing_alert.json`. Los
defectos son de tres clases y **cualquiera de ellas por sí sola los deja inoperantes**.

### 3.1 Contrato roto contra el backend

| Campo que leen los workflows | ¿Lo emite el backend? |
|---|---|
| `body.event_id`, `severity`, `path`, `agent_id`, `detected_at` | Sí |
| `body.status` | **No.** Renderiza vacío en los tres canales |
| `body.recipient` (destinatario del email) | **No.** Cae siempre al hardcodeado `security@example.com` |
| `body.ticketing_system` (routing Jira/Linear) | **No.** Cae siempre a `'jira'`; la rama Linear es inalcanzable |

Además, el payload que el backend emite (`alert_id`, `event_id`, `path`, `severity`, `agent_id`,
`detected_at`, `alert_created_at`) **no cumple** lo que RN-53 y US-23 exigen: faltan la **acción
tomada**, el **contexto de proceso** (`process_pid`, `process_uid`, `process_exe`) y `received_at`.
El contexto de proceso es el dato de mayor valor forense de un FIM y **nunca sale del sistema**.

### 3.2 Expresiones inválidas

- `{{ $json.body.severity | upper }}` — sintaxis de filtro **Jinja/Liquid**. Las expresiones de n8n
  son **JavaScript**: `| upper` se evalúa como OR bit a bit contra una variable inexistente. Aparece
  en el asunto del email, en el `summary` de Jira y en el `title` de Linear.
- `{{ $credentials.slackWebhookUrl }}` en un nodo que declara `"authentication": "none"` y **no tiene
  bloque `credentials`**. La URL resuelve vacía.
- Idem `{{ $credentials.jiraBaseUrl }}` y `{{ $credentials.jiraProjectKey }}`.
- Nodo *Route by System* (`switch`, typeVersion 3) con `"mode": "expression"` devolviendo un
  **nombre** cuando Switch v3 espera un **índice numérico**, y sin `numberOutputs`. No rutea.
- `"responseData": "firstEntryJson"` sólo es válido con `"responseMode": "lastNode"`; los tres usan
  `"onReceived"`.

### 3.3 Metadatos de importación

Los tres carecen de `id`, `active`, `versionId`, `meta` y `tags`, y llevan una clave no estándar
`__meta` en la raíz. Los `id` de nodo son `"1"`, `"2"`, `"3"` en vez de UUIDs, con riesgo de colisión
al importar los tres en la misma instancia. **Y como no traen `active: true`, tras importarlos quedan
inactivos**: un workflow inactivo sólo responde en la URL de prueba `/webhook-test/...`, no en
`/webhook/...`. Aun corrigiendo todo lo demás, el primer POST del backend daría 404.

### 3.4 No hay enrutador, y las URLs no coinciden con nada

`docs/arquitectura_stack.md:1295` documenta `POST http://n8n:5678/webhook/fim-alert`. Los tres
workflows declaran los paths `fim/alert/email`, `fim/alert/slack`, `fim/alert/ticket`. **Ninguno
coincide con el documento y ninguno coincide con otro.**

El backend tiene **una sola** `n8n_webhook_url`, así que como mucho **uno** de los tres puede recibir
tráfico. No existe el workflow enrutador que la tesis describe («ejecuta el flujo de trabajo y
reencamina la notificación hacia los canales configurados»): no hay un `fim-alert` que reciba una vez
y abanique a email, Slack y ticket según severidad.

### 3.5 Nada los importa

Verificado por búsqueda exhaustiva: **nada** monta `./n8n/workflows` en el contenedor, nada ejecuta
`n8n import:workflow`, no hay script en `scripts/`, no hay init container, y `docs/operations.md` no
describe el procedimiento. Las únicas instrucciones son prosa dentro del `__meta` de cada JSON
(«Import via n8n UI > Workflows > Import from file»), y **la UI no es alcanzable porque el puerto no
se publica**.

---

## 4. Qué falta — lista accionable

### 4.1 Contenedor y despliegue

1. **Variables mínimas que faltan en el servicio `n8n`** del compose:
   - `N8N_ENCRYPTION_KEY` — sin ella las credenciales quedan atadas a una clave autogenerada dentro
     del volumen; recrear el volumen las invalida **en silencio**.
   - `WEBHOOK_URL` (y `N8N_HOST` / `N8N_PROTOCOL`) — sin `WEBHOOK_URL`, la URL productiva que n8n
     muestra no es la que el backend debe llamar.
   - Autenticación de la UI administrativa.
2. **Healthcheck del servicio** (`GET /healthz`) y `depends_on: {n8n: service_healthy}` en `backend`.
   Hoy el backend no sabe si n8n existe.
3. **Setup de owner de n8n 2.x**: es obligatorio en el primer arranque y no está documentado ni
   automatizado. Definir si se resuelve por variables de entorno, por provisioning, o por un
   procedimiento manual documentado.
4. **Acceso administrativo**: el puerto 5678 no se publica por decisión (D-04), pero entonces hay que
   documentar cómo se administra n8n — túnel, `docker compose exec`, o publicación restringida a
   loopback.
5. **Volumen persistente**: ya existe (`n8n_data:/home/node/.n8n`). No hay que tocarlo.

### 4.2 Provisioning automático

6. Un servicio `n8n-init` en el compose, o `scripts/provision-n8n.sh`, que monte `./n8n/workflows` y
   ejecute `n8n import:workflow --separate --input=/workflows` más `n8n import:credentials`, de forma
   **idempotente**, con las credenciales tomadas del `.env`. Sin esto, los workflows son archivos que
   nadie carga.

### 4.3 Workflows

7. **Escribir un enrutador `fim-alert`** (webhook path `fim-alert`, coherente con
   `arquitectura_stack.md:1295`) que reciba el payload único del backend y abanique por severidad y
   configuración hacia los sub-flujos. Reescribir los tres existentes como sub-flujos invocados por
   él, no como tres webhooks paralelos e inalcanzables.
8. **Corregir cada expresión**: `.toUpperCase()` en lugar de `| upper`; bloques `credentials` reales
   en los nodos Slack, Jira y Linear; Switch v3 con `numberOutputs` y salidas por índice;
   `responseMode`/`responseData` coherentes; `active: true`.

### 4.4 Contrato del payload

9. **Ampliar `_build_payload`** (`backend/app/modules/alerts/service.py`, ~líneas 114-124) con
   `status`/`action_taken`, `process_pid`, `process_uid`, `process_exe`, `received_at`,
   `action_failed` e `is_symlink`. Decidir y unificar el nombre canónico (`path` vs `file_path`) y
   actualizar `docs/arquitectura_stack.md:1295-1305` en el mismo movimiento.
10. **Test de contrato** en la suite del backend: cargar los JSON de los workflows, extraer por
    expresión regular las referencias `$json.body.X` y afirmar que `X` está en el payload que
    `_build_payload` produce. Falla en CI ante cualquier deriva futura. **Es el test que habría
    detectado toda la sección 3.1**, y su ausencia es la razón por la que el contrato pudo divergir
    sin que nadie lo notara.

### 4.5 Configuración y verificabilidad

11. **Sacar el default `/healthz`** de `docker-compose.yml:138`. Sin `N8N_WEBHOOK_URL` explícito, el
    canal debe quedar **no configurado**, no falsamente sano.
12. **Llevar las ocho variables de notificación a `.env.example`** (`n8n_webhook_url`, `smtp_*`,
    `webhook_fallback_url`). Hoy existen en `Settings` y en `docs/operations.md`, pero configurarlas
    exige editar el compose en vez del `.env`.
13. **`send_smtp` fuerza `start_tls=True` incondicionalmente**
    (`backend/app/modules/alerts/notifier.py:70`). Un relay en 465 (SMTPS implícito) o uno interno
    sin STARTTLS falla siempre. Faltan `smtp_starttls` / `smtp_ssl` en `Settings`.
14. **`POST /alerts/test`** (admin) que dispare la cascada con un payload sintético y devuelva por
    qué canal salió y con qué error por canal. Hoy la única forma de verificar la configuración es
    esperar un evento `critical`/`high` real.

### 4.6 Durabilidad

15. **La notificación no sobrevive un reinicio.** `notify_event` vive sólo en una `asyncio.Task`
    fire-and-forget. El retry ladder dura hasta 155 s; si el proceso reinicia en esa ventana, la fila
    queda con `delivered_at IS NULL AND failed_at IS NULL` para siempre y nada la retoma — no aparece
    en la DLQ ni en el banner. **Hay una fila así en la base de producción.** Hace falta
    `next_retry_at` + `attempt` persistidos y una tarea de barrido en el lifespan.
16. **`retry_count` se sobrescribe con el índice del intento actual** en vez de acumular, y un
    reintento manual desde la DLQ lo resetea a 0. RN-86 pide el total histórico.
17. **`last_error` es genérico** (`"All channels failed on attempt N"`). El error real de cada canal
    se pierde en el log. RN-86 define `last_error` como el dato accionable de la DLQ; hoy no dice
    *qué* falló.

### 4.7 Cobertura que la tesis exige y no está

18. **RN-92: «sin heartbeat 5 min → `dead` + webhook n8n»** — ese webhook no existe. La única emisión
    hacia n8n por cambio de salud opera sobre el agregado «ok si alguno online», así que un agente
    que muere en una flota de dos no cambia el agregado y **no notifica nada**.
19. **La notificación de cambio de salud no pasa por la cascada**: llama `send_n8n` directo, sin
    retry, sin fallback, sin fila en `alerts`, sin DLQ. **Si n8n está caído —el escenario que motiva
    la alerta— la alerta de que n8n está caído se pierde.**
20. **`_check_n8n` hace fallback a `GET` sobre la misma URL del webhook** cuando HEAD devuelve
    404/405. El propio docstring lo admite: *«un GET a un webhook productivo puede disparar el
    workflow n8n»*. El health check puede emitir notificaciones espurias cada 10 s.

---

## 5. Riesgo para la defensa

La tesis se titula, en parte, por la orquestación de notificaciones; usa «SOAR» en sus palabras
clave; agradece explícitamente a los mantenedores de n8n; y la Tabla 15 (p. 50) consigna ya como
hecho, en la columna «Plataforma FIM», la fila **«Notificación automática con fallbacks: Sí»**.

Con el estado actual, esa afirmación **no es sostenible**: el contenedor está apagado, el webhook
apunta a un endpoint de salud, los workflows no son importables ni ejecutables, y nada los importa.

Además, la Batería 4 del Capítulo 5 (ítems 11-22, tiempos de notificación) se midió contra un
receptor de laboratorio propio (`scripts/receptor_webhook.py`), **no contra n8n**. Eso es correcto
según la definición del intervalo —el plan excluye explícitamente la entrega en n8n y el canal
final— pero **debe declararse**, y significa que la cascada, los reintentos y la DLQ siguen sin
evidencia empírica.

---

## 6. Orden sugerido de ataque

1. Puntos 11 y 12 (sacar el default falso, exponer la configuración). Es lo que hace que el sistema
   deje de **mentir** sobre el estado de las notificaciones. Barato y de mayor valor inmediato.
2. Punto 9 y 10 (payload completo + test de contrato). Sin el test, cualquier corrección de los
   workflows vuelve a divergir.
3. Puntos 1 a 6 (contenedor operable y provisioning). Es el bloque que convierte «hay tres JSON» en
   «hay una integración».
4. Punto 7 y 8 (enrutador y expresiones). Recién acá los workflows ejecutan.
5. Puntos 15 a 17 (durabilidad). Convierte la garantía de entrega en una propiedad del sistema y no
   de un proceso vivo.
6. Puntos 14, 18, 19 y 20 (verificabilidad y las brechas de RN-87/RN-92).
