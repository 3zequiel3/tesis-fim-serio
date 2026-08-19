"""
Tests HTTP del router de acciones (POST /actions/*).

Cierra la brecha 11 del anexo docs/trazabilidad_us_tests.md §7 (nivel 2): el
módulo `actions` estaba probado sólo a nivel de servicio, de modo que el
mapeo de excepciones de dominio a códigos HTTP, el gate `require_admin` y la
forma de las respuestas no los verificaba ningún test. Afecta a US-11
(aprobación), US-12 (rechazo) y US-25 (bulk).

Cubre:
  - `ConflictError` → 409 con `detail.code == "conflict"`.
  - `AbsentConfirmationRequired` → 422 con `detail.code == "absent_confirmation_required"`,
    distinguible de un 422 de validación de Pydantic.
  - `require_admin` en los cuatro endpoints: 401 sin token, 403 con usuario no admin.
  - Forma de `ActionResponse` y de `BulkResultResponse`.
  - Contrato real de los endpoints bulk: `items[]` con `{event_id, version, ...}`,
    no `event_ids[]`.

Postgres real (el engine de conftest) y autenticación real: los tokens se
firman para usuarios que existen en la base, sin sobreescribir `get_current_user`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from sqlmodel import Session, select

from app.core.database import engine
from app.core.security import create_access_token
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus

_ENDPOINTS = ("/actions/approve", "/actions/reject", "/actions/bulk-approve", "/actions/bulk-reject")


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(
        agent_id=f"agent-actions-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.online,
        shared_secret_hex=uuid.uuid4().hex + uuid.uuid4().hex,  # 32 bytes hex
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


@pytest.fixture()
def admin_id(session: Session) -> int:
    """id del admin sembrado por `_db_isolation` (rol admin)."""
    admin = session.exec(select(User).where(User.role == "admin")).one()
    return admin.id


@pytest.fixture()
def operator_id(session: Session) -> int:
    """Usuario autenticable pero sin rol admin — el que `require_admin` debe frenar."""
    user = User(
        username=f"operator-{uuid.uuid4().hex[:6]}",
        email=f"op-{uuid.uuid4().hex[:6]}@fim.local",
        password_hash="x",
        role="operator",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def _headers(user_id: int) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        username="whoever",
        must_change_password=False,
        jti=f"jti-actions-{uuid.uuid4().hex[:8]}",
    )
    return {"Authorization": f"Bearer {token}"}


def _pending_event(session: Session, agent: Agent, *, hash_detected: str = "abc123") -> Event:
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=f"evt-actions-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        path=f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected=hash_detected,
        status=EventStatus.pending,
        version=0,
        detected_at=now,
        received_at=now,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


# ── require_admin en los cuatro endpoints ────────────────────────────────────


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
async def test_actions_endpoints_require_authentication(client, endpoint) -> None:
    """Sin token, los cuatro endpoints responden 401."""
    resp = await client.post(endpoint, json={})
    assert resp.status_code == 401


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
async def test_actions_endpoints_reject_non_admin(client, operator_id, endpoint) -> None:
    """
    Con un usuario autenticado pero sin rol admin, los cuatro endpoints
    responden 403 `admin_required` — antes de validar el cuerpo.
    """
    resp = await client.post(endpoint, json={}, headers=_headers(operator_id))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "admin_required"


# ── POST /actions/approve ─────────────────────────────────────────────────────


async def test_approve_returns_action_response_shape(client, session, agent, admin_id) -> None:
    """200 con la forma exacta de `ActionResponse` y el evento aprobado en la base."""
    event = _pending_event(session, agent)

    resp = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 0},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "event_id": event.id,
        "status": "approved",
        "baseline_absent": False,
    }

    session.expire_all()
    persisted = session.get(Event, event.id)
    assert persisted.status == EventStatus.approved
    assert persisted.version == 1
    assert persisted.resolved_by == admin_id
    assert persisted.resolved_at is not None


async def test_approve_with_stale_version_returns_409(client, session, agent, admin_id) -> None:
    """`ConflictError` (locking optimista C5) se mapea a 409, no a 500."""
    event = _pending_event(session, agent)

    resp = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 99},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "conflict"

    session.expire_all()
    assert session.get(Event, event.id).status == EventStatus.pending


async def test_approve_already_resolved_event_returns_409(client, session, agent, admin_id) -> None:
    """Aprobar dos veces el mismo evento: la segunda es un conflicto, no un no-op silencioso."""
    event = _pending_event(session, agent)
    first = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 0},
        headers=_headers(admin_id),
    )
    assert first.status_code == 200

    second = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 1},
        headers=_headers(admin_id),
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "conflict"


async def test_approve_absent_file_without_confirmation_returns_422(
    client, session, agent, admin_id
) -> None:
    """
    C10: aprobar un evento cuyo archivo ya no está exige confirmación explícita.
    El 422 es de dominio y trae `detail.code`, distinto de un 422 de validación.
    """
    event = _pending_event(session, agent, hash_detected="")  # hash vacío = archivo ausente

    resp = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 0},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == {"code": "absent_confirmation_required"}

    session.expire_all()
    assert session.get(Event, event.id).status == EventStatus.pending


async def test_approve_absent_file_with_confirmation_succeeds(
    client, session, agent, admin_id
) -> None:
    """Con `confirm_absent=true` la aprobación procede y el baseline queda `absent`."""
    event = _pending_event(session, agent, hash_detected="")

    resp = await client.post(
        "/actions/approve",
        json={"event_id": event.id, "version": 0, "confirm_absent": True},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    session.expire_all()
    entry = session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == event.path, BaselineEntry.agent_id == agent.agent_id
        )
    ).one()
    assert entry.status == BaselineStatus.absent


async def test_approve_missing_required_field_returns_validation_422(
    client, admin_id
) -> None:
    """Un 422 de validación de Pydantic NO tiene `detail.code` — el contraste importa."""
    resp = await client.post(
        "/actions/approve", json={"event_id": 1}, headers=_headers(admin_id)
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)  # errores de Pydantic, no código de dominio


# ── POST /actions/reject ──────────────────────────────────────────────────────


async def test_reject_returns_action_response_shape(client, session, agent, admin_id) -> None:
    """200 con `ActionResponse` y el evento rechazado y resuelto en la base."""
    event = _pending_event(session, agent)

    resp = await client.post(
        "/actions/reject",
        json={"event_id": event.id, "version": 0, "action": "restore"},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "event_id": event.id,
        "status": "rejected",
        "baseline_absent": False,
    }

    session.expire_all()
    persisted = session.get(Event, event.id)
    assert persisted.status == EventStatus.rejected
    assert persisted.resolved_by == admin_id
    assert persisted.resolved_at is not None


async def test_reject_with_absent_baseline_reports_the_noop(
    client, session, agent, admin_id
) -> None:
    """RN-74: baseline `absent` → no-op observable vía `baseline_absent=true`."""
    event = _pending_event(session, agent)
    session.add(
        BaselineEntry(
            path=event.path,
            agent_id=agent.agent_id,
            hash=None,
            status=BaselineStatus.absent,
            last_updated=datetime.now(timezone.utc),
            ruleset_version=1,
        )
    )
    session.commit()

    resp = await client.post(
        "/actions/reject",
        json={"event_id": event.id, "version": 0, "action": "restore"},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    assert resp.json()["baseline_absent"] is True


async def test_reject_with_stale_version_returns_409(client, session, agent, admin_id) -> None:
    event = _pending_event(session, agent)

    resp = await client.post(
        "/actions/reject",
        json={"event_id": event.id, "version": 42, "action": "quarantine"},
        headers=_headers(admin_id),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "conflict"

    session.expire_all()
    assert session.get(Event, event.id).status == EventStatus.pending


async def test_reject_with_invalid_action_returns_422(client, session, agent, admin_id) -> None:
    """`action` sólo acepta `restore` o `quarantine`."""
    event = _pending_event(session, agent)

    resp = await client.post(
        "/actions/reject",
        json={"event_id": event.id, "version": 0, "action": "delete"},
        headers=_headers(admin_id),
    )
    assert resp.status_code == 422


# ── POST /actions/bulk-approve y /actions/bulk-reject ────────────────────────


async def test_bulk_approve_uses_items_contract_and_partitions_results(
    client, session, agent, admin_id
) -> None:
    """
    El contrato real es `items[]` con `{event_id, version}` (no `event_ids[]`).
    La respuesta parte los resultados en `succeeded` / `failed` con el motivo.
    """
    ok1 = _pending_event(session, agent)
    ok2 = _pending_event(session, agent)
    stale = _pending_event(session, agent)

    resp = await client.post(
        "/actions/bulk-approve",
        json={
            "items": [
                {"event_id": ok1.id, "version": 0},
                {"event_id": stale.id, "version": 77},  # conflicto
                {"event_id": ok2.id, "version": 0},
            ]
        },
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"succeeded", "failed", "baseline_absent"}
    assert sorted(body["succeeded"]) == sorted([ok1.id, ok2.id])
    assert body["failed"] == [{"event_id": stale.id, "reason": "conflict"}]

    session.expire_all()
    assert session.get(Event, ok1.id).status == EventStatus.approved
    assert session.get(Event, ok2.id).status == EventStatus.approved
    assert session.get(Event, stale.id).status == EventStatus.pending


async def test_bulk_approve_reports_absent_confirmation_as_failed_item(
    client, session, agent, admin_id
) -> None:
    """En bulk, el archivo ausente no corta el lote: cae en `failed` con su motivo."""
    ok = _pending_event(session, agent)
    absent = _pending_event(session, agent, hash_detected="")

    resp = await client.post(
        "/actions/bulk-approve",
        json={
            "items": [
                {"event_id": ok.id, "version": 0},
                {"event_id": absent.id, "version": 0},
            ]
        },
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == [ok.id]
    assert body["failed"] == [
        {"event_id": absent.id, "reason": "absent_confirmation_required"}
    ]


async def test_bulk_reject_uses_items_contract_with_per_item_action(
    client, session, agent, admin_id
) -> None:
    """Cada ítem de `bulk-reject` lleva su propia acción; la respuesta mapea `baseline_absent`."""
    restored = _pending_event(session, agent)
    quarantined = _pending_event(session, agent)
    stale = _pending_event(session, agent)

    resp = await client.post(
        "/actions/bulk-reject",
        json={
            "items": [
                {"event_id": restored.id, "version": 0, "action": "restore"},
                {"event_id": quarantined.id, "version": 0, "action": "quarantine"},
                {"event_id": stale.id, "version": 13, "action": "restore"},  # conflicto
            ]
        },
        headers=_headers(admin_id),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["succeeded"]) == sorted([restored.id, quarantined.id])
    assert body["failed"] == [{"event_id": stale.id, "reason": "conflict"}]
    # `baseline_absent` está poblado por cada evento exitoso (M8).
    assert body["baseline_absent"] == {str(restored.id): False, str(quarantined.id): False}

    session.expire_all()
    assert session.get(Event, restored.id).status == EventStatus.rejected
    assert session.get(Event, quarantined.id).status == EventStatus.rejected
    assert session.get(Event, stale.id).status == EventStatus.pending


async def test_bulk_endpoints_accept_an_empty_batch(client, admin_id) -> None:
    """Un lote vacío es válido y devuelve la estructura vacía, no un 500."""
    for endpoint in ("/actions/bulk-approve", "/actions/bulk-reject"):
        resp = await client.post(endpoint, json={"items": []}, headers=_headers(admin_id))
        assert resp.status_code == 200, endpoint
        assert resp.json()["succeeded"] == []
        assert resp.json()["failed"] == []
