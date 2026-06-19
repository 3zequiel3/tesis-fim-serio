"""
Router de agentes FIM — registro (admin), bootstrap (público) y gestión operacional (C06, C14).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import require_admin
from app.core.config import settings
from app.core.valkey import get_valkey_client
from app.modules.agents.models import (
    AgentBootstrapRequest,
    AgentBootstrapResponse,
    AgentConfigRequest,
    AgentListResponse,
    AgentRegisterRequest,
    AgentRescanRequest,
    AgentResponse,
)
from app.modules.agents.service import (
    PendingEventsExist,
    bootstrap_agent,
    get_agent,
    list_agents,
    register_agent,
    rescan_agent,
    update_agent_config,
)

router = APIRouter(tags=["agents"])


@router.post("/agents/register", status_code=status.HTTP_201_CREATED)
async def register(
    req: AgentRegisterRequest,
    session: Session = Depends(get_session),
    _admin=Depends(require_admin),
) -> dict[str, str]:
    agent = register_agent(req, session)
    return {"agent_id": agent.agent_id, "status": agent.status.value}


@router.post("/agents/bootstrap", response_model=AgentBootstrapResponse)
async def bootstrap(
    req: AgentBootstrapRequest,
    session: Session = Depends(get_session),
) -> AgentBootstrapResponse:
    return bootstrap_agent(
        req,
        session,
        ca_cert_path=settings.ca_cert_path,
        ca_key_path=settings.ca_key_path,
    )


@router.get("/agents", response_model=AgentListResponse)
async def get_agents_list(
    session: Session = Depends(get_session),
    _admin=Depends(require_admin),
) -> AgentListResponse:
    """Retorna la lista de todos los agentes con su estado operacional."""
    items = list_agents(session)
    return AgentListResponse(items=items, total=len(items))


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent_detail(
    agent_id: str,
    session: Session = Depends(get_session),
    _admin=Depends(require_admin),
) -> AgentResponse:
    """Retorna el detalle de un agente. 404 si no existe."""
    return get_agent(session, agent_id)


@router.post("/agents/{agent_id}/config", response_model=AgentResponse)
async def update_config(
    agent_id: str,
    req: AgentConfigRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    _admin=Depends(require_admin),
) -> AgentResponse:
    """Actualiza watch_paths del agente (replace-all) y publica update_config."""
    return update_agent_config(
        db=session,
        valkey_client=valkey_client,
        agent_id=agent_id,
        watch_paths=req.watch_paths,
        user_id=_admin.id,
    )


@router.post("/agents/{agent_id}/rescan", status_code=status.HTTP_200_OK)
async def rescan(
    agent_id: str,
    req: AgentRescanRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    _admin=Depends(require_admin),
) -> dict[str, str]:
    """Fuerza re-scan de baseline. 409 si hay pending y force=False."""
    try:
        rescan_agent(
            db=session,
            valkey_client=valkey_client,
            agent_id=agent_id,
            force=req.force,
            user_id=_admin.id,
        )
    except PendingEventsExist as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "pending_events_exist", "count": exc.count},
        )
    return {"status": "ok"}
