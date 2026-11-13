"""Agent health, reliability, containment, and circuit-breaker operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_org_id, require_admin
from ..errors import NotFoundError
from ..models import (
    Agent,
    AgentState,
    CircuitBreaker,
    Notification,
    QuarantineEvent,
    User,
)
from ..schemas_v2 import (
    AgentHealthOut,
    QuarantineEventOut,
    QuarantineRequest,
    RecoveryRequest,
    ReliabilityOut,
)
from ..services import containment as containment_service
from ..services import reliability as reliability_service

router = APIRouter(tags=["operations"])

_CIRCUIT_RANK = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}


def _require_agent(db: Session, org_id: str, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.org_id != org_id:
        raise NotFoundError("Agent not found")
    return agent


def _state(db: Session, agent: Agent) -> AgentState:
    state = db.get(AgentState, agent.id)
    if state is None:
        state = containment_service.get_or_create_state(db, agent)
        db.commit()
        db.refresh(state)
    return state


def _circuit_state(db: Session, agent: Agent) -> str:
    circuits = list(
        db.execute(select(CircuitBreaker).where(CircuitBreaker.agent_id == agent.id)).scalars()
    )
    if not circuits:
        return "CLOSED"
    return max(circuits, key=lambda row: _CIRCUIT_RANK.get(row.state, 0)).state


def _health(db: Session, agent: Agent) -> AgentHealthOut:
    state = _state(db, agent)
    reliability = reliability_service.compute_reliability(db, agent=agent)
    db.commit()
    return AgentHealthOut(
        agent_id=agent.id,
        agent_name=agent.name,
        status=agent.status,
        operational_status=state.operational_status,
        quarantine_reason=state.quarantine_reason,
        quarantined_at=state.quarantined_at,
        circuit_state=_circuit_state(db, agent),
        reliability=ReliabilityOut(**reliability),
        recent_failures=int(state.validation_failure_count or 0)
        + int(state.decision_failure_count or 0),
    )


@router.get("/agents/{agent_id}/health", response_model=AgentHealthOut)
def agent_health(
    agent_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return _health(db, _require_agent(db, org_id, agent_id))


@router.get("/agents/{agent_id}/reliability", response_model=ReliabilityOut)
def agent_reliability(
    agent_id: str,
    window_days: int | None = None,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = _require_agent(db, org_id, agent_id)
    result = reliability_service.compute_reliability(
        db, agent=agent, window_days=window_days
    )
    db.commit()
    return ReliabilityOut(**result)


@router.get("/reliability", response_model=list[ReliabilityOut])
def list_reliability(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    agents = list(
        db.execute(
            select(Agent).where(Agent.org_id == org_id).order_by(Agent.name)
        ).scalars()
    )
    results = [
        ReliabilityOut(**reliability_service.compute_reliability(db, agent=agent))
        for agent in agents
    ]
    db.commit()
    return results


@router.get("/containment/agents", response_model=list[AgentHealthOut])
def list_agent_health(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    agents = list(db.execute(select(Agent).where(Agent.org_id == org_id)).scalars())
    return [_health(db, agent) for agent in agents]


@router.get("/containment/circuits")
def list_circuits(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    rows = db.execute(
        select(CircuitBreaker)
        .where(CircuitBreaker.org_id == org_id)
        .order_by(CircuitBreaker.updated_at.desc())
    ).scalars()
    return [
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "tool_name": row.tool_name,
            "state": row.state,
            "failure_count": row.failure_count,
            "threshold": row.threshold,
            "opened_at": row.opened_at,
            "half_open_at": row.half_open_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/agents/{agent_id}/quarantine-events", response_model=list[QuarantineEventOut])
def quarantine_events(
    agent_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    _require_agent(db, org_id, agent_id)
    return list(
        db.execute(
            select(QuarantineEvent)
            .where(QuarantineEvent.org_id == org_id, QuarantineEvent.agent_id == agent_id)
            .order_by(QuarantineEvent.created_at.desc())
        ).scalars()
    )


@router.post("/agents/{agent_id}/quarantine", response_model=AgentHealthOut)
def quarantine_agent(
    agent_id: str,
    input: QuarantineRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    agent = _require_agent(db, user.org_id, agent_id)
    containment_service.quarantine_agent(
        db,
        agent=agent,
        reason=input.reason,
        actor_user_id=user.id,
        evidence=input.evidence,
    )
    db.commit()
    return _health(db, agent)


@router.post("/agents/{agent_id}/recovery/start", response_model=AgentHealthOut)
def start_recovery(
    agent_id: str,
    input: RecoveryRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    agent = _require_agent(db, user.org_id, agent_id)
    evidence = input.evidence if input else {}
    containment_service.start_recovery(
        db, agent=agent, actor_user_id=user.id, evidence=evidence
    )
    db.commit()
    return _health(db, agent)


@router.post("/agents/{agent_id}/recovery/complete", response_model=AgentHealthOut)
def complete_recovery(
    agent_id: str,
    input: RecoveryRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    agent = _require_agent(db, user.org_id, agent_id)
    if input is not None and not input.confirm:
        from ..errors import ConflictError

        raise ConflictError("Recovery must be explicitly confirmed")
    evidence = input.evidence if input else {}
    containment_service.complete_recovery(
        db, agent=agent, actor_user_id=user.id, evidence=evidence
    )
    db.commit()
    return _health(db, agent)


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    query = select(Notification).where(Notification.org_id == org_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 1000)))
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "severity": row.severity,
            "title": row.title,
            "body": row.body,
            "incident_id": row.incident_id,
            "created_at": row.created_at,
            "read_at": row.read_at,
        }
        for row in db.execute(query).scalars()
    ]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    from ..models import utcnow

    row = db.get(Notification, notification_id)
    if row is None or row.org_id != user.org_id:
        raise NotFoundError("Notification not found")
    row.read_at = row.read_at or utcnow()
    db.commit()
    return {"id": row.id, "read_at": row.read_at}
