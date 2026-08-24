"""
Health check de componentes para FIM Platform (C15 — backend-notifications).

Implementa GET /health/components (D-C15-05):
  - postgres: SELECT 1 con timeout 2s
  - valkey: PING con timeout 2s
  - n8n: GET a N8N_HEALTH_URL con timeout 3s; degraded si no configurado.
         NUNCA toca N8N_WEBHOOK_URL — un GET a un webhook productivo puede
         disparar el workflow (D43/RN-137).
  - agents: query DB; ok si alguno online, degraded si ninguno

Cache del último estado en _last_state (variable de módulo) para detección de cambios.
Si hay cambio → asyncio.create_task(send_n8n(change_payload, ...)).
"""

from __future__ import annotations

import asyncio
import uuid
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


async def _check_n8n(n8n_health_url: str) -> str:
    """
    GET al endpoint de salud de n8n con timeout 3s (D43/RN-137).

    POR QUÉ CAMBIÓ (y por qué el baile HEAD→GET ya no existe)
        Hasta C46 este check apuntaba a `settings.n8n_webhook_url`. Eso obligaba
        a intentar HEAD primero —un GET contra un webhook productivo puede
        DISPARAR el workflow— y a caer a GET igual cuando HEAD devolvía 404/405,
        que es lo que responde un webhook n8n sano. El fallback terminaba
        haciendo exactamente lo que el HEAD intentaba evitar: el docstring
        anterior lo admitía y lo difería. Con el enrutador `fim-alert` operativo
        (change 47) eso sería un disparo espurio cada 10 segundos.

        Apuntando a un endpoint de salud real, un GET es la operación correcta y
        no tiene efectos secundarios, así que toda la heurística desaparece.

    LO QUE SE CONSERVA DE M9 (C34)
        Cualquier 4xx/5xx se reporta `down` vía `raise_for_status()`. La
        regresión original era comparar `status_code < 500`, que trataba un 405
        como `ok`. Un endpoint de salud que responde 404 está mal configurado,
        no sano — acá sí es `down`, sin excepciones por código.

    Vacío ⇒ `degraded`: sin URL de salud no se puede afirmar que n8n esté sano.
    """
    if not n8n_health_url:
        return "degraded"

    # Importado FUERA del try: el except referencia httpx.HTTPStatusError, así
    # que si el import fallara dentro del try la cláusula levantaría NameError
    # en vez de devolver "down" — y RN-101 exige que este check nunca lance.
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_N8N_TIMEOUT) as client:
            response = await client.get(n8n_health_url)
            response.raise_for_status()
            return "ok"
    except httpx.HTTPStatusError as exc:
        log.warning("health.n8n_error_status", status_code=exc.response.status_code)
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
        _check_n8n(settings.n8n_health_url),
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
                    from app.modules.alerts.contract import (
                        NOTIFICATION_TYPE_HEALTH_CHANGE,
                        SCHEMA_VERSION,
                    )
                    from app.modules.alerts.notifier import send_n8n

                    # Sobre plano de D40/RN-134. `type` es el discriminador
                    # canónico: alertas de evento y cambios de salud comparten
                    # una única URL de webhook, así que sin él el receptor no
                    # puede distinguir las dos formas. `event` se conserva por
                    # compatibilidad con cualquier consumidor previo.
                    change_payload = {
                        "schema_version": SCHEMA_VERSION,
                        "notification_id": str(uuid.uuid4()),
                        "type": NOTIFICATION_TYPE_HEALTH_CHANGE,
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
