# Guion del video de demostración y procedimiento de borrado

Objetivo: mostrar el prototipo funcionando de punta a punta en un entorno controlado, partiendo de
cero, con una prueba de notificación por severidad a una dirección de correo propia.

Todas las rutas, nombres de servicio y comandos de este documento están verificados contra el
código del repositorio, no supuestos.

---

## Parte 0 — Tres cosas que hay que saber antes de planificar

### El destinatario del correo NO es el usuario administrador

Los dos canales toman la dirección de destino de una **variable de entorno global**:

| Canal | Variable | Dónde |
|---|---|---|
| n8n (primario) | `N8N_EMAIL_TO` | servicio `n8n` en el compose |
| SMTP del backend (respaldo) | `SMTP_TO` | servicio `backend` en el compose |

En el flujo de trabajo de n8n el campo es literalmente `toEmail = __FIM_ENV_N8N_EMAIL_TO__`, y en el
backend es `msg["To"] = cfg.smtp_to`. **Ninguno consulta la tabla de usuarios.** Es una sola dirección
para toda la instalación.

Para el video eso simplifica: cambiar de destinatario es cambiar una variable, sin tocar usuarios.
Conviene, eso sí, **declararlo como limitación** en la defensa: hoy no se puede enrutar las críticas a
un equipo y las medias a otro.

Ventaja para la prueba de severidad: el asunto del correo **ya la lleva**.

```
[FIM Alert] CRITICAL — /srv/fim-watch/critico/passwd
```

Se ve en la bandeja de entrada sin abrir el mensaje. En cámara queda muy bien.

### Solo `critical` y `high` generan alerta

Por RN-52, una regla con severidad `medium` o `low` produce evento pero **no** alerta y **no** correo.
Si en el video tocás un archivo que cae en una regla `low`, va a aparecer en el panel y no va a llegar
ningún mail. No es una falla: es la política.

### Mailpit no es parte del despliegue

No está en `docker-compose.yml` ni en `docker-compose.tls.yml`. Se usó sólo como sumidero desechable
para las mediciones de la tesis. **Para el video, con un correo real, no hace falta.**

---

## Parte 1 — Procedimiento de borrado

### 1.a Anfitrión monitoreado: desinstalar el agente

**No existe modo de desinstalación.** Lo verifiqué: `agent/install.sh` y `agent/installer.py` no
tienen `--uninstall`, ni subcomando de remoción, ni script de limpieza. La desinstalación es manual, y
ésta es la secuencia completa derivada de lo que el instalador crea:

```bash
# 1. Detener y deshabilitar el servicio
sudo systemctl stop fim-agent
sudo systemctl disable fim-agent

# 2. Quitar la unidad y su drop-in
sudo rm -f  /etc/systemd/system/fim-agent.service
sudo rm -rf /etc/systemd/system/fim-agent.service.d

# 3. Que systemd olvide la unidad
sudo systemctl daemon-reload
sudo systemctl reset-failed fim-agent 2>/dev/null || true

# 4. Código instalado y entorno virtual
sudo rm -rf /opt/fim-agent

# 5. Configuración (config.yaml, env, ca.pem)
sudo rm -rf /etc/fim-agent

# 6. Estado en tiempo de ejecución  ← LEER LA ADVERTENCIA DE ABAJO
sudo rm -rf /var/lib/fim-agent

# 7. Directorio de registro
sudo rm -rf /var/log/fim-agent

# 8. Usuario del sistema y su grupo
sudo userdel fim-agent
sudo groupdel fim-agent 2>/dev/null || true
```

Comprobación de que no quedó nada:

```bash
systemctl status fim-agent 2>&1 | head -3      # debe decir que no existe la unidad
ls -d /opt/fim-agent /etc/fim-agent /var/lib/fim-agent 2>&1   # los tres: no such file
id fim-agent 2>&1                               # no such user
```

#### Lo que el paso 6 destruye, y no se recupera

`/var/lib/fim-agent` contiene:

