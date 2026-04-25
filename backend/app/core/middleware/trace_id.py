"""
Middleware ASGI que genera un UUID v4 por request HTTP y lo propaga como:
  - Header de response: X-Trace-Id
  - Contexto de structlog: trace_id (via bind_contextvars)
  - ContextVar: trace_id_var (para código que quiera leerlo directamente)

Decisión D-CHANGE-02: usar contextvars.ContextVar en lugar de threading.local.
FastAPI/Uvicorn ejecutan handlers como corutinas; threading.local no propaga
a través de await. ContextVar es la API estándar de Python para context-local
en async (PEP 567) y structlog la soporta con merge_contextvars.

Structlog integration: el middleware llama bind_contextvars/unbind_contextvars
en lugar de solo setear trace_id_var, para que merge_contextvars (en la
pipeline de logging) lo incluya automáticamente en cada log emitido durante
el procesamiento de la request.
"""

import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

# ContextVar público — otros módulos pueden importarlo para leer el trace_id
# sin pasar por structlog.contextvars.
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


class TraceIdMiddleware:
    """
    ASGI middleware que gestiona el trace_id del ciclo de vida de la request.

    No hereda de BaseHTTPMiddleware (que wrappea en ThreadPoolExecutor en
    versiones viejas de starlette); implementa directamente la interfaz ASGI
    para control total y mínimo overhead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # WebSocket, lifespan, etc. — pasar sin tocar.
            await self.app(scope, receive, send)
            return

        trace_id = str(uuid.uuid4())

        # Bind al contexto structlog para que merge_contextvars lo inyecte
        # en cada log emitido durante esta request.
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        # ContextVar — disponible para código que lo lea directamente.
        token = trace_id_var.set(trace_id)

        async def send_with_trace(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", trace_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")
            trace_id_var.reset(token)
