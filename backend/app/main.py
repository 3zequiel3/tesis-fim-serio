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
from typing import Any

import valkey.asyncio as avalkey
from fastapi import FastAPI, Depends
from sqlmodel import SQLModel, Session

import app.modules  # noqa: F401 — registra todos los modelos en SQLModel.metadata
from app.core.config import settings
from app.core.database import engine, get_session
from app.core.health import check_components
from app.core.logging import configure_logging, log
from app.core.middleware.cors import CORSOriginMiddleware
from app.core.middleware.trace_id import TraceIdMiddleware
from app.core.pki import ensure_ca, start_mtls_server
from app.core.valkey import close_async_valkey, close_valkey, get_valkey_client, init_async_valkey, init_valkey
from app.modules.agents.heartbeat_consumer import run_heartbeat_consumer
from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import seed_admin
from app.modules.events.consumer import run_consumer
from app.modules.events.router import router as events_router
from app.modules.events.service import retention_task
from app.modules.actions.router import router as actions_router
from app.modules.alerts.router import router as alerts_router
from app.modules.rules.router import router as rules_router
from app.modules.users.router import router as users_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    log.info("backend.startup", environment=settings.environment)
    init_valkey(settings.valkey_url)
    init_async_valkey(settings.valkey_url)
    ensure_ca(
        cert_path=settings.ca_cert_path,
        key_path=settings.ca_key_path,
        backend_cert_path=settings.backend_cert_path,
        backend_key_path=settings.backend_key_path,
    )
    SQLModel.metadata.create_all(engine)
    seed_admin()

    mtls_server = start_mtls_server(
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
    retention_task_handle = asyncio.create_task(retention_task())
    mtls_task = asyncio.create_task(mtls_server.serve()) if mtls_server is not None else None

    yield

    # Shutdown cooperativo de las tareas (RN-93)
    stop_event.set()
    consumer_task.cancel()
    heartbeat_task.cancel()
    retention_task_handle.cancel()
    tasks_to_gather = [consumer_task, heartbeat_task, retention_task_handle]
    if mtls_task is not None:
        mtls_task.cancel()
        tasks_to_gather.append(mtls_task)
    await asyncio.gather(*tasks_to_gather, return_exceptions=True)
    await async_valkey.aclose()

    await close_async_valkey()
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
app.include_router(events_router)
app.include_router(rules_router)
app.include_router(actions_router)
app.include_router(alerts_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/components")
async def health_components(
    session: Session = Depends(get_session),
    valkey_client: Any = Depends(get_valkey_client),
) -> dict[str, Any]:
    """
    Verificación real de componentes: postgres, valkey, n8n, agents.
    Sin auth JWT (RN-101 — monitoreo sin login). Siempre retorna 200.
    """
    return await check_components(session, valkey_client, settings)
