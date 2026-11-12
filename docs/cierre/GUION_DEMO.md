# Guion de la demostración en vivo

Diapositiva: **«Qué vamos a mostrar»**. Cuatro escenas, unos 10 minutos.

Convenciones del documento:

- **Decir** = texto para leer en voz alta (español profesional neutro).
- **Tocar** = comandos y pantallas exactas.
- `[entre corchetes]` = en qué momento cae la frase respecto de la acción.
- Todo lo marcado en la sección final **⚠️ No verificado** no se ejecutó ni se leyó en el código: ensayarlo antes.

Fuente de cada dato: el código del repositorio (rutas citadas entre paréntesis). **No se ejecutó nada en esta sesión**: los comandos salen de lo que el código y los scripts del repositorio dicen que existe.

---

> **Puesta a punto del laboratorio:** los comandos para dejar el entorno en el estado
> inicial, volver a ese estado después de cada ensayo y resolver los problemas conocidos
> están en [PREPARAR_DEMO.md](PREPARAR_DEMO.md). Este archivo es el guion hablado.

## Antes de empezar

### 1. Topología: una sola máquina, agente nativo

Servidor (Docker Compose) y agente (systemd) en el mismo equipo Linux con núcleo 5.9 o superior (`uname -r`).
**No usar el agente contenedorizado del perfil `lab`**: usa un secreto por defecto y no es lo que midió la tesis.
Los pasos completos de instalación, borrado y generación del `.env` ya están escritos y verificados en:

- `tesis/PREPARATIVOS_VPS_DEMO.md` (preparar, probar el correo, dejar limpio)
- `tesis/GUION_VIDEO_DEMO.md`, Partes 1 a 4 (borrar agente y base, levantar, registrar, instalar)

Resumen mínimo de lo que tiene que quedar corriendo:

```bash
cd <ruta-del-repo>
# Todo comando de Compose lleva los DOS archivos (README, Regla 1)
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps      # certs-init debe figurar Exited (0)
curl -s http://127.0.0.1:8000/health/components | python3 -m json.tool               # todo en ok
systemctl status fim-agent                                                           # active (running)
```

### 2. Crear los archivos vigilados ANTES de instalar el agente

El agente toma la línea base (baseline cifrado) de lo que existe en el directorio vigilado al primer arranque (RN-15).
Un archivo creado después aparece como `file_created`, sin versión anterior que mostrar en el diff ni a la cual restaurar.
Por eso los tres archivos se crean antes de `agent/install.sh`:

```bash
sudo mkdir -p /srv/fim-watch/revision /srv/fim-watch/restaurar /srv/fim-watch/corte
echo "clausula=original"   | sudo tee /srv/fim-watch/revision/contrato.txt
echo "puerto=8080"         | sudo tee /srv/fim-watch/revision/configuracion.conf
echo "acceso=restringido"  | sudo tee /srv/fim-watch/restaurar/politica.txt
sudo chmod 644 /srv/fim-watch/revision/* /srv/fim-watch/restaurar/*
```

La ruta de vigilancia del agente es el directorio `/srv/fim-watch` (sin `/*`); el glob va en las reglas (README, Paso 18 y F.10).

Si el agente ya estaba instalado: Agentes, tarjeta del agente, sección de re-scan (US-22). Es más simple repetir la instalación limpia.

### 3. Reglas (se crean desde la consola, pantalla Reglas)

**No ejecutar `scripts/seed-reglas-lab.sh` antes de la demo.** Crea `/srv/fim-watch/*` con `alert_only`.
El agente evalúa las reglas en orden y toma la acción de la **primera** que coincide (`agent/rules.py`, `evaluate`): esa regla ancha podría ganarle a las de la demo.

Menú lateral: **Reglas** (título de la pantalla: «Reglas de monitoreo»). Botón **Nueva regla**. Campos: `Patrón`, `Severidad`, `Acción`. Botón **Crear regla**.

