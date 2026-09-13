# Despliegue en un servidor remoto

Guía de producto para llevar la plataforma FIM a un servidor real (VPS o
equivalente) y enrolar hosts monitoreados remotos, sin editar YAML, sin tocar
`/etc/hosts` y sin ejecutar nada dentro de contenedores a mano. Implementa las
decisiones D53–D56 (RN-147 a RN-150); el detalle de arquitectura vive en
`docs/arquitectura_stack.md` y las reglas de negocio en
`docs/reglas_de_negocio.md`.

Esta guía asume dos roles, posiblemente la misma persona:

- **Operador del servidor**: tiene acceso Docker en la máquina que corre el
  stack (backend, Postgres, Valkey, consola, n8n).
- **Operador del host monitoreado**: instala el agente FIM en la máquina cuyo
  filesystem se vigila. Puede ser un tercero que solo recibe los datos de
  registro descriptos abajo — nunca necesita acceso al servidor.

## 1. Requisitos

### Servidor

- Docker Engine y Docker Compose v2 (plugin `docker compose`).
- Puertos disponibles para publicar: el de la consola (80 y/o 443, según el
  modo elegido — sección 3), 8443, 8444 y 6380.
- Un nombre DNS público, una IP pública, o ambos. No hace falta un dominio:
  el despliegue funciona igual con solo una IP (sección 3, modo `off`).

### Host monitoreado

- Linux con systemd, kernel ≥ 5.1 (fanotify en modo FID) y Python 3.13.
- Conectividad saliente hacia el servidor en los puertos 8444 y 6380.
- Root para instalar el agente como servicio systemd (`agent/install.sh`
  requiere `CAP_SYS_ADMIN` y las demás capabilities de
  `docs/operations.md` §"Instalación del agente FIM").

## 2. Preparación del `.env` del servidor

`scripts/prepare_server_env.py` genera un `.env` completo sin editar nada a
mano: secretos con un generador criptográfico, `CORS_ALLOWED_ORIGINS`
derivado de los hosts públicos, y las URLs productivas de n8n.

```bash
python3 scripts/prepare_server_env.py \
  --fim-public-hosts <ip-o-dominio-publico>[,<otro-host>...] \
  --console-tls-mode off
```

Cualquier valor no provisto por flag (usuario admin, correo del owner de
n8n, etc.) se pregunta de forma interactiva, con un default entre corchetes
que `Enter` acepta tal cual. Para una corrida no atendida, proveer todos los
flags relevantes (`--admin-username`, `--n8n-owner-email`,
`--n8n-owner-first-name`, `--n8n-owner-last-name`) evita cualquier prompt.

Puntos importantes:

- **Nunca sobrescribe un `.env` existente.** Si ya hay uno, el script termina
  con error y no lo toca — usar `--output .env.new` para generar un archivo
  de referencia y fusionar a mano.
- Las contraseñas del admin y del owner de n8n se muestran **una sola vez**
  en la terminal al final de la corrida. Guardarlas en un gestor de
  contraseñas antes de cerrar la sesión: no quedan en ningún log ni archivo
  además del propio `.env` (el owner de n8n queda como hash bcrypt, nunca en
  claro).
- `.env` queda con modo `0600` — solo el usuario que lo generó puede leerlo.
- Cada entrada de `FIM_PUBLIC_HOSTS` se valida con la misma regla que usa el
  backend para el SAN del certificado (IP o nombre DNS RFC 1123, sin
  comodines); una entrada inválida aborta sin escribir nada.
- Las variables de canales de n8n (`N8N_FIM_CHANNELS` y las específicas por
  canal — email, Slack, Jira, Linear) se completan a mano en `.env` después:
  ver `openspec/changes/vps-deployment-readiness/design.md` §D-6 addendum
  para la lista completa y sus defaults. Sin ningún canal habilitado, el
  enrutador de alertas responde `channel_disabled` en los tres — es un modo
  válido para levantar el stack por primera vez y habilitar canales después.

## 3. Elección del modo de consola

`CONSOLE_TLS_MODE` en `.env` controla cómo sirve HTTPS la consola web
(D55/RN-149):

