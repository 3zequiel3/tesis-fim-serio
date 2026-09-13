# Dockerfile — FIM Platform Backend
#
# Multi-stage build (D-CHANGE-05):
#   builder  — crea un virtualenv en /opt/venv y le instala las dependencias
#   runtime  — imagen final mínima, usuario no-root app (uid 10001), copia el venv
#
# Imagen base: python:3.13-slim (debian) en lugar de alpine porque
# psycopg[binary] y cryptography necesitan ABI glibc.
#
# Por qué venv y no `pip install --target=/install`:
#   `--target` mete los paquetes en un directorio plano y los ejecutables
#   (uvicorn, pytest, etc.) quedan en `<target>/bin/`. Al copiar el target
#   a site-packages en el runtime, los binarios no terminan en el PATH y el
#   container falla con `exec: "uvicorn": executable file not found in $PATH`.
#   Un venv encapsula `lib/` + `bin/` en un solo árbol; copiarlo entero al
#   runtime y setear PATH=/opt/venv/bin:$PATH resuelve ambos en una línea.
#
# Sin HEALTHCHECK en Dockerfile: se agrega cuando exista /health/components
# en Change 11/15. Para smoke test manual usar:
#   curl -fsS http://localhost:8000/health

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — venv + dependencias
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Crear virtualenv y forzar a pip a usarlo. PATH apunta primero al venv para
# que `pip install` instale ahí, y los scripts queden con shebang `/opt/venv/bin/python`.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — imagen final mínima
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Usuario no-root (uid 10001) — D-CHANGE-05, verifica con: id -u → 10001
RUN useradd --create-home --uid 10001 app

# Copiar el venv completo (lib + bin) del builder.
COPY --from=builder /opt/venv /opt/venv

# Poner el venv en el PATH para que `uvicorn`, `python`, etc. queden disponibles
# y, además, `python` resuelva contra el intérprete del venv (mismo binario que
# en el builder, así los shebangs de los scripts en /opt/venv/bin no rompen).
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Pre-crear /certs con ownership de app para que el volumen Docker
# tome los permisos correctos en el primer arranque (volumen vacío).
RUN mkdir /certs && chown app:app /certs

# Copiar solo el paquete de aplicación (tests/, .env, __pycache__ excluidos
# por .dockerignore).
COPY --chown=app:app app/ /app/app/

USER app

EXPOSE 8000
EXPOSE 8443
EXPOSE 8444

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
