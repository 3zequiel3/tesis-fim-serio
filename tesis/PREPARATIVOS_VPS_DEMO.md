# Preparativos de la VPS antes de grabar

Para una VPS que **ya tiene el repositorio clonado**, con la topología de una sola máquina: servidor y
agente nativo en el mismo host.

Hacer todo esto **antes** de empezar a grabar. El video arranca en el paso de la Parte 5.

---

## Parte 1 — Actualizar el repositorio

```bash
cd <ruta-del-repo>
git fetch --all --tags
git checkout main
git pull --ff-only
git log --oneline -1
git describe --tags --abbrev=0    # debería decir v4.0-tesis
```

Si `git pull` se niega porque hay cambios locales, mirá qué son antes de descartarlos:

```bash
git status --short
```

---

## Parte 2 — Verificar requisitos, en orden de probabilidad de bloquearte

### 2.a Python: el que más veces frena la instalación

El instalador del agente exige **exactamente Python 3.13** (`REQUIRED_PYTHON_MINOR=13`), porque las
dependencias del agente no van más allá. Si el `python3` por defecto de la VPS es más nuevo, el
instalador **aborta**.

```bash
python3 --version
ls /usr/bin/python3.13 2>&1
```

Si `python3` no es 3.13 pero existe `/usr/bin/python3.13`, no hay problema: se le pasa al instalador con
`--python /usr/bin/python3.13`. Anotalo ahora para no descubrirlo en cámara.

Si no existe:

```bash
sudo apt-get update && sudo apt-get install -y python3.13 python3.13-venv
```

### 2.b Núcleo

```bash
uname -r
```

Tiene que ser **5.9 o superior**: el detector usa `FAN_REPORT_DIR_FID`, que no existe antes. El producto
**no** verifica esto por sí mismo — es una limitación declarada, y conviene mencionarla en el video
justamente acá.

### 2.c Docker

```bash
docker --version
docker compose version     # tiene que ser v2: "docker compose", no "docker-compose"
systemctl is-active docker
```

### 2.d Puertos libres

```bash
sudo ss -lntp | rg -N ':(80|443|8443|8444|6380|8000)\b' || echo "los seis libres"
```

Si algo ocupa el 80 o el 443 (un nginx del sistema, por ejemplo), o lo paras o cambiás
`CONSOLE_HTTP_PORT` / `CONSOLE_HTTPS_PORT` en el `.env`.

---

## Parte 3 — Borrar el agente

No existe modo de desinstalación: la limpieza es manual. Estos ocho pasos cubren todo lo que el
instalador crea.

```bash
sudo systemctl stop fim-agent
sudo systemctl disable fim-agent
sudo rm -f  /etc/systemd/system/fim-agent.service
sudo rm -rf /etc/systemd/system/fim-agent.service.d
sudo systemctl daemon-reload
sudo systemctl reset-failed fim-agent 2>/dev/null || true
sudo rm -rf /opt/fim-agent
sudo rm -rf /etc/fim-agent
sudo rm -rf /var/lib/fim-agent
sudo rm -rf /var/log/fim-agent
sudo userdel fim-agent 2>/dev/null || true
sudo groupdel fim-agent 2>/dev/null || true
```

Comprobar:

```bash
systemctl status fim-agent 2>&1 | head -3     # la unidad no debe existir
ls -d /opt/fim-agent /etc/fim-agent /var/lib/fim-agent 2>&1
id fim-agent 2>&1                              # no such user
```

`/var/lib/fim-agent` contenía la línea base cifrada, los secretos del enrolamiento y el certificado del
anfitrión. Nada de eso se regenera — que es exactamente lo que querés para el video.

---

## Parte 4 — Borrar el servidor por completo

Como el agente ya no existe, **no hay ningún certificado que preservar**, así que conviene el borrado
total:

```bash
cd <ruta-del-repo>
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down -v
```

Eso borra `pg_data`, `valkey_data`, `n8n_data` y `backend_certs` — incluida la clave privada de la CA.
Al levantar de nuevo, `certs-init` emite una CA nueva. Es lo correcto acá.

Comprobar que no quedaron volúmenes ni contenedores:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps -a
docker volume ls | rg -N "$(basename "$PWD")" || echo "sin volumenes del proyecto"
```

Con la base limpia **no hace falta aplicar migraciones**: el backend crea el esquema al arrancar. Se
aplican a mano sólo sobre una base preexistente.

---

## Parte 5 — Generar el `.env`

Hay un generador propio, que sólo usa la biblioteca estándar y valida los hosts con la misma regla que
el backend:

```bash
python3 scripts/prepare_server_env.py \
  --fim-public-hosts <ip-publica-de-la-vps> \
  --console-tls-mode self_signed \
  --admin-username admin \
  --n8n-owner-email <tu-correo-de-prueba> \
  --output .env
