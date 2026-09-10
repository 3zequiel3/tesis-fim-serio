from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "workflows" / "fim_alert_router.json"

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")

from app.modules.alerts.notifier import send_n8n  # noqa: E402


def test_router_has_one_canonical_webhook_and_waits_for_receiver() -> None:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    webhook = next(node for node in workflow["nodes"] if node["type"].endswith(".webhook"))
    responder = next(
        node for node in workflow["nodes"] if node["type"].endswith(".respondToWebhook")
    )
    receiver = next(
        node for node in workflow["nodes"] if node["name"] == "Deliver to controlled receiver"
    )

    assert webhook["parameters"]["path"] == "fim-alert"
    assert webhook["parameters"]["responseMode"] == "responseNode"
    assert "? 202 : 502" in responder["parameters"]["options"]["responseCode"]
    assert receiver["parameters"]["url"] == "http://controlled-receiver:8080/fim-alert"
    assert receiver["onError"] == "continueRegularOutput"
    assert receiver["parameters"]["options"]["response"]["response"]["fullResponse"] is True


@pytest.mark.asyncio
async def test_n8n_wire_payload_has_independent_dispatch_timestamp() -> None:
    original = {"notification_id": "notification-1", "received_at": "2026-09-09T12:00:00+00:00"}
    response = MagicMock(status_code=202)
    response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)

    with patch("httpx.AsyncClient", return_value=client):
        assert await send_n8n(original, "http://n8n:5678/webhook/fim-alert") is True

    sent = client.post.await_args.kwargs["json"]
    assert sent["received_at"] == original["received_at"]
    assert datetime.fromisoformat(sent["backend_dispatched_at"]).tzinfo is not None
    assert "backend_dispatched_at" not in original
