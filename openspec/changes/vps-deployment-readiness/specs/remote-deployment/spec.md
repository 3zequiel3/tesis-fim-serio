## ADDED Requirements

### Requirement: Script de preparación del `.env` del servidor (D54/RN-148)

El repositorio SHALL proveer un script de preparación del servidor, ejecutable con `python3` de la biblioteca estándar y Docker, que genere `.env` en la raíz del repositorio. Las entradas (`FIM_PUBLIC_HOSTS`, `CONSOLE_TLS_MODE` y, en modo `provided`, `CONSOLE_TLS_DIR`, `CONSOLE_TLS_CERT_FILE` y `CONSOLE_TLS_KEY_FILE`, usuario admin y correo del owner de n8n) SHALL aceptarse por flags o prompt. El script SHALL:

- validar cada entrada de `FIM_PUBLIC_HOSTS` con la misma regla IP/DNS que el backend, antes de escribir nada;
- generar con un generador criptográfico `DB_PASSWORD` (con caracteres seguros para URL), `JWT_SECRET_CURRENT` (32 bytes en hex), `ADMIN_PASSWORD`, `N8N_ENCRYPTION_KEY` y una contraseña del owner de n8n, cuyo hash bcrypt SHALL escribirse en `N8N_INSTANCE_OWNER_PASSWORD_HASH` —nunca la contraseña en claro—;
- escribir `N8N_WEBHOOK_URL=http://n8n:5678/webhook/fim-alert`, `N8N_HEALTH_URL=http://n8n:5678/healthz`, las rutas de certificados con sus valores canónicos y `CORS_ALLOWED_ORIGINS` derivado de los hosts y del esquema de la consola;
- crear `.env` con modo `0600` de forma exclusiva y SHALL NOT sobrescribir un `.env` existente, terminando con exit distinto de 0 sin modificarlo;
- mostrar una única vez en la terminal la contraseña inicial del admin y la del owner de n8n, sin escribirlas en ningún otro archivo ni log.

El `.env` resultante SHALL permitir `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app config` sin warnings de variables faltantes.

#### Scenario: Generación en un servidor nuevo
- **WHEN** se ejecuta el script con `FIM_PUBLIC_HOSTS=203.0.113.10` y `CONSOLE_TLS_MODE=off` sin `.env` previo
- **THEN** existe `.env` con modo `0600`, todos los secretos no vacíos y las URLs productivas de n8n
- **AND** la renderización de la composición no emite warnings de variables faltantes

#### Scenario: `.env` existente
- **WHEN** ya existe `.env`
- **THEN** el script termina con exit distinto de 0 y `.env` queda byte a byte idéntico

#### Scenario: Hash bcrypt del owner
- **WHEN** se inspecciona `N8N_INSTANCE_OWNER_PASSWORD_HASH`
- **THEN** su valor tiene formato bcrypt (`$2a$`, `$2b$` o `$2y$`) y no coincide con la contraseña mostrada

#### Scenario: Host inválido
- **WHEN** se provee `FIM_PUBLIC_HOSTS=bad_host!`
- **THEN** el script termina con exit distinto de 0 nombrando la entrada y no crea `.env`

#### Scenario: Secretos independientes por despliegue
- **WHEN** el script se ejecuta dos veces en directorios distintos
- **THEN** ningún secreto generado coincide entre ambos `.env`

### Requirement: Registro de agente en un único paso del lado del servidor (D56/RN-150)

El repositorio SHALL proveer un script que, ejecutado en el servidor con el stack arriba y recibiendo un `agent_id`, en un único paso: genere un secreto de bootstrap de un solo uso de al menos 32 caracteres hexadecimales con un generador criptográfico; registre el agente usando la misma lógica de servicio que `POST /agents/register` (hash Argon2id, conflicto si el `agent_id` ya existe); exporte el `ca.pem` público a un archivo en el directorio actual; y muestre al operador los hosts de `FIM_PUBLIC_HOSTS`, la huella SHA-256 del `ca.pem` en el formato que acepta el instalador, el secreto, y el comando de instalación sugerido **sin** el secreto. El secreto SHALL NOT escribirse en disco, en logs ni en argumentos de procesos. El paso SHALL NOT exigir la contraseña del admin: requiere acceso a Docker en el servidor, que es un privilegio mayor.

#### Scenario: Registro exitoso
- **WHEN** se ejecuta el script con un `agent_id` nuevo
- **THEN** el agente existe en la base con `status=offline` y `bootstrap_secret_hash` poblado
- **AND** la salida contiene los hosts, la huella de la CA, el secreto y un comando de instalación que no contiene el secreto

#### Scenario: Huella coherente con OpenSSL
- **WHEN** se compara la huella mostrada con `openssl x509 -in <ca exportado> -outform DER | sha256sum`
- **THEN** ambas representan el mismo valor

#### Scenario: `agent_id` duplicado
- **WHEN** se ejecuta el script con un `agent_id` ya registrado
- **THEN** termina con exit distinto de 0, informa el conflicto y no muestra ningún secreto como válido

#### Scenario: El secreto no queda en logs
- **WHEN** se inspeccionan los logs del backend después del registro
- **THEN** el valor del secreto no aparece

### Requirement: Guía de despliegue de producto

El repositorio SHALL incluir una guía de despliegue en `docs/`, fuera de `docs/cierre/evidencia/`, que cubra en orden: requisitos del servidor y de los hosts monitoreados; preparación del `.env`; elección del modo de consola con la advertencia del modo `off`; arranque con `docker-compose.yml` + `docker-compose.tls.yml` y el perfil `app`; restricción de acceso a 8443, 8444 y 6380 considerando que Docker omite las reglas de `ufw` para puertos publicados; registro del agente; instalación del agente con los datos entregados; verificación del despliegue; reinstalación y actualización del agente; y renovación del certificado provisto de la consola. `README.md` SHALL enlazar la guía. La guía SHALL NOT requerir editar YAML, editar `/etc/hosts` ni ejecutar archivos de `docs/cierre/evidencia/`.

#### Scenario: Enlace desde el README
- **WHEN** se inspecciona `README.md`
- **THEN** contiene un enlace a la guía de despliegue

#### Scenario: Sin dependencias de la evidencia
- **WHEN** se buscan referencias a `docs/cierre/evidencia/` entre los comandos de la guía
- **THEN** no hay ninguna

#### Scenario: Reproducción multi-host siguiendo la guía
- **WHEN** un operador sigue la guía en un servidor con `FIM_PUBLIC_HOSTS=<ip>` y un host monitoreado distinto, sin editar YAML ni `/etc/hosts`
- **THEN** el agente completa el bootstrap por 8444, publica por 6380 y sus eventos aparecen en la consola
- **AND** `GET /health/components` reporta `n8n: ok`
