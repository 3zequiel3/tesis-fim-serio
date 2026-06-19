"""
Health check de componentes para FIM Platform (C15 — backend-notifications).

Implementa GET /health/components (D-C15-05):
  - postgres: SELECT 1 con timeout 2s
  - valkey: PING con timeout 2s
  - n8n: GET/HEAD webhook URL con timeout 3s; degraded si no configurado
  - agents: query DB; ok si alguno online, degraded si ninguno

Cache del último estado en _last_state (variable de módulo) para detección de cambios.
Si hay cambio → asyncio.create_task(send_n8n(change_payload, ...)).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlmodel import Session, select

from app.modules.agents.models import Agent, AgentStatus

log = structlog.get_logger()

# Cache del último estado (solo para detectar cambios — D-C15-05)
_last_state: dict[str, str] = {}

_POSTGRES_TIMEOUT = 2.0
_VALKEY_TIMEOUT = 2.0
_N8N_TIMEOUT = 3.0


async def _check_postgres(session: Session) -> str:
    """Ejecuta SELECT 1 con timeout 2s."""
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lambda: session.exec(select(1)).first()),
            timeout=_POSTGRES_TIMEOUT,
        )
        return "ok" if result is not None else "down"
    except Exception as exc:
        log.warning("health.postgres_down", error=str(exc))
        return "down"


async def _check_valkey(valkey_client: Any) -> str:
    """Ejecuta PING con timeout 2s."""
    try:
        result = await asyncio.wait_for(valkey_client.ping(), timeout=_VALKEY_TIMEOUT)
        return "ok" if result else "down"
    except Exception as exc:
        log.warning("health.valkey_down", error=str(exc))
        return "down"


async def _check_n8n(n8n_webhook_url: str) -> str:
    """GET/HEAD al webhook de n8n con timeout 3s."""
    if not n8n_webhook_url:
        return "degraded"
    try:
        import httpx

        # Intentar HEAD primero (menos costoso), luego GET si falla
        async with httpx.AsyncClient(timeout=_N8N_TIMEOUT) as client:
            try:
                response = await client.head(n8n_webhook_url)
                return "ok" if response.status_code < 500 else "down"
            except httpx.HTTPStatusError:
                return "down"
    except Exception as exc:
        log.warning("health.n8n_down", error=str(exc))
        return "down"


def _check_agents(session: Session) -> dict[str, Any]:
    """
    Consulta todos los agentes registrados.
    status agregado: 'ok' si alguno está online, 'degraded' si ninguno.
    """
    agents = session.exec(select(Agent)).all()
    items = [
        {"agent_id": a.agent_id, "hostname": a.agent_id, "status": a.status.value}
        for a in agents
    ]
    has_online = any(a.status == AgentStatus.online for a in agents)
    return {
        "status": "ok" if has_online else "degraded",
        "items": items,
    }


async def check_components(
    session: Session,
    valkey_client: Any,
    settings: Any,
) -> dict[str, Any]:
    """
    Verifica todos los componentes en paralelo y detecta cambios de estado.
    Retorna el estado actual; nunca lanza excepción (RN-101).
    """
    global _last_state

    checked_at = datetime.now(timezone.utc).isoformat()

    # Checks en paralelo
    postgres_status, valkey_status, n8n_status = await asyncio.gather(
        _check_postgres(session),
        _check_valkey(valkey_client),
        _check_n8n(settings.n8n_webhook_url),
    )
    agents_result = _check_agents(session)

    current_state = {
        "postgres": postgres_status,
        "valkey": valkey_status,
        "n8n": n8n_status,
        "agents": agents_result["status"],
    }

    result: dict[str, Any] = {
        "postgres": postgres_status,
        "valkey": valkey_status,
        "n8n": n8n_status,
        "agents": agents_result,
        "checked_at": checked_at,
    }

    # Detectar cambios y disparar webhook (D-C15-05, spec backend-health)
    if _last_state:
        for component, new_status in current_state.items():
            old_status = _last_state.get(component, "unknown")
            if old_status != new_status:
                log.info(
                    "health.state_change",
                    component=component,
                    old=old_status,
                    new=new_status,
                )
                if settings.n8n_webhook_url:
                    from app.modules.alerts.notifier import send_n8n

                    change_payload = {
                        "event": "health_change",
                        "component": component,
                        "old_status": old_status,
                        "new_status": new_status,
                        "checked_at": checked_at,
                    }
                    asyncio.create_task(
                        send_n8n(change_payload, settings.n8n_webhook_url, timeout=5.0)
                    )

    _last_state = current_state
    return result