| Modo | Cuándo usarlo | Puertos | HSTS |
|---|---|---|---|
| `off` | Solo IP, sin dominio, o una primera prueba rápida | 80 (HTTP) | ninguno |
| `self_signed` | Hay un dominio o IP fijo pero no un certificado provisto | 80 → 301 a 443, HTTPS autofirmado | `max-age=300` (D60/RN-154 — corto a propósito) |
| `provided` | Hay un certificado real (Let's Encrypt u otro) | 80 → 301 a 443, HTTPS con ese certificado | `max-age=63072000; includeSubDomains` |

> **Advertencia del modo `off`.** El login y el refresh de sesión de la
> consola viajan en texto plano: cualquiera en la misma red puede capturar
> las credenciales del admin. El arranque del backend deja un `warning` en
> el log recordándolo. Usarlo solo detrás de una red ya confiable (VPN,
> túnel SSH) o mientras se decide el nombre público definitivo.

En modo `provided`, montar el directorio completo con el certificado (no
archivos sueltos) en `${CONSOLE_TLS_DIR:-./deploy/console-tls}` — así
funciona un árbol estilo `/etc/letsencrypt`, donde `live/<dominio>/*.pem` son
enlaces relativos a `archive/`. `CONSOLE_TLS_CERT_FILE` y
`CONSOLE_TLS_KEY_FILE` son las rutas relativas a ese directorio. Tras cada
renovación del certificado: `docker compose restart frontend`.

Con `self_signed`, `certs-init` imprime en su log la huella SHA-256 del
certificado autofirmado de la consola al arrancar (`certs_init.step.done
step=console`) — comparar contra la huella que muestra el navegador antes de
aceptar la excepción de seguridad.

## 4. Arranque del stack

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --build
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
```

Sin editar ningún archivo YAML. `--profile app` deja **afuera** el agente de
laboratorio (`agent` pasó al perfil `lab` — D54/RN-148: un agente de prueba
con secreto por defecto no debe correr en un servidor real). `certs-init` y
`n8n-provision` son servicios one-shot: terminan con exit 0 y no vuelven a
correr hasta el próximo `up` — verlos en `Exited (0)` en el `ps` es el
resultado esperado, no una falla.

Verificar salud:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app logs certs-init
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app logs n8n-provision
curl -k https://<host>:8443/health   # o el endpoint de salud que exponga el backend
```

`GET /health/components` (autenticado, desde la consola) debe reportar
`valkey: ok` y, una vez completada la sección 8, `n8n: ok`.

## 5. Restricción de acceso a los puertos publicados

Docker escribe sus propias reglas de `iptables`/`nftables` para los puertos
publicados y **estas reglas se evalúan antes que las de `ufw`** — un
`ufw deny 8443` no alcanza a bloquear nada si Docker ya aceptó la conexión.
Filtrar en la cadena `DOCKER-USER`, que Docker respeta:

```bash
# Reglas base: aceptar únicamente desde subredes/IPs conocidas de hosts
# monitoreados, para 8443 (mTLS), 8444 (bootstrap) y 6380 (Valkey TLS).
sudo iptables -I DOCKER-USER -p tcp --dport 8443 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 8444 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 6380 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 8443 -j DROP
sudo iptables -I DOCKER-USER -p tcp --dport 8444 -j DROP
sudo iptables -I DOCKER-USER -p tcp --dport 6380 -j DROP
```

Ajustar el orden de las reglas (`-I` inserta al principio) según cuántos
hosts monitoreados haya y si su IP es conocida de antemano. `8000` no
necesita regla: ya publica solo en `127.0.0.1` (D54/RN-148). El puerto de
consola (80/443) queda abierto a cualquiera a propósito — es la interfaz
pública del producto.

## 6. Registro del agente

Con el stack arriba, en el servidor:

```bash
scripts/register-agent.sh <agent_id>
```

Esto genera un secreto de bootstrap de un solo uso, registra el agente (misma
lógica que usaría un admin desde la consola) y muestra en la terminal:

- los hosts de `FIM_PUBLIC_HOSTS`,
- la huella SHA-256 de la CA del servidor,
- el secreto de bootstrap (de un solo uso — no se vuelve a mostrar),
- un comando `agent/install.sh` sugerido, **sin** el secreto.

También exporta `./fim-ca.pem` en el directorio actual. No pide la
contraseña del admin: acceder a Docker en el servidor ya es un privilegio
mayor (D56/RN-150).

Copiar `fim-ca.pem`, la huella y el secreto al host monitoreado por un canal
que el operador considere seguro (el secreto es de un solo uso, así que una
intercepción posterior al primer bootstrap no sirve de nada).

## 7. Instalación del agente en el host monitoreado

Con el repositorio del agente disponible en el host monitoreado (clonar el
repo o copiar solo `agent/`):

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <host-del-servidor> \
  --agent-id <agent_id> \
  --watch-path /etc --watch-path /bin --watch-path /usr/bin \
  --ca-cert ./fim-ca.pem \
  --ca-fingerprint <huella-mostrada-por-register-agent.sh> \
  --bootstrap-secret-file <archivo-con-el-secreto>
```

Sin `--non-interactive`, el instalador pregunta por cualquier valor faltante
(incluido el secreto, con un prompt oculto que no lo muestra en pantalla). El
secreto **nunca** se acepta como argumento (`--bootstrap-secret` se rechaza
explícitamente sin escribir nada) ni como variable de entorno — solo por
prompt oculto o `--bootstrap-secret-file`. Borrar ese archivo después de la
instalación.

`install.sh` verifica el alcance a 8444 y 6380 antes de habilitar el
servicio; si la verificación falla, no habilita nada y termina con exit 3
mostrando qué puerto falló y por qué (DNS, conexión rechazada, timeout, o
verificación TLS/hostname).

## 8. Verificación del despliegue

- `systemctl status fim-agent` en el host monitoreado: `active (running)`.
- El log del backend muestra el bootstrap por el puerto 8444.
- Un cambio en un `watch_path` configurado aparece como evento en la consola
  dentro de los segundos siguientes.
- `GET /health/components` reporta `n8n: ok` una vez que `n8n-provision`
  terminó exitosamente (sección 4) y al menos un canal está habilitado en
  `.env` (`N8N_FIM_CHANNELS`).
- Un `POST` real contra `/webhook/fim-alert` del enrutador de n8n entrega el
  canal habilitado y responde 202; dos `POST` con el mismo `event_id` de un
  evento de ticketing producen un único ticket (search-before-create,
  D41/RN-135).

## 9. Reinstalación y actualización del agente

`agent/install.sh` es idempotente y **reemplaza** el código instalado en
lugar de fusionarlo: re-ejecutarlo con el código del repositorio actualizado
deja `/opt/fim-agent/agent` idéntico a la fuente (sin archivos viejos
sobrantes) y reinicia el servicio si estaba activo. Sin `--reconfigure`,
`config.yaml` y `/etc/fim-agent/env` quedan byte a byte intactos:

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <host-del-servidor> --agent-id <agent_id> \
  --watch-path /etc --ca-cert ./fim-ca.pem \
  --ca-fingerprint <huella> --bootstrap-secret-file <archivo>
```

Para cambiar los datos de conexión de un agente que **todavía no se
enroló** (por ejemplo, corregir el host del servidor), agregar
`--reconfigure`: se guarda una copia `.bak-<timestamp>` del archivo anterior.
Tras el primer bootstrap exitoso, la configuración autoritativa vive en el
backend y se administra desde la consola — reconfigurar localmente ya no
tiene efecto sobre un agente enrolado.

## 10. Renovación del certificado provisto de la consola

Solo aplica al modo `provided` (sección 3). Renovar el certificado con la
herramienta que corresponda (por ejemplo `certbot renew` para Let's Encrypt)
apuntando al mismo directorio montado en `CONSOLE_TLS_DIR`, y luego:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app restart frontend
```

nginx no relee el certificado en caliente — el `restart` es necesario. Los
certificados del backend y de Valkey se reemiten automáticamente por
`certs-init` en cada `up`/reinicio del stack cuando les quedan menos de 15
días de vigencia (D61/RN-155); no requieren ninguna acción manual siempre que
el stack se reinicie con cierta regularidad (recomendado: antes del día 75 de
cada certificado de 90 días).
