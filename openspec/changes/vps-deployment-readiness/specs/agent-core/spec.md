## ADDED Requirements

### Requirement: Instalador parametrizable con prompts para valores faltantes (D56/RN-150)

`agent/install.sh` SHALL aceptar sus entradas por flags o por variables de entorno, con precedencia flag > variable de entorno > prompt interactivo:

| Entrada | Flag | Variable de entorno |
|---|---|---|
| Host del servidor (DNS o IP) | `--server-host` | `FIM_SERVER_HOST` |
| `agent_id` (default: hostname del equipo) | `--agent-id` | `FIM_AGENT_ID` |
| `watch_paths` (repetible / separadas por comas) | `--watch-path` | `FIM_WATCH_PATHS` |
| Ruta del `ca.pem` del servidor | `--ca-cert` | `FIM_CA_CERT` |
| Huella SHA-256 esperada de la CA | `--ca-fingerprint` | `FIM_CA_FINGERPRINT` |
| Archivo con el secreto de bootstrap | `--bootstrap-secret-file` | `FIM_BOOTSTRAP_SECRET_FILE` |

A partir del host SHALL derivar `backend_url=https://<host>:8444`, `mtls_backend_url=https://<host>:8443` y `valkey_url=valkeys://<host>:6380`, encerrando entre corchetes un literal IPv6. Cada `watch_path` SHALL ser absoluto, existir, y pasar la misma validación que el generador del drop-in (`agent.deployment`). Con `--non-interactive`, un valor faltante SHALL terminar la instalación con exit distinto de 0 nombrando la entrada, antes de modificar nada bajo `/etc/fim-agent`. `config.yaml` SHALL generarse a partir de `agent/deploy/config.yaml.example`, reemplazando sólo los campos derivados de las entradas y conservando los demás defaults.

#### Scenario: Instalación con flags completos
- **WHEN** se ejecuta `install.sh --non-interactive --server-host 203.0.113.10 --agent-id web-01 --watch-path /srv/app --ca-cert ./fim-ca.pem --ca-fingerprint <huella> --bootstrap-secret-file ./secret` en un host sin instalación previa
- **THEN** `/etc/fim-agent/config.yaml` contiene `agent_id: web-01`, `backend_url: https://203.0.113.10:8444`, `mtls_backend_url: https://203.0.113.10:8443`, `valkey_url: valkeys://203.0.113.10:6380` y `watch_paths: [/srv/app]`

#### Scenario: `agent_id` por defecto
- **WHEN** no se provee `agent_id` y se acepta el prompt vacío
- **THEN** `agent_id` es el hostname del equipo

#### Scenario: Ruta vigilada inválida
- **WHEN** un `watch_path` es relativo o no existe
- **THEN** la instalación termina con exit distinto de 0 nombrando la ruta y no se escribe nada bajo `/etc/fim-agent`

#### Scenario: Valor faltante en modo no interactivo
- **WHEN** se ejecuta con `--non-interactive` sin `--server-host` ni `FIM_SERVER_HOST`
- **THEN** termina con exit distinto de 0 nombrando la entrada faltante

### Requirement: El secreto de bootstrap nunca se acepta como argumento (D56/RN-150)

El instalador SHALL obtener el secreto de bootstrap únicamente por prompt oculto (sin eco en la terminal) o leyéndolo de un archivo. SHALL NOT existir flag, argumento posicional ni variable de entorno que transporte el valor del secreto; un flag no reconocido que lo intente (por ejemplo `--bootstrap-secret`) SHALL rechazarse sin escribir nada. El secreto SHALL validarse (al menos 16 caracteres) antes de escribirlo, SHALL escribirse sólo en `/etc/fim-agent/env` como `FIM_BOOTSTRAP_SECRET` (modo `0600`, `root:root`), y SHALL NOT aparecer en `config.yaml`, en la salida del instalador, en logs, ni en los argumentos de ningún proceso que el instalador lance.

#### Scenario: Intento de pasar el secreto por argumento
- **WHEN** se ejecuta `install.sh --bootstrap-secret 0123456789abcdef`
- **THEN** termina con exit distinto de 0 indicando que el secreto se provee por prompt o archivo
- **AND** no se escribe ningún archivo bajo `/etc/fim-agent`

#### Scenario: Secreto desde archivo
- **WHEN** se provee `--bootstrap-secret-file` con un secreto válido
- **THEN** `/etc/fim-agent/env` contiene `FIM_BOOTSTRAP_SECRET=<secreto>` con modo `0600` y dueño `root:root`
- **AND** el valor no aparece en la salida del instalador ni en los argumentos de los subprocesos lanzados

#### Scenario: Secreto demasiado corto
- **WHEN** el secreto provisto tiene menos de 16 caracteres
- **THEN** la instalación termina con exit distinto de 0 sin escribir `/etc/fim-agent/env`

### Requirement: Ancla de confianza verificada por huella SHA-256 (D56/RN-150, RN-114)

El instalador SHALL calcular la huella SHA-256 sobre la codificación DER del certificado provisto como `ca.pem` y SHALL compararla con la huella esperada, aceptando hexadecimal sin distinguir mayúsculas e ignorando `:` y espacios —el mismo formato que entrega el paso de registro del servidor—. Si no coinciden, si el archivo no es un certificado PEM válido o si no es un certificado de CA, SHALL abortar antes de escribir cualquier archivo bajo `/etc/fim-agent` y antes de habilitar el servicio, mostrando la huella esperada y la calculada. Si coinciden, SHALL copiar el certificado a `ca_cert_path` con modo `0644` y dueño `root`.

