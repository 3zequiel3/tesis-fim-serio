# RUNBOOK_PHASES_3_7.md — Ensayo A-3, Fases 3–7 (LANE L9)

Continúa `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/RUNBOOK_WSL2_MTLS.md`
(Fases 0–2, ya completas: preparación de Windows/WSL2 y de la laptop). Este
documento cubre las Fases 3–7, ahora que el carril L8 (backend→Valkey mTLS)
está verificado y L9 agrega SANs configurables, el override de compose
multihost y el tooling de `scripts/multihost/`.

**Regla del ensayo (heredada):** no se modifica nada para "hacer pasar" una
prueba. Todo intento fallido se conserva y se documenta. Ninguna salida con
contraseñas, claves privadas o tokens se pega en chats ni se archiva.

**Convención de esta corrida:**

| Variable | Valor | Anotar |
|---|---|---|
| `<IP_SERVIDOR>` | IP LAN reservada de la laptop (Fase 2.1 del runbook base) | ______ |
| `<IP_PC_WINDOWS>` | IP LAN de la PC con WSL2 (Fase 0.9) | ______ |
| `<AGENT_ID>` | identificador del agente remoto, ej. `host-wsl2-01` | ______ |

Todos los comandos de "Servidor" van en la laptop; los de "Agente (WSL2)"
en la terminal Ubuntu dentro de WSL2.

---

## FASE 3 — Servidor: stack, certificados con SAN, firewall

### 3.1 Variables de entorno de la corrida

En la laptop, en la raíz del worktree `lane/l9-multihost`:

```bash
export FIM_HOST_IP=<IP_SERVIDOR>
export FIM_EXTRA_SANS="IP:${FIM_HOST_IP}"
# Completar también las obligatorias de docker-compose.yml (ver .env.example):
export DB_PASSWORD="$(openssl rand -hex 24)"
export JWT_SECRET_CURRENT="$(openssl rand -hex 32)"
export JWT_SECRET_PREVIOUS=""
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD="$(openssl rand -hex 16)"
export CA_CERT_PATH=/certs/ca.pem CA_KEY_PATH=/certs/ca-key.pem
export BACKEND_CERT_PATH=/certs/backend.pem BACKEND_KEY_PATH=/certs/backend-key.pem
export SMTP_PORT=587 SMTP_STARTTLS=true SMTP_SSL=false
```

**Guardar `DB_PASSWORD` y `ADMIN_PASSWORD` en un gestor de contraseñas —
no quedan en ningún archivo del repo.** `FIM_HOST_IP`/`FIM_EXTRA_SANS`
default a `192.168.1.43` si no se exportan (ver comentarios en
`docker-compose.multihost.yml`); exportarlos explícitamente igual, para que
quede en el historial de la sesión qué IP se usó.

### 3.2 Validar el merge de compose (sin levantar nada)

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml config
```

**Esperado:** sale el YAML combinado sin error. Confirmar a ojo que
`backend.ports` tiene SOLO `<IP_SERVIDOR>:8443:8443` y `127.0.0.1:8000:8000`
(nunca `0.0.0.0`), que `valkey.ports` tiene SOLO
`<IP_SERVIDOR>:6380:6380`, y que `frontend.ports` es `127.0.0.1:80:80`.
`db` no debe tener `ports` en absoluto.

### 3.3 Primer arranque — CA en texto plano, luego TLS

La primera vez, Valkey en modo TLS no puede arrancar sano sin el
certificado de servidor (`valkey.pem`), que a su vez necesita que el
backend ya haya generado la CA (`ca.pem`/`ca-key.pem`) en su primer
arranque. Por eso el orden es: **base primero, TLS después.**

```bash
# 1) Sin tls.yml — deja que el backend inicialice la CA y su propio cert.
docker compose -f docker-compose.yml -f docker-compose.multihost.yml \
  --profile app up -d db valkey backend

# Esperar a que /health responda:
curl -fsS http://127.0.0.1:8000/health
```

**Esperado:** `{"status":"ok"}`. Ver en los logs (`docker compose logs backend`)
la línea `pki.backend_cert.generated` con `extra_sans` igual al valor
exportado.

### 3.4 Emitir el certificado de servidor de Valkey con el SAN real

El script no viaja dentro de la imagen (el Dockerfile del backend sólo
copia `app/`) — se copia al contenedor con `docker compose cp`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml \
  cp scripts/emitir_cert_valkey.py backend:/tmp/emitir_cert_valkey.py

docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml \
  exec -T -e FIM_EXTRA_SANS="${FIM_EXTRA_SANS}" backend python /tmp/emitir_cert_valkey.py
```