| Patrón | Severidad | Acción (texto del selector) | Para qué escena |
|---|---|---|---|
| `/srv/fim-watch/revision/*` | `high` | Revisión manual (`manual_review`) | 1 y 2 |
| `/srv/fim-watch/restaurar/*` | `medium` | Auto-restaurar (`auto_restore`) | 3 |

La columna **Sincronización** de la tabla debe decir `sincronizado` en ambas antes de seguir (la regla viaja al agente por `rule_sync`, US-18).
La carpeta `/srv/fim-watch/corte/` queda **sin regla** a propósito: sin regla coincidente el agente aplica `alert_only` por defecto (`agent/rules.py`, RN-06). Sirve para la escena 4.

### 4. Segundo operador (escena 2)

No hay pantalla de alta de usuarios en la consola: el alta es por API (`POST /users`, solo admin; `backend/app/modules/users/router.py`). El usuario se identifica por su correo, la contraseña exige 12 caracteres o más y la política RN-100, y el primer ingreso obliga a cambiarla.

```bash
API=http://127.0.0.1:8000
TOKEN=$(curl -fsS -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -fsS -X POST $API/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"operador2@demo.local","password":"<clave-de-12-o-mas-caracteres>"}'
```

Después, **ingresar una vez con ese usuario** en el navegador B y completar el cambio obligatorio de contraseña (pantalla «Cambiar contraseña», US-27). Hacerlo antes de grabar.

### 5. Ventanas, en este orden de pantalla

| Ventana | Contenido |
|---|---|
| Terminal 1 (izquierda, arriba) | Comandos de la demo, directorio del repo |
| Terminal 2 (izquierda, abajo) | `sudo journalctl -u fim-agent -f \| rg 'decision.evaluated\|publisher\.(event_published\|unsent_drain_stopped\|queue_drained)'` |
| Navegador A (derecha) | Perfil normal, sesión `admin`, en `https://<host>/events` |
| Navegador B (escena 2) | **Otro navegador, o ventana de incógnito del mismo**, sesión `operador2@demo.local` |

Detalles de la sesión doble:

- Dos pestañas del mismo navegador **no sirven**: comparten la cookie de refresco. Usar ventana de incógnito o un segundo navegador.
- En incógnito hay que aceptar el aviso del certificado autofirmado una vez, antes de grabar.
- Se usan dos usuarios distintos (no dos sesiones del mismo): en el detalle quedará «Resuelto por (ID de usuario)» con el de quien ganó.
- Rate limit de login: 5 intentos fallidos en 15 minutos bloquean el usuario (README, Paso 8). No probar contraseñas a ciegas.

### 6. Lista de comprobación final

- [ ] `/health/components` en `ok` y `systemctl is-active fim-agent` = `active`.
- [ ] Reglas creadas y en `sincronizado`; no existe regla `/srv/fim-watch/*`.
- [ ] Los tres archivos existen con su contenido original (`cat` de cada uno).
- [ ] Sesiones abiertas: A (`admin`) y B (`operador2`), ambas con el cambio de contraseña ya hecho.
- [ ] Eventos limpios para la demo (base recién creada) o, al menos, saber qué hay en la lista.
- [ ] Ensayo completo hecho una vez: **una escena que ya consumió sus archivos hay que rearmarla** (restaurar contenido original; el evento de aprobación cambió el baseline de `contrato.txt`).

---

## Escena 1 · Aprobar y rechazar

**Qué demuestra:** estado `pending` por regla de revisión manual (RN-12, RN-13, RN-14), diff del evento (US-09), aprobación (US-11, RN-16/D2) y rechazo con restauración (US-12, RN-26, RN-28), máquina de estados (RN-71, RN-72) y ACK del comando (RN-73).

### Preparación

Reglas de la sección «Antes de empezar» en `sincronizado`. En el navegador A: **Eventos**. Terminal 2 visible.

### Acciones

1. Navegador A, menú **Reglas**: mostrar la regla `/srv/fim-watch/revision/*` con acción «Revisión manual» y sincronización `sincronizado`.
2. Terminal 1, modificar los dos archivos:

   ```bash
   echo "clausula=MODIFICADA" | sudo tee -a /srv/fim-watch/revision/contrato.txt
   echo "puerto=9999"         | sudo tee -a /srv/fim-watch/revision/configuracion.conf
   ```

