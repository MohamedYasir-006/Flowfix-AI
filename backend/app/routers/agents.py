"""Agent registry endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import ConflictError, NotFoundError
from ..models import User
from ..schemas import AgentCreated, AgentCreate, AgentOut, AgentUpdate, PermissionsUpdate
from ..services import agents as agents_service

router = APIRouter(prefix="/agents", tags=["agents"])


def _out(agent, db) -> dict:
    return agents_service.agent_to_dict(agent, agents_service.tool_ids_for(db, agent.id))


def _require(db: Session, agent_id: str):
    agent = agents_service.get_agent(db, agent_id)
    if agent is None:
        raise NotFoundError("Agent not found")
    return agent


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)) -> list[dict]:
    return [_out(agent, db) for agent in agents_service.list_agents(db)]


@router.post("", response_model=AgentCreated, status_code=201)
def create_agent(
    input: AgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        agent, api_key = agents_service.create_agent(db, input, user.id)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return {**_out(agent, db), "api_key": api_key}


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)) -> dict:
    return _out(_require(db, agent_id), db)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    input: AgentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = _require(db, agent_id)
    try:
        updated = agents_service.update_agent(db, agent, input, user.id)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return _out(updated, db)


@router.post("/{agent_id}/disable", response_model=AgentOut)
def disable_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = _require(db, agent_id)
    return _out(agents_service.set_status(db, agent, "DISABLED", user.id), db)


@router.post("/{agent_id}/enable", response_model=AgentOut)
def enable_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = _require(db, agent_id)
    return _out(agents_service.set_status(db, agent, "ACTIVE", user.id), db)


@router.put("/{agent_id}/permissions", response_model=AgentOut)
def set_permissions(
    agent_id: str,
    input: PermissionsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = _require(db, agent_id)
    return _out(agents_service.set_permissions(db, agent, input, user.id), db)


@router.post("/{agent_id}/rotate-key", response_model=AgentCreated)
def rotate_key(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = _require(db, agent_id)
    api_key = agents_service.rotate_key(db, agent, user.id)
    return {**_out(agent, db), "api_key": api_key}