**Esperado:** línea `cert : CN=valkey  SAN=valkey,localhost,<IP_SERVIDOR>  vence <fecha>`.

O, de forma guiada (hace esto y el registro del agente en un solo paso,
Fase 4.1):

```bash
ADMIN_PASSWORD="${ADMIN_PASSWORD}" AGENT_ID=<AGENT_ID> \
  FIM_HOST_IP=${FIM_HOST_IP} FIM_EXTRA_SANS="${FIM_EXTRA_SANS}" \
  scripts/multihost/server-prepare.sh
```

### 3.5 Levantar con TLS + el override multihost

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml \
  --profile app up -d db valkey backend

docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml ps
```

**Esperado:** los tres servicios `Up`/`healthy`. Si `backend` reinicia en
loop con `SSL: CERTIFICATE_VERIFY_FAILED: Missing Authority Key Identifier`,
el certificado de Valkey es de una versión vieja del script — repetir 3.4
con el `scripts/emitir_cert_valkey.py` de este worktree (el fix de
`AuthorityKeyIdentifier` es parte de LANE L9).

```bash
curl -fsS http://127.0.0.1:8000/health/components
```

**Esperado:** `"postgres":"ok"`, `"valkey":"ok"` (el backend ya conectó a
Valkey por `valkeys://` con su propio cert de cliente — D-A3/L8).

### 3.6 Firewall — abrir SOLO los dos puertos, SOLO para la IP de la PC Windows

```bash
sudo ufw allow from <IP_PC_WINDOWS> to any port 8443 proto tcp
sudo ufw allow from <IP_PC_WINDOWS> to any port 6380 proto tcp
sudo ufw status verbose
```

**Esperado:** dos reglas nuevas, ambas con `ALLOW` y el origen
`<IP_PC_WINDOWS>` — nunca `Anywhere`. Confirmar que 8000, 80 y 5432 NO
tienen reglas de entrada (no hace falta: sólo escuchan en 127.0.0.1 o ni
siquiera se publican).

### 3.7 Digests de imagen, estado de servicios, reloj

```bash
mkdir -p .v10-evidence/l9/fase3
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml ps \
  > .v10-evidence/l9/fase3/compose-ps.txt
for img in fim-backend:dev valkey/valkey:9.0.3 postgres:18.3; do
  docker image inspect "$img" --format 'Id: {{.Id}}  RepoDigests: {{.RepoDigests}}'
done | tee .v10-evidence/l9/fase3/image-digests.txt
timedatectl | tee .v10-evidence/l9/fase3/timedatectl.txt
chronyc tracking | tee .v10-evidence/l9/fase3/chronyc-tracking.txt
```

### 3.8 `openssl s_client` contra los dos puertos TLS (confirmación rápida, previa a las pruebas negativas formales de Fase 6)

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml \
  exec -T backend cat /certs/ca.pem > /tmp/l9-ca.pem

openssl s_client -connect 127.0.0.1:8443 -CAfile /tmp/l9-ca.pem </dev/null | grep -A2 "Certificate chain"
openssl s_client -connect 127.0.0.1:6380 -CAfile /tmp/l9-ca.pem </dev/null | grep -A2 "Certificate chain"
```

**Esperado:** ambos muestran la cadena `CN=fim-backend`/`CN=valkey` →
`CN=FIM Platform CA`. Si el `openssl` del PATH no es
`/usr/bin/openssl` (ej. un build de Homebrew/Linuxbrew con soporte
post-cuántico), usar la ruta absoluta — un build no estándar puede no
mostrar la alerta TLS de un rechazo real (ver la nota al principio de
`scripts/multihost/collect-server-evidence.sh`, hallazgo confirmado en el
dry-run de LANE L9).

**Punto de control Fase 3:** compartir `fase3/compose-ps.txt`,
`fase3/image-digests.txt`, la salida de 3.6 (`ufw status verbose`) y la
confirmación de 3.5 (`health/components`).

---

## FASE 4 — Pre-registro y agente nativo en WSL2

### 4.1 Pre-registrar el agente (Servidor)

Si no se usó `server-prepare.sh` en 3.4, hacerlo ahora — es el mismo
script, idempotente para esta parte:

```bash
ADMIN_PASSWORD="${ADMIN_PASSWORD}" AGENT_ID=<AGENT_ID> \
  FIM_HOST_IP=${FIM_HOST_IP} FIM_EXTRA_SANS="${FIM_EXTRA_SANS}" \
  scripts/multihost/server-prepare.sh
