# Runbook A-3 — Ensayo multianfitrión con mTLS y TLS de Valkey (agente en WSL2)

**Estado:** Fases 0–2 ejecutadas (ver "Registro de ejecución"). Fase 3 escrita y **no ejecutada**. Fases 4–7
pendientes. El carril L8 se resuelve por configuración (opción A: certificado de cliente propio del backend), sin
cambios de código.

**Regla del ensayo:** no se modifica nada para "hacer pasar" una prueba. Todo intento fallido se conserva y se
documenta. Ninguna salida con contraseñas, claves privadas o tokens se pega en chats ni se archiva.

---

## 0. Qué se construye y qué se podrá afirmar

```
PC Windows (192.168.1.x)                     Laptop (192.168.1.43)
┌──────────────────────────────┐             ┌────────────────────────────────┐
│ WSL2 → Ubuntu 24.04          │   LAN real  │ Docker Compose (servidor)      │
│  └─ agente FIM (systemd)     │ ──mTLS────▶ │  ├─ backend  (listener mTLS)   │
│     vigila /srv/fim-watch    │ ──TLS─────▶ │  ├─ Valkey   (TLS + cert. cli.)│
│     con fanotify real        │             │  ├─ PostgreSQL                 │
└──────────────────────────────┘             │  └─ frontend                   │
                                             └────────────────────────────────┘
```

- **Anfitrión 1 (servidor central):** laptop Linux, con los servicios en Docker Compose y el override TLS.
- **Anfitrión 2 (monitoreado):** PC física distinta, con Ubuntu sobre WSL2 y el agente instalado de forma
  nativa con `install.sh` y systemd.

**Afirmación defendible si todo pasa:** "ensayo sobre dos equipos físicos conectados por LAN; agente nativo en
Ubuntu sobre WSL2 (máquina virtual ligera de Hyper-V); mTLS agente–backend y TLS con certificado de cliente en
Valkey verificados, incluidos los rechazos negativos".

**No se podrá afirmar:** despliegue productivo, alta disponibilidad, red WAN o Internet, anfitrión Linux de metal
desnudo, ni rendimiento extrapolable.

**Por qué WSL2 y no WSL1:** WSL2 ejecuta un kernel Linux real dentro de una VM liviana. WSL1 traduce llamadas del
sistema a Windows y no ofrece fanotify.

**Por qué no un contenedor en la laptop:** comparte kernel y pila de red con el servidor. Sería un único
anfitrión.

---

# FASE 0 — Preparar Windows (PC monitoreada)

Todo se hace en la PC con Windows. Algunos pasos requieren **PowerShell como administrador**: menú Inicio,
escribir "PowerShell", clic derecho y elegir "Ejecutar como administrador".

## 0.1 Verificar la versión de Windows

1. `Win + R` → escribir `winver` → Enter.
2. Anotar la edición y el número de compilación ("Compilación del SO").

| Resultado | Qué significa |
|---|---|
| Windows 11, compilación 22621 o mayor | Todo disponible, incluido el modo de red espejo (recomendado) |
| Windows 11 anterior a 22621 o Windows 10 con compilación 19041 o mayor | WSL2 funciona; se usa la red NAT por defecto |
| Windows 10 con compilación menor a 19041 | Actualizar Windows antes de seguir |

## 0.2 Verificar la virtualización en la BIOS

1. Abrir el Administrador de tareas (`Ctrl + Shift + Esc`) → **Rendimiento** → **CPU**.
2. Abajo a la derecha, el campo **Virtualización** tiene que decir **Habilitado**.

Si dice "Deshabilitado":

1. Reiniciar y entrar a la BIOS/UEFI (según el fabricante: F2, Supr, F10 o Esc al encender).
2. Activar "Intel Virtualization Technology (VT-x)" en Intel, o "SVM Mode" / "AMD-V" en AMD.
3. Guardar (normalmente F10) y reiniciar.

Sin virtualización, WSL2 no arranca.

## 0.3 Evitar suspensión durante el ensayo

La suspensión provoca desfase de reloj en WSL2. Eso afecta la ventana anti-replay de 300 s y las mediciones.

1. Configuración → Sistema → Inicio/apagado y suspensión (o "Energía").
2. Con la PC enchufada, poner "Suspender" y "Apagar pantalla" en **Nunca** mientras dure el ensayo.
3. Si es una notebook, dejarla conectada a la corriente.

## 0.4 Instalar o actualizar WSL

En **PowerShell como administrador**:

```powershell
wsl --version
```

| Resultado | Acción |
|---|---|
| Muestra "Versión de WSL: 2.x.x" | Seguir con 0.5 |
| Error o texto de ayuda sin versión | WSL viejo o ausente; ejecutar lo que sigue |

```powershell
wsl --install --no-distribution
wsl --update
```

**Qué hace:** habilita los componentes "Subsistema de Windows para Linux" y "Plataforma de máquina virtual", e
instala la versión actual de WSL desde Microsoft.

**Reiniciar Windows** si lo pide. Después, volver a ejecutar `wsl --version` y confirmar que muestra versión 2.x.

## 0.5 Fijar WSL2 como versión por defecto

```powershell
wsl --set-default-version 2
```

Debe responder que la operación se completó correctamente.

## 0.6 Instalar Ubuntu 24.04

```powershell
wsl --list --online
wsl --install -d Ubuntu-24.04
```

Al terminar se abre una ventana de Ubuntu que pide:

- **Nombre de usuario Unix:** por ejemplo `fimlab`, en minúsculas y sin espacios.
- **Contraseña:** no se ve mientras se escribe, es normal. Guardarla: se usará para `sudo`.

Cuando aparezca un prompt como `fimlab@NOMBRE-PC:~$`, escribir `exit`.

Si la PC ya tenía otra distro Ubuntu instalada (por ejemplo 22.04 `jammy`), fijar la nueva como predeterminada y
confirmar desde adentro que es la correcta:

```powershell
wsl --set-default Ubuntu-24.04
```

```bash
lsb_release -cs   # debe responder: noble
```

Una distro nueva parte vacía: la Fase 1 completa se ejecuta en ella, empezando por 1.1.

## 0.7 Confirmar que la distro corre en WSL2

En PowerShell:

```powershell
wsl -l -v
```

Salida esperada:

```
  NAME            STATE           VERSION
* Ubuntu-24.04    Stopped         2
```

Si VERSION dice **1**, convertirla. Tarda unos minutos:

```powershell
wsl --set-version Ubuntu-24.04 2
```

## 0.8 Configurar recursos y red de WSL2 (`.wslconfig`)

1. Abrir el Bloc de notas.
2. Pegar **una** de estas dos variantes, según el paso 0.1.

**Windows 11, compilación 22621 o mayor (recomendado):**

```ini
[wsl2]
memory=4GB
processors=2
networkingMode=mirrored
```