3. Navegador A, menú **Eventos**. La lista se refresca sola cada 15 s (`useEvents.ts`) y también al llegar una alerta; si no aparecen, recargar. Deben verse dos filas con la insignia **Pendiente `pending`**.
4. Clic en la ruta de `contrato.txt` (columna **Ruta**) para abrir `/events/<id>`. Mostrar, de arriba abajo: insignia de estado, **Severidad** `high`, la sección **Proceso que generó el evento** (PID, UID, Ejecutable), y **Diferencias de contenido** (parche unificado con la línea agregada).
5. Clic en **Aprobar**. Aparece el aviso «Evento aprobado» y la insignia pasa a **Aprobado `approved`**. Aparece «Resuelto por».
6. Volver (**Volver**) a **Eventos** y abrir `configuracion.conf`. Clic en **Rechazar**: se abre el modal «Rechazar evento».
7. En el modal dejar marcada la opción **Restaurar archivo (volver al baseline)** y pulsar **Confirmar rechazo**. Aviso: «Rechazo registrado; restauración solicitada».
8. En el detalle aparece la sección «Ejecución del comando»: primero «Esperando la confirmación del agente...», luego «El agente confirmó la ejecución.» (la pantalla consulta cada 3 s, hasta 60 s). Insignia: **Rechazado `rejected`**.
9. Terminal 1, comprobar el efecto en disco:

   ```bash
   cat /srv/fim-watch/revision/configuracion.conf   # vuelve a "puerto=8080"
   cat /srv/fim-watch/revision/contrato.txt         # conserva "clausula=MODIFICADA" (aprobado)
   ```

### Guion

> [al mostrar la regla] «Esta regla indica que cualquier cambio en esta carpeta requiere una decisión humana. Es la acción de revisión manual.»
>
> [mientras ejecuta los dos comandos] «Voy a modificar dos archivos vigilados. Uno es un contrato; el otro, una configuración.»
>
> [al aparecer las dos filas] «Ambos eventos llegan en estado pendiente. El sistema no decide: espera a un operador.»
>
> [en el detalle, sobre el diff] «Antes de decidir, el operador ve qué cambió, qué proceso lo hizo y con qué usuario. Aquí está la diferencia exacta de contenido.»
>
> [al pulsar Aprobar] «Este cambio es legítimo. Al aprobarlo, el baseline pasa a considerar este contenido como el estado válido.»
>
> [en el segundo evento, al abrir el modal] «Este otro no estaba autorizado. Al rechazarlo elijo la acción correctiva: restaurar el archivo desde el baseline cifrado.»
>
> [cuando aparece “El agente confirmó la ejecución”] «El servidor envía una orden firmada. El agente la ejecuta y confirma. No damos el cambio por hecho hasta recibir esa confirmación.»
>
> [al mostrar los dos `cat`] «El archivo rechazado volvió a su contenido original. El aprobado conserva el cambio.»

### Qué mirar en pantalla

La insignia `Pendiente pending` → `Aprobado approved` / `Rechazado rejected`; el diff; el texto «El agente confirmó la ejecución.»; y los dos `cat` en la terminal.

### Si falla

Si el evento tarda, recargar **Eventos**; si el rechazo queda en «Esperando...», pulsar **Actualizar** en esa sección y revisar la Terminal 2 (`journalctl -u fim-agent`). Como último recurso, mostrar el mismo flujo ya grabado.

---

## Escena 2 · Dos operadores

**Qué demuestra:** bloqueo optimista por versión: `UPDATE ... WHERE id AND version AND status='pending'`, y si afecta 0 filas, HTTP 409 (RN-77, C5). Sólo se resuelve el último evento accionable (RN-22, RN-24). Criterio explícito en US-11 y US-12.

### Preparación

Hace falta un evento `pending` **nuevo** (el de la escena 1 ya fue resuelto). Con un solo archivo basta:

