"""Agent registry: CRUD, credentials, permissions, and agent authentication."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, AgentToolPermission, Tool, utcnow
from ..schemas import AgentCreate, AgentUpdate, PermissionsUpdate
from ..security import generate_agent_key, hash_key, verify_key
from .audit import record_event


def authenticate(db: Session, api_key: str | None) -> Agent | None:
    """Resolve an agent from its API key. Fail closed on any problem."""
    if not api_key:
        return None
    agents = db.execute(select(Agent)).scalars().all()
    for agent in agents:
        if verify_key(api_key, agent.credential_hash):
            return agent
    return None


def get_agent(db: Session, agent_id: str) -> Agent | None:
    return db.get(Agent, agent_id)


def get_agent_by_name(db: Session, name: str) -> Agent | None:
    return db.execute(select(Agent).where(Agent.name == name)).scalar_one_or_none()


def list_agents(db: Session) -> list[Agent]:
    return list(db.execute(select(Agent).order_by(Agent.updated_at.desc())).scalars())


def tool_ids_for(db: Session, agent_id: str) -> list[str]:
    rows = db.execute(
        select(AgentToolPermission.tool_id).where(AgentToolPermission.agent_id == agent_id)
    ).scalars().all()
    return list(rows)


def create_agent(db: Session, input: AgentCreate, actor_user_id: str | None) -> tuple[Agent, str]:
    if get_agent_by_name(db, input.name):
        raise ValueError(f"Agent name '{input.name}' is already registered")

    api_key = generate_agent_key()
    agent = Agent(
        name=input.name,
        owner_user_id=input.owner_user_id,
        environment=input.environment,
        status="ACTIVE",
        credential_hash=hash_key(api_key),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(agent)
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{agent.id}",
        agent_id=agent.id,
        reason_codes=["AGENT_REGISTERED"],
        metadata={"actorUserId": actor_user_id, "environment": agent.environment},
    )
    db.commit()
    db.refresh(agent)
    return agent, api_key


def update_agent(db: Session, agent: Agent, input: AgentUpdate, actor_user_id: str | None) -> Agent:
    if input.name is not None:
        existing = get_agent_by_name(db, input.name)
        if existing and existing.id != agent.id:
            raise ValueError(f"Agent name '{input.name}' is already registered")
        agent.name = input.name
    if input.owner_user_id is not None:
        agent.owner_user_id = input.owner_user_id
    if input.environment is not None:
        agent.environment = input.environment
    agent.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{agent.id}",
        agent_id=agent.id,
        reason_codes=["AGENT_UPDATED"],
        metadata={"actorUserId": actor_user_id},
    )
    db.commit()
    db.refresh(agent)
    return agent


def set_status(db: Session, agent: Agent, status: str, actor_user_id: str | None) -> Agent:
    previous = agent.status
    agent.status = status
    agent.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{agent.id}",
        agent_id=agent.id,
        reason_codes=["AGENT_DISABLED_BY_ADMIN" if status == "DISABLED" else "AGENT_ENABLED_BY_ADMIN"],
        metadata={"actorUserId": actor_user_id, "previousStatus": previous},
    )
    db.commit()
    db.refresh(agent)
    return agent


def set_permissions(
    db: Session, agent: Agent, input: PermissionsUpdate, actor_user_id: str | None
) -> Agent:
    valid_tools = {
        tool.id
        for tool in db.execute(select(Tool).where(Tool.id.in_(input.tool_ids))).scalars().all()
    } if input.tool_ids else set()

    db.query(AgentToolPermission).filter(AgentToolPermission.agent_id == agent.id).delete()
    for tool_id in valid_tools:
        db.add(
            AgentToolPermission(
                agent_id=agent.id,
                tool_id=tool_id,
                scopes=input.scopes or {},
                created_at=utcnow(),
            )
        )
    agent.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{agent.id}",
        agent_id=agent.id,
        reason_codes=["PERMISSIONS_UPDATED"],
        metadata={"actorUserId": actor_user_id, "toolIds": sorted(valid_tools)},
    )
    db.commit()
    db.refresh(agent)
    return agent


def rotate_key(db: Session, agent: Agent, actor_user_id: str | None) -> str:
    api_key = generate_agent_key()
    agent.credential_hash = hash_key(api_key)
    agent.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{agent.id}",
        agent_id=agent.id,
        reason_codes=["CREDENTIAL_ROTATED"],
        metadata={"actorUserId": actor_user_id},
    )
    db.commit()
    return api_key


def has_permission(db: Session, agent_id: str, tool_id: str) -> bool:
    return (
        db.execute(
            select(AgentToolPermission).where(
                AgentToolPermission.agent_id == agent_id,
                AgentToolPermission.tool_id == tool_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def touch_last_action(db: Session, agent: Agent) -> None:
    agent.last_action_at = utcnow()
    db.flush()


def agent_to_dict(agent: Agent, tool_ids: list[str]) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "owner_user_id": agent.owner_user_id,
        "environment": agent.environment,
        "status": agent.status,
        "tool_ids": tool_ids,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "last_action_at": agent.last_action_at,
    }