**Windows 10 o Windows 11 anterior:**

```ini
[wsl2]
memory=4GB
processors=2
```

3. Guardar como `C:\Users\<TU_USUARIO_WINDOWS>\.wslconfig`. En "Tipo" elegir "Todos los archivos" para que no
   agregue `.txt`.
4. Aplicar en PowerShell:

```powershell
wsl --shutdown
```

**Qué hace:**

- `memory` y `processors` limitan lo que consume la VM.
- `networkingMode=mirrored` hace que Ubuntu vea la misma IP de LAN que Windows; así el tráfico de la captura se
  corresponde con la red física.
- En modo NAT (por defecto) también funciona, porque el agente sólo inicia conexiones salientes hacia la laptop.

## 0.9 Anotar la IP de la PC Windows en la LAN

En PowerShell:

```powershell
ipconfig
```

Anotar la "Dirección IPv4" del adaptador Wi-Fi o Ethernet conectado al mismo router que la laptop (por ejemplo
`192.168.1.50`). Se usará para abrir el firewall de la laptop **sólo** para esa IP.

**Punto de control 0:** anotar y compartir la salida de `wsl --version`, `wsl -l -v`, la compilación de Windows y
la IPv4 de la PC.

---

# FASE 1 — Preparar Ubuntu dentro de WSL2

Abrir Ubuntu desde el menú Inicio ("Ubuntu 24.04"). Todos los comandos de esta fase van en esa terminal.

## 1.1 Activar systemd

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true

[time]
useWindowsTimezone=true
EOF
cat /etc/wsl.conf
```

**Qué hace:** WSL2 no arranca systemd por defecto, y el agente se instala como servicio systemd (`fim-agent.service`).

Aplicar:

1. Salir de Ubuntu con `exit`.
2. En PowerShell: `wsl --shutdown`.
3. Esperar unos 10 segundos y volver a abrir Ubuntu.
4. Verificar:

```bash
systemctl is-system-running
```

Valores aceptables: `running` o `degraded`. `degraded` es habitual en WSL, porque algunas unidades de hardware no
aplican. Si dice `offline` o "System has not been booted with systemd", repetir 1.1.

## 1.2 Actualizar e instalar herramientas

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y python3 python3-venv python3-pip git openssl chrony netcat-openbsd tcpdump jq curl ca-certificates
```

**Para qué sirve cada una:**

| Herramienta | Uso |
|---|---|
| `python3`, `python3-venv`, `python3-pip` | El agente corre en un entorno virtual en `/opt/fim-agent` |
| `git` | Traer el código del candidato |
| `openssl` | Inspeccionar certificados y handshakes TLS |
| `chrony` | Sincronización NTP y medición del desfase de reloj |
| `netcat-openbsd` | Probar conectividad TCP con la laptop |
| `tcpdump` | Capturar tráfico para demostrar que viaja cifrado |
| `jq`, `curl` | Leer respuestas JSON de la API |

## 1.3 Activar la sincronización de reloj

```bash
sudo systemctl enable --now chrony
sleep 20
chronyc tracking
timedatectl
```

- En `chronyc tracking`, "System time" debería estar por debajo de unas decenas de milisegundos.
- En `timedatectl`, "System clock synchronized" tiene que decir **yes**.

**Limitación de esta medición:** en WSL2, chrony suele sincronizar contra `PHC0` (stratum 1), que es el reloj que
Hyper-V expone desde Windows, no un servidor NTP externo. Un desfase de microsegundos sólo prueba que WSL coincide
con Windows. El desfase relevante para la ventana anti-replay y para la latencia es **Windows ↔ laptop**. Registrar
en PowerShell:

```powershell
w32tm /query /status
```

## 1.4 Crear el directorio vigilado en el disco Linux

```bash
sudo mkdir -p /srv/fim-watch
sudo chmod 755 /srv/fim-watch
df -T /srv/fim-watch
```

La columna "Type" tiene que decir **ext4**. **Nunca** vigilar `/mnt/c/...`: es un montaje de Windows (9p/drvfs),
donde fanotify en modo identificador de archivo no funciona.

## 1.5 Chequeo previo completo

Ejecutar y **compartir toda la salida**:

```bash
echo "== kernel";   uname -r
echo "== fanotify"; (zgrep CONFIG_FANOTIFY /proc/config.gz 2>/dev/null || grep CONFIG_FANOTIFY /boot/config-$(uname -r) 2>/dev/null || echo "config del kernel no visible")
echo "== syscall";  python3 - <<'PY'
import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
FAN_CLASS_NOTIF, FAN_REPORT_DFID_NAME = 0x0, 0x00000c00
fd = libc.fanotify_init(FAN_CLASS_NOTIF | FAN_REPORT_DFID_NAME, os.O_RDONLY)
print("fanotify_init sin privilegios:", fd, "errno", ctypes.get_errno(), "(kernel >= 5.13: descriptor valido en modo FID; EPERM=1 en kernels anteriores)")
PY
sudo python3 - <<'PY'
import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.fanotify_init(0x0 | 0x00000c00, os.O_RDONLY)
print("fanotify_init con root:", fd, "errno", ctypes.get_errno())
PY
echo "== systemd";  systemctl is-system-running
echo "== reloj";    timedatectl | sed -n '1,7p'; chronyc tracking | sed -n '1,6p'
echo "== python";   python3 --version
echo "== red";      ip -br addr; ip route
echo "== laptop";   ping -c 3 192.168.1.43; nc -vz -w 3 192.168.1.43 22 || true
echo "== fs";       df -T /srv/fim-watch | tail -1
```

**Criterios para seguir:**

| Chequeo | Requisito |
|---|---|
| Kernel | 5.9 o superior |
| fanotify con root | Un número ≥ 0 (descriptor válido). Un valor -1 con errno 22 (EINVAL) o 38 (ENOSYS) invalida WSL2 para este ensayo |
| systemd | `running` o `degraded` |
| Reloj | Sincronizado |
| Laptop | `ping` responde. El `nc` al puerto 22 puede fallar si la laptop no tiene SSH; no bloquea |
| Sistema de archivos | `ext4` |

**Notas de lectura:**

- **fanotify sin privilegios:** desde Linux 5.13 un proceso sin privilegios puede crear un grupo fanotify en modo
  FID, restringido a marcas sobre inodos individuales. Marcar un filesystem o un mount completo sigue exigiendo
  `CAP_SYS_ADMIN`, por eso el agente mantiene sus capabilities. Un descriptor válido sin root no es una anomalía.
- **"config del kernel no visible" junto a líneas `CONFIG_FANOTIFY=y`:** la línea se partió al pegarla en la
  terminal. Vale el resultado de `zgrep`.
- **`nc` con "Connection refused":** la laptop respondió con RST; hay ruta TCP y no hay servicio en el puerto 22.
  Un *timeout* indicaría filtrado.
