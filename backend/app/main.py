"""
Entry point del backend FIM Platform.

Orden de inicialización:
  1. configure_logging() — ANTES de instanciar FastAPI.
  2. lifespan — init_valkey + create_all + seed_admin en startup (D3, D7).
  3. app = FastAPI(..., lifespan=lifespan)
  4. Middlewares: CORSOriginMiddleware (RN-95), TraceIdMiddleware (D7).
  5. Routers: /auth, /users.
  6. @app.get("/health") — Done criterion de Change 02.
"""

import asyncio
from contextlib import asynccontextmanager

import valkey.asyncio as avalkey
from fastapi import FastAPI
from sqlmodel import SQLModel

import app.modules  # noqa: F401 — registra todos los modelos en SQLModel.metadata
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging, log
from app.core.middleware.cors import CORSOriginMiddleware
from app.core.middleware.trace_id import TraceIdMiddleware
from app.core.pki import ensure_ca, start_mtls_server
from app.core.valkey import close_valkey, init_valkey
from app.modules.agents.heartbeat_consumer import run_heartbeat_consumer
from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import seed_admin
from app.modules.events.consumer import run_consumer
from app.modules.users.router import router as users_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    log.info("backend.startup", environment=settings.environment)
    init_valkey(settings.valkey_url)
    ensure_ca(
        cert_path=settings.ca_cert_path,
        key_path=settings.ca_key_path,
        backend_cert_path=settings.backend_cert_path,
        backend_key_path=settings.backend_key_path,
    )
    SQLModel.metadata.create_all(engine)
    seed_admin()
    start_mtls_server(
        app,
        ca_cert_path=settings.ca_cert_path,
        cert_path=settings.backend_cert_path,
        key_path=settings.backend_key_path,
    )

    # Consumers asyncio — conexiones Valkey dedicadas (no bloquean el cliente HTTP)
    stop_event = asyncio.Event()
    async_valkey = avalkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
    consumer_task = asyncio.create_task(run_consumer(async_valkey, stop_event))
    heartbeat_task = asyncio.create_task(run_heartbeat_consumer(async_valkey, stop_event))

    yield

    # Shutdown cooperativo de las tareas (RN-93)
    stop_event.set()
    consumer_task.cancel()
    heartbeat_task.cancel()
    await asyncio.gather(consumer_task, heartbeat_task, return_exceptions=True)
    await async_valkey.aclose()

    close_valkey()
    log.info("backend.shutdown")


app = FastAPI(
    title="FIM Platform Backend",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(CORSOriginMiddleware)
app.add_middleware(TraceIdMiddleware)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(agents_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