#### Scenario: Huella coincidente
- **WHEN** la huella calculada coincide con la esperada
- **THEN** el certificado queda en `ca_cert_path` y la instalación continúa

#### Scenario: Huella distinta
- **WHEN** la huella calculada no coincide con la esperada
- **THEN** la instalación termina con exit distinto de 0, muestra ambas huellas y no escribe nada bajo `/etc/fim-agent`

#### Scenario: Formatos equivalentes de huella
- **WHEN** la huella esperada se provee como `AB:CD:...` en mayúsculas y la calculada es `abcd...`
- **THEN** se consideran coincidentes

### Requirement: La configuración existente no se sobrescribe sin reconfiguración explícita (D56/RN-150)

Si `/etc/fim-agent/config.yaml` o `/etc/fim-agent/env` existen, el instalador SHALL NOT modificarlos salvo que se invoque con `--reconfigure`. Sin ese flag, si se proveyeron entradas que difieren de la configuración existente, SHALL advertir que se ignoran y cómo aplicarlas. Con `--reconfigure`, SHALL regenerarlos a partir de las entradas, conservando una copia del archivo anterior. Al finalizar toda ejecución SHALL informar que, tras el primer bootstrap, la configuración autoritativa vive en el backend y se modifica desde la consola, y que reconfigurar localmente sólo afecta los datos de conexión de un agente aún no enrolado.

#### Scenario: Re-ejecución sin reconfiguración
- **WHEN** se ejecuta `install.sh` sobre un host con `config.yaml` y `env` existentes, sin `--reconfigure`
- **THEN** ambos archivos quedan byte a byte idénticos

#### Scenario: Reconfiguración explícita
- **WHEN** se ejecuta con `--reconfigure` y un `--server-host` distinto
- **THEN** `config.yaml` refleja las URLs derivadas del nuevo host y existe una copia del archivo anterior

#### Scenario: Aviso de autoridad de la configuración
- **WHEN** termina cualquier ejecución del instalador
- **THEN** la salida informa que tras el primer bootstrap la configuración autoritativa vive en el backend

### Requirement: La reinstalación reemplaza el código instalado (D56/RN-150)

Re-ejecutar el instalador SHALL reemplazar el árbol de código instalado en `/opt/fim-agent/agent` por el de la fuente, en lugar de copiar la fuente dentro del destino existente. Tras la reinstalación, `/opt/fim-agent/agent/agent` SHALL NOT existir, los archivos eliminados de la fuente SHALL NOT permanecer en el destino, y la propiedad SHALL seguir siendo `root:root` (D36/RN-130). Si el servicio estaba activo, SHALL reiniciarse para ejecutar el código nuevo.

#### Scenario: Código actualizado
- **WHEN** se modifica un módulo en la fuente y se re-ejecuta el instalador
- **THEN** el archivo instalado es idéntico al de la fuente
- **AND** no existe `/opt/fim-agent/agent/agent`

#### Scenario: Archivo eliminado en la fuente
- **WHEN** un archivo existe en la instalación previa pero ya no en la fuente
- **THEN** tras la reinstalación el archivo no existe en `/opt/fim-agent/agent`

#### Scenario: Servicio activo reiniciado
- **WHEN** `fim-agent.service` está activo al re-ejecutar el instalador
- **THEN** el servicio se reinicia y el proceso resultante carga el código nuevo

### Requirement: Verificación de alcance antes de habilitar el servicio (D56/RN-150)

Antes de habilitar `fim-agent.service`, el instalador SHALL verificar, para el puerto 8444 y el puerto 6380 del host del servidor, la resolución del nombre, la conexión TCP y un handshake TLS que verifique el certificado del servidor contra la CA verificada y su SAN contra el host configurado, con un tiempo máximo acotado por intento. SHALL informar el resultado por puerto distinguiendo resolución, conexión rechazada o agotada, y verificación TLS (incluida la discrepancia de hostname). En el puerto 6380 el rechazo posterior por falta de certificado de cliente SHALL NOT contarse como falla, porque el agente todavía no se enroló. Si alguna verificación falla, el instalador SHALL completar la instalación sin habilitar ni arrancar el servicio y SHALL terminar con exit distinto de 0; si todas pasan, SHALL habilitar el servicio y arrancarlo cuando haya un secreto de bootstrap provisto para un host sin certificado propio.

#### Scenario: Servidor alcanzable
- **WHEN** 8444 y 6380 responden con certificados que encadenan a la CA y cubren el host
- **THEN** el instalador informa ambos puertos como alcanzables y habilita el servicio

#### Scenario: Puerto 6380 inalcanzable
- **WHEN** la conexión TCP a 6380 es rechazada
- **THEN** el instalador informa la falla nombrando el puerto 6380 y la causa, no habilita el servicio y termina con exit distinto de 0

#### Scenario: Hostname no cubierto por el SAN
- **WHEN** el certificado presentado en 8444 encadena a la CA pero no cubre el host configurado
- **THEN** el instalador informa una discrepancia de hostname y sugiere revisar `FIM_PUBLIC_HOSTS` del servidor