- **Latencia de `ping` muy variable** (Wi-Fi): registrarla, porque condiciona la medición de latencia de la Fase 5.

**Punto de control 1:** compartir la salida completa de 1.5.

**Plan B si fanotify no funciona en WSL2:** arrancar esa misma PC con un USB de Ubuntu 24.04 en modo "live" (sin
instalar) y repetir las Fases 1–2 allí. Siguen siendo dos equipos físicos.

---

# FASE 2 — Preparar la laptop (servidor central)

Todo en la laptop (192.168.1.43).

## 2.1 IP fija para la laptop

En el panel del router (normalmente `http://192.168.1.1`), sección DHCP, reservar `192.168.1.43` para la MAC de la
interfaz Wi-Fi de la laptop.

Consultar la MAC:

```bash
ip link show wlp2s0 | awk '/ether/{print $2}'
```

**Por qué:** si la IP cambia durante el ensayo, los certificados, la configuración del agente y el firewall
quedan apuntando a una dirección vieja.

**Alternativa si el panel del router está bloqueado** (caso de este ensayo, router Movistar): fijar la IP en la
laptop con NetworkManager, conservando la dirección, el gateway y los DNS que entregó el DHCP:

```bash
nmcli con mod "<CONEXION>" ipv4.method manual ipv4.addresses 192.168.1.43/24 \
  ipv4.gateway 192.168.1.1 ipv4.dns "<DNS1> <DNS2>"
nmcli con up "<CONEXION>"
```

Limitación: el router no conoce la reserva y, al vencer el préstamo, podría asignar esa IP a otro dispositivo.
Registrar `ip -br addr show wlp2s0` en la laptop y `ping 192.168.1.43` desde WSL al inicio y al final del ensayo.
Al terminar, restaurar DHCP:

```bash
nmcli con mod "<CONEXION>" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
nmcli con up "<CONEXION>"
```

## 2.2 Desactivar la suspensión durante el ensayo

Configuración de energía del escritorio: suspensión en **Nunca**, con el cargador conectado.

## 2.3 Estado del firewall

```bash
sudo ufw status verbose
```

- Si dice `inactive`, no hay filtrado local. Igual se recomienda activarlo con reglas explícitas en la Fase 3.
- Si dice `active`, anotar las reglas. En la Fase 3 se abrirán **sólo desde la IP de la PC Windows** los puertos
  del listener mTLS del backend y de Valkey TLS.

## 2.4 Sincronización de reloj en la laptop

```bash
timedatectl
chronyc tracking 2>/dev/null || systemctl status systemd-timesyncd --no-pager | head -5
```

Ambos anfitriones deben estar sincronizados. El desfase se registra al inicio y al final del ensayo.

## 2.5 Confirmar la ruta de red entre los dos equipos

Desde la laptop:

```bash
ping -c 3 <IP_DE_LA_PC_WINDOWS>
```

Si el ping no responde, Windows puede estar bloqueando ICMP entrante. No bloquea el ensayo, porque el agente
inicia las conexiones hacia la laptop. Lo que importa es que desde Ubuntu/WSL se alcance la laptop (verificado en
1.5).

**Punto de control 2:** compartir la salida de 2.3 y 2.4 y la confirmación de la reserva DHCP.

---

# Registro de ejecución

## Punto de control 1 — 2026-09-12 (PASA)

| Chequeo | Observado | Criterio |
|---|---|---|
| Distro | Ubuntu 24.04 (`noble`) | Ubuntu 24.04 |
| Kernel | `6.18.33.2-microsoft-standard-WSL2` | ≥ 5.9 |
| `CONFIG_FANOTIFY` / `..._ACCESS_PERMISSIONS` | `y` / `y` | habilitado |
| `fanotify_init` con root | fd 3, errno 0 | fd ≥ 0 |
| `fanotify_init` sin privilegios | fd 3, errno 0 | informativo (kernel ≥ 5.13) |
| systemd | `running` | `running` o `degraded` |
| Reloj WSL | sincronizado; referencia `PHC0` stratum 1; desfase ~2 µs | sincronizado (ver limitación en 1.3) |
| Zona horaria WSL | `Etc/UTC` (`useWindowsTimezone` no aplicado) | no bloquea; timestamps de logs en UTC |
| Python | 3.12.3 | — |
| Red | modo espejo; `eth0` = **192.168.1.36/24**, gateway 192.168.1.1 | misma LAN que la laptop |
| Laptop 192.168.1.43 | ping 3/3, RTT 2.7 / 86 / 278 ms | responde |
| TCP laptop:22 | `Connection refused` | no bloquea |
| `/srv/fim-watch` | ext4 | ext4 |

**IP de la PC monitoreada para el firewall de la laptop:** `192.168.1.36`.

**Pendiente:** desfase Windows ↔ laptop (`w32tm /query /status` y `chronyc tracking` en la laptop).

## Punto de control 2 — 2026-09-12 (PARCIAL)

| Paso | Observado | Estado |
|---|---|---|
| 2.1 IP fija | Panel del router bloqueado. IP fijada en la laptop con NetworkManager (~18:00 -03): `manual`, `192.168.1.43/24`, gateway `192.168.1.1`, DNS `186.130.128.250`, `186.130.129.250`. Ruta por defecto `proto static`; gateway e Internet responden | hecho (reserva del lado cliente, ver limitación en 2.1) |
| 2.2 Suspensión | — | pendiente |
| 2.3 Firewall | laptop: `ufw` inactivo; cadena `DOCKER-USER` vacía (sólo `-N DOCKER-USER`). PC: `ufw` inactivo (no escucha puertos para el ensayo) | pasa; sin filtrado local en la laptop. Los puertos publicados por Docker evitan las reglas de `ufw`: la restricción a `192.168.1.36` se aplicará en `DOCKER-USER` durante la Fase 3 |
| 2.4 Reloj laptop | sincronizado; referencia `ntp-nts-2.ps6.canonical.com` stratum 3; +0,47 ms | pasa |
| 2.5 Ping laptop → PC | 0/3 hacia `192.168.1.36` | no bloquea (Windows filtra ICMP entrante; WSL → laptop verificado en 1.5) |

**Restaurar DHCP al terminar:** ver `~/Escritorio/VOLVER_IP_DHCP_LAPTOP.md` en la laptop.

## Cambio de plataforma del anfitrión monitoreado — 2026-09-12

WSL2 pasó el punto de control 1, pero se reemplazó por Linux instalado en disco en la misma PC física. Motivo:
permite afirmar "anfitrión Linux de metal desnudo" y elimina la VM de Hyper-V, el reloj heredado de Windows y la red
espejo. El registro WSL2 de arriba se conserva como intento válido y no se usa para el ensayo.

## Punto de control 1 (nativo) — 2026-09-12 (PASA, con bloqueo en Python)