| Subdirectorio | Qué guarda | Si se borra |
|---|---|---|
| `baseline` | Instantáneas cifradas con AES-256-GCM del estado aprobado | **No se regenera.** El agente vuelve a tomar como legítimo el estado actual del disco |
| `secrets` | `master_secret` y `shared_secret` entregados en el enrolamiento | El anfitrión deja de poder autenticarse |
| `certs/agent-cert.pem` | El certificado propio del anfitrión | **Exige re-enrolamiento completo** con un secreto nuevo |
| `quarantine` | Artefactos en cuarentena, cifrados | Se pierden |
| `discarded` | Eventos que nunca se entregaron | Se pierde evidencia de detecciones perdidas |
| `queue` | Cola offline pendiente de envío | Se pierden los eventos en vuelo |

Para el video, borrar todo eso es **exactamente lo que querés**: que el agente parta sin línea base y
la construya en cámara. En producción sería grave, y conviene decirlo al pasar en la narración.

### 1.b Servidor central: borrar la base y empezar limpio

Hay dos niveles, y la diferencia importa mucho.

**Nivel 1 — borrar los datos, conservar la CA (recomendado para el video):**

```bash
cd <repo>
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down
docker volume rm "$(basename "$PWD")_pg_data" "$(basename "$PWD")_valkey_data"
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

El backend recrea el esquema al arrancar, así que el panel queda vacío. **La CA sobrevive**, de modo
que un agente ya enrolado sigue siendo válido.

**Nivel 2 — borrar todo, incluida la CA:**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down -v
```

Esto **no es un reinicio limpio: es una instalación nueva.** Borra `pg_data`, `valkey_data`,
`n8n_data` y —lo crítico— **`backend_certs`, donde vive la clave privada de la CA**. Al levantar de
nuevo, el servicio `certs-init` emite una **CA nueva**, y con eso:

- El certificado de **todos** los anfitriones ya enrolados queda inválido.
- Hay que redistribuir el `ca.pem` nuevo **y su huella SHA-256 nueva**.
- Hay que re-enrolar cada anfitrión con un secreto de arranque nuevo.

Para un video que arranca de cero en todo, el nivel 2 es el honesto. Sólo asegurate de tener el
anfitrión monitoreado también limpio, porque si no vas a pelear con certificados inválidos en cámara.

### 1.c Qué camino elegir

| | Borrar el anfitrión actual | Crear un anfitrión nuevo |
|---|---|---|
| Narración | «este servidor no tenía nada» | «así se suma un anfitrión al sistema» |
| Si algo falla en vivo | No hay red de contención | Queda el anterior funcionando |
| Evidencia operativa existente | Se destruye | Se conserva |

**Recomendación**: **anfitrión nuevo** para el agente, y **nivel 1** en el servidor. Muestra el caso
real de uso —sumar un anfitrión a un sistema que ya corre—, deja el panel vacío para que se vea entrar
el primer evento, y conserva la CA, que es la parte que más duele perder.

Si el requisito es explícitamente «todo desde cero», entonces nivel 2 más el borrado completo del
anfitrión, y grabalo sabiendo que un error de huella te corta la toma.

---

## Parte 2 — Guion del video

Duración estimada: 12 a 16 minutos con los cortes declarados.

**Regla de honestidad que sostiene todo el video**: cada vez que se corte una espera, decirlo en
pantalla — «se omiten 4 minutos de descarga de imágenes». Declarar el corte es lo que lo vuelve
creíble; disimularlo es lo que lo vuelve sospechoso.

### Bloque 1 — El punto de partida (1 min)

**Qué se muestra**: el servidor vacío.

```bash
uname -a
docker ps -a
systemctl status fim-agent 2>&1 | head -3
```

**Qué se dice**: que se parte de un servidor sin nada instalado, y que todo lo que se vea a
continuación se construye en cámara.

### Bloque 2 — El servidor central (3 min, con corte declarado)

```bash
git clone <url> && cd tesis-fim-serio
cp .env.example .env    # y editarlo: es el paso que la guía marca como obligatorio
```

