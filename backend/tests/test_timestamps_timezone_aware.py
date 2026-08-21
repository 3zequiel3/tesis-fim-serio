"""
Tests de D39/RN-133 (change timestamps-timezone-aware) que no pueden pasar
bajo el defecto — D-5 del design: nunca `fromisoformat` como aserción de
formato, nunca un round-trip que se compara consigo mismo, y la zona de
prueba siempre fijada donde el render depende de ella.

Cubre:
  - Esquema: las 19 columnas son `timestamptz` en el esquema que construye
    `create_all` (el mismo que corre en producción por la migración 011).
  - Serialización: el instante emitido lleva desfase explícito, verificado
    por `tzinfo`, no por que la cadena "parsee".
  - Ida y vuelta: un instante UTC conocido y literal se preserva a través de
    la API, comparado contra la constante — no contra otro valor de la
    misma ruta.
  - Filtros: dos rangos equivalentes expresados con desfases distintos
    devuelven el mismo conjunto de eventos.
  - Borde de rango: los eventos exactamente en date_from/date_to se incluyen.

Postgres real (el engine de conftest), mismo patrón que
test_event_listing_contract.py.
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

import sqlalchemy
from sqlmodel import Session

from app.core.database import engine
from app.core.security import create_access_token
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity

# Instante UTC conocido y literal (D-5 regla 2): la constante contra la que
# se compara, nunca un valor producido por la misma ruta que se está probando.
_KNOWN_INSTANT = datetime(2026, 8, 20, 19, 55, 59, 641248, tzinfo=timezone.utc)

# Inventario de las 19 columnas migradas — idéntico al de la migración 011 y
# al de domain-models/spec.md. Vive acá también, y no solo en el SQL, porque
# es la propiedad que este test existe para afirmar sobre el esquema que
# create_all construye (D-2 del design).
_MIGRATED_COLUMNS: set[tuple[str, str]] = {
    ("agents", "last_heartbeat"),
    ("alerts", "created_at"),
    ("alerts", "delivered_at"),
    ("alerts", "failed_at"),
    ("audit_log", "created_at"),
    ("baseline_entries", "last_updated"),
    ("events", "created_at"),
    ("events", "detected_at"),
    ("events", "received_at"),
    ("events", "resolved_at"),
    ("published_commands", "acked_at"),
    ("published_commands", "published_at"),
    ("rejected_events_audit", "detected_at"),
    ("rejected_events_audit", "received_at"),
    ("revoked_certificates", "revoked_at"),
    ("rules", "created_at"),
    ("rules", "updated_at"),
    ("ruleset_versions", "updated_at"),
    ("users", "created_at"),
}


def _auth_headers() -> dict[str, str]:
    token = create_access_token(
        user_id=1, username="admin", must_change_password=False, jti="test-jti-tz"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-tz-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _persist(session: Session, *events: Event) -> None:
    for event in events:
        session.add(event)
    session.commit()
    for event in events:
        session.refresh(event)


def _new_event(agent: Agent, *, created_at: datetime, path: str | None = None) -> Event:
    return Event(
        event_id=f"evt-tz-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        path=path if path is not None else f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected="deadbeef",
        status=EventStatus.pending,
        severity=RuleSeverity.low,
        detected_at=created_at,
        received_at=created_at,
        created_at=created_at,
    )


# ── 5.1 Esquema (D-2) ─────────────────────────────────────────────────────────


def test_schema_all_19_columns_are_timestamptz(session: Session) -> None:
    """Las 19 columnas del inventario de D39/RN-133 son timestamptz en el
    esquema construido por create_all — el mismo que corre en producción
    vía la migración 011."""
    # Lista de tablas fija (no entrada de usuario): se arma el IN por
    # formato de string en vez de bindparam para evitar la fricción de
    # adaptar listas de Python a arrays de Postgres a través de text().
    tables_sql = ", ".join(f"'{t}'" for t in sorted({t for t, _ in _MIGRATED_COLUMNS}))
    rows = session.exec(
        sqlalchemy.text(
            f"""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ({tables_sql})
            """
        )
    ).all()

    all_cols = {(r.table_name, r.column_name): r.data_type for r in rows}
    # Filtrar a las 19 del inventario: las tablas también tienen columnas que
    # no son instantes (status, path, etc.) y no forman parte de esta aserción.
    found = {k: v for k, v in all_cols.items() if k in _MIGRATED_COLUMNS}
    assert set(found.keys()) == _MIGRATED_COLUMNS, (
        f"faltan columnas del inventario en information_schema: "
        f"{_MIGRATED_COLUMNS - set(found.keys())}"
    )
    non_tz = {k: v for k, v in found.items() if v != "timestamp with time zone"}
    assert non_tz == {}, f"columnas que deberían ser timestamptz y no lo son: {non_tz}"


def test_schema_no_column_is_left_without_a_zone(session: Session) -> None:
    """Ninguna columna `timestamp without time zone` sobrevive en el esquema
    — de modo que una tabla nueva con una fecha naive haga fallar la suite
    (D-2: la propiedad que hoy no era expresable en el arnés)."""
    rows = session.exec(
        sqlalchemy.text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'timestamp without time zone'
            """
        )
    ).all()
    offenders = [(r.table_name, r.column_name) for r in rows]
    assert offenders == [], f"columnas naive remanentes: {offenders}"


# ── 5.2 Serialización (D-5 regla 1) ───────────────────────────────────────────