| Chequeo | Observado | Criterio |
|---|---|---|
| Distro | **Ubuntu 26.04.1 LTS (`resolute`)**, instalado en disco | el runbook preveía 24.04; ver desvío |
| Kernel | `7.0.0-31-generic` | ≥ 5.9 |
| `CONFIG_FANOTIFY` / `..._ACCESS_PERMISSIONS` | `y` / `y` | habilitado |
| `fanotify_init` con root | fd 4, errno 0 | fd ≥ 0 |
| systemd | `running` | `running` o `degraded` |
| Reloj | sincronizado; `ntp-nts-3.ps6.canonical.com` stratum 3; −0,28 ms; zona `America/Argentina/Mendoza` | sincronizado |
| Python del sistema | **3.14.4** | ver bloqueo |
| Red | Ethernet `enp6s0` = **192.168.1.36/24** (DHCP), gateway 192.168.1.1 | misma LAN que la laptop |
| Laptop 192.168.1.43 | ping 3/3, RTT 158 / 2,4 / 2,4 ms | responde |
| TCP laptop:8443 | `succeeded` | listener mTLS del backend alcanzable |
| `/srv/fim-watch` | ext4 (`/dev/nvme0n1p2`) | ext4 |

**IP de la PC monitoreada para el firewall de la laptop:** `192.168.1.36` (sin cambios; ahora por Ethernet y DHCP).

**Bloqueo detectado — dependencias del agente en Python 3.14:** verificado en la laptop con `uv` y Python 3.14.4.
`pydantic==2.10.6` requiere `pydantic-core==2.27.2`, que no publica wheels para 3.14 y cuya compilación desde
fuente falla. `PyYAML==6.0.2` tampoco publica wheels para 3.14. `agent/install.sh` crea el venv con el `python3`
del sistema, así que la instalación nativa fallaría. La versión validada del agente es 3.13 (`agent/Dockerfile`).

**Resolución sin cambiar código:** Python 3.13.15 instalado con `uv` en `/opt/python`, y venv creado de antemano con
`uv venv --seed --python <3.13> /opt/fim-agent/venv`. `install.sh` sólo crea el venv si `venv/bin/python` no existe,
así que reutiliza este. Verificado: `sudo -u nobody /opt/fim-agent/venv/bin/python --version` → `Python 3.13.15`.

## Sincronización del código del agente — 2026-09-12

Los cambios del agente pendientes en la laptop se commitearon y pushearon a `origin/devel` (`26c6cee`, `ca34335`,
`223f85c`). Suite del agente en Python 3.13: 513 aprobados, 1 omitido. En la PC: `HEAD` = `223f85c` y
`git status --porcelain agent` vacío. **Limitación:** el backend de la laptop se construye desde el árbol de trabajo,
que tiene cambios sin commitear fuera de `agent/`.

## Fase 3 — intento 1 — 2026-09-12 21:16 -03 (FALLA en 3.5)

| Paso | Resultado | Evidencia |
|---|---|---|
| 3.0 | `HEAD` = `223f85c`; 129 entradas en `git status --porcelain`; stack en texto plano | `fase3/00-estado-inicial.txt` |
| 3.1 | agente en contenedor detenido (`exited`) | — |
| 3.2 | certificado de cliente emitido: `CN=fim-backend-valkey`, EKU `clientAuth`, vence 2026-10-13, sha256 `44f8b298…dea0f`, clave `0400` uid 10001; `openssl verify` OK | `fase3/01-emision-cert-cliente.txt`, `fase3/02-certificados.txt` |
| 3.3 | configuración combinada correcta (URL con certificado, `--tls-auth-clients`, 6380 publicado) | `fase3/03-config.txt` |
| 3.4 | `valkey` healthy con TLS en 6380 publicado; `backend` running | `fase3/04-compose-ps.txt`, `fase3/04-imagenes.txt` |
| 3.5 | **FALLA**: `/health/components` → `"valkey": "down"`. El backend rechaza el certificado **del servidor** Valkey: `CERTIFICATE_VERIFY_FAILED ... Missing Authority Key Identifier` | `fase3/05-health-components.json`, `fase3/05-backend-logs.txt` |

**Causa verificada:**

- `ssl.create_default_context()` de Python 3.13 (usado por valkey-py, `connection.py:846`) activa
  `VERIFY_X509_STRICT` (`verify_flags=557088`, bit `0x20`). Ese modo exige la extensión Authority Key Identifier en
  certificados no raíz.
- `valkey.pem` no la tiene: `scripts/emitir_cert_valkey.py` no la agrega. `openssl verify -x509_strict` reproduce el
  error `85 Missing Authority Key Identifier`.
- `backend.pem` y `backend-valkey.pem` sí la tienen y pasan en modo estricto. La CA es válida (`CA:TRUE` crítica,
  `keyCertSign`, SKI presente).
- El certificado de cliente (carril L8) no interviene en el error: la falla ocurre al verificar el servidor.
- **Impacto sobre la Fase 4:** el agente de la PC también corre en Python 3.13, así que fallaría igual contra este
  `valkey.pem`.

El stack quedó con Valkey en TLS y el backend sin acceso a Valkey. No se modificó nada tras la falla.

## Fase 3 — intento 2 — 2026-09-12 21:19 -03 (3.0–3.6 PASAN; 3.7 pendiente)

**Corrección aplicada:** `scripts/emitir_cert_valkey.py` agrega ahora la extensión Authority Key Identifier (misma
construcción que `backend/app/core/pki.py`). `valkey.pem` reemitido: SAN `valkey, localhost`, EKU
`serverAuth, clientAuth`, AKI `52:F1:C7:…:9A:29` (= SKI de la CA), vence 2026-12-12, `openssl verify -x509_strict` OK.
Valkey reiniciado para cargar el certificado. El certificado del intento 1 se conserva como
`fase3/valkey-intento1-sin-aki.pem`.

| Paso | Resultado | Evidencia |
|---|---|---|
| 3.5 | **PASA**: `"valkey": "ok"`; `consumer.started` (grupo `fim-backend`) y `command_ack_consumer.started`; transición `health.state_change` `down → ok`. `docker-agent` figura `offline` porque el agente en contenedor está detenido (3.1) | `fase3/08-reemision-valkey-cert.txt`, `fase3/05b-health-components-intento2.json`, `fase3/05b-backend-logs-intento2.txt` |
| 3.6 | **PASA**: sin certificado de cliente, el certificado del servidor verifica (`verify return:1` en ambas profundidades) y Valkey corta con `tlsv13 alert certificate required` (alerta 116); sin `+PONG` | `fase3/06-valkey-sin-cert-cliente.txt` |

**Desde la PC** (`/etc/hosts`: `192.168.1.43 valkey backend`): `getent` resuelve ambos nombres; `nc` a `valkey:6380` y
`backend:8443` → `succeeded` (sin firewall todavía).

