# Dockerfile — FIM Platform Backend
#
# Multi-stage build (D-CHANGE-05):
#   builder  — instala dependencias con pip en /install (sin cachés)
#   runtime  — imagen final mínima, usuario no-root app (uid 10001)
#
# Imagen base: python:3.13-slim (debian) en lugar de alpine porque
# psycopg[binary] y cryptography necesitan ABI glibc.
#
# Sin HEALTHCHECK en Dockerfile: se agrega cuando exista /health/components
# en Change 11/15. Para smoke test manual usar:
#   curl -fsS http://localhost:8000/health

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — instala dependencias
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --target=/install -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — imagen final mínima
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Usuario no-root (uid 10001) — D-CHANGE-05, verifica con: id -u → 10001
RUN useradd --create-home --uid 10001 app

# Copiar dependencias instaladas por el builder al site-packages del runtime.
COPY --from=builder /install /usr/local/lib/python3.13/site-packages

WORKDIR /app

# Copiar solo el paquete de aplicación (tests/, .env, __pycache__ excluidos
# por .dockerignore).
COPY --chown=app:app app/ /app/app/

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
