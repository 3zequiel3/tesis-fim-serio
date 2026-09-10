"""
Tests de contrato del listado y el detalle de eventos (GET /events, GET /events/{id}).

Cierra las brechas 1-4 del nivel 1 de docs/trazabilidad_us_tests.md §7:

  1. `superseded` excluido por defecto y visible con `include_superseded=true`
     (US-13 criterio 3, US-31 criterio 5, US-06 criterio 4, US-07 criterio 3).
  2. Orden `created_at DESC` y `page_size` por defecto = 50 (US-06 criterio 3,
     US-26 criterio 1).
  3. `total` refleja los filtros activos — estado, `path_prefix` y rango de
     fechas (US-26 criterio 5, US-07 criterios 1-2).
  4. `GET /events/{id}` camino feliz con el conjunto de campos, incluidos los
     timestamps dobles y el contexto forense del proceso (US-08).

Postgres real (el engine de conftest) y autenticación real: el token se firma
para el admin sembrado por `_db_isolation`, sin mockear `get_current_user`.
Cada test crea sus propios eventos sobre una base ya truncada, de modo que
`total` es exactamente lo que el test insertó.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from sqlmodel import Session

from app.core.database import engine
from app.core.security import create_access_token
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity

# D39/RN-133: las columnas de timestamp son `timestamptz` y toda escritura vía
# ORM/API es UTC-aware. _NOW es aware a propósito — un `_NOW` naive comparado
# por `==` contra un valor aware devuelve False sin lanzar excepción (D-5,
# design de timestamps-timezone-aware), que es exactamente el modo de fallo
# silencioso que esta suite existe para no volver a dejar pasar.
_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-listing-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _auth_headers() -> dict[str, str]:
    """Token del admin sembrado (id=1 tras TRUNCATE ... RESTART IDENTITY)."""
    token = create_access_token(
        user_id=1, username="admin", must_change_password=False, jti="test-jti-listing"
    )
    return {"Authorization": f"Bearer {token}"}


def _new_event(
    agent: Agent,
    *,
    status: EventStatus = EventStatus.pending,
    path: str | None = None,
    created_at: datetime | None = None,
    severity: RuleSeverity = RuleSeverity.low,
    hash_expected: str | None = None,
    diff_text: str | None = None,
) -> Event:
    return Event(
        event_id=f"evt-listing-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        path=path if path is not None else f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected="deadbeef",
        hash_expected=hash_expected,
        diff_text=diff_text,
        status=status,
        severity=severity,
        detected_at=created_at or _NOW,
        received_at=created_at or _NOW,
        created_at=created_at or _NOW,
    )


def _new_pathless_event(
    agent: Agent,
    *,
    status: EventStatus = EventStatus.alert_only,
    event_type: str = "detection_gap",
    severity: RuleSeverity = RuleSeverity.high,
    created_at: datetime | None = None,
) -> Event:
    """D51/RN-145: evento SIN ruta real (no el sentinel de _new_event) — el
    path va NULL de punta a punta, como un detection_gap real (D50/RN-144)."""
    when = created_at or _NOW
    return Event(
        event_id=f"evt-listing-gap-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        event_type=event_type,
        path=None,
        hash_detected="",
        status=status,
        severity=severity,
        detected_at=when,
        received_at=when,
        created_at=when,
        resolved_at=when if status == EventStatus.alert_only else None,
    )


def _persist(session: Session, *events: Event) -> None:
    for event in events:
        session.add(event)
    session.commit()
    for event in events:
        session.refresh(event)


# ── 1. Filtro de `superseded` (US-13, US-31, US-06, US-07) ───────────────────


async def test_list_events_excludes_superseded_by_default(client, session, agent) -> None:
    """W1: un evento `superseded` no aparece en el listado por defecto."""
    pending = _new_event(agent, status=EventStatus.pending)
    superseded = _new_event(agent, status=EventStatus.superseded)
    _persist(session, pending, superseded)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [pending.id]
    assert superseded.id not in [item["id"] for item in body["items"]]


async def test_list_events_includes_superseded_when_flag_is_true(client, session, agent) -> None:
    """El toggle `include_superseded=true` devuelve también los `superseded`."""
    pending = _new_event(agent, status=EventStatus.pending)
    superseded = _new_event(agent, status=EventStatus.superseded)
    _persist(session, pending, superseded)

    resp = await client.get("/events?include_superseded=true", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {pending.id, superseded.id}
    assert "superseded" in {item["status"] for item in body["items"]}


async def test_superseded_filter_applies_to_total_not_only_to_the_page(
    client, session, agent
) -> None:
    """El `superseded` excluido tampoco cuenta en `total` (paginación coherente)."""
    kept = _new_event(agent, status=EventStatus.pending)
    dropped = [_new_event(agent, status=EventStatus.superseded) for _ in range(3)]
    _persist(session, kept, *dropped)

    resp = await client.get("/events?page_size=1", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ── 2. Orden y tamaño de página por defecto (US-06, US-26) ───────────────────


async def test_list_events_orders_by_created_at_desc(client, session, agent) -> None:
    """El listado devuelve el más reciente primero, sin importar el orden de inserción."""
    oldest = _new_event(agent, created_at=_NOW - timedelta(hours=3))
    newest = _new_event(agent, created_at=_NOW - timedelta(hours=1))
    middle = _new_event(agent, created_at=_NOW - timedelta(hours=2))
    # Insertados fuera de orden cronológico a propósito: un ORDER BY id daría
    # otra secuencia y el test lo detectaría.
    _persist(session, oldest, newest, middle)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["items"]] == [newest.id, middle.id, oldest.id]


async def test_list_events_default_page_size_is_50(client, session, agent) -> None:
    """Sin `page_size`, la página trae 50 ítems aunque haya más eventos."""
    events = [
        _new_event(agent, created_at=_NOW - timedelta(minutes=i)) for i in range(51)
    ]
    _persist(session, *events)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["total"] == 51
    assert len(body["items"]) == 50

    # La segunda página trae el resto: la paginación corta, no descarta.
    resp2 = await client.get("/events?page=2", headers=_auth_headers())
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert len(body2["items"]) == 1
    assert body2["items"][0]["id"] == events[-1].id  # el más viejo, último en el orden desc


# ── 3. `total` respeta los filtros activos (US-26 criterio 5, US-07) ─────────


async def test_pagination_total_respects_status_filter(client, session, agent) -> None:
    """`total` cuenta sólo los eventos del estado filtrado, no la tabla entera."""
    approved = [_new_event(agent, status=EventStatus.approved) for _ in range(2)]
    pending = [_new_event(agent, status=EventStatus.pending) for _ in range(3)]
    _persist(session, *approved, *pending)

    resp = await client.get("/events?status=approved&page_size=1", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2, "total ignoró el filtro de estado"
    # La página también discrimina: el ítem devuelto es uno de los approved.
    assert body["items"][0]["status"] == "approved"
    assert body["items"][0]["id"] in {e.id for e in approved}


async def test_status_filter_accepts_multiple_values(client, session, agent) -> None:
    """El filtro repetible `status` es una unión, no una intersección vacía."""
    approved = _new_event(agent, status=EventStatus.approved)
    rejected = _new_event(agent, status=EventStatus.rejected)
    pending = _new_event(agent, status=EventStatus.pending)
    _persist(session, approved, rejected, pending)

    resp = await client.get(
        "/events?status=approved&status=rejected", headers=_auth_headers()
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {approved.id, rejected.id}


async def test_pagination_total_respects_path_prefix_filter(client, session, agent) -> None:
    """`total` cuenta sólo los eventos bajo el prefijo pedido."""
    matching = [
        _new_event(agent, path="/etc/ssh/sshd_config"),
        _new_event(agent, path="/etc/ssh/ssh_config"),
    ]
    other = [_new_event(agent, path="/var/log/syslog") for _ in range(3)]
    _persist(session, *matching, *other)

    resp = await client.get("/events?path_prefix=/etc/ssh&page_size=1", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2, "total ignoró path_prefix"
    assert body["items"][0]["path"].startswith("/etc/ssh")


# ── D51/RN-145: event_type y eventos sin ruta (tasks 9.2, 9.3, 10.7) ─────────


async def test_list_events_includes_event_type_field(client, session, agent) -> None:
    """9.1/10.7: cada ítem del listado trae event_type."""
    event = _new_event(agent, path="/etc/hosts")
    _persist(session, event)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["event_type"] == "file_modified"


async def test_pathless_event_appears_without_path_prefix_filter(client, session, agent) -> None:
    """10.7: un evento sin ruta aparece en el listado con path: null cuando no hay path_prefix."""
    gap = _new_pathless_event(agent)
    _persist(session, gap)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    matching = [item for item in body["items"] if item["id"] == gap.id]
    assert len(matching) == 1
    assert matching[0]["path"] is None
    assert matching[0]["event_type"] == "detection_gap"


async def test_pathless_event_excluded_by_path_prefix_filter(client, session, agent) -> None:
    """9.2: un NULL no matchea ningún path_prefix — el evento queda fuera del filtro
    por ruta, comportamiento correcto porque no tiene ruta que buscar."""
    gap = _new_pathless_event(agent)
    with_path = _new_event(agent, path="/etc/passwd")
    _persist(session, gap, with_path)

    resp = await client.get("/events?path_prefix=/etc", headers=_auth_headers())

    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert with_path.id in ids
    assert gap.id not in ids


async def test_pathless_event_matches_severity_and_status_filters(client, session, agent) -> None:
    """9.3: los filtros de status/severity siguen alcanzando a un evento con path nulo."""
    gap = _new_pathless_event(agent, status=EventStatus.alert_only, severity=RuleSeverity.high)
    _persist(session, gap)

    resp = await client.get("/events?severity=high&status=alert_only", headers=_auth_headers())

    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert gap.id in ids


async def test_pathless_event_matches_date_range_filter(client, session, agent) -> None:
    """9.3: el rango de fechas también sigue alcanzando a un evento con path nulo."""
    gap = _new_pathless_event(agent, created_at=_NOW - timedelta(hours=1))
    _persist(session, gap)

    date_from = quote((_NOW - timedelta(hours=2)).isoformat())
    date_to = quote((_NOW + timedelta(hours=1)).isoformat())
    resp = await client.get(
        f"/events?date_from={date_from}&date_to={date_to}", headers=_auth_headers()
    )

    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert gap.id in ids


async def test_pagination_total_respects_date_range_filter(client, session, agent) -> None:
    """`total` cuenta sólo los eventos dentro de [date_from, date_to]."""
    inside = [
        _new_event(agent, created_at=_NOW - timedelta(hours=2)),
        _new_event(agent, created_at=_NOW - timedelta(hours=3)),
    ]
    too_old = _new_event(agent, created_at=_NOW - timedelta(days=5))
    too_new = _new_event(agent, created_at=_NOW + timedelta(days=5))
    _persist(session, *inside, too_old, too_new)

    # quote(): un `+` crudo en la query string se decodifica como espacio
    # (urllib.parse.parse_qsl), así que el desfase aware de _NOW debe ir
    # percent-encoded para llegar intacto al parser de FastAPI.
    date_from = quote((_NOW - timedelta(hours=4)).isoformat())
    date_to = quote((_NOW - timedelta(hours=1)).isoformat())
    resp = await client.get(
        f"/events?date_from={date_from}&date_to={date_to}&page_size=1",
        headers=_auth_headers(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2, "total ignoró el rango de fechas"
    assert body["items"][0]["id"] in {e.id for e in inside}


# ── 4. GET /events/{id} — camino feliz (US-08) ───────────────────────────────


async def test_get_event_by_id_returns_full_detail(client, session, agent) -> None:
    """
    200 con el conjunto de campos del detalle: identificadores, estado,
    severidad, timestamps dobles (detected_at / received_at, W13) y el
    contexto forense del proceso causante.
    """
    parent = _new_event(agent, status=EventStatus.superseded)
    _persist(session, parent)

    event = _new_event(agent, path="/etc/passwd", severity=RuleSeverity.critical)
    event.process_pid = 4242
    event.process_uid = 1000
    event.process_exe = "/usr/bin/vim"
    event.parent_event_id = parent.id
    event.is_symlink = True
    event.symlink_target = "/etc/passwd.real"
    event.detected_at = _NOW - timedelta(seconds=30)
    event.received_at = _NOW
    _persist(session, event)

    resp = await client.get(f"/events/{event.id}", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == event.id
    assert body["event_id"] == event.event_id
    assert body["agent_id"] == agent.agent_id
    assert body["path"] == "/etc/passwd"
    assert body["hash_detected"] == "deadbeef"
    assert body["status"] == "pending"
    assert body["severity"] == "critical"
    assert body["version"] == 0
    assert body["parent_event_id"] == parent.id
    assert body["resolved_at"] is None
    assert body["resolved_by"] is None

    # Contexto forense del proceso causante (US-08 criterio 4).
    assert body["process_pid"] == 4242
    assert body["process_uid"] == 1000
    assert body["process_exe"] == "/usr/bin/vim"

    # Timestamps dobles (W13): detected_at del agente, received_at del backend.
    # D-5 regla 1 (design de timestamps-timezone-aware): estas dos aserciones
    # comparan datetimes aware contra datetimes aware refrescados desde la
    # base — no un mero "fromisoformat no lanza", que pasaría igual con o sin
    # el defecto porque acepta ambas formas.
    assert datetime.fromisoformat(body["detected_at"]) == event.detected_at
    assert datetime.fromisoformat(body["received_at"]) == event.received_at
    # Esta comparación de orden es el ejemplo canónico que pasa antes Y
    # después del arreglo: el orden entre dos instantes se conserva sea cual
    # sea la forma en que se serialicen. Se deja intacta a propósito — no es
    # una omisión, es la contrademostración documentada de D-5 regla 1.
    assert datetime.fromisoformat(body["detected_at"]) < datetime.fromisoformat(
        body["received_at"]
    )

    # Metadatos de symlink (D33/RN-127).
    assert body["is_symlink"] is True
    assert body["symlink_target"] == "/etc/passwd.real"


async def test_get_event_by_id_unknown_returns_404(client, session, agent) -> None:
    """Un id inexistente devuelve 404, no 200 con un cuerpo vacío."""
    resp = await client.get("/events/987654", headers=_auth_headers())
    assert resp.status_code == 404


async def test_get_event_by_id_returns_textual_diff_metadata(client, session, agent) -> None:
    diff = "--- a/etc/hosts\n+++ b/etc/hosts\n@@ -1 +1 @@\n-old\n+new\n"
    event = _new_event(agent, hash_expected="e" * 64, diff_text=diff)
    _persist(session, event)

    resp = await client.get(f"/events/{event.id}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["hash_expected"] == "e" * 64
    assert resp.json()["diff_text"] == diff


async def test_list_events_does_not_expose_textual_diff(client, session, agent) -> None:
    event = _new_event(agent, diff_text="sensitive patch")
    _persist(session, event)

    resp = await client.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    assert "diff_text" not in resp.json()["items"][0]


async def test_get_event_by_id_pathless_event_returns_null_path(client, session, agent) -> None:
    """10.7: GET /events/{id} sobre un evento sin ruta responde 200 con path:
    null y event_type discriminante, sin fallar la serialización (D51/RN-145)."""
    gap = _new_pathless_event(agent)
    _persist(session, gap)

    resp = await client.get(f"/events/{gap.id}", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] is None
    assert body["event_type"] == "detection_gap"
    assert body["severity"] == "high"
    assert body["status"] == "alert_only"
