"""Automatic failure containment: quarantine, circuit breakers, recovery.

State transitions use conditional SQL updates so two concurrent failures cannot
both "win" a transition. Recovery is explicit: releasing an agent requires an
authorized administrator, no unresolved invalid outputs, and a successful
recovery check. Recovery does not bypass normal policy authorization.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ConflictError, ForbiddenError, NotFoundError
from ..models import (
    Agent,
    AgentState,
    Artifact,
    CircuitBreaker,
    Notification,
    QuarantineEvent,
    WorkflowExecution,
    utcnow,
)
from . import audit as audit_service


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        value = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_or_create_state(db: Session, agent: Agent) -> AgentState:
    state = db.get(AgentState, agent.id)
    if state is None:
        state = AgentState(
            agent_id=agent.id,
            org_id=agent.org_id,
            operational_status="ACTIVE",
            updated_at=utcnow(),
        )
        db.add(state)
        db.flush()
    return state


def get_or_create_circuit(
    db: Session, agent: Agent, tool_name: str = "*", threshold: int | None = None
) -> CircuitBreaker:
    settings = get_settings()
    circuit = db.execute(
        select(CircuitBreaker).where(
            CircuitBreaker.agent_id == agent.id, CircuitBreaker.tool_name == tool_name
        )
    ).scalar_one_or_none()
    if circuit is None:
        circuit = CircuitBreaker(
            org_id=agent.org_id,
            agent_id=agent.id,
            tool_name=tool_name,
            state="CLOSED",
            failure_count=0,
            threshold=threshold or settings.containment_failure_threshold,
            updated_at=utcnow(),
        )
        db.add(circuit)
        db.flush()
    return circuit


def record_validation_failure(
    db: Session,
    *,
    agent: Agent,
    artifact_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> AgentState:
    settings = get_settings()
    state = get_or_create_state(db, agent)
    db.execute(
        update(AgentState)
        .where(AgentState.agent_id == agent.id)
        .values(
            validation_failure_count=AgentState.validation_failure_count + 1,
            consecutive_successes=0,
            last_failure_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    db.flush()
    db.refresh(state)

    circuit = get_or_create_circuit(db, agent)
    db.execute(
        update(CircuitBreaker)
        .where(CircuitBreaker.id == circuit.id)
        .values(failure_count=CircuitBreaker.failure_count + 1, updated_at=utcnow())
    )
    db.flush()
    db.refresh(circuit)

    threshold = settings.containment_failure_threshold
    if circuit.failure_count >= circuit.threshold:
        _open_circuit(db, circuit)

    if state.validation_failure_count >= threshold and state.operational_status != "QUARANTINED":
        quarantine_agent(
            db,
            agent=agent,
            reason=f"{state.validation_failure_count} validation failures (last: {reason})",
            actor_user_id=None,
            evidence={
                "artifactId": artifact_id,
                "reason": reason,
                **(evidence or {}),
                "automatic": True,
            },
        )
    return state


def record_execution_failure(
    db: Session,
    *,
    agent: Agent,
    action_id: str,
    error: str | None,
    tool_name: str = "*",
) -> AgentState:
    settings = get_settings()
    state = get_or_create_state(db, agent)
    db.execute(
        update(AgentState)
        .where(AgentState.agent_id == agent.id)
        .values(
            decision_failure_count=AgentState.decision_failure_count + 1,
            last_failure_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    circuit = get_or_create_circuit(db, agent, tool_name)
    db.execute(
        update(CircuitBreaker)
        .where(CircuitBreaker.id == circuit.id)
        .values(failure_count=CircuitBreaker.failure_count + 1, updated_at=utcnow())
    )
    db.flush()
    db.refresh(circuit)
    if circuit.failure_count >= circuit.threshold:
        _open_circuit(db, circuit)
    db.refresh(state)
    if (
        state.decision_failure_count >= settings.containment_failure_threshold
        and state.operational_status != "QUARANTINED"
    ):
        quarantine_agent(
            db,
            agent=agent,
            reason=f"{state.decision_failure_count} repeated execution failures",
            actor_user_id=None,
            evidence={"actionId": action_id, "error": error, "automatic": True},
        )
    return state


def _open_circuit(db: Session, circuit: CircuitBreaker) -> None:
    db.execute(
        update(CircuitBreaker)
        .where(CircuitBreaker.id == circuit.id, CircuitBreaker.state != "OPEN")
        .values(state="OPEN", opened_at=utcnow(), updated_at=utcnow())
    )
    db.flush()
    db.refresh(circuit)


def quarantine_agent(
    db: Session,
    *,
    agent: Agent,
    reason: str,
    actor_user_id: str | None,
    evidence: dict[str, Any] | None = None,
) -> AgentState:
    from .incidents import create_incident

    state = get_or_create_state(db, agent)
    result = db.execute(
        update(AgentState)
        .where(
            AgentState.agent_id == agent.id,
            AgentState.operational_status != "QUARANTINED",
        )
        .values(
            operational_status="QUARANTINED",
            quarantine_reason=reason,
            quarantined_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    if result.rowcount == 0:
        db.flush()
        db.refresh(state)
        return state

    db.flush()
    db.refresh(state)
    for circuit in db.execute(
        select(CircuitBreaker).where(CircuitBreaker.agent_id == agent.id)
    ).scalars():
        _open_circuit(db, circuit)

    db.add(
        QuarantineEvent(
            org_id=agent.org_id,
            agent_id=agent.id,
            action="QUARANTINE",
            reason=reason,
            actor_user_id=actor_user_id,
            evidence=evidence or {},
            created_at=utcnow(),
        )
    )
    incident = create_incident(
        db,
        org_id=agent.org_id,
        workflow_execution_id=None,
        origin_agent_id=agent.id,
        failure_type="AGENT_QUARANTINED",
        risk_level="CRITICAL",
        summary=f"Agent '{agent.name}' quarantined: {reason}",
        evidence={"reason": reason, **(evidence or {})},
    )
    db.add(
        Notification(
            org_id=agent.org_id,
            kind="containment",
            severity="CRITICAL",
            title=f"Agent quarantined: {agent.name}",
            body=reason,
            incident_id=incident.id,
            created_at=utcnow(),
        )
    )
    audit_service.record_event(
        db,
        event_type="containment",
        agent_id=agent.id,
        reason_codes=["AGENT_QUARANTINED"],
        risk_level="CRITICAL",
        metadata={
            "reason": reason,
            "actorUserId": actor_user_id,
            "incidentId": incident.id,
            "evidence": evidence or {},
        },
        org_id=agent.org_id,
    )
    return state


def start_recovery(
    db: Session, *, agent: Agent, actor_user_id: str, evidence: dict[str, Any] | None = None
) -> AgentState:
    state = get_or_create_state(db, agent)
    result = db.execute(
        update(AgentState)
        .where(
            AgentState.agent_id == agent.id,
            AgentState.operational_status == "QUARANTINED",
        )
        .values(operational_status="RECOVERING", updated_at=utcnow())
    )
    if result.rowcount == 0:
        raise ConflictError(
            "Agent is not quarantined", reason_codes=["AGENT_NOT_QUARANTINED"]
        )
    db.flush()
    db.refresh(state)
    db.add(
        QuarantineEvent(
            org_id=agent.org_id,
            agent_id=agent.id,
            action="START_RECOVERY",
            reason="Recovery requested by administrator",
            actor_user_id=actor_user_id,
            evidence=evidence or {},
            created_at=utcnow(),
        )
    )
    audit_service.record_event(
        db,
        event_type="containment",
        agent_id=agent.id,
        reason_codes=["RECOVERY_STARTED"],
        risk_level="HIGH",
        metadata={"actorUserId": actor_user_id, "evidence": evidence or {}},
        org_id=agent.org_id,
    )
    return state


def unresolved_invalid_artifacts(db: Session, agent: Agent) -> list[Artifact]:
    """Invalid outputs with no newer validated replacement of the same type/name."""
    invalid = db.execute(
        select(Artifact).where(
            Artifact.org_id == agent.org_id,
            Artifact.producer_agent_id == agent.id,
            Artifact.validation_status.in_(["INVALID", "REJECTED"]),
        )
    ).scalars().all()
    unresolved: list[Artifact] = []
    for artifact in invalid:
        replacement = db.execute(
            select(Artifact).where(
                Artifact.org_id == agent.org_id,
                Artifact.producer_agent_id == agent.id,
                Artifact.artifact_type == artifact.artifact_type,
                Artifact.name == artifact.name,
                Artifact.validation_status == "VALIDATED",
                Artifact.created_at >= artifact.created_at,
            )
        ).scalars().first()
        if replacement is None and artifact.validation_status == "INVALID":
            unresolved.append(artifact)
    return unresolved


def complete_recovery(
    db: Session, *, agent: Agent, actor_user_id: str, evidence: dict[str, Any] | None = None
) -> AgentState:
    state = get_or_create_state(db, agent)
    if state.operational_status not in ("RECOVERING", "QUARANTINED"):
        raise ConflictError(
            "Agent is not in recovery", reason_codes=["AGENT_NOT_RECOVERING"]
        )
    unresolved = unresolved_invalid_artifacts(db, agent)
    if unresolved:
        raise ConflictError(
            "Cannot release an agent with unresolved invalid outputs; revalidate or replace them first",
            reason_codes=["UNRESOLVED_INVALID_OUTPUTS"],
        )

    result = db.execute(
        update(AgentState)
        .where(
            AgentState.agent_id == agent.id,
            AgentState.operational_status.in_(["RECOVERING", "QUARANTINED"]),
        )
        .values(
            operational_status="ACTIVE",
            quarantine_reason=None,
            quarantined_at=None,
            validation_failure_count=0,
            decision_failure_count=0,
            consecutive_successes=0,
            updated_at=utcnow(),
        )
    )
    if result.rowcount == 0:
        raise ConflictError("Agent recovery state changed concurrently")
    db.flush()
    db.refresh(state)
    for circuit in db.execute(
        select(CircuitBreaker).where(CircuitBreaker.agent_id == agent.id)
    ).scalars():
        db.execute(
            update(CircuitBreaker)
            .where(CircuitBreaker.id == circuit.id)
            .values(
                state="CLOSED",
                failure_count=0,
                opened_at=None,
                half_open_at=None,
                updated_at=utcnow(),
            )
        )
    db.add(
        QuarantineEvent(
            org_id=agent.org_id,
            agent_id=agent.id,
            action="RELEASE",
            reason="Recovery checks passed",
            actor_user_id=actor_user_id,
            evidence=evidence or {},
            created_at=utcnow(),
        )
    )
    audit_service.record_event(
        db,
        event_type="containment",
        agent_id=agent.id,
        reason_codes=["AGENT_RECOVERED"],
        risk_level="MEDIUM",
        metadata={"actorUserId": actor_user_id, "evidence": evidence or {}},
        org_id=agent.org_id,
    )
    db.flush()
    return state


def check_operational_gate(
    db: Session, *, agent: Agent, tool_name: str
) -> dict[str, Any]:
    """Return a fail-closed gate for quarantine and circuit-breaker state."""
    settings = get_settings()
    state = get_or_create_state(db, agent)
    if state.operational_status == "QUARANTINED":
        return {
            "allowed": False,
            "reason_code": "AGENT_QUARANTINED",
            "detail": state.quarantine_reason or "Agent is quarantined",
            "operational_status": state.operational_status,
            "circuit_state": "OPEN",
        }

    circuit = get_or_create_circuit(db, agent, tool_name)
    if circuit.state == "CLOSED":
        return {
            "allowed": True,
            "operational_status": state.operational_status,
            "circuit_state": "CLOSED",
        }

    if circuit.state == "OPEN":
        opened = _parse(circuit.opened_at)
        cooldown = timedelta(seconds=settings.circuit_open_seconds)
        if opened and datetime.now(timezone.utc) - opened >= cooldown:
            result = db.execute(
                update(CircuitBreaker)
                .where(
                    CircuitBreaker.id == circuit.id,
                    CircuitBreaker.state == "OPEN",
                )
                .values(state="HALF_OPEN", half_open_at=utcnow(), updated_at=utcnow())
            )
            if result.rowcount == 1:
                db.flush()
                return {
                    "allowed": True,
                    "operational_status": state.operational_status,
                    "circuit_state": "HALF_OPEN",
                    "trial": True,
                }
        return {
            "allowed": False,
            "reason_code": "CIRCUIT_BREAKER_OPEN",
            "detail": "Circuit breaker is open after repeated failures",
            "operational_status": state.operational_status,
            "circuit_state": "OPEN",
        }

    # HALF_OPEN: allow a single trial; the caller records success/failure.
    return {
        "allowed": True,
        "operational_status": state.operational_status,
        "circuit_state": "HALF_OPEN",
        "trial": True,
    }


def record_trial_success(db: Session, *, agent: Agent, tool_name: str) -> None:
    circuit = get_or_create_circuit(db, agent, tool_name)
    if circuit.state != "CLOSED":
        db.execute(
            update(CircuitBreaker)
            .where(CircuitBreaker.id == circuit.id)
            .values(
                state="CLOSED",
                failure_count=0,
                opened_at=None,
                half_open_at=None,
                updated_at=utcnow(),
            )
        )
        db.flush()
        state = get_or_create_state(db, agent)
        db.execute(
            update(AgentState)
            .where(AgentState.agent_id == agent.id)
            .values(consecutive_successes=AgentState.consecutive_successes + 1)
        )
        db.flush()


def pause_workflow(
    db: Session, *, workflow_execution: WorkflowExecution, actor_user_id: str, reason: str
) -> WorkflowExecution:
    workflow_execution.status = "PAUSED"
    workflow_execution.metadata_json = {
        **(workflow_execution.metadata_json or {}),
        "pauseReason": reason,
        "pausedBy": actor_user_id,
    }
    db.flush()
    audit_service.record_event(
        db,
        event_type="containment",
        agent_id=None,
        reason_codes=["WORKFLOW_PAUSED"],
        risk_level="HIGH",
        metadata={
            "workflowExecutionId": workflow_execution.id,
            "actorUserId": actor_user_id,
            "reason": reason,
        },
        org_id=workflow_execution.org_id,
    )
    return workflow_execution


def resume_workflow(
    db: Session, *, workflow_execution: WorkflowExecution, actor_user_id: str
) -> WorkflowExecution:
    if workflow_execution.status != "PAUSED":
        raise ConflictError("Workflow execution is not paused")
    workflow_execution.status = "RUNNING"
    db.flush()
    audit_service.record_event(
        db,
        event_type="containment",
        agent_id=None,
        reason_codes=["WORKFLOW_RESUMED"],
        risk_level="MEDIUM",
        metadata={
            "workflowExecutionId": workflow_execution.id,
            "actorUserId": actor_user_id,
        },
        org_id=workflow_execution.org_id,
    )
    return workflow_execution
