"""
Change 59 (`notify-isolate-executor-lane`, D76/RN-170) — verificación de
slice 2.7: el lifespan real de `app.main` instala DOS executors con sus
tamaños y prefijos configurados, el de ingesta queda como executor por
defecto del loop, y el shutdown los cierra en el orden que D-9 del design
exige (notificación antes que ingesta).

Mismo patrón que `test_rejected_events_retention.py::
test_lifespan_creates_and_cancels_rejected_retention_task`: se monkeypatchea
todo lo pesado del lifespan (Valkey, CA, mTLS, DB, consumers) para observar
sólo la construcción/cierre de los executors, sin levantar el stack completo.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock

from app.core import executors as executors_mod


async def _fake_noop_forever(*_args, **_kwargs):
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        raise


class _FakeAsyncValkey:
    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_lifespan_installs_two_disjoint_executors_with_ingest_as_default(monkeypatch) -> None:
    import app.main as main_module
    from app.core.config import settings

    monkeypatch.setattr(main_module, "init_valkey", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "init_async_valkey", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "ensure_ca", lambda *a, **k: None)
    monkeypatch.setattr(main_module.SQLModel.metadata, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "seed_admin", lambda: None)
    monkeypatch.setattr(main_module, "start_mtls_server", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "start_bootstrap_server", lambda *a, **k: None)
    monkeypatch.setattr(
        main_module, "build_async_valkey_client", lambda *a, **k: _FakeAsyncValkey()
    )
    monkeypatch.setattr(main_module, "close_async_valkey", AsyncMock())
    monkeypatch.setattr(main_module, "close_valkey", lambda: None)
    monkeypatch.setattr(main_module, "run_consumer", _fake_noop_forever)
    monkeypatch.setattr(main_module, "run_heartbeat_consumer", _fake_noop_forever)
    monkeypatch.setattr(main_module, "run_command_ack_consumer", _fake_noop_forever)
    monkeypatch.setattr(main_module, "retention_task", lambda: _fake_noop_forever())
    monkeypatch.setattr(main_module, "outbox_publisher_task", lambda: _fake_noop_forever())
    monkeypatch.setattr(main_module, "recover_pending_notifications", lambda: _fake_noop_forever())
    monkeypatch.setattr(main_module, "rejected_events_retention_task", lambda: _fake_noop_forever())

    shutdown_order: list[str] = []
    real_ingest_executor = None
    real_notify_executor = None

    async with main_module.lifespan(main_module.app):
        loop = asyncio.get_running_loop()

        real_ingest_executor = executors_mod.get_ingest_executor()
        real_notify_executor = executors_mod.get_notify_executor()

        # Tamaños tomados de Settings, no hardcodeados en main.py.
        assert real_ingest_executor._max_workers == settings.db_executor_max_workers
        assert real_notify_executor._max_workers == settings.db_notify_executor_max_workers

        # Prefijos distinguibles, cada uno pide un trabajo real para verlo.
        ingest_name = await loop.run_in_executor(real_ingest_executor, lambda: __import__("threading").current_thread().name)
        notify_name = await loop.run_in_executor(real_notify_executor, lambda: __import__("threading").current_thread().name)
        assert ingest_name.startswith("fim-db")
        assert notify_name.startswith("fim-notify")

        # El executor de INGESTA es el default del loop — un run_in_executor
        # con None debe correr en él, nunca en el de notificación.
        default_name = await loop.run_in_executor(None, lambda: __import__("threading").current_thread().name)
        assert default_name.startswith("fim-db")

        # Instrumentar el shutdown para verificar el ORDEN (D-9 del design):
        # notificación antes que ingesta.
        orig_notify_shutdown = real_notify_executor.shutdown
        orig_ingest_shutdown = real_ingest_executor.shutdown

        def traced_notify_shutdown(*a, **k):
            shutdown_order.append("notify")
            return orig_notify_shutdown(*a, **k)

        def traced_ingest_shutdown(*a, **k):
            shutdown_order.append("ingest")
            return orig_ingest_shutdown(*a, **k)

        real_notify_executor.shutdown = traced_notify_shutdown
        real_ingest_executor.shutdown = traced_ingest_shutdown

    # Tras salir del `async with` (shutdown), el registro global quedó
    # limpio otra vez sólo si install_executors nunca se re-invocó — acá no
    # hace falta resetearlo porque el fixture de conftest lo reinstala antes
    # del próximo test.
    assert shutdown_order == ["notify", "ingest"], (
        f"orden de cierre incorrecto: {shutdown_order} — D-9 del design exige "
        "notificación antes que ingesta"
    )