**Detenerse en el `.env`** y mostrar tres variables, porque son las que gobiernan la demostración:

- `FIM_PUBLIC_HOSTS` — de acá salen los nombres alternativos del certificado del servidor.
- `N8N_EMAIL_TO` — **el destinatario de las alertas**. Acá va tu correo exclusivo para la prueba.
- `N8N_FIM_CHANNELS=email` — habilita el canal de correo.

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

**[CORTE DECLARADO: descarga de imágenes]**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
docker compose -f docker-compose.yml -f docker-compose.tls.yml logs certs-init | tail -20
```

**Qué se dice**: que `certs-init` es un servicio de una sola ejecución que emite toda la PKI antes de
que arranque el backend, y que la clave privada de la CA queda en un volumen que nunca se publica.

### Bloque 3 — Primer ingreso y la PKI (2 min)

Entrar al panel por HTTPS con `admin` / `admin` y **mostrar el cambio de contraseña forzado**. Es un
detalle chico que dice mucho: el sistema no te deja operar con la credencial de fábrica.

Después, mostrar dónde vive la PKI:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec backend ls -l /certs
```

**Qué se dice**: que el mismo backend es su propia autoridad certificante, que el agente va a recibir
un certificado firmado por ella, y que el transporte con el agente es mTLS en los dos sentidos.

### Bloque 4 — Enrolar el anfitrión (3 min)

En el servidor:

```bash
bash scripts/register-agent.sh demo-host
```

**Mostrar la salida completa**: imprime el `agent_id`, la huella SHA-256 de la CA y **el secreto de
arranque**, y exporta el `ca.pem` a `./fim-ca.pem`.

**Qué se dice, y es el punto fuerte del bloque**: ese secreto es **de un solo uso**. Un segundo intento
con el mismo secreto recibe 401, y pedir otro secreto para el mismo `agent_id` recibe 409. No se puede
reutilizar ni por error.

Transferir al anfitrión el `ca.pem`, la huella y el secreto. En el anfitrión:

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <ip-del-servidor> \
  --agent-id demo-host \
  --watch-path /srv/fim-watch \
  --ca-cert /tmp/fim-ca.pem \
  --ca-fingerprint <huella> \
  --bootstrap-secret-file /root/fim-bootstrap-secret
