"""Audit event search endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, AuditEvent
from ..schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(
    decision: str | None = None,
    agent_id: str | None = None,
    tool_name: str | None = None,
    event_type: str | None = None,
    q: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[EventOut]:
    query = select(AuditEvent)
    if decision:
        query = query.where(AuditEvent.decision == decision)
    if agent_id:
        query = query.where(AuditEvent.agent_id == agent_id)
    if tool_name:
        query = query.where(AuditEvent.tool_name == tool_name)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    query = query.order_by(AuditEvent.created_at.desc()).limit(max(1, min(limit, 1000)))

    events = list(db.execute(query).scalars().all())
    agents = {
        agent.id: agent.name for agent in db.execute(select(Agent.id, Agent.name)).all()
    }

    search = (q or "").strip().lower()
    results: list[EventOut] = []
    for event in events:
        dto = EventOut.model_validate(event)
        dto.agent_name = agents.get(event.agent_id) if event.agent_id else None
        if search:
            haystack = " ".join(
                [
                    dto.agent_name or "",
                    dto.tool_name or "",
                    dto.action_id or "",
                    dto.decision or "",
                    *dto.reason_codes,
                ]
            ).lower()
            if search not in haystack:
                continue
        results.append(dto)
    return results
