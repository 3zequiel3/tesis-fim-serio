"""
M6 — regression test: incremento atómico y unificado de ruleset_version (C34).

Antes del fix, `increment_ruleset_version` (rules/service.py) y
`_increment_ruleset_version` (actions/service.py) hacían un patrón
lee-modifica-escribe (`SELECT` + `version += 1` + `flush`) sin bloqueo,
propenso a perder incrementos bajo requests concurrentes. El fix unifica
ambos en una única sentencia atómica `UPDATE ... RETURNING`.

Este test corre dos incrementos concurrentes (threads + sesiones/conexiones
Postgres independientes) sobre la fila real de RulesetVersion y verifica que
ninguno se pierde: los resultados son exactamente {N+1, N+2}.
"""

from __future__ import annotations

import threading

from sqlmodel import Session, select

from app.core.database import engine
from app.modules.rules.models import RulesetVersion
from app.modules.rules.service import increment_ruleset_version


def test_concurrent_increments_no_lost_update() -> None:
    """M6: dos incrementos concurrentes producen N+1 y N+2, sin pérdida."""
    with Session(engine) as setup_session:
        setup_session.add(RulesetVersion(version=10))
        setup_session.commit()

    results: list[int] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def _worker() -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=5)
                version = increment_ruleset_version(session)
                session.commit()
                results.append(version)
        except BaseException as exc:  # noqa: BLE001 - se reporta explícitamente abajo
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Unexpected errors in concurrent increment: {errors!r}"
    assert sorted(results) == [11, 12], f"Lost update detected: {results!r}"

    with Session(engine) as verify_session:
        final = verify_session.exec(select(RulesetVersion)).one()
    assert final.version == 12


def test_actions_and_rules_share_single_implementation() -> None:
    """M6: actions/service.py reutiliza la misma función, no la reimplementa."""
    from app.modules.actions import service as actions_service

    assert actions_service._increment_ruleset_version is increment_ruleset_version