## Fase 3 — paso 3.7 — 2026-09-12 21:22–21:25 -03 (PASA)

| Prueba | Resultado | Evidencia |
|---|---|---|
| Estado previo (21:22) | `DOCKER-USER` vacía en IPv4 e IPv6 (`-N DOCKER-USER`) | salida de consola; ver nota de evidencia |
| Reglas aplicadas (21:22) | IPv4: `DROP` en 8443 y 6380 desde `wlp2s0` si el origen no es `192.168.1.36`. IPv6: `DROP` en 8443 y 6380 desde `wlp2s0` | salida de consola; ver nota de evidencia |
| Positiva (PC permitida) | `nc` desde la PC a `valkey:6380` y `backend:8443` → `succeeded` | salida en consola de la PC |
| Negativa (IP permitida cambiada a `192.168.1.250`, contadores en cero) | `nc` desde la PC → `timed out` en ambos puertos. Contadores: 3 paquetes / 180 bytes descartados por regla (SYN y reintentos) | `fase3/07-firewall-negativo.txt` |
| Restauración | reglas de nuevo con `!192.168.1.36` | `fase3/07-firewall-restaurado.txt` |

**Nota de evidencia — archivos sobrescritos:** `aplicar_firewall_a3.sh` escribe en los mismos nombres
`07-firewall-antes.txt` y `07-firewall-despues.txt` que el bloque manual de las 21:22. Al ejecutarse a las 21:50
para agregar el puerto 8444, los sobrescribió antes del commit `34611dd`, así que las capturas de las 21:22 no se
conservan como archivo; su contenido se registra arriba desde la salida de consola. Los archivos actuales
corresponden a la ejecución de las 21:50: antes, reglas para 8443 y 6380; después, además 8444. La re-ejecución de
las 22:05 no cambió nada (idempotente) y quedó en `07b-firewall-8444-antes.txt` / `07b-firewall-8444-despues.txt`.
Las capturas de la prueba negativa (`07-firewall-negativo.txt`) y de la restauración (`07-firewall-restaurado.txt`)
no se vieron afectadas.

**Nota de operación:** un primer intento de aplicar las reglas se ejecutó por error en la PC. No tuvo efecto
(las reglas exigían la interfaz `wlp2s0`, inexistente en la PC) y la cadena `DOCKER-USER` de la PC quedó vacía.

**Tras la restauración:** `nc` desde la PC a `valkey:6380` y `backend:8443` → `succeeded`.

**Punto de control 3: PASA** (3.0–3.7).

## Hallazgo previo a la Fase 4 — el bootstrap no tiene canal TLS (2026-09-12)

Detectado al preparar la instalación del agente en la PC, por lectura de código. No se ejecutó ningún bootstrap.

- `POST /agents/bootstrap` sólo existe en la aplicación principal, servida en el puerto 8000 **sin TLS**
  (`backend/Dockerfile`: `uvicorn ... --port 8000`; `backend/app/main.py:120`).
- El listener 8443 sirve una aplicación aparte (`mtls_app`, `backend/app/main.py:47-48`) que sólo incluye
  `POST /agents/renew`, y exige certificado de cliente (`ssl.CERT_REQUIRED`, `backend/app/core/pki.py:368`). Un agente
  sin certificado no puede hacer bootstrap por ahí.
- El agente arma la URL como `{backend_url}/agents/bootstrap` (`agent/bootstrap.py:154`) y `config.yaml.example`
  usa `http://`. Con `http://`, el `verify=ca_cert_path` (`agent/bootstrap.py:166`) no tiene efecto.
- La respuesta del bootstrap incluye `shared_secret_hex` y `master_secret_hex`
  (`backend/app/modules/agents/models.py:75-79`), además del `bootstrap_secret` enviado en la solicitud.

**Contraste con la documentación canónica:** RN-114/D16 exige que la llamada inicial use `ca_cert_path` como ancla
de confianza TLS y prohíbe `verify=False`. `arquitectura_stack.md` describe el `shared_secret` como "cifrado en
tránsito por TLS". En el despliegue actual eso no se cumple.

**Impacto:** en el laboratorio de un solo anfitrión, el bootstrap viajaba dentro de la red interna de Docker. En
el ensayo multianfitrión cruzaría la LAN en texto plano: una captura durante el bootstrap expondría el
`master_secret` (clave de cifrado del baseline) y el `shared_secret` (HMAC de comandos y eventos).

**Decisión (2026-09-12):** corregir el despliegue antes de la Fase 4, **sin change OPSX**, por decisión del
responsable del proyecto. Alcance: listener TLS 1.3 dedicado al bootstrap en el puerto 8444, autenticado con el
certificado de servidor del backend y sin certificado de cliente; `/agents/bootstrap` deja de estar expuesto en el
puerto 8000; el agente rechaza un `backend_url` que no sea `https`. El puerto 8443 sigue exigiendo certificado de
cliente, sólo para renovación. La decisión se registra en los apéndices de decisiones de implementación de
`reglas_de_negocio.md` y `arquitectura_stack.md`. Las specs de `openspec/specs/` no se editan a mano y quedan
desactualizadas en este punto hasta su sincronización.

**Impacto en el ensayo:** el firewall de la laptop suma el puerto 8444 (`aplicar_firewall_a3.sh`), la imagen del
backend se reconstruye con el cambio y la configuración del agente de la PC usa `backend_url: https://backend:8444`.

## Corrección del bootstrap — implementación y verificación — 2026-09-12 21:49 -03 (PASA)

**Cambios** (sin commitear al momento del registro): `backend/app/core/pki.py` (`start_bootstrap_server`, TLS 1.3,
`CERT_NONE`; helper común con el listener 8443), `backend/app/main.py` (`bootstrap_app` en 8444),
`backend/app/modules/agents/router.py` (`bootstrap_router` separado), `backend/Dockerfile` y `docker-compose.yml`
(puerto 8444), `agent/bootstrap.py` (rechaza `backend_url` sin `https` antes de cualquier solicitud),
`agent/deploy/config.yaml.{docker,example,test}` y `scripts/run-isolated-acceptance-lab.sh` (`https://…:8444`).
Tests nuevos: `backend/tests/test_bootstrap_tls_listener.py` (7) y un caso en `agent/tests/test_bootstrap.py`.
Decisión registrada como **D52/RN-146**.

**Verificación:**

