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

_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
    """Ejecuta PING con timeout 2s (cliente sync — corre en threadpool)."""
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, valkey_client.ping),
            timeout=_VALKEY_TIMEOUT,
        )
        return "ok" if result else "down"
    except Exception as exc:
        log.warning("health.valkey_down", error=str(exc))
        return "down"


async def _check_n8n(n8n_webhook_url: str) -> str:
    """
    HEAD al webhook de n8n con timeout 3s (M9). Cualquier status de error
    (4xx/5xx) se reporta `down` vía `raise_for_status()` — antes, el check
    comparaba `status_code < 500`, que trataba erróneamente los 4xx (p. ej.
    405 Method Not Allowed) como `ok`, y el `except httpx.HTTPStatusError`
    era dead code porque `head()` sin `raise_for_status()` nunca lo lanzaba.

    Preferimos HEAD sobre GET porque un GET a un webhook n8n podría disparar
    el workflow; si HEAD falla (conexión/timeout) o el endpoint no soporta
    HEAD, reintentamos con GET como fallback documentado antes de decidir el
    resultado final. Un webhook n8n sano suele responder 404 ("not
    registered for HEAD") — NO 405 —, así que tanto 404 como 405 disparan el
    fallback; de lo contrario un n8n sano se reportaría `down` en cada check.

    NOTA (efecto secundario): el fallback usa la misma URL (webhook). Un GET a
    un webhook productivo puede disparar el workflow n8n. Si se dispone de un
    endpoint de health/base de n8n, es preferible apuntar el fallback ahí; se
    deja como mejora acotada para no cambiar el contrato de configuración
    (settings.n8n_webhook_url) en este fix.
    """
    if not n8n_webhook_url:
        return "degraded"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_N8N_TIMEOUT) as client:
            try:
                response = await client.head(n8n_webhook_url)
                response.raise_for_status()
                return "ok"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (404, 405):
                    # Error real (4xx que no indica "HEAD no soportado", o 5xx) — down directo.
                    log.warning(
                        "health.n8n_error_status",
                        status_code=exc.response.status_code,
                    )
                    return "down"
                # 404/405 — HEAD no soportado por el webhook n8n, fallback a GET.
            except httpx.HTTPError as exc:
                # HEAD falló por conexión/timeout — fallback a GET.
                log.warning("health.n8n_head_failed", error=str(exc))

            response = await client.get(n8n_webhook_url)
            response.raise_for_status()
            return "ok"
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
                    _fire_and_forget(
                        send_n8n(change_payload, settings.n8n_webhook_url, timeout=5.0)
                    )

    _last_state = current_state
    return result
