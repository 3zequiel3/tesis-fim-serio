"""
Router de agentes FIM — registro (admin) y bootstrap (público) (Change 06).
"""

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import require_admin
from app.core.config import settings
from app.modules.agents.models import AgentBootstrapRequest, AgentBootstrapResponse, AgentRegisterRequest
from app.modules.agents.service import bootstrap_agent, register_agent

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