| Verificación | Resultado |
|---|---|
| Suite del agente (Python 3.13) | 514 aprobados, 1 omitido (base 513 + 1 nuevo) |
| Tests de backend PKI/mTLS/renovación/bootstrap (`--noconftest`) | 21 aprobados (repetido por el orquestador) |
| Suite completa del backend | no ejecutable en este entorno: 612 errores de fixture por credenciales de Postgres del conftest, ajenos al cambio |
| `scripts/check_spec_integrity.py` | OK — 44 main specs, 249 requisitos |
| Backend reconstruido y recreado con TLS en Valkey | `pki.mtls_server.configured` 8443 y `pki.bootstrap_tls_server.configured` 8444; `postgres` y `valkey` en `ok` |
| 8444 sin certificado de cliente | handshake TLS 1.3 (`TLS_AES_256_GCM_SHA384`), certificado `CN=fim-backend` verificado contra la CA con hostname `backend` (`Verify return code: 0`) |
| `POST https://backend:8444/agents/bootstrap` (agente inexistente) | `404` de negocio, respondido por TLS |
| `POST http://…:8000/agents/bootstrap` | `405`: la ruta ya no existe en la app en texto plano |
| 8443 sin certificado de cliente | el handshake no se completa |

Evidencia: `fase3b/01-listeners-bootstrap.txt`.

**Desvío de specs:** `openspec/specs/{backend-agents,agent-bootstrap,backend-pki,infra-compose}/spec.md` describen
el comportamiento anterior y no se editaron (guardia de integridad).

## Fase 4 — instalación, registro y bootstrap del agente — 2026-09-12 21:55–22:04 -03

Commits en ambos equipos: `34611dd` (PC con `git pull`).

| Paso | Dónde | Resultado |
|---|---|---|
| Integridad de la CA transferida | PC | huella SHA-256 de `fase3/ca.pem` en la PC = la calculada en la laptop (`96:7A:63:1E:…:03:5E`), comparada por un canal distinto de git |
| Aprovisionamiento | PC | `/etc/fim-agent/certs/ca.pem` (0644); `config.yaml` con `agent_id: a3-pc-ubuntu`, `backend_url: https://backend:8444`, `mtls_backend_url: https://backend:8443`, `valkey_url: valkeys://valkey:6380`, `watch_paths: [/srv/fim-watch]` |
| `agent/install.sh` | PC | reutiliza el venv de Python 3.13; respeta `config.yaml`; drop-in con `ReadWritePaths` `/etc/fim-agent` y `/srv/fim-watch`; servicio habilitado sin arrancar |
| Lectura de la configuración como `fim-agent` | PC | `config OK: a3-pc-ubuntu https://backend:8444 valkeys://valkey:6380 ['/srv/fim-watch']` |
| TLS al listener de bootstrap | PC | `openssl s_client` como `fim-agent`: `Verification: OK`, `Verified peername: backend`, `TLSv1.3`, `TLS_AES_256_GCM_SHA384`, `No client certificate CA names sent`, grupo `X25519MLKEM768`. Como usuario común falla con `Permission denied` sobre la CA (`/etc/fim-agent` es 0750 `root:fim-agent`), lo esperado |
| Registro | laptop | `registrar_agente_a3.sh` contra `127.0.0.1:8000`: primer intento `401` en login (contraseña de admin incorrecta; nada registrado); segundo intento `http_code=201`, `{"agent_id":"a3-pc-ubuntu","status":"offline"}` (`fase4/02-registro-agente.txt`) |
| Bootstrap | PC → laptop | log del backend: `192.168.1.36 - "POST /agents/bootstrap HTTP/1.1" 200 OK` (sólo servible por 8444) |
| Material criptográfico | PC | `/var/lib/fim-agent/certs`: `agent-cert.pem`, `agent-key.pem`, `ca.pem` (0600 `fim-agent`); `/var/lib/fim-agent/secrets`: `master_secret`, `shared_secret` (0400 `fim-agent`) |
| Latido por Valkey mTLS | laptop | `/health/components`: `a3-pc-ubuntu` → `online` (`fase4/03-backend-agente-online.txt`) |

**Notas de operación:**

- El secreto de bootstrap se tipeó a mano (no hay copia entre equipos): 24 caracteres hex agrupados de a 4, con
  confirmación visual antes de enviar. El valor quedó escrito en el chat de asistencia; por decisión del responsable
  se mantuvo, dado que es de un solo uso y el entorno es un laboratorio aislado de dos equipos propios.
- En `fase4/03-backend-agente-online.txt`, las líneas `404` y `405` desde `172.19.0.1` corresponden a las
  verificaciones locales del listener de bootstrap hechas desde la laptop, no al agente.

## Hallazgo en la Fase 4 — avalancha de comandos ajenos al primer arranque (2026-09-12)

Observado en el journal de la PC durante los primeros 20 s: más de 22 000 `detector.out_of_scope_drop` sobre
`/state.tmp` y `/state.json`, intercalados con `publisher.command_signature_invalid`.

**Causa verificada en código y en Valkey:**

- El stream `commands` es único para todos los agentes y tenía **38 794 mensajes** históricos de agentes de
  laboratorio anteriores (`XLEN commands`).
- Un agente nuevo recorre el stream desde el principio (`agent/publisher.py:381-411`). Cada mensaje pasa por
  `_verify_and_parse` (`:415-431`), que verifica la firma HMAC con el `shared_secret` propio **antes** de mirar a
  qué agente va dirigido: todo comando ajeno registra `command_signature_invalid`. El rechazo es correcto; el
  registro como advertencia genera ruido.
- Tras cada mensaje, ajeno o propio, se guarda `last_stream_command_id` con `save_state` (`:404-406`): una
  escritura de `state.json` por mensaje.
- Esas escrituras generan eventos fanotify que el detector descarta por estar fuera de `watch_paths`. Que la ruta
  aparezca como `/state.json` y no como `/var/lib/fim-agent/state.json` es consistente con que el servicio resuelve
  las rutas dentro de su espacio de montaje (`ProtectSystem=strict` con `ReadWritePaths`); **no verificado**.

**Impacto:** ruido en el journal y consumo de CPU al primer arranque de un agente nuevo en un despliegue con
historial de comandos. No compromete la seguridad (los comandos ajenos se rechazan) ni el funcionamiento (el
agente quedó `online`). No se corrige durante el ensayo; queda registrado como limitación.

**Confirmación posterior (≈22:10):** en el último minuto, 0 `command_signature_invalid`: el recorrido del historial
terminó. Durante el recorrido journald suprimió ≈5 400–5 700 mensajes por ventana de 30 s. Persisten ≈65
`detector.out_of_scope_drop` por minuto: la marca fanotify es `FAN_MARK_FILESYSTEM` sobre el filesystem raíz de la
PC (`agent/detector.py:390-397`), y como el directorio de trabajo comparte filesystem con `/srv/fim-watch` se omite la
máscara de exclusión (`detector.mark_exclusion_skipped_same_fs`). Cualquier escritura de otro proceso del escritorio
en ese filesystem genera un evento que el filtro de alcance descarta y registra como advertencia.

## Hallazgo en la Fase 4 — el preflight de escritura da falso `permission_denied` (2026-09-12)