```

**Esperado:** al final imprime `agent_id` y `bootstrap_secret`. **Copiarlos
AHORA** — no quedan en ningún archivo ni log; el `bootstrap_secret` es de
un solo uso (el backend lo invalida en el primer bootstrap exitoso).

Si el admin todavía tiene la contraseña seed (primer login del backend),
el script fallará con `password_change_required` — cambiarla primero:

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
NEW_PW="$(openssl rand -hex 16)Aa1!"
curl -fsS -X POST http://127.0.0.1:8000/users/change-password \
  -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"current_password\":\"${ADMIN_PASSWORD}\",\"new_password\":\"${NEW_PW}\"}"
# Guardar $NEW_PW en el gestor de contraseñas; re-exportar ADMIN_PASSWORD="$NEW_PW"
# y volver a correr server-prepare.sh.
```

### 4.2 Copiar la CA al segundo equipo (Agente, WSL2)

Desde Ubuntu dentro de WSL2:

```bash
mkdir -p /tmp/l9-certs
scp <usuario>@<IP_SERVIDOR>:<ruta-al-volumen-backend_certs>/ca.pem /tmp/l9-certs/ca.pem
```

Si no hay SSH habilitado en la laptop, copiar `ca.pem` por cualquier medio
fuera de banda (pendrive, recorte de pantalla + `base64 -d` no sirve para
binarios — usar el PEM en texto, es seguro copiarlo así: es material
público). **Nunca copiar `ca-key.pem`.**

### 4.3 Clonar el candidato e instalar el agente (Agente, WSL2)

```bash
git clone <url-del-repo> ~/tesis-fim-serio
cd ~/tesis-fim-serio
git checkout lane/l9-multihost   # o el commit exacto acordado para el ensayo
```

Configurar ANTES de instalar:

```bash
sudo mkdir -p /etc/fim-agent
sudo cp scripts/multihost/agent-config.yaml.example /tmp/config.yaml
# Editar /tmp/config.yaml: agent_id = <AGENT_ID>, y reemplazar 192.168.1.43
# por <IP_SERVIDOR> en backend_url/mtls_backend_url/valkey_url si difiere
# del default del template.
sudo cp /tmp/config.yaml /etc/fim-agent/config.yaml
sudo mkdir -p /etc/fim-agent/certs
sudo cp /tmp/l9-certs/ca.pem /etc/fim-agent/certs/ca.pem
sudo chmod 0644 /etc/fim-agent/certs/ca.pem
```

Instalar (crea el usuario de sistema, venv, unit de systemd, drop-in de
`ReadWritePaths` derivado de `watch_paths`):

```bash
sudo bash agent/install.sh
```

**Esperado:** termina con
`[fim-agent] Installation complete.` sin errores. Revisar que
`/etc/fim-agent/config.yaml` NO fue sobreescrito (install.sh sólo copia el
example si no existe ya un config — como ya lo pusimos en 4.3, debe
seguir siendo el nuestro).

### 4.4 Bootstrap secret y arranque (Agente, WSL2)

```bash
echo "FIM_BOOTSTRAP_SECRET=<pegar el bootstrap_secret de 4.1>" | sudo tee /etc/fim-agent/env
sudo chmod 0600 /etc/fim-agent/env
sudo systemctl start fim-agent
sudo systemctl status fim-agent --no-pager
```

**Esperado:** `active (running)`. En los logs
(`sudo journalctl -u fim-agent -n 50 --no-pager`), la secuencia
`agent.bootstrap.start` → `agent.bootstrap.complete` → `agent started`.

**Tras el primer bootstrap exitoso, borrar el secreto** (es de un solo
uso y el archivo ya no hace falta):

```bash
sudo rm -f /etc/fim-agent/env
```

### 4.5 Confirmar el certificado del agente y el handshake mTLS

```bash
sudo ls -la /var/lib/fim-agent/certs/
# agent-cert.pem, agent-key.pem, ca.pem — 0600, dueño fim-agent.

openssl s_client -connect <IP_SERVIDOR>:8443 -CAfile /var/lib/fim-agent/certs/ca.pem \
  -cert /var/lib/fim-agent/certs/agent-cert.pem -key /var/lib/fim-agent/certs/agent-key.pem \
  -ign_eof <<< $'GET /health HTTP/1.0\r\nHost: fim-backend\r\n\r\n' | tail -20
```

