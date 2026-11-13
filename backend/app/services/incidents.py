"""Incidents, chronological replay, and isolated what-if simulation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models import (
    Agent,
    Approval,
    Artifact,
    ArtifactValidation,
    AuditEvent,
    Incident,
    RiskAssessmentRecord,
    Transaction,
    TransactionStep,
    WorkflowExecution,
    utcnow,
)
from ..schemas_v2 import IncidentReport, TimelineEntry
from .dependencies import downstream_impact


def create_incident(
    db: Session,
    *,
    org_id: str,
    workflow_execution_id: str | None,
    origin_agent_id: str | None,
    failure_type: str,
    risk_level: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
) -> Incident:
    incident = Incident(
        org_id=org_id,
        workflow_execution_id=workflow_execution_id,
        origin_agent_id=origin_agent_id,
        failure_type=failure_type,
        risk_level=risk_level,
        status="OPEN",
        summary=summary,
        evidence=evidence or {},
        created_at=utcnow(),
    )
    db.add(incident)
    db.flush()
    return incident


def list_incidents(
    db: Session, org_id: str, status: str | None = None, limit: int = 200
) -> list[Incident]:
    query = select(Incident).where(Incident.org_id == org_id)
    if status:
        query = query.where(Incident.status == status)
    query = query.order_by(Incident.created_at.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(query).scalars())


def get_incident(db: Session, org_id: str, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None or incident.org_id != org_id:
        raise NotFoundError("Incident not found")
    return incident


def resolve_incident(
    db: Session, incident: Incident, actor_user_id: str, resolution: str = ""
) -> Incident:
    incident.status = "RESOLVED"
    incident.resolved_at = utcnow()
    incident.evidence = {
        **(incident.evidence or {}),
        "resolution": resolution,
        "resolvedBy": actor_user_id,
    }
    db.flush()
    return incident


def workflow_timeline(
    db: Session, org_id: str, workflow_execution_id: str
) -> list[TimelineEntry]:
    execution = db.get(WorkflowExecution, workflow_execution_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("Workflow execution not found")

    agent_ids = {
        artifact.producer_agent_id
        for artifact in db.execute(
            select(Artifact).where(
                Artifact.org_id == org_id,
                Artifact.workflow_execution_id == workflow_execution_id,
            )
        ).scalars()
    }
    entries: list[TimelineEntry] = []

    events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.created_at.asc())
    ).scalars().all()
    for event in events:
        metadata = event.redacted_metadata or {}
        if (
            metadata.get("workflowExecutionId") == workflow_execution_id
            or (event.agent_id in agent_ids and event.created_at >= execution.started_at)
        ):
            entries.append(
                TimelineEntry(
                    timestamp=event.created_at,
                    kind=event.event_type,
                    actor=event.agent_id,
                    summary=", ".join(event.reason_codes or []) or event.event_type,
                    evidence_ref=event.id,
                    data={
                        "decision": event.decision,
                        "riskLevel": event.risk_level,
                        "toolName": event.tool_name,
                        "actionId": event.action_id,
                        "metadata": metadata,
                    },
                )
            )

    for artifact in db.execute(
        select(Artifact).where(
            Artifact.org_id == org_id,
            Artifact.workflow_execution_id == workflow_execution_id,
        )
    ).scalars():
        entries.append(
            TimelineEntry(
                timestamp=artifact.created_at,
                kind="artifact",
                actor=artifact.producer_agent_id,
                summary=f"Artifact '{artifact.name}' recorded ({artifact.validation_status})",
                evidence_ref=artifact.id,
                data={
                    "artifactType": artifact.artifact_type,
                    "integrityHash": artifact.integrity_hash,
                    "validationStatus": artifact.validation_status,
                },
            )
        )

    risk_rows = db.execute(
        select(RiskAssessmentRecord).where(
            RiskAssessmentRecord.org_id == org_id,
            RiskAssessmentRecord.workflow_execution_id == workflow_execution_id,
        )
    ).scalars().all()
    for row in risk_rows:
        entries.append(
            TimelineEntry(
                timestamp=row.created_at,
                kind="risk",
                actor=row.agent_id,
                summary=f"Risk evaluation: {row.decision} ({row.risk_level})",
                evidence_ref=row.id,
                data={
                    "triggeredRules": row.rules,
                    "evidence": row.evidence,
                    "propagation": row.propagation,
                },
            )
        )

    transactions = db.execute(
        select(Transaction).where(
            Transaction.org_id == org_id,
            Transaction.workflow_execution_id == workflow_execution_id,
        )
    ).scalars().all()
    for transaction in transactions:
        entries.append(
            TimelineEntry(
                timestamp=transaction.created_at,
                kind="transaction",
                summary=f"Transaction {transaction.status}",
                evidence_ref=transaction.id,
                data={"transactionId": transaction.id, "status": transaction.status},
            )
        )
        for step in db.execute(
            select(TransactionStep).where(TransactionStep.transaction_id == transaction.id)
        ).scalars():
            entries.append(
                TimelineEntry(
                    timestamp=step.completed_at or step.started_at or step.created_at,
                    kind="transaction_step",
                    summary=f"Step '{step.step_key}' {step.status}",
                    evidence_ref=step.id,
                    data={
                        "toolName": step.tool_name,
                        "compensationStatus": step.compensation_status,
                        "error": step.last_error,
                    },
                )
            )

    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def incident_report(db: Session, org_id: str, incident_id: str) -> IncidentReport:
    incident = get_incident(db, org_id, incident_id)
    timeline = (
        workflow_timeline(db, org_id, incident.workflow_execution_id)
        if incident.workflow_execution_id
        else []
    )
    impact = downstream_impact(
        db,
        org_id,
        agent_id=incident.origin_agent_id,
        failure_type=incident.failure_type,
    ) if incident.origin_agent_id else {
        "affected_agents": [],
        "affected_workflows": [],
        "evidence": [],
    }
    return IncidentReport(
        incident=incident,
        timeline=timeline,
        affected_agents=impact.get("affected_agents", []),
        affected_workflows=impact.get("affected_workflows", []),
        recommendation=(
            "Revalidate the origin artifact, rerun dependent agents, then release "
            "containment through the authorized recovery endpoint."
        ),
    )


def what_if(db: Session, org_id: str, action_id: str, hypothetical: str) -> dict[str, Any]:
    """Reconstruct a decision and describe the hypothetical effect.

    This is read-only: it never calls a tool, never writes a decision, and never
    changes containment state. Nondeterministic external model outputs are not
    replayed; only recorded evidence is used.
    """
    risk = db.execute(
        select(RiskAssessmentRecord).where(
            RiskAssessmentRecord.org_id == org_id,
            RiskAssessmentRecord.action_id == action_id,
        )
    ).scalar_one_or_none()
    event = db.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.action_id == action_id,
            AuditEvent.event_type == "decision",
        )
    ).scalars().first()
    if risk is None and event is None:
        raise NotFoundError("Action not found")

    actual = risk.decision if risk else (event.decision or "UNKNOWN")
    propagation = risk.propagation if risk else {}
    effect = propagation.get("effect", "NONE")
    if hypothetical == "ALLOW":
        if effect == "DENY":
            effect_text = (
                "UNSAFE_EXECUTION: the action would have executed despite a "
                "deterministic propagation denial."
            )
        elif effect == "REQUIRE_APPROVAL":
            effect_text = (
                "EXECUTED_WITHOUT_REQUIRED_REVIEW: the action would have skipped "
                "the human review required by unverified upstream information."
            )
        else:
            effect_text = "SAFE_TO_EXECUTE: no propagation violation was recorded."
    else:
        effect_text = f"NO_EXECUTION: hypothetical decision is {hypothetical}."

    return {
        "action_id": action_id,
        "actual_decision": actual,
        "hypothetical_decision": hypothetical,
        "would_execute": hypothetical == "ALLOW",
        "hypothetical_effect": effect_text,
        "evidence": {
            "riskLevel": risk.risk_level if risk else event.risk_level,
            "triggeredRules": risk.rules if risk else event.reason_codes,
            "propagation": propagation,
            "recordedDecision": actual,
        },
        "note": (
            "Simulation only. No external operation is executed and no production "
            "state is modified. Replay relies on recorded outputs; it does not "
            "recreate nondeterministic model behavior."
        ),
    }