```bash
echo "clausula=SEGUNDA-MODIFICACION" | sudo tee -a /srv/fim-watch/revision/contrato.txt
```

Esto crea un evento `pending` nuevo para `contrato.txt`. Importante: **no tocar el archivo de nuevo** durante la escena, porque un segundo cambio sobre el mismo archivo con un evento `pending` genera la cadena y el anterior pasa a `superseded` (RN-21), lo cual también produciría un 409, pero por otra causa.

### Acciones

1. Navegador A y navegador B, ambos con sesión iniciada en usuarios distintos, **abrir el mismo evento pending** en `/events/<id>`. Ambos muestran los botones **Aprobar** y **Rechazar**.
2. **Recargar la página en B** (F5) justo antes de continuar. Motivo: los datos de la pantalla se consideran frescos durante 30 s (`staleTime` en `queryClient.ts`); pasado ese tiempo, al volver el foco a la ventana se refrescan solos y el botón desaparecería antes de poder provocar el conflicto. Ver «No verificado».
3. En A: clic en **Aprobar**. Aviso «Evento aprobado».
4. En B, dentro de los 30 s: clic en **Aprobar** (no en Rechazar: ver «No verificado»).
5. B recibe HTTP 409 y muestra el aviso exacto: **«Este evento ya fue resuelto o reemplazado. Refrescando lista...»**. Inmediatamente la pantalla se vuelve a consultar: la insignia pasa a **Aprobado `approved`**, los botones **Aprobar** / **Rechazar** desaparecen y aparece «Resuelto por (ID de usuario)» con el usuario de A.

Respuesta del backend en el 409 (`backend/app/modules/actions/router.py`):

```json
{"detail": {"code": "conflict", "detail": "event already modified or not pending"}}
```

Opcional, para mostrar el código HTTP (DevTools de B, pestaña Network, `POST /api/actions/approve` o la URL equivalente de la consola): estado 409.

### Guion

> [al abrir el mismo evento en las dos ventanas] «Dos operadores abren el mismo evento pendiente. Cada uno ve el estado que había al cargar la página.»
>
> [al aprobar en A] «El primer operador aprueba. Su decisión se registra.»
>
> [al aprobar en B] «El segundo operador decide sobre una vista que ya quedó desactualizada.»
>
> [al aparecer el aviso] «El servidor rechaza la segunda orden con un error 409, conflicto. Cada decisión viaja con la versión del evento que el operador vio; si esa versión ya no coincide, no se aplica.»
>
> [al refrescarse la pantalla] «La consola se actualiza sola y muestra el resultado real: el evento ya está aprobado, y por quién. No se pierde ni se duplica ninguna decisión.»

### Qué mirar en pantalla

Las dos ventanas lado a lado; el aviso rojo de B; el cambio de insignia en B a `Aprobado approved`; la desaparición de los botones; el campo «Resuelto por».

### Si falla

Si B llega a refrescarse antes de pulsar y no hay conflicto, generar otro evento `pending` y repetir con B recargado a menos de 30 s. Alternativa determinista por API, que dispara dos aprobaciones del mismo evento con la misma versión (solo una gana; la otra devuelve 409):

```bash
# EVENT_ID y VERSION: los de un evento pending (VERSION se ve en el detalle: «Versión (bloqueo optimista)»)
for i in 1 2; do
  curl -s -o /dev/null -w "intento $i -> HTTP %{http_code}\n" -X POST $API/actions/approve \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"event_id\":$EVENT_ID,\"version\":$VERSION}" &
done; wait
```

(`$API` y `$TOKEN` como en «Segundo operador».) Resultado esperado: un `200` y un `409`.

---

## Escena 3 · Restauración automática

**Qué demuestra:** acción `auto_restore` sin intervención humana: restauración desde el baseline cifrado AES-256-GCM (RN-30, RN-31), verificación posterior por hash (RN-32), el baseline no cambia (RN-33), y el estado terminal `auto_restored` se deriva en el servidor (RN-13, D35/RN-129). No hay una historia de usuario específica para esta acción: se cubre con las reglas.

### Preparación

