"""Overview statistics for the dashboard."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, Approval, AuditEvent
from ..schemas import EventOut, OverviewStats

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewStats)
def overview(db: Session = Depends(get_db)) -> OverviewStats:
    agents = list(db.execute(select(Agent)).scalars().all())
    pending = db.execute(
        select(Approval).where(Approval.status == "PENDING")
    ).scalars().all()

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    events = list(
        db.execute(
            select(AuditEvent).where(AuditEvent.event_type == "decision")
        ).scalars().all()
    )
    todays = [
        event
        for event in events
        if datetime.fromisoformat(event.created_at) >= start_of_day
    ]

    recent = list(
        db.execute(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(8)
        ).scalars().all()
    )
    agent_names = {
        agent.id: agent.name for agent in db.execute(select(Agent.id, Agent.name)).all()
    }
    recent_events = []
    for event in recent:
        dto = EventOut.model_validate(event)
        dto.agent_name = agent_names.get(event.agent_id) if event.agent_id else None
        recent_events.append(dto)

    return OverviewStats(
        active_agents=sum(1 for agent in agents if agent.status == "ACTIVE"),
        total_agents=len(agents),
        actions_today=len(todays),
        blocked_today=sum(1 for event in todays if event.decision == "DENY"),
        pending_approvals=len(pending),
        decisions_today={
            "allow": sum(1 for event in todays if event.decision == "ALLOW"),
            "deny": sum(1 for event in todays if event.decision == "DENY"),
            "requireApproval": sum(1 for event in todays if event.decision == "REQUIRE_APPROVAL"),
        },
        recent_events=recent_events,
    )