async def test_serialized_instant_is_tzinfo_aware(client, session, agent) -> None:
    """El instante serializado, una vez parseado, lleva tzinfo — no basta
    con que `fromisoformat` no lance, porque acepta ambas formas."""
    event = _new_event(agent, created_at=_KNOWN_INSTANT)
    _persist(session, event)

    resp = await client.get(f"/events/{event.id}", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()

    parsed = datetime.fromisoformat(body["detected_at"])
    assert parsed.tzinfo is not None, (
        f"detected_at serializado sin desfase: {body['detected_at']!r}"
    )
    parsed_created = datetime.fromisoformat(body["created_at"])
    assert parsed_created.tzinfo is not None


async def test_null_instant_serializes_as_null(client, session, agent) -> None:
    """resolved_at ausente sigue siendo null, no cadena vacía ni epoch."""
    event = _new_event(agent, created_at=_KNOWN_INSTANT)
    _persist(session, event)

    resp = await client.get(f"/events/{event.id}", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["resolved_at"] is None


# ── 5.3 Ida y vuelta (D-5 regla 2) ────────────────────────────────────────────


async def test_round_trip_preserves_the_known_instant(client, session, agent) -> None:
    """Un instante UTC conocido y literal, escrito y leído por la API,
    denota el mismo instante que la CONSTANTE — no que otro valor producido
    por la misma ruta. Un round-trip que se compara consigo mismo pasa
    aunque las dos puntas estén corridas por igual (el estado del defecto)."""
    event = _new_event(agent, created_at=_KNOWN_INSTANT)
    _persist(session, event)

    resp = await client.get(f"/events/{event.id}", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()

    assert datetime.fromisoformat(body["detected_at"]) == _KNOWN_INSTANT
    assert datetime.fromisoformat(body["received_at"]) == _KNOWN_INSTANT
    assert datetime.fromisoformat(body["created_at"]) == _KNOWN_INSTANT


# ── 5.4 Filtros equivalentes en distintos desfases ────────────────────────────


async def test_equivalent_ranges_in_different_offsets_return_same_events(
    client, session, agent
) -> None:
    """El mismo intervalo de instantes, expresado una vez con +00:00 y otra
    con -03:00, devuelve el mismo conjunto de eventos — la aserción que
    distingue 'interpreta el instante' de 'compara cadenas'."""
    inside = _new_event(agent, created_at=_KNOWN_INSTANT)
    outside = _new_event(agent, created_at=_KNOWN_INSTANT + timedelta(hours=2))
    _persist(session, inside, outside)

    # quote(): un `+` crudo en la query string se decodifica como espacio
    # (urllib.parse.parse_qsl), así que el desfase debe ir percent-encoded
    # para llegar intacto al parser de FastAPI.
    date_from_utc = quote((_KNOWN_INSTANT - timedelta(minutes=1)).isoformat())
    date_to_utc = quote((_KNOWN_INSTANT + timedelta(minutes=1)).isoformat())

    # Mismos instantes, escritos con offset -03:00 (Argentina).
    ar_tz = timezone(timedelta(hours=-3))
    date_from_ar = quote((_KNOWN_INSTANT - timedelta(minutes=1)).astimezone(ar_tz).isoformat())
    date_to_ar = quote((_KNOWN_INSTANT + timedelta(minutes=1)).astimezone(ar_tz).isoformat())

    resp_utc = await client.get(
        f"/events?date_from={date_from_utc}&date_to={date_to_utc}",
        headers=_auth_headers(),
    )
    resp_ar = await client.get(
        f"/events?date_from={date_from_ar}&date_to={date_to_ar}",
        headers=_auth_headers(),
    )

    assert resp_utc.status_code == 200
    assert resp_ar.status_code == 200
    ids_utc = {item["id"] for item in resp_utc.json()["items"]}
    ids_ar = {item["id"] for item in resp_ar.json()["items"]}
    assert ids_utc == ids_ar == {inside.id}
    assert outside.id not in ids_utc


async def test_naive_date_filter_is_read_as_utc(client, session, agent) -> None:
    """Un date_from sin desfase se interpreta como UTC — la respuesta es
    idéntica a la misma llamada con +00:00 explícito (RN-133)."""
    event = _new_event(agent, created_at=_KNOWN_INSTANT)
    _persist(session, event)

    naive = quote(_KNOWN_INSTANT.replace(tzinfo=None).isoformat())
    explicit = quote(_KNOWN_INSTANT.isoformat())

    resp_naive = await client.get(
        f"/events?date_from={naive}&date_to={naive}", headers=_auth_headers()
    )
    resp_explicit = await client.get(
        f"/events?date_from={explicit}&date_to={explicit}", headers=_auth_headers()
    )

    assert resp_naive.status_code == 200
    assert resp_explicit.status_code == 200
    assert {i["id"] for i in resp_naive.json()["items"]} == {
        i["id"] for i in resp_explicit.json()["items"]
    } == {event.id}


# ── 5.5 Borde de rango ────────────────────────────────────────────────────────


async def test_boundary_events_are_included(client, session, agent) -> None:
    """Un evento con created_at == date_from exacto y otro == date_to exacto
    aparecen ambos — los límites siguen siendo inclusivos."""
    date_from = _KNOWN_INSTANT
    date_to = _KNOWN_INSTANT + timedelta(hours=1)
    at_from = _new_event(agent, created_at=date_from)
    at_to = _new_event(agent, created_at=date_to)
    outside = _new_event(agent, created_at=date_to + timedelta(seconds=1))
    _persist(session, at_from, at_to, outside)

    resp = await client.get(
        f"/events?date_from={quote(date_from.isoformat())}&date_to={quote(date_to.isoformat())}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert at_from.id in ids
    assert at_to.id in ids
    assert outside.id not in ids
