"""
Tests de verificación de retención y compactación de cadenas (C20).

Verifica que retention_task() y compact_chain() implementados en C11 se
comportan correctamente:

  - retention_task(): elimina eventos terminales con created_at > 30d,
    preserva los referenciados en audit_log (RN-98).
  - compact_chain(): compacta cadenas de superseded de longitud > 10,
    respetando los protegidos por audit_log.

Fixtures usan override explícito de created_at (sin sleep — D4).
Requiere PostgreSQL (skip en Windows sin psycopg — patrón C08+).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.events.service import compact_chain


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_engine():
    """SQLite in-memory engine con todos los modelos creados."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_event(
    session: Session,
    path: str,
    event_status: EventStatus,
    days_old: int = 31,
    event_id_suffix: str = "",
) -> Event:
    """
    Crea un evento con created_at sobreescrito explícitamente para simular antigüedad.
    No usa sleep (D4).
    """
    created = datetime.utcnow() - timedelta(days=days_old)
    suffix = event_id_suffix or f"{path}-{days_old}"
    e = Event(
        event_id=f"eid-{suffix}",
        agent_id="agent-test",
        path=path,
        hash_detected="deadbeef",
        status=event_status,
        detected_at=created,
        received_at=created,
        created_at=created,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _make_user(session: Session, username: str = "audit_user") -> User:
    u = User(username=username, email=f"{username}@fim.local", password_hash="x", role="admin")
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


# ── Helpers: ejecutar una iteración de retention_task ────────────────────────

async def _run_retention_once(mem_engine) -> None:
    """Ejecuta retention_task() parcheando asyncio.sleep para una sola iteración."""
    import app.modules.events.service as svc

    call_count = 0

    async def sleep_once(seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise asyncio.CancelledError()

    with patch.object(svc, "engine", mem_engine), \
         patch("app.modules.events.service.asyncio.sleep", side_effect=sleep_once):
        try:
            await svc.retention_task()
        except asyncio.CancelledError:
            pass


# ── Tests: retention_task ─────────────────────────────────────────────────────

def test_retention_elimina_terminal_mayor_30d(mem_engine) -> None:
    """retention_task() elimina evento terminal con created_at > 30d."""
    with Session(mem_engine) as session:
        e = _make_event(session, "/tmp/old.log", EventStatus.approved, days_old=31)
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is None, "Evento viejo terminal debería haber sido eliminado"


def test_retention_preserva_referenciado_en_audit_log(mem_engine) -> None:
    """retention_task() NO elimina eventos terminales referenciados en audit_log (RN-98)."""
    with Session(mem_engine) as session:
        user = _make_user(session, "reviewer")
        e = _make_event(session, "/etc/cron.d/old", EventStatus.rejected, days_old=35)
        audit = AuditLog(
            user_id=user.id,
            action="review",
            target_type="event",
            target_id=e.id,
        )
        session.add(audit)
        session.commit()
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is not None, "Evento referenciado en audit_log no debe eliminarse"


def test_retention_preserva_terminal_reciente(mem_engine) -> None:
    """retention_task() preserva eventos terminales recientes (< 30d)."""
    with Session(mem_engine) as session:
        e = _make_event(session, "/tmp/recent.log", EventStatus.approved, days_old=10)
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is not None, "Evento reciente no debe eliminarse"


# ── Tests: compact_chain ──────────────────────────────────────────────────────

def test_compact_chain_compacta_cadena_mayor_10(mem_engine) -> None:
    """compact_chain() elimina los superseded más antiguos cuando hay >10 en el path."""
    path = "/etc/passwd"
    with Session(mem_engine) as session:
        # Crear 12 eventos superseded para el mismo path
        eventos = []
        for i in range(12):
            e = _make_event(
                session, path, EventStatus.superseded,
                days_old=31 - i,  # distintos tiempos, el i=0 es el más viejo
                event_id_suffix=f"chain-{i}",
            )
            eventos.append(e)

        # compact_chain debería eliminar los 2 más viejos (12 - 10 = 2)
        compact_chain(session, path)
        session.commit()

    with Session(mem_engine) as session:
        remaining = session.exec(
            select(Event).where(Event.path == path, Event.status == EventStatus.superseded)
        ).all()
    assert len(remaining) == 10, f"Debería quedar exactamente 10, quedaron {len(remaining)}"


def test_compact_chain_no_elimina_si_10_o_menos(mem_engine) -> None:
    """compact_chain() no elimina nada si la cadena tiene <= 10 eventos."""
    path = "/etc/hosts"
    with Session(mem_engine) as session:
        for i in range(8):
            _make_event(
                session, path, EventStatus.superseded,
                days_old=31 - i,
                event_id_suffix=f"short-{i}",
            )
        compact_chain(session, path)
        session.commit()

    with Session(mem_engine) as session:
        remaining = session.exec(
            select(Event).where(Event.path == path, Event.status == EventStatus.superseded)
        ).all()
    assert len(remaining) == 8


def test_compact_chain_preserva_protegidos_por_audit_log(mem_engine) -> None:
    """compact_chain() no elimina eventos superseded referenciados en audit_log."""
    path = "/etc/shadow"
    with Session(mem_engine) as session:
        user = _make_user(session, "protector")
        # 11 eventos superseded — se intentaría eliminar 1
        eventos = []
        for i in range(11):
            e = _make_event(
                session, path, EventStatus.superseded,
                days_old=40 - i,
                event_id_suffix=f"prot-{i}",
            )
            eventos.append(e)

        # Proteger el más viejo con audit_log
        oldest = eventos[0]
        audit = AuditLog(
            user_id=user.id,
            action="review",
            target_type="event",
            target_id=oldest.id,
        )
        session.add(audit)
        session.commit()

        compact_chain(session, path)
        session.commit()
        oldest_id = oldest.id

    with Session(mem_engine) as session:
        protected = session.exec(select(Event).where(Event.id == oldest_id)).first()
    assert protected is not None, "Evento protegido por audit_log no debe eliminarse"