```

**Momento que vale la pena grabar**: el instalador **valida la huella de la CA antes de escribir nada**.
Si querés mostrarlo, pasá una huella mal a propósito en una toma aparte: aborta y muestra las dos
huellas, la esperada y la recibida. Eso demuestra que el anfitrión no confía en un certificado sólo
porque llegó por la red.

```bash
systemctl status fim-agent
sudo systemd-analyze security fim-agent | head -12
```

**Qué se dice**: que el servicio corre como usuario de sistema sin shell, con `ProtectSystem=strict` y
sólo cinco capacidades, y que cada una está ahí por una razón documentada — `CAP_SYS_ADMIN` para
`fanotify`, `CAP_DAC_READ_SEARCH` para resolver rutas en modo FID, y tres más para poder remediar.

Después, borrar el secreto:

```bash
sudo shred -u /root/fim-bootstrap-secret
```

### Bloque 5 — Las reglas (1 min)

```bash
WATCH_PREFIX=/srv/fim-watch bash scripts/seed-reglas-lab.sh <contraseña-admin>
```

Crea dos reglas: `/srv/fim-watch/*` con severidad **high**, y `/srv/fim-watch/critico/*` con severidad
**critical**. Las dos con acción `alert_only`.

**Qué se dice**: que sin regla no hay severidad, y sin severidad `high` o `critical` no hay alerta ni
correo. Mostrarlas en el panel, en `/rules`.

### Bloque 6 — La toma continua (3 min, SIN cortes)

Ésta es la que no se corta. Pantalla partida: terminal del anfitrión a la izquierda, panel y bandeja de
entrada a la derecha.

```bash
# severidad high
sudo touch /srv/fim-watch/documento.txt
echo "modificacion" | sudo tee -a /srv/fim-watch/documento.txt

# severidad critical
sudo mkdir -p /srv/fim-watch/critico
echo "root:x:0:0" | sudo tee /srv/fim-watch/critico/passwd
```

**Qué se ve, en orden**: el evento aparece en `/events` en segundos → la alerta aparece en `/alerts` →
llega el correo con la severidad en el asunto.

**El plano que cierra la prueba de severidad**: la bandeja de entrada con los dos correos, uno
`[FIM Alert] HIGH` y otro `[FIM Alert] CRITICAL`, sin abrir ninguno.

Mostrar también el detalle del evento en `/events/:id`: la ruta, el proceso que lo tocó con su PID y
su ejecutable, los hashes antes y después, y la diferencia.

### Bloque 7 — Resiliencia (2 min)

Lo más impresionante que tiene el sistema, y casi nadie lo muestra.

```bash
# En el servidor: cortar el broker
docker compose -f docker-compose.yml -f docker-compose.tls.yml stop valkey
```

Con el broker caído, seguir tocando archivos en el anfitrión. Mostrar que la cola crece:

```bash
sudo ls /var/lib/fim-agent/queue | wc -l
```

Reconectar:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d valkey
```

**Qué se ve**: los eventos entran todos, en orden, sin duplicados. Mostrar el conteo en el panel contra
el conteo de la cola.

**Qué se dice**: que el agente no depende de que el servidor esté disponible para no perder
detecciones, y que la preservación medida fue del 100 % de lo encolado en las tres repeticiones.

### Bloque 8 — Lo que no cumple (1 min)

El bloque que más va a jugar a favor, por contraintuitivo que suene.

**Qué se dice**: que el protocolo de medición exige drenar la cola en 30 segundos y la mediana medida
es **35,044 s**; que el incumplimiento se redujo de 4,7× a 1,17× a lo largo de tres candidatos
corrigiendo la causa —el carril de notificación competía con la ingesta por el mismo conjunto de
hilos—; y que la corrección completa está documentada como dirección y fuera del alcance de lo
entregado.

Mencionar también que la latencia de notificación individual **empeoró** al acotar la concurrencia, y
que ése fue el intercambio elegido: antes 787 de 1.000 notificaciones no llegaban nunca, ahora llegan
todas y tardan más. Pérdida silenciosa convertida en espera declarada.

**Por qué este bloque**: un prototipo que muestra su propio incumplimiento medido se lee como trabajo
de ingeniería. Uno que sólo muestra aciertos se lee como demostración de ventas. El tribunal conoce la
diferencia.

---

## Parte 3 — Lista de verificación antes de grabar

- [ ] `N8N_EMAIL_TO` apunta al correo de prueba, y llegó un mensaje de prueba antes de grabar.
- [ ] `N8N_FIM_CHANNELS=email` está puesto.
- [ ] Las credenciales SMTP funcionan (si es Gmail, contraseña de aplicación, no la del usuario).
- [ ] `FIM_PUBLIC_HOSTS` incluye la IP o el nombre con que vas a entrar al panel, o el certificado no
      va a coincidir y el navegador va a protestar en cámara.
- [ ] El anfitrión monitoreado tiene núcleo **5.9 o superior** (lo exige `FAN_REPORT_DIR_FID`).
      Comprobar con `uname -r`. El producto **no** verifica esto por sí mismo: es una limitación
      declarada.
- [ ] `/srv/fim-watch` existe en el anfitrión antes de instalar; el instalador valida que sea un
      directorio existente y absoluto.
- [ ] El secreto de arranque está en un archivo, no en el historial del shell.
- [ ] Si vas a mostrar el rechazo por huella equivocada, grabá esa toma **antes** de la instalación
      buena, porque el secreto es de un solo uso.
- [ ] Si borraste `pg_data` de una base preexistente, aplicá las migraciones a mano: no hay ejecutor
      automático. Sobre base limpia no hace falta.
