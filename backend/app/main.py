"""
Entry point del backend FIM Platform.

Orden de inicialización:
  1. configure_logging() — ANTES de instanciar FastAPI, para que los logs
     del lifespan ya salgan formateados (D-CHANGE-07).
  2. lifespan — ejecuta create_all + seed_admin en startup; ambos son no-op
     funcional en M1 hasta Change 03/04 (D-CHANGE-03, D3).
  3. app = FastAPI(..., lifespan=lifespan)
  4. add_middleware(TraceIdMiddleware) — cross-cutting desde el día 1 (D7).
  5. @app.get("/health") — endpoint mínimo del Done criterion de Change 02.

Ver design.md D-CHANGE-03 para el razonamiento del lifespan idempotente.
Ver design.md D-CHANGE-01 / D-CHANGE-02 para los controles cross-cutting.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

import app.modules  # noqa: F401 — registra todos los modelos en SQLModel.metadata
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.logging import log
from app.core.middleware.trace_id import TraceIdMiddleware
from app.modules.auth.service import seed_admin

# ─────────────────────────────────────────────────────────────────────────────
# 1. Logging — debe estar configurado antes de cualquier log o instancia FastAPI
# ─────────────────────────────────────────────────────────────────────────────
configure_logging()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Lifespan — startup + shutdown hooks (D3, D-CHANGE-03)
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """
    Lifespan idempotente del backend.

    - create_all: crea todas las tablas del schema (modelos registrados via
      app.modules import). Idempotente si ya existen (D3, RN-76).
    - seed_admin: crea el primer admin si no existe; no-op en M1 si la tabla
      'users' todavía no está lista (RN-62).
    """
    log.info("backend.startup", environment=settings.environment)
    SQLModel.metadata.create_all(engine)
    seed_admin()
    yield
    log.info("backend.shutdown")


# ─────────────────────────────────────────────────────────────────────────────
# 3. FastAPI app instance
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FIM Platform Backend",
    version="0.2.0",
    lifespan=lifespan,
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Middlewares cross-cutting (D7, D-CHANGE-02)
# ─────────────────────────────────────────────────────────────────────────────
app.add_middleware(TraceIdMiddleware)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check mínimo — Done criterion de Change 02.

    NO realiza checks de DB/Valkey/n8n. Eso es responsabilidad de
    GET /health/components en Change 11/15.
    """
    return {"status": "ok"}