**Esperado:** una respuesta HTTP real (`HTTP/1.1 404 Not Found` es
correcto — el listener mTLS sólo expone `/renew`, no `/health`; lo que
importa es que HUBO respuesta, no un cierre abrupto).

**Punto de control Fase 4:** compartir el `agent_id` usado, la salida de
`systemctl status fim-agent`, y las líneas de bootstrap del journal (sin
pegar el `bootstrap_secret` ni ningún hash).

---

## FASE 5 — Verificación funcional y pruebas positivas

### 5.1 Crear, modificar y eliminar archivos vigilados (Agente, WSL2)

```bash
echo "hola" | sudo tee /srv/fim-watch/prueba.txt
echo "cambio" | sudo tee -a /srv/fim-watch/prueba.txt
sudo rm /srv/fim-watch/prueba.txt
```

**Esperado:** en `journalctl -u fim-agent -f`, tres líneas
`detector.change_detected` (`file_created`, `file_modified`,
`file_deleted`) seguidas de `publisher.event_published` y
`publisher.event_acked` para cada una.

### 5.2 Confirmar persistencia en el backend (Servidor)

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS http://127.0.0.1:8000/events?agent_id=<AGENT_ID> \
  -H "Authorization: Bearer ${TOKEN}" | python3 -m json.tool | head -40
```

**Esperado:** los tres eventos de 5.1, `status: "pending"`.

### 5.3 Aprobar desde la UI (opcional, si el frontend está en el alcance de este ensayo)

Frontend queda en `127.0.0.1:80` — sólo accesible desde la laptop
(por diseño, ver `docker-compose.multihost.yml`). Aprobar/rechazar un
evento desde ahí y confirmar `event_ack` en los logs del agente.

### 5.4 Latencia — 100 modificaciones a 10 ops/s (Agente, WSL2 + Servidor)

En el agente:

```bash
RUN_ID="a3-$(date -u +%Y%m%dT%H%M%SZ)"
scripts/multihost/latency-run.sh /srv/fim-watch/l9-latency-marker.txt \
  "/tmp/${RUN_ID}.local.csv"
```

Anotar el `run_id` que imprime al final. En el servidor, con el mismo
`run_id`:

```bash
scripts/multihost/latency-server-export.sh "${RUN_ID}" .v10-evidence/l9/fase5
```

**Esperado:** `.v10-evidence/l9/fase5/latency-<run_id>.csv` con ~100 filas
(menos si hubo coalescencia de escrituras muy rápidas — normal, no es un
error; cruzar con el journal del agente si el número llama la atención) y
`latency-<run_id>-server-clock.txt`. Comparar ese archivo de reloj del
servidor con la salida de `timedatectl`/`chronyc tracking` que
`latency-run.sh` imprime al principio y al final en el agente — la
columna `agent_to_backend_receive_s` del CSV incluye cualquier desfase
entre los dos relojes; `backend_internal_s` no (mismo reloj en ambos
extremos).

### 5.5 Corte del backend y drenaje (Servidor + Agente)

```bash
# Servidor:
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml stop backend
```

En el agente, seguir generando cambios (`touch /srv/fim-watch/otro.txt`) —
deben quedar en la cola local (`/var/lib/fim-agent/queue`), no perderse.

```bash
# Servidor, reanudar:
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml start backend
```

**Esperado:** en el journal del agente, el flush de la cola offline al
reconectar (`publisher` procesando los eventos acumulados). Confirmar en
el backend que esos eventos llegan con `received_at` posterior a la
reconexión.

**Punto de control Fase 5:** compartir el CSV de latencia, los dos
archivos de reloj (agente y servidor), y la confirmación del drenaje.

---

## FASE 6 — Pruebas negativas y captura de tráfico

### 6.1 Evidencia del lado servidor

```bash
mkdir -p .v10-evidence/l9/fase6/servidor
FIM_HOST_IP=${FIM_HOST_IP} MONITORED_FILE=/srv/fim-watch/l9-latency-marker.txt \
  BACKEND_HOST=${FIM_HOST_IP} VALKEY_HOST=${FIM_HOST_IP} \
  scripts/multihost/collect-server-evidence.sh .v10-evidence/l9/fase6/servidor
