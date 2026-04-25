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

import sqlalchemy
from fastapi import FastAPI
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.logging import log
from app.core.middleware.trace_id import TraceIdMiddleware

# ─────────────────────────────────────────────────────────────────────────────
# 1. Logging — debe estar configurado antes de cualquier log o instancia FastAPI
# ─────────────────────────────────────────────────────────────────────────────
configure_logging()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Seed admin skeleton (D-CHANGE-03)
# ─────────────────────────────────────────────────────────────────────────────
def seed_admin() -> None:
    """
    Inicializa el usuario admin por defecto si aún no existe.

    Guard: si la tabla 'users' no existe todavía (M1, antes de Change 03),
    retorna temprano con log informativo. NO lanza excepción — el backend
    debe poder arrancar sin tablas creadas (RN-62, RN-76).

    El cuerpo real se completa en Change 04 (backend-auth), cuando el modelo
    User esté definido y la tabla creada por create_all.
    """
    inspector = sqlalchemy.inspect(engine)
    if not inspector.has_table("users"):
        log.info(
            "seed_admin.skipped",
            reason="users_table_not_yet_created",
        )
        return
    # Body filled in Change 04 (backend-auth).
    pass  # noqa: PIE790


# ─────────────────────────────────────────────────────────────────────────────
# 3. Lifespan — startup + shutdown hooks (D3, D-CHANGE-03)
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """
    Lifespan idempotente del backend.

    - create_all: no-op si no hay modelos registrados (M1); cuando Change 03
      agregue modelos, creará las tablas. Idempotente si ya existen.
    - seed_admin: no-op en M1 (tabla 'users' no existe); cuando Change 04
      complete el cuerpo, sembrará el admin si no existe (RN-62).
    """
    log.info("backend.startup", environment=settings.environment)
    SQLModel.metadata.create_all(engine)
    seed_admin()
    yield
    log.info("backend.shutdown")


# ─────────────────────────────────────────────────────────────────────────────
# 4. FastAPI app instance
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FIM Platform Backend",
    version="0.2.0",
    lifespan=lifespan,
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Middlewares cross-cutting (D7, D-CHANGE-02)
# ─────────────────────────────────────────────────────────────────────────────
app.add_middleware(TraceIdMiddleware)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check mínimo — Done criterion de Change 02.

    NO realiza checks de DB/Valkey/n8n. Eso es responsabilidad de
    GET /health/components en Change 11/15.
    """
    return {"status": "ok"}