**Observado:** al arrancar, `agent.preflight.degraded` con `"path": "/srv/fim-watch", "classification":
"permission_denied"`. `/srv/fim-watch` es `root:root 0755` y el servicio corre como `fim-agent` con
`CAP_DAC_OVERRIDE` como capability ambiental.

**Causa verificada en la PC** (`setpriv` como `fim-agent`, sólo con `CAP_DAC_OVERRIDE`; `CapEff: 0000000000000002`):

| Prueba | Resultado |
|---|---|
| `os.access('/srv/fim-watch', W_OK)` (usado por `agent/preflight.py:30,64`) | `False` |
| `os.access('/srv/fim-watch', W_OK, effective_ids=True)` | `True` |
| Crear y borrar un archivo en `/srv` (`root:root 0755`) | OK |

`access(2)` evalúa con el uid real y, para un uid distinto de root, el kernel descarta las capabilities efectivas
durante la comprobación; con `AT_EACCESS` (`effective_ids=True`) se respetan. El preflight informa sin permiso de
escritura un directorio sobre el que el agente sí puede escribir. En el despliegue en contenedor no se manifestaba
porque ese agente corre como root.

**Impacto:** sólo informativo. La clasificación viaja en `watch_path_status` del latido (`agent/heartbeat.py:111-112`)
y no condiciona la detección ni la remediación (`detector.started` con `/srv/fim-watch`). Afecta a cualquier
`watch_path` propiedad de root (`/etc`, `/usr/bin`), que es el caso normal de un FIM. `baseline.init_scan.complete`
con `scanned: 0` se debe a que `/srv/fim-watch` estaba vacío, no a este hallazgo.

**Corrección (antes de la Fase 5, inline como bug fix de una línea según `CLAUDE.md`):** `agent/preflight.py` usa
por defecto `os.access(path, mode, effective_ids=True)`. Test nuevo en `agent/tests/test_preflight.py`
(`test_default_access_probe_uses_effective_ids`); con el código anterior la clasificación da `permission_denied` y
el test falla. Suite del agente en Python 3.13: 515 aprobados, 1 omitido. Pendiente: desplegar en la PC
(`git pull`, `install.sh`, reinicio) y confirmar `watch_path_status` = `writable`.

---

# FASE 3 — Servidor central con TLS en Valkey (laptop)

Todo en la laptop, desde la raíz del repositorio. Los pasos con `sudo` son sólo los del firewall (3.7).

**Decisiones de esta fase:**

| Tema | Decisión | Motivo |
|---|---|---|
| Identidad del backend ante Valkey (L8) | Certificado de cliente propio: `CN=fim-backend-valkey`, EKU sólo `clientAuth`, firmado por la CA del proyecto | `backend.pem` sólo tiene `serverAuth` y Valkey lo rechazaría; reusar `valkey.pem` haría que el backend se presente con la identidad del servidor |
| Cómo se entrega al backend | Parámetros en la query de `VALKEY_URL` | valkey-py 6.1.0 (`_parsers/url_parser.py`) pasa las claves desconocidas como kwargs de la conexión; no requiere cambios de código |
| Verificación de hostname del backend | `ssl_check_hostname=true` explícito | En valkey-py 6.1.0 el valor por defecto es `False` |
| Nombres en el agente | `valkey` y `backend` resueltos a `192.168.1.43` vía `/etc/hosts` en la PC (Fase 4) | Los certificados de servidor ya tienen esos nombres en el SAN; la verificación de hostname sigue siendo real sin reemitir con IP |
| Filtrado por origen | Reglas en la cadena `DOCKER-USER`, no en `ufw` | Docker publica puertos con reglas propias que se evalúan antes que las de `ufw` |
| Agente en contenedor de la laptop | Detenido durante el ensayo | Un agente en el mismo anfitrión contaminaría la evidencia multianfitrión |

**Archivos del ensayo** (en esta carpeta, fuera del código de producción):

- `emitir_cert_cliente_backend_valkey.py` — emite el certificado de cliente del backend.
- `docker-compose.a3.yml` — publica 6380 y configura `VALKEY_URL` con el certificado de cliente.

## 3.0 Preparar la sesión

```bash
cd ~/Facultad/tesis/tesis-fim-serio
A3=docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost
dc() { docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$A3/docker-compose.a3.yml" --profile app "$@"; }
mkdir -p "$A3/fase3"
```

`dc` es una función (funciona en bash y zsh). Si se abre otra terminal, repetir este bloque.

Registrar el punto de partida:

```bash
{ date -Is; git rev-parse HEAD; git status --porcelain | wc -l; dc ps; } 2>&1 | tee "$A3/fase3/00-estado-inicial.txt"
```

La cantidad de archivos modificados queda registrada porque el backend se construye desde el árbol de trabajo.

## 3.1 Detener el agente en contenedor

```bash
dc stop agent
```

## 3.2 Emitir el certificado de cliente del backend

Con el backend todavía corriendo en texto plano:

```bash
docker compose exec -T backend python - < "$A3/emitir_cert_cliente_backend_valkey.py" | tee "$A3/fase3/01-emision-cert-cliente.txt"
```

Copiar **sólo certificados públicos** (nunca claves) y verificarlos:

```bash
docker compose cp backend:/certs/ca.pem "$A3/fase3/ca.pem"
docker compose cp backend:/certs/valkey.pem "$A3/fase3/valkey.pem"
docker compose cp backend:/certs/backend-valkey.pem "$A3/fase3/backend-valkey.pem"
{
  for c in valkey backend-valkey; do
    echo "== $c"
    openssl x509 -in "$A3/fase3/$c.pem" -noout -subject -issuer -dates -ext subjectAltName,extendedKeyUsage
    openssl verify -CAfile "$A3/fase3/ca.pem" "$A3/fase3/$c.pem"
  done
} 2>&1 | tee "$A3/fase3/02-certificados.txt"
```

**Esperado:**

- `valkey.pem`: SAN `valkey, localhost`; EKU `TLS Web Server Authentication, TLS Web Client Authentication`; `notAfter`
  posterior a la fecha del ensayo.
- `backend-valkey.pem`: `CN = fim-backend-valkey`; EKU sólo `TLS Web Client Authentication`.
- Ambos: `OK` en `openssl verify`.

Verificar además en modo estricto, que es el que aplica Python 3.13 en el backend y en el agente:

```bash
openssl verify -x509_strict -CAfile "$A3/fase3/ca.pem" "$A3/fase3/valkey.pem"
```

Si `valkey.pem` venció, no existe o falla en modo estricto (`Missing Authority Key Identifier`), reemitirlo con el
script corregido y reiniciar Valkey antes de seguir:
`docker compose exec -T backend python - < scripts/emitir_cert_valkey.py`.

## 3.3 Revisar la configuración resultante

```bash
dc config | grep -nE 'VALKEY_URL|FIM_VALKEY_URL|6380|tls-auth-clients' | tee "$A3/fase3/03-config.txt"
```