```

**Esperado (ver la nota al principio del script sobre cómo leer estos
`.log`):**

| Archivo | Resultado esperado |
|---|---|
| `openssl/positive-backend.log` | una respuesta HTTP real |
| `openssl/negative-backend-no-cert.log` | `unexpected eof while reading` |
| `openssl/negative-backend-foreign-ca.log` | `unexpected eof while reading` |
| `openssl/negative-backend-expired.log` | `unexpected eof while reading` |
| `openssl/positive-valkey.log` | `+PONG` en la salida |
| `openssl/negative-valkey-no-cert.log` | `SSL alert number 116` (certificate required) |
| `openssl/negative-valkey-foreign-ca.log` | `SSL alert number 48` (unknown ca) |
| `openssl/negative-valkey-expired.log` | `SSL alert ... certificate expired` |
| `openssl/negative-valkey-wrong-hostname.log` | `Verify return code: 62 (hostname mismatch)` |
| `pcap/summary.txt` | 0 matches del marker en texto plano |

Si `pcap/SKIPPED_no_privileges.txt` aparece: correr el script con `sudo`,
o dar `cap_net_raw+ep` a `tcpdump` (`sudo setcap cap_net_raw,cap_net_admin+eip $(which tcpdump)`).

### 6.2 Evidencia del lado agente (WSL2)

```bash
mkdir -p ~/l9-evidencia-agente
BACKEND_HOST=<IP_SERVIDOR> VALKEY_HOST=<IP_SERVIDOR> \
  scripts/multihost/collect-agent-evidence.sh ~/l9-evidencia-agente
```

Mismos resultados esperados que 6.1 para los casos que comparten (el
agente no repite el caso "vencido firmado por la CA real" — no tiene la
clave privada de esa CA; usa una CA ad hoc propia, documentado en el
encabezado del script).

**Punto de control Fase 6:** compartir ambos árboles de evidencia
(`fase6/servidor/`, `~/l9-evidencia-agente/`) o al menos los `.log`
mencionados arriba, y confirmar que ninguno contiene `PRIVATE KEY`
(`grep -rl "PRIVATE KEY" <dir>` debe no encontrar nada).

---

## FASE 7 — Teardown, inventario y sellado de evidencia

### 7.1 Detener el agente (Agente, WSL2)

```bash
sudo systemctl stop fim-agent
sudo systemctl disable fim-agent   # si el ensayo terminó
```

### 7.2 Revocar el certificado del agente (Servidor, opcional si el ensayo cierra)

Vía la UI de administración de agentes, o `POST /agents/{agent_id}/revoke`
con el token de admin — deja el `serial_number` en
`revoked_certificates` para que un uso posterior del mismo cert falle.

### 7.3 Bajar el stack del servidor

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml -f docker-compose.multihost.yml \
  --profile app down
```

**No usar `-v`** si se quiere preservar la CA y el histórico de eventos
para una repetición del ensayo; usarlo si se quiere un estado limpio de
cero.

### 7.4 Inventario de recursos residuales (Servidor)

```bash
docker ps -a --format '{{.Names}}' | grep -i multihost || echo "sin contenedores residuales"
docker volume ls --format '{{.Name}}' | grep -i multihost || echo "sin volúmenes residuales (si se usó -v)"
docker network ls --format '{{.Name}}' | grep -i multihost || echo "sin redes residuales"
sudo ufw status verbose   # confirmar si las reglas de 3.6 se retiran o quedan (decisión del operador)
```

### 7.5 `SHA256SUMS` y sellado

```bash
cd .v10-evidence/l9
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
cat SHA256SUMS
```

Pegar el contenido de `SHA256SUMS` como verificador del paquete completo de
evidencia (Fase 3 a 6 + latencia + capturas).

**Punto de control Fase 7:** compartir la salida de 7.4 (inventario) y el
`SHA256SUMS` final.

---

## Resumen — qué queda demostrado si todas las fases pasan

- mTLS agente↔backend (puerto 8443) y TLS con certificado de cliente
  agente↔Valkey (puerto 6380) y backend↔Valkey, entre DOS equipos físicos
  reales conectados por LAN, con rechazos negativos verificados
  (sin certificado, CA ajena, hostname inválido, certificado vencido).
- Latencia extremo a extremo medida con desfase de reloj registrado en
  ambos lados.
- Cero rutas en texto plano en la captura de tráfico de los dos puertos
  bajo prueba.
- Cero recursos Docker residuales tras el teardown.

**Lo que esto NO permite afirmar** (ver también RUNBOOK_WSL2_MTLS.md,
sección 0): despliegue productivo, alta disponibilidad, red WAN/Internet,
anfitrión Linux de metal desnudo, ni rendimiento extrapolable a un entorno
de producción.
