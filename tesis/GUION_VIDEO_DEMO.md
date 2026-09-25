# Guion del video de demostración — topología de una sola máquina

Objetivo: mostrar el prototipo funcionando de punta a punta, partiendo de cero, con una prueba de
notificación por severidad a una dirección de correo propia. **Todo en una sola VPS, con una sola
terminal y un navegador.**

Todas las rutas, nombres de servicio y comandos están verificados contra el código del repositorio.

---

## Parte 0 — La topología, y por qué esta y no otra

### Sí: el agente se instala en la misma VPS y vigila un directorio de la VPS

El «anfitrión monitoreado» pasa a ser el propio servidor. No hay ningún impedimento técnico:

- **El agente no abre ningún puerto.** Lo prohíbe D8/RN-108: no hay servidor HTTP en el agente, todo
  el diálogo con el backend va por Valkey Streams. Verificado: no hay una sola llamada a `bind` ni a
  `listen` en su código. No puede chocar con el backend.
- El servidor publica `8443`, `8444` y `6380` en `0.0.0.0`, así que el agente en el mismo host los
  alcanza sin nada especial.

Único cuidado: **`FIM_PUBLIC_HOSTS` tiene que incluir el nombre o IP que le pases como
`--server-host`**, porque el certificado del servidor tiene que coincidir con lo que el agente pide.

### No usar el agente contenedorizado del compose

El compose trae un servicio `agent` bajo el perfil `lab` justo para «probar todo en una sola máquina».
**No lo uses en el video**, por dos razones:

1. Usa un **secreto de arranque por defecto** (`docker-bootstrap-secret`), y la guía de instalación
   dice textual: «**En un servidor real no se levanta**».
2. **Contradice tu propio capítulo.** La tesis declara que el candidato evaluado usó el agente
   **nativo bajo systemd**. Si el video muestra un contenedor, la demostración no es lo que se midió, y
   eso es exactamente la clase de detalle que un tribunal pregunta.

El agente nativo en la misma VPS te da enrolamiento real con secreto de un solo uso, `systemd` de
verdad, y las capacidades y el endurecimiento reales.

### El destinatario del correo no es el usuario administrador

Los dos canales toman la dirección de una **variable de entorno global**:

| Canal | Variable | Servicio |
|---|---|---|
| n8n (primario) | `N8N_EMAIL_TO` | `n8n` |
| SMTP del backend (respaldo) | `SMTP_TO` | `backend` |

En el flujo de n8n el campo es literalmente `toEmail = __FIM_ENV_N8N_EMAIL_TO__`; en el backend,
`msg["To"] = cfg.smtp_to`. **Ninguno consulta la tabla de usuarios.** Una sola dirección para toda la
instalación.

Ventaja para la prueba de severidad: **el asunto ya la lleva**.

```
[FIM Alert] CRITICAL — /srv/fim-watch/critico/passwd
```

Se ve en la bandeja de entrada sin abrir el mensaje.

Conviene declarar la limitación al pasar: hoy no se puede enrutar las críticas a un equipo y las medias
a otro.

### Solo `critical` y `high` generan alerta

Por RN-52. Una regla `medium` o `low` produce evento pero **no** alerta y **no** correo. Si en cámara
tocás un archivo que cae en una regla `low`, vas a ver el evento y no va a llegar mail. No es falla, es
la política — pero si no lo sabés, desconcierta.

### Mailpit no hace falta

No está en `docker-compose.yml` ni en `docker-compose.tls.yml`: fue sólo un sumidero desechable para
las mediciones de la tesis. Con un correo real no lo necesitás.

---

## Parte 1 — Borrar todo lo que haya del agente en la VPS

**No existe modo de desinstalación.** Verificado: `agent/install.sh` y `agent/installer.py` no tienen
`--uninstall`, ni subcomando de remoción, ni script de limpieza. La secuencia es manual, y ésta es
completa, derivada de lo que el instalador realmente crea.

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

# 6. Estado en tiempo de ejecución  ← leer la advertencia
sudo rm -rf /var/lib/fim-agent

# 7. Directorio de registro
sudo rm -rf /var/log/fim-agent