Regla `/srv/fim-watch/restaurar/*` con acción «Auto-restaurar» en `sincronizado`. Contenido original: `acceso=restringido`.

### Acciones

1. Terminal 1:

   ```bash
   cat /srv/fim-watch/restaurar/politica.txt                       # acceso=restringido
   echo "acceso=publico" | sudo tee -a /srv/fim-watch/restaurar/politica.txt
   sleep 2
   cat /srv/fim-watch/restaurar/politica.txt                       # vuelve a acceso=restringido
   ```

   Usar `tee -a` (una sola escritura), no el `tee` sin `-a`.
2. Terminal 2 muestra la línea `decision.evaluated ... action=auto_restore action_failed=False` (`agent/decision.py`).
3. Navegador A, **Eventos**: marcar el filtro de estado **Restaurado `auto_restored`** (o desmarcar los demás). Fila con la insignia **Restaurado `auto_restored`**.
4. Abrir el evento. Mostrar: **Tipo de acción** `auto_restore`, la insignia de estado y el diff de lo que alguien intentó cambiar. **No hay botones Aprobar ni Rechazar** (solo se resuelve un evento `pending`).

### Guion

> [antes de modificar] «Esta carpeta tiene una regla distinta: restauración automática. Aquí no se espera a nadie.»
>
> [mientras ejecuta el comando] «Modifico la política de acceso.»
>
> [tras el segundo `cat`] «En menos de un par de segundos, el archivo ya está como estaba. El agente lo restauró desde su copia cifrada y verificó que el contenido coincide con el original.»
>
> [en el detalle del evento] «El incidente queda registrado como restaurado, con el diff de lo que se intentó. El operador se entera, pero no tiene que intervenir.»

### Qué mirar en pantalla

El segundo `cat` (contenido original), la línea `action=auto_restore` en el log, la insignia `Restaurado auto_restored` y la ausencia de botones de decisión.

### Si falla

Si el archivo no vuelve a su contenido, mirar en el evento la causa: aparece un cuadro «Causa: ...» (por ejemplo, permiso denegado o no hay contenido de baseline) y el evento queda `pending` con los botones de decisión (RN-129). Explicarlo como el comportamiento previsto ante un fallo y resolverlo con **Rechazar** y **Restaurar archivo**.

---

## Escena 4 · Corte de Valkey

**Qué demuestra:** cola offline en disco del agente, escritura atómica y cifrada (RN-38, RN-84); envío en orden FIFO al reconectar sin adelantar eventos (RN-39, D79/RN-173); borrado de la cola solo tras el `event_ack` del servidor (RN-40, RN-73); reintento deduplicado por `event_id` (RN-40, RN-73; el campo `event_id` es único en la tabla de eventos).

### Preparación

La carpeta `/srv/fim-watch/corte/` está vacía y sin regla. Opcional, en el navegador A: **Eventos**, campo **Prefijo de ruta** = `/srv/fim-watch/corte` (el filtro es por prefijo literal, RN-185). Terminal 2 con el log del agente visible.

### Acciones

1. Detener Valkey (con los dos archivos de Compose):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tls.yml stop valkey
   ```

   En la consola, hasta unos 10 s después, aparece el aviso rojo «Sistema degradado — valkey ... no disponible» (la consola consulta el estado cada 10 s).
2. Hacer varios cambios, uno por archivo, de a uno por segundo:

   ```bash
   for i in 1 2 3 4 5; do
     sudo touch /srv/fim-watch/corte/archivo_$i.txt
     sleep 1
   done
   ```

3. Mostrar la cola en disco y **anotar el número**:

   ```bash
   sudo ls /var/lib/fim-agent/queue | wc -l
   sudo ls /var/lib/fim-agent/queue            # nombres: {detected_at_epoch_ms}_{event_id}.json
   ```

   Los nombres empiezan con la marca de tiempo de detección, por eso se ordenan en el orden en que ocurrieron los cambios. El contenido está cifrado: no se puede leer a simple vista.
4. En el navegador A el listado del prefijo `/srv/fim-watch/corte` sigue **vacío**.
5. Levantar Valkey de nuevo:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tls.yml start valkey
   ```