```

Genera `DB_PASSWORD`, `JWT_SECRET_CURRENT`, `ADMIN_PASSWORD`, las rutas de certificados y
`CORS_ALLOWED_ORIGINS` derivado de los hosts públicos.

**`--fim-public-hosts` es el que más cuesta si se equivoca**: de ahí salen los nombres alternativos del
certificado del servidor. Tiene que incluir **la misma IP o nombre** que vas a usar después como
`--server-host` del agente y con el que vas a entrar al panel. Si no coincide, el navegador protesta en
cámara y el agente falla la validación.

Guardá la contraseña que generó, que la necesitás para el primer ingreso:

```bash
rg -N "^ADMIN_PASSWORD=" .env
```

### El generador NO configura las notificaciones

Hay que agregarlas a mano. Es lo que habilita la prueba de severidad:

```bash
cat >> .env <<'EOF'

# ── Canal de notificación para la demostración ──
N8N_FIM_CHANNELS=email
N8N_EMAIL_TO=<tu-correo-de-prueba>
N8N_EMAIL_FROM=<remitente>
N8N_EMAIL_SMTP_HOST=smtp.gmail.com
N8N_EMAIL_SMTP_PORT=587
N8N_EMAIL_SMTP_USER=<usuario-smtp>
N8N_EMAIL_SMTP_PASSWORD=<contraseña-de-aplicacion>
N8N_EMAIL_SMTP_SECURE=false
N8N_WEBHOOK_URL=http://n8n:5678/webhook/fim-alert
N8N_HEALTH_URL=http://n8n:5678/healthz
EOF
```

Dos advertencias:

- Con Gmail va **contraseña de aplicación**, no la del usuario.
- `N8N_EMAIL_SMTP_SECURE=false` significa STARTTLS en el 587. No es «sin cifrado».

**`N8N_EMAIL_TO` es el destinatario de todas las alertas.** No sale del usuario administrador ni de
ninguna tabla: es una dirección global para toda la instalación.

Revisar que no haya quedado ningún `$` sin escapar, que es el error clásico del `.env`:

```bash
rg -N '\$' .env || echo "sin interpolaciones"
```

---

## Parte 6 — Levantar y verificar

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
```

`certs-init` debe figurar **`Exited (0)`**: es un servicio de una sola ejecución, ese es el resultado
correcto y no una falla.

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app logs certs-init | tail -20
curl -sk https://127.0.0.1/ -o /dev/null -w '%{http_code}\n'
curl -s http://127.0.0.1:8000/health/components | python3 -m json.tool
```

En `/health/components`, **el canal de n8n tiene que figurar sano**. Si aparece degradado, el correo no
va a salir y el video se cae justo en el bloque que importa.

---

## Parte 7 — Probar el correo ANTES de grabar

Esto no es opcional. Es el único paso del video que depende de un tercero.

```bash
sudo mkdir -p /srv/fim-watch/critico
```

Instalar el agente, sembrar las reglas, y disparar **un** evento crítico de prueba:

```bash
bash scripts/register-agent.sh demo-host
# transferir nada: el ca.pem queda en ./fim-ca.pem, en esta misma máquina

umask 077 && sudo tee /root/fim-bootstrap-secret <<< "<el-secreto-impreso>"

sudo bash agent/install.sh --non-interactive \
  --server-host <ip-publica-de-la-vps> \
  --agent-id demo-host \
  --watch-path /srv/fim-watch \
  --ca-cert ./fim-ca.pem \
  --ca-fingerprint <huella-impresa> \
  --bootstrap-secret-file /root/fim-bootstrap-secret
# agregar --python /usr/bin/python3.13 si python3 no es 3.13

WATCH_PREFIX=/srv/fim-watch bash scripts/seed-reglas-lab.sh <ADMIN_PASSWORD>

echo "prueba" | sudo tee /srv/fim-watch/critico/prueba.txt
```

**Esperá el correo.** Si llega con el asunto `[FIM Alert] CRITICAL — …`, la cadena completa funciona y
podés grabar.

Si no llega:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  logs backend --since 5m | rg -N -i "notify|alert"
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  logs n8n --since 5m | tail -30
```

### Y después, volver a dejar todo limpio para grabar

La prueba consumió el secreto de arranque —es de un solo uso— y dejó datos en la base. Para grabar
desde cero hay que repetir las Partes 3 y 4, y volver a generar el secreto en cámara con
`register-agent.sh`.

El `.env` **no** hay que rehacerlo: sobrevive al `down -v`, porque es un archivo del repositorio y no
un volumen.

---

## Resumen de lo que tiene que quedar anotado antes de grabar

| Dato | Para qué |
|---|---|
| IP pública de la VPS | `--fim-public-hosts` y `--server-host`, tienen que coincidir |
| `ADMIN_PASSWORD` del `.env` | Primer ingreso al panel y `seed-reglas-lab.sh` |
| Ruta del Python 3.13 | Por si hay que pasar `--python` |
| Que el correo de prueba llegó | Es lo único que depende de un tercero |