# 8. Usuario del sistema y su grupo
sudo userdel fim-agent
sudo groupdel fim-agent 2>/dev/null || true
```

Comprobación de que no quedó nada:

```bash
systemctl status fim-agent 2>&1 | head -3   # la unidad no debe existir
ls -d /opt/fim-agent /etc/fim-agent /var/lib/fim-agent 2>&1
id fim-agent 2>&1                            # no such user
```

### Qué destruye el paso 6, y no se recupera

| Subdirectorio | Qué guarda | Consecuencia |
|---|---|---|
| `baseline` | Instantáneas cifradas con AES-256-GCM del estado aprobado | **No se regenera.** El agente vuelve a tomar como legítimo el estado actual del disco |
| `secrets` | `master_secret` y `shared_secret` del enrolamiento | El anfitrión deja de poder autenticarse |
| `certs/agent-cert.pem` | El certificado propio del anfitrión | **Exige re-enrolamiento** con secreto nuevo |
| `quarantine` | Artefactos en cuarentena, cifrados | Se pierden |
| `discarded` | Eventos que nunca se entregaron | Se pierde evidencia de detecciones perdidas |
| `queue` | Cola offline pendiente | Se pierden los eventos en vuelo |

Para el video es **justo lo que querés**: que el agente parta sin línea base y la construya en cámara.
En producción sería grave, y vale mencionarlo en la narración.

---

## Parte 2 — Borrar la base del servidor

Dos niveles, y la diferencia importa.

**Nivel 1 — borrar los datos, conservar la CA (recomendado):**

```bash
cd <repo>
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down
docker volume rm "$(basename "$PWD")_pg_data" "$(basename "$PWD")_valkey_data"
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

El backend recrea el esquema al arrancar, así que el panel queda vacío.

**Nivel 2 — borrar todo, incluida la CA:**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down -v
```

Esto **no es un reinicio limpio: es una instalación nueva.** Borra `pg_data`, `valkey_data`,
`n8n_data` y —lo crítico— **`backend_certs`, donde vive la clave privada de la CA**. Al levantar,
`certs-init` emite una CA nueva e invalida todo certificado ya emitido.

**Para esta topología, el nivel 2 es el correcto**: como vas a borrar el agente igual (Parte 1), no hay
ningún certificado que preservar, y así el video arranca de cero de verdad. Es más honesto y no te
cuesta nada.

Como la base queda limpia, **no hace falta aplicar migraciones**: el backend crea el esquema al
arrancar. Las migraciones se aplican a mano sólo sobre una base preexistente.

---

## Parte 3 — El guion

Duración estimada: 12 a 15 minutos con los cortes declarados.

**Regla que sostiene la credibilidad del video**: cada vez que se corte una espera, decirlo en pantalla
— «se omiten 4 minutos de descarga de imágenes». Declarar el corte es lo que lo vuelve creíble;
disimularlo es lo que lo vuelve sospechoso.

**Disposición de pantalla**: terminal a la izquierda, navegador a la derecha, siempre visibles las dos.
Nunca aparece «otra máquina», y el evento entra a la derecha mientras la mano todavía está en el
comando de la izquierda. Eso es lo que convence.

### Bloque 1 — El punto de partida (1 min)

```bash
uname -a
uname -r                 # tiene que ser 5.9 o superior
docker ps -a
systemctl status fim-agent 2>&1 | head -3
ls -d /opt/fim-agent /etc/fim-agent /var/lib/fim-agent 2>&1
```

**Qué se dice**: que se parte de una máquina sin nada del sistema instalado, y que todo lo que se vea
se construye en cámara. Aprovechar el `uname -r` para explicar que el detector necesita núcleo 5.9 o
superior por `FAN_REPORT_DIR_FID`, y que **el producto no verifica eso por sí mismo** — es una
limitación declarada.

### Bloque 2 — El servidor central (3 min, con corte declarado)

```bash
git clone <url> && cd tesis-fim-serio
cp .env.example .env
```

**Detenerse en el `.env`** y mostrar cuatro variables, que son las que gobiernan la demostración:

- `FIM_PUBLIC_HOSTS` — de acá salen los nombres alternativos del certificado. **Tiene que incluir la
  IP o el nombre que uses después como `--server-host`.**
- `N8N_FIM_CHANNELS=email` — habilita el canal de correo.
- `N8N_EMAIL_TO` — **tu correo de prueba.**
- Las credenciales SMTP.

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

**[CORTE DECLARADO: descarga de imágenes]**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
docker compose -f docker-compose.yml -f docker-compose.tls.yml logs certs-init | tail -20
```