6. Pocos segundos después, en **Eventos** aparecen las filas. Recargar si hace falta.
7. Comprobar orden y ausencia de duplicados contra la base:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T db psql -U fim -d fim -c \
     "SELECT id, path, detected_at FROM events WHERE path LIKE '/srv/fim-watch/corte/%' ORDER BY id;"
   docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T db psql -U fim -d fim -c \
     "SELECT event_id, count(*) FROM events GROUP BY 1 HAVING count(*) > 1;"
   sudo ls /var/lib/fim-agent/queue | wc -l    # la cola vuelve a 0
   ```

   La primera consulta debe dar tantas filas como el número anotado en el paso 3, con `detected_at` creciente. La segunda debe devolver 0 filas.

### Guion

> [al detener Valkey] «Voy a cortar el broker de mensajes, el canal por el que el agente le habla al servidor.»
>
> [mientras ejecuta el bucle] «Mientras tanto, el host sigue cambiando. El agente no deja de detectar.»
>
> [al mostrar la cola] «Cada evento se guarda en disco, cifrado, con la marca de tiempo de detección en el nombre del archivo. Hay N eventos esperando.»
>
> [mirando la lista vacía] «El servidor no sabe nada de ellos todavía.»
>
> [al levantar Valkey] «Restablezco el servicio.»
>
> [al aparecer los eventos] «El agente reenvía en orden de detección, sin adelantar eventos nuevos al backlog. Un archivo de la cola se borra únicamente cuando el servidor confirma que lo guardó.»
>
> [al mostrar la consulta SQL] «Llegaron los N, en orden, y ninguno está duplicado: si un evento se reenvía, el servidor lo reconoce por su identificador y lo descarta.»

### Qué mirar en pantalla

El aviso de sistema degradado; el contador de la cola (`wc -l`); el listado vacío; las filas apareciendo; la consulta SQL (N filas, `detected_at` creciente, cero duplicados); la cola en 0.

### Si falla

Si los eventos no llegan en 30 s: `docker compose -f docker-compose.yml -f docker-compose.tls.yml ps valkey` y verificar que se levantó **con el archivo `docker-compose.tls.yml`** (sin él, el puerto 6380 no se publica y el agente queda sin transporte; README, F.1). El backend reintenta solo cada segundo (`consumer.loop_error` en su log) y no hace falta reiniciarlo.

---

## Cierre

> «Mostramos cuatro garantías del sistema. Que ningún cambio sensible se resuelve sin una decisión explícita y trazable. Que dos operadores no pueden pisarse. Que lo crítico puede repararse sin intervención humana. Y que un corte de infraestructura no hace perder detecciones. Paso ahora a las conclusiones.»

Volver a la diapositiva siguiente.

---

## Tiempos sugeridos

| Escena | Duración objetivo | Nota |
|---|---|---|
| 1 · Aprobar y rechazar | 3:00 | Es la más larga; no explicar el modal de más |
| 2 · Dos operadores | 2:00 | Tener los dos navegadores ya abiertos en el evento |
| 3 · Restauración | 1:30 | La más corta y la más visual |
| 4 · Corte de Valkey | 3:00 | Incluye el corte y el regreso; la consulta SQL se puede mostrar rápido |
| Cierre | 0:30 | |
| **Total** | **10:00** | Dejar 1 minuto de margen para imprevistos |

---

## ✅ Ensayo del 12/11/2026 — qué quedó verificado

Las cuatro escenas se corrieron de punta a punta contra el stack local, con el **agente
en Docker** (`--profile lab`) vigilando `/watch` (bind mount de `./fim-watch`), no con la
instalación nativa sobre `/srv/fim-watch`. El comportamiento de producto es el mismo; lo
que NO quedó probado por esta vía está al final.

| Escena | Resultado |
|---|---|
| 1 · Aprobar y rechazar | ✅ Dos archivos modificados → **exactamente un evento `pending` por archivo**, `severity: high`, con `diff_text` completo. Aprobar devuelve `{"status":"approved"}`; rechazar con `action: "restore"` devuelve `{"status":"rejected"}` y **el agente revirtió el archivo en disco**. |
| 2 · Dos operadores | ✅ Dos `POST /actions/approve` concurrentes sobre el mismo evento con la misma `version`: uno **HTTP 200**, el otro **HTTP 409** con `{"code":"conflict","detail":"event already modified or not pending"}`. |
| 3 · Restauración | ✅ Archivo bajo regla `auto_restore` modificado → evento único en estado `auto_restored`, `severity: critical`, `action_failed: false`, **la línea agregada desapareció sola** y el evento **sí trae el diff completo**. |
| 4 · Corte de Valkey | ✅ Con Valkey detenido, 5 cambios → **5 archivos en `/var/lib/fim-agent/queue`, uno por cambio**, con prefijo secuencial monótono. Al reiniciar Valkey: los 5 eventos ingresaron **en el mismo orden de escritura**, la cola quedó en 0 y **no hubo duplicados**. Drenaje completo: **43 s** desde `start valkey` (incluye arranque del contenedor y healthcheck). |

### Datos concretos para el guion

- **`detected_at` vs `created_at`.** En la escena 4 los eventos conservan la hora real de
  detección (12:37:08 → 12:37:12) aunque hayan ingresado un minuto más tarde
  (12:38:10 → 12:38:15). Es el mejor argumento visual de que la cola no pierde información
  temporal: **mostrar las dos columnas**.
- **Rechazar obliga a elegir.** `RejectRequest` exige `action`, con dos valores posibles:
  `restore` o `quarantine`. No es un rechazo a secas.
- **Aviso de degradado.** La consola consulta `GET /health/components`. Con Valkey caído
  devuelve `"valkey": "down"` (el `GET /health` simple sigue devolviendo `ok`: no sirve
  para la demo).
- **Orden de evaluación de reglas.** Gana la **primera que coincide**; el default es
  `alert_only` (RN-06, `agent/rules.py:61-72`). `GET /rules` las devuelve ordenadas por
  severidad y después por patrón.
- **Mensaje del 409 en pantalla:** `Este evento ya fue resuelto o reemplazado. Refrescando
  lista...` (`frontend/src/hooks/useEventActions.ts:51`).

### Tres cosas que hay que arreglar ANTES de grabar

1. **Agente fantasma.** La base tiene un agente `fim-vm` en estado `dead` de una corrida
   vieja. El dashboard lo muestra como «1 agente caído» y mete ruido en la escena de
   apertura. Borrarlo antes de grabar.
2. **`FIM_VALKEY_URL` no lo lee nadie.** `docker-compose.tls.yml:98` define esa variable
   para el servicio `agent`, pero el agente sólo lee `/etc/fim-agent/config.yaml`
   (`agent/config.py:108`); la variable no aparece en ningún lado de `agent/`. Con el
   overlay TLS activo, el agente Docker intenta `valkey://valkey:6379`, que ya no escucha,
   y queda sin publicar. **Hay que corregir `valkey_url` en el archivo de config**, no en
   el entorno.