**Esperado:** `VALKEY_URL` del backend con `valkeys://valkey:6380?ssl_certfile=/certs/backend-valkey.pem...`, Valkey con
`--tls-auth-clients yes` y el puerto `6380` publicado.

## 3.4 Levantar Valkey y backend con TLS

```bash
dc up -d valkey backend
sleep 20
dc ps 2>&1 | tee "$A3/fase3/04-compose-ps.txt"
docker image inspect -f '{{.RepoTags}} {{.Id}}' valkey/valkey:9.0.3 fim-backend:dev 2>&1 | tee "$A3/fase3/04-imagenes.txt"
```

**Esperado:** `valkey` en `healthy` y `backend` en `running`. `agent` detenido.

## 3.5 Prueba positiva: el backend usa Valkey por TLS con su certificado

```bash
curl -s http://127.0.0.1:8000/health/components | jq . | tee "$A3/fase3/05-health-components.json"
dc logs --since 5m backend 2>&1 | grep -iE 'valkey|ssl|tls|certificate' | tee "$A3/fase3/05-backend-logs.txt"
```

**Esperado:** `"valkey": "ok"` y ningún error de TLS en los logs.

**Si falla:** conservar la salida, no editar nada y compartirla. Causas a descartar, en orden:
clave ilegible (`docker compose exec backend ls -l /certs`), certificado vencido y rechazo del EKU.

## 3.6 Prueba negativa local: Valkey rechaza clientes sin certificado

```bash
{
  echo "== handshake sin certificado de cliente"
  printf 'PING\r\n' | timeout 10 openssl s_client -quiet -connect 127.0.0.1:6380 \
    -CAfile "$A3/fase3/ca.pem" -verify_hostname valkey -verify_return_error
  echo "exit=$?"
} 2>&1 | tee "$A3/fase3/06-valkey-sin-cert-cliente.txt"
```

**Esperado:** el certificado del servidor verifica (`verify return:1`), pero **no aparece `+PONG`**; OpenSSL informa una
alerta del tipo `certificate required`. Un `+PONG` invalida la fase: Valkey estaría aceptando clientes sin certificado.

Las variantes con CA ajena y hostname inválido se hacen en la Fase 6.

## 3.7 Firewall: 6380 y 8443 sólo desde la PC

Estado previo:

```bash
{ sudo iptables -S DOCKER-USER; sudo ip6tables -S DOCKER-USER; } 2>&1 | tee "$A3/fase3/07-firewall-antes.txt"
```

Reglas (IPv4: todo lo que entra por Wi-Fi hacia esos puertos y no viene de la PC se descarta):

```bash
for p in 6380 8443; do
  sudo iptables -I DOCKER-USER -i wlp2s0 -p tcp -m conntrack --ctorigdstport "$p" --ctdir ORIGINAL ! -s 192.168.1.36 -j DROP
done
```

Si `ip6tables -S DOCKER-USER` existe, bloquear también IPv6 (la PC usa IPv4):

```bash
for p in 6380 8443; do
  sudo ip6tables -I DOCKER-USER -i wlp2s0 -p tcp -m conntrack --ctorigdstport "$p" --ctdir ORIGINAL -j DROP
done
```

**Por qué `-i wlp2s0` y `--ctorigdstport`:** `-i` limita la regla al tráfico que llega por la LAN, así que el
backend sigue llegando a Valkey por la red interna de Docker. `--ctorigdstport` compara con el puerto
original, anterior a la traducción que hace Docker.

```bash
{ sudo iptables -L DOCKER-USER -v -n --line-numbers; sudo ip6tables -L DOCKER-USER -v -n --line-numbers; } 2>&1 | tee "$A3/fase3/07-firewall-despues.txt"
```

**Prueba desde la PC** (debe conectar):

```bash
nc -vz -w 3 192.168.1.43 6380; nc -vz -w 3 192.168.1.43 8443
```

**Prueba negativa con un solo equipo:** en la laptop, cambiar temporalmente la IP permitida por una que no existe y
repetir el `nc` desde la PC. Debe fallar por *timeout*, no por *refused*:

```bash
sudo iptables -R DOCKER-USER 1 -i wlp2s0 -p tcp -m conntrack --ctorigdstport 8443 --ctdir ORIGINAL ! -s 192.168.1.250 -j DROP
sudo iptables -R DOCKER-USER 2 -i wlp2s0 -p tcp -m conntrack --ctorigdstport 6380 --ctdir ORIGINAL ! -s 192.168.1.250 -j DROP
# en la PC: nc -vz -w 3 192.168.1.43 6380; nc -vz -w 3 192.168.1.43 8443   → timeout
sudo iptables -R DOCKER-USER 1 -i wlp2s0 -p tcp -m conntrack --ctorigdstport 8443 --ctdir ORIGINAL ! -s 192.168.1.36 -j DROP
sudo iptables -R DOCKER-USER 2 -i wlp2s0 -p tcp -m conntrack --ctorigdstport 6380 --ctdir ORIGINAL ! -s 192.168.1.36 -j DROP
# en la PC: los dos nc vuelven a conectar
```

Los números de regla asumen el orden de inserción del bloque anterior (`-I` agrega arriba: 8443 queda en 1 y 6380
en 2). Confirmarlo con `--line-numbers` antes de reemplazar.

Las reglas no persisten tras reiniciar la laptop. Para quitarlas antes: `sudo iptables -D DOCKER-USER 1` (repetir).

**Punto de control 3:** compartir los archivos de `fase3/` y las salidas de los `nc` desde la PC.

**Volver al laboratorio en texto plano** (al terminar el ensayo, Fase 7): quitar las reglas y ejecutar
`docker compose --profile app up -d`.

---

# FASES 4–7 — Pendientes

| Fase | Contenido previsto |
|---|---|
| 4 | Pre-registrar el agente (identificador y secreto de bootstrap de 32 bytes, que no se archivan); instalar el agente nativo en WSL2 con `agent/install.sh`; configurar `valkeys://` y la URL mTLS del backend; arrancar `fim-agent.service`; verificar la emisión del certificado del agente, el handshake mTLS y el latido |
| 5 | Pruebas positivas: crear, modificar y eliminar archivos en `/srv/fim-watch`; eventos persistidos; aprobación desde la UI y `event_ack`; 100 modificaciones para medir latencia entre anfitriones (con el desfase de reloj registrado); corte del backend y drenaje |
| 6 | Pruebas negativas: conexión a Valkey sin certificado de cliente, con CA ajena y con hostname inválido; conexión mTLS al backend sin certificado, con CA ajena y con certificado vencido; captura `tcpdump` en ambos lados que muestre registros TLS sin rutas ni `diff_text` en claro |
| 7 | Teardown, inventario de recursos residuales, `SHA256SUMS`, verificador del paquete y README con límites |