**Qué se dice**: que `certs-init` es un servicio de una sola ejecución que emite toda la PKI antes de
que arranque el backend, y que su estado correcto es `Exited (0)` — no es una falla. Y que la clave
privada de la CA queda en un volumen que nunca se publica.

### Bloque 3 — Primer ingreso y la PKI (2 min)

Entrar al panel por HTTPS con `admin` / `admin` y mostrar el **cambio de contraseña forzado**. Es un
detalle chico que dice mucho: el sistema no deja operar con la credencial de fábrica.

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec backend ls -l /certs
```

**Qué se dice**: que el backend es su propia autoridad certificante, que el agente va a recibir un
certificado firmado por ella, y que el transporte es mTLS en los dos sentidos.

### Bloque 4 — Enrolar el agente, en la misma máquina (4 min)

```bash
bash scripts/register-agent.sh demo-host
```

**Mostrar la salida completa**: imprime el `agent_id`, la huella SHA-256 de la CA y el **secreto de
arranque**, y exporta el `ca.pem` a `./fim-ca.pem`.

**El punto fuerte del bloque**: ese secreto es **de un solo uso**. Un segundo intento con el mismo
secreto recibe 401, y pedir otro para el mismo `agent_id` recibe 409. No se puede reutilizar, ni por
error.

Preparar el directorio a vigilar y el secreto:

```bash
sudo mkdir -p /srv/fim-watch/critico
umask 077 && sudo tee /root/fim-bootstrap-secret <<< "<el-secreto>"
```

Instalar el agente **en esta misma máquina**:

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <ip-publica-de-esta-vps> \
  --agent-id demo-host \
  --watch-path /srv/fim-watch \
  --ca-cert ./fim-ca.pem \
  --ca-fingerprint <huella> \
  --bootstrap-secret-file /root/fim-bootstrap-secret
```

```bash
systemctl status fim-agent
sudo systemd-analyze security fim-agent | head -12
```

**Qué se dice**: que el servicio corre como usuario de sistema sin shell, con `ProtectSystem=strict` y
sólo cinco capacidades, cada una con una razón documentada — `CAP_SYS_ADMIN` para `fanotify`,
`CAP_DAC_READ_SEARCH` para resolver rutas en modo FID, y tres más para poder remediar. Y que las rutas
vigiladas entran a la unidad por un *drop-in* generado, no editando la unidad base.

Borrar el secreto:

```bash
sudo shred -u /root/fim-bootstrap-secret
```

**Toma aparte, grabada ANTES de la instalación buena**: pasar una huella equivocada a propósito. El
instalador **valida la huella de la CA antes de escribir nada**: aborta y muestra las dos, la esperada
y la recibida. Demuestra que el anfitrión no confía en un certificado sólo porque llegó por la red.
Grabala antes, porque el secreto es de un solo uso.

### Bloque 5 — Las reglas (1 min)

```bash
WATCH_PREFIX=/srv/fim-watch bash scripts/seed-reglas-lab.sh <contraseña-admin>
```

Crea `/srv/fim-watch/*` con severidad **high** y `/srv/fim-watch/critico/*` con severidad **critical**,
ambas con acción `alert_only`.

**Qué se dice**: que sin regla no hay severidad, y sin `high` o `critical` no hay alerta ni correo.
Mostrarlas en `/rules`.

### Bloque 6 — La toma continua (3 min, SIN cortes)

Ésta no se corta.