3. **Stream de comandos sin recortar.** El stream `commands` tenía **265.422 entradas**
   acumuladas y `agent_heartbeat` 255.204, mientras que `events` está recortado en 400. Un
   agente que arranca sin checkpoint los reprocesa todos, uno por uno, fallando la firma
   —tarda más de 15 minutos en llegar al presente—. Antes de grabar, recortar esos dos
   streams o arrancar con el checkpoint puesto.

### Qué NO prueba este ensayo

- La instalación nativa (`agent/install.sh`): usuario de sistema, unit de systemd,
  capacidades y el drop-in `ReadWritePaths`.
- La restauración sobre archivos propiedad de `root` (en el ensayo eran del usuario).
- El 409 **a través de la interfaz** con dos navegadores: se verificó a nivel de API y se
  leyó el texto exacto del aviso en el código, pero no se vio el aviso en pantalla.
- Los tiempos de aparición del cartel «Sistema degradado» en la consola.
- El envío de correo por n8n ante una regla `high`.

---

## ⚠️ No verificado

Lo siguiente **no se ejecutó** o **no se pudo confirmar** leyendo el repositorio. Ensayar antes de la defensa.

1. ~~**Nada se ejecutó.**~~ **Resuelto el 12/11/2026**: las cuatro escenas se corrieron con el agente en Docker. Ver «Ensayo del 12/11/2026» más arriba. Lo que sigue en esta lista es lo que ese ensayo **no** cubrió.
2. **Falta de una pantalla para crear usuarios.** El segundo operador se da de alta por API. No encontré ninguna otra vía. Tampoco confirmé de forma empírica que dos usuarios distintos puedan tener sesión simultánea, aunque no encontré ninguna restricción de sesión única en el login (`backend/app/modules/auth/router.py`).
3. **Condición de carrera humana.** «Casi a la vez» con dos personas no es concurrencia real: el 409 se produce porque la ventana B actúa sobre una vista vieja. Que B siga mostrando los botones depende de que su dato tenga menos de 30 s (`staleTime`) o de que no regrese el foco; es una deducción del código, no una observación. La alternativa con `curl` sí es concurrente.
4. **Rechazar desde B.** En el código, si el rechazo devuelve 409, el modal «Rechazar evento» no se cierra por sí solo (el cierre está sólo en `onSuccess`, `EventDetail.tsx`). Por eso se usa **Aprobar** en B. No lo probé en pantalla.
5. ~~**Diff en el evento `auto_restored`.**~~ **Verificado**: el evento `auto_restored` trae `diff_text` completo y el detalle lo renderiza lado a lado.
6. ~~**Eventos por archivo.**~~ **Verificado**: una escritura completa (`printf > archivo`) genera **exactamente un evento**. Con `touch` o `tee -a` sigue sin estar medido, así que usar reescritura completa en la demo.
7. ~~**Orden de llegada.**~~ **Verificado para 5 eventos**: los nombres de archivo de la cola llevan un prefijo secuencial monótono y los `id` de la base salieron en el mismo orden de escritura, sin duplicados. No se probó con carga alta ni con escrituras concurrentes.
8. **Tiempos.** No medí cuánto tarda en aparecer el aviso «Sistema degradado» tras cortar Valkey (el sondeo es de 10 s, pero depende de cómo el backend determine que Valkey no está disponible). Tampoco el tiempo de drenaje de la cola: la tesis reporta mediana de 35 s con carga alta; con cinco eventos debería ser de segundos, pero es una estimación.
9. **Restauración sobre archivos de `root`.** Depende de las capacidades del servicio y del drop-in `ReadWritePaths` generados por `agent/install.sh`. Probar el rechazo con restauración y la auto-restauración sobre estos archivos en el ensayo.
10. **Subdirectorios en la línea base.** Asumo que el escaneo inicial del agente es recursivo sobre `/srv/fim-watch` (coincide con lo que dicen README y las guías previas). No leí `agent/baseline.py` para confirmarlo.
11. **Correo y n8n.** No verifiqué qué ocurre con la regla `high` si el canal de n8n no está configurado. Con la configuración de `tesis/PREPARATIVOS_VPS_DEMO.md` debería enviarse un correo; sin ella, la severidad `high` puede dejar alertas fallidas. Si molesta, usar `medium` en la regla de revisión manual (solo cambia que no habrá alerta).
12. **Historias de usuario.** No hay una US específica para auto-restauración ni para la cola offline. Para esas dos escenas se citan las reglas de negocio (RN-30 a RN-33 y RN-38 a RN-40). La cola offline figura como «W3» en el apéndice de decisiones.
13. **Reglas de negocio que se contradicen.** RN-16 y RN-17 dicen que al aprobar se hashea el archivo actual; la decisión D2 (que prevalece) establece que se usa el hash del evento. Si el jurado pregunta, citar D2/US-11.
14. **El directorio `docs/cierre/` no existía** y se creó para este archivo. El resto de la documentación de cierre vive en `tesis/`.
