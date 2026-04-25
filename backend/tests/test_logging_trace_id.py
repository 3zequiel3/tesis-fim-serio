"""
Tests del TraceIdMiddleware y propagación de trace_id a logs.

Nota sobre structlog.testing.capture_logs() + httpx ASGI:
  El contexto de structlog.contextvars es por coroutine/asyncio-task.
  Durante una request ASGI en tests, el bind_contextvars del middleware
  opera en el mismo task que el handler. capture_logs() captura los
  logs emitidos en el mismo contexto de ejecución del test.

  Sin embargo, capture_logs() reconfigura structlog para capturar en
  una lista (sin procesadores externos), lo que significa que merge_contextvars
  NO se ejecuta automáticamente — los logs capturados son dicts raw sin trace_id
  inyectado por merge_contextvars.

  Para verificar que trace_id llega a los logs producidos por el handler,
  usamos el processor sanitize_secrets/merge_contextvars de manera explícita
  o verificamos a través del header X-Trace-Id que el middleware generó el UUID.

  El test de integración real del trace_id en logs se verifica con el
  smoke test Docker (tasks 10.3/10.4).
"""

import os
import re

import structlog

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")

from app.core.middleware.trace_id import trace_id_var

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


async def test_trace_id_header_present_and_valid(client):
    """X-Trace-Id en response es UUID v4 válido."""
    response = await client.get("/health")
    trace_id = response.headers.get("x-trace-id")

    assert trace_id is not None, "Header X-Trace-Id ausente"
    assert UUID_V4_RE.match(trace_id), f"X-Trace-Id '{trace_id}' no es UUID v4"


async def test_trace_id_unique_per_request(client):
    """Dos requests secuenciales generan trace_ids distintos."""
    r1 = await client.get("/health")
    r2 = await client.get("/health")

    t1 = r1.headers.get("x-trace-id")
    t2 = r2.headers.get("x-trace-id")

    assert t1 is not None
    assert t2 is not None
    assert t1 != t2, "Dos requests tienen el mismo trace_id — posible fuga de contexto"


async def test_trace_id_contextvars_reset_after_request(client):
    """
    El ContextVar trace_id_var debe quedar en None después de la request
    (el middleware hace reset en el finally).
    """
    await client.get("/health")
    # Después de que la request terminó, el ContextVar debe estar en None
    # (el middleware hizo trace_id_var.reset(token)).
    assert trace_id_var.get() is None, (
        "trace_id_var no fue reseteado después de la request — fuga de contexto"
    )


async def test_trace_id_in_structlog_context_during_request(client):
    """
    Verifica que el trace_id es bind-eado al contexto structlog durante la
    request y que coincide con el header X-Trace-Id de la response.

    Usamos una variable externa para capturar el trace_id del contexto
    structlog mientras se procesa la request.
    """
    captured_trace_id: list[str | None] = []

    # Patch temporal del endpoint /health para capturar el contexto structlog
    # durante la ejecución del handler.
    from app.main import app

    @app.get("/health_trace_test", include_in_schema=False)
    async def health_trace_test():
        # Leer el trace_id del contexto structlog en el momento del handler
        ctx = structlog.contextvars.get_contextvars()
        captured_trace_id.append(ctx.get("trace_id"))
        return {"status": "ok"}

    response = await client.get("/health_trace_test")
    header_trace_id = response.headers.get("x-trace-id")

    assert header_trace_id is not None
    assert len(captured_trace_id) == 1
    assert captured_trace_id[0] is not None
    assert captured_trace_id[0] == header_trace_id, (
        f"trace_id en contexto structlog ({captured_trace_id[0]}) "
        f"no coincide con header X-Trace-Id ({header_trace_id})"
    )

    # Cleanup del route dinámico
    app.routes.pop()