```bash
# severidad high
sudo touch /srv/fim-watch/documento.txt
echo "modificacion" | sudo tee -a /srv/fim-watch/documento.txt

# severidad critical
echo "root:x:0:0" | sudo tee /srv/fim-watch/critico/passwd
```

**Qué se ve, en orden**: el evento aparece en `/events` en segundos → la alerta en `/alerts` → llega el
correo con la severidad en el asunto.

**El plano que cierra la prueba**: la bandeja con los dos correos, `[FIM Alert] HIGH` y
`[FIM Alert] CRITICAL`, sin abrir ninguno.

Después, el detalle en `/events/:id`: la ruta, el proceso que lo tocó con su PID y su ejecutable, los
hashes antes y después, y la diferencia.

### Bloque 7 — El plano que sólo existe en esta topología (1 min)

Éste lo ganás por correr en la misma máquina que Docker, y es de los puntos técnicos más sólidos del
diseño.

El agente marca **todo el sistema de archivos** con `FAN_MARK_FILESYSTEM` y descarta por política lo
que cae fuera de sus rutas vigiladas, **contando cada descarte**. Con Docker escribiendo en el mismo
sistema de archivos, ese contador se mueve solo.

Mostrarlo en `/agents` y explicarlo: **no es ruido, es la prueba visible de que el agente recibe todo
el sistema de archivos del núcleo y filtra por regla**, en lugar de mirar un directorio aislado. Un FIM
que sólo observa un directorio no puede detectar que alguien escribió fuera de él; éste lo ve y lo
descarta a propósito, y lo deja registrado.

### Bloque 8 — Resiliencia (2 min)

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml stop valkey
```

Con el broker caído, seguir tocando archivos. Mostrar que la cola crece:

```bash
sudo ls /var/lib/fim-agent/queue | wc -l
```

Reconectar:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d valkey
```

**Qué se ve**: entran todos, en orden, sin duplicados. Comparar el conteo del panel contra el de la
cola.

**Qué se dice**: que el agente no depende de que el servidor esté disponible para no perder
detecciones, y que la preservación medida fue del 100 % de lo encolado en las tres repeticiones.

### Bloque 9 — Lo que no cumple (1 min)

El bloque que más va a jugar a favor, por contraintuitivo que suene.

**Qué se dice**: que el protocolo exige drenar la cola en 30 segundos y la mediana medida es
**35,044 s**; que el incumplimiento bajó de 4,7× a 1,17× a lo largo de tres candidatos corrigiendo la
causa —el carril de notificación competía con la ingesta por el mismo conjunto de hilos—; y que la
corrección completa está documentada como dirección y fuera del alcance de lo entregado.

Mencionar también que la latencia de notificación individual **empeoró** al acotar la concurrencia, y
que fue el intercambio elegido: antes 787 de 1.000 notificaciones no llegaban nunca, ahora llegan todas
y tardan más. Pérdida silenciosa convertida en espera declarada.

**Por qué este bloque**: un prototipo que muestra su propio incumplimiento medido se lee como trabajo
de ingeniería. Uno que sólo muestra aciertos se lee como demostración de ventas.

---

## Parte 4 — Lista de verificación antes de grabar

- [ ] `uname -r` da **5.9 o superior**.
- [ ] `FIM_PUBLIC_HOSTS` incluye la IP o nombre que vas a usar como `--server-host` **y** con el que
      vas a entrar al panel. Si no, el navegador protesta en cámara.
- [ ] `N8N_FIM_CHANNELS=email` está puesto y `N8N_EMAIL_TO` apunta al correo de prueba.
- [ ] Llegó un correo de prueba **antes** de empezar a grabar.
- [ ] Credenciales SMTP válidas (si es Gmail, contraseña de aplicación, no la del usuario).
- [ ] `/srv/fim-watch` y `/srv/fim-watch/critico` existen: el instalador exige que la ruta vigilada sea
      un directorio absoluto y existente.
- [ ] El secreto de arranque está en un archivo, no en el historial del shell.
- [ ] La toma del rechazo por huella equivocada ya está grabada, **antes** de la instalación buena.
- [ ] Si vas a mostrar el panel vacío, la base se borró (Parte 2) y el agente también (Parte 1).
