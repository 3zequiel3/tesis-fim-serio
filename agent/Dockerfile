# Dockerfile — FIM Platform Agent
#
# El agente detecta cambios de archivos vía fanotify usando el backend interno
# agent/_fanotify.py (ctypes/glibc, modo FID FAN_REPORT_DFID_NAME). Requiere:
#   - Linux kernel >= 5.1
#   - CAP_SYS_ADMIN        → fanotify_init + marcar filesystems completos
#   - CAP_DAC_READ_SEARCH  → open_by_handle_at(2) para resolver paths en modo FID
# Ambas capabilities se otorgan vía `cap_add` en docker-compose.yml.
#
# Corre como ROOT dentro del contenedor: fanotify_init necesita CAP_SYS_ADMIN
# efectivo, y el camino simple en Docker es root + cap_add (en un host real se
# usa systemd AmbientCapabilities — ver agent/deploy/fim-agent.service).
#
# Imagen base: python:3.13-slim (glibc) — _fanotify.py llama glibc vía ctypes y
# cryptography necesita ABI glibc; alpine (musl) no sirve.

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — venv + dependencias
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — imagen final
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Paquete del agente. El contexto de build es ./agent, así que el código vive en
# la raíz del contexto; se copia a /app/agent/ para importarse como `agent`.
# tests/, __pycache__/ y deploy/ quedan excluidos por .dockerignore.
COPY . /app/agent/

# Directorios de estado (baseline cifrado, cola offline, journal, secrets, certs)
# y el punto de montaje del directorio vigilado.
RUN mkdir -p /var/lib/fim-agent /watch

# Sin USER: corre como root para tener CAP_SYS_ADMIN efectivo (con cap_add).
CMD ["python", "-m", "agent", "--config", "/etc/fim-agent/config.yaml", "--log-format", "console"]
