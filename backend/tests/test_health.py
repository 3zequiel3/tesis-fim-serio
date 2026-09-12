"""
Tests del endpoint GET /health.

Verifica: HTTP 200, body {"status": "ok"}, header X-Trace-Id con UUID v4.
"""

import re


async def test_health_returns_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("content-type", "").startswith("application/json")


async def test_health_includes_trace_id_header(client):
    response = await client.get("/health")

    trace_id = response.headers.get("x-trace-id")
    assert trace_id is not None, "Header X-Trace-Id ausente en la response"

    # UUID v4: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx con y ∈ {8,9,a,b}
    uuid_v4_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    assert uuid_v4_pattern.match(trace_id), (
        f"X-Trace-Id '{trace_id}' no es un UUID v4 válido"
    )


async def test_health_trace_id_unique_per_request(client):
    """Dos requests seguidas deben tener X-Trace-Id distintos."""
    r1 = await client.get("/health")
    r2 = await client.get("/health")

    t1 = r1.headers.get("x-trace-id")
    t2 = r2.headers.get("x-trace-id")

    assert t1 is not None
    assert t2 is not None
    assert t1 != t2, "Dos requests consecutivas tienen el mismo X-Trace-Id"


# ── GET /health/components — HTTP-level (US-28) ─────────────────────────────
#
# The rest of this module (test_notifications.py §7.3) exercises
# `check_components()` directly as a unit. Nothing previously hit the real
# route through the ASGI app, so the wiring (no-auth, response shape, status
# code) was unverified at the HTTP layer. These tests close that gap.


async def test_health_components_returns_200_without_auth(client) -> None:
    """RN-101: monitoring endpoint, no JWT required — unlike every /events,
    /rules, /actions route."""
    response = await client.get("/health/components")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/json")


async def test_health_components_reports_every_monitored_component(client) -> None:
    """Body carries postgres/valkey/n8n/agents + checked_at, per US-28 criterio 2."""
    response = await client.get("/health/components")
    body = response.json()

    for key in ("postgres", "valkey", "n8n", "checked_at"):
        assert key in body, f"'{key}' ausente en GET /health/components"

    assert isinstance(body["agents"], dict)
    assert "status" in body["agents"]
    assert "items" in body["agents"]

    for component in ("postgres", "valkey", "n8n"):
        assert body[component] in ("ok", "degraded", "down"), (
            f"{component}='{body[component]}' no es un estado válido"
        )
    assert body["agents"]["status"] in ("ok", "degraded", "down")
