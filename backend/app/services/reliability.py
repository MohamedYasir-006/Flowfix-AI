"""Confidence-aware agent reliability scoring.

The score is deliberately transparent: every component is an observed rate with
Bayesian smoothing, the time window and observation count are reported, and
``INSUFFICIENT`` is a first-class level. A new agent with no history is never
treated as safe: it receives normal policy evaluation with an explicit warning,
not a high score or an implicit trust decision.

A reliability score can only add friction (validation/approval/quarantine). It
never overrides an explicit policy DENY.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Agent,
    AgentExecution,
    AgentState,
    Approval,
    Artifact,
    ArtifactValidation,
    AuditEvent,
    QuarantineEvent,
    ReliabilitySnapshot,
    utcnow,
)

WEIGHTS = {
    "validation_success": 0.35,
    "execution_success": 0.20,
    "policy_compliance": 0.20,
    "task_completion": 0.15,
    "recovery_success": 0.10,
}

METHODOLOGY = (
    "Score = 100 * weighted sum of smoothed component rates. Each rate uses a "
    "Beta-style prior (mean=prior_mean, strength=prior_strength) so a handful of "
    "observations cannot produce an extreme score. Weights: validation 0.35, "
    "execution success 0.20, policy compliance 0.20, task completion 0.15, "
    "recovery 0.10. Confidence = min(1, observations/30), discounted when no "
    "validation evidence exists. Level INSUFFICIENT is reported below the "
    "configured minimum observation count; it never implies trust."
)


def _smooth(successes: int, failures: int, prior_mean: float, prior_strength: float) -> float:
    return (successes + prior_mean * prior_strength) / (
        successes + failures + prior_strength
    )


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def compute_reliability(
    db: Session,
    *,
    agent: Agent,
    window_days: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    window = window_days or settings.reliability_window_days
    start = _iso_days_ago(window)

    artifacts = db.execute(
        select(Artifact).where(
            Artifact.producer_agent_id == agent.id, Artifact.created_at >= start
        )
    ).scalars().all()
    artifact_ids = [artifact.id for artifact in artifacts]

    validation_pass = 0
    validation_fail = 0
    if artifact_ids:
        validations = db.execute(
            select(ArtifactValidation).where(
                ArtifactValidation.artifact_id.in_(artifact_ids),
                ArtifactValidation.created_at >= start,
            )
        ).scalars().all()
        for row in validations:
            if row.status == "PASS":
                validation_pass += 1
            elif row.status == "FAIL":
                validation_fail += 1

    decision_events = db.execute(
        select(AuditEvent).where(
            AuditEvent.agent_id == agent.id,
            AuditEvent.event_type == "decision",
            AuditEvent.created_at >= start,
        )
    ).scalars().all()
    decision_total = len(decision_events)
    decision_denies = sum(1 for event in decision_events if event.decision == "DENY")

    execution_events = db.execute(
        select(AuditEvent).where(
            AuditEvent.agent_id == agent.id,
            AuditEvent.event_type == "execution",
            AuditEvent.created_at >= start,
        )
    ).scalars().all()
    execution_total = len(execution_events)
    execution_success = sum(
        1 for event in execution_events if (event.redacted_metadata or {}).get("success") is True
    )

    agent_executions = db.execute(
        select(AgentExecution).where(
            AgentExecution.agent_id == agent.id, AgentExecution.started_at >= start
        )
    ).scalars().all()
    task_total = len(agent_executions)
    task_completed = sum(1 for row in agent_executions if row.status == "COMPLETED")

    approvals = db.execute(
        select(Approval).where(
            Approval.requested_by_agent_id == agent.id,
            Approval.decided_at.isnot(None),
            Approval.decided_at >= start,
        )
    ).scalars().all()
    approval_total = len(approvals)
    approval_rejected = sum(1 for row in approvals if row.status == "REJECTED")

    quarantine_events = db.execute(
        select(QuarantineEvent).where(
            QuarantineEvent.agent_id == agent.id, QuarantineEvent.created_at >= start
        )
    ).scalars().all()
    quarantine_total = len(quarantine_events)
    releases = sum(1 for row in quarantine_events if row.action == "RELEASE")

    prior_mean = settings.reliability_prior_mean
    prior_strength = settings.reliability_prior_strength

    validation_success = _smooth(validation_pass, validation_fail, prior_mean, prior_strength)
    execution_success_rate = _smooth(
        execution_success, execution_total - execution_success, prior_mean, prior_strength
    )
    policy_compliance = _smooth(
        decision_total - decision_denies, decision_denies, 0.9, prior_strength
    )
    task_completion = _smooth(
        task_completed, task_total - task_completed, prior_mean, prior_strength
    )
    recovery_success = _smooth(releases, quarantine_total - releases, 0.75, prior_strength)

    components = {
        "validation_success": validation_success,
        "execution_success": execution_success_rate,
        "policy_compliance": policy_compliance,
        "task_completion": task_completion,
        "recovery_success": recovery_success,
    }
    score = 100 * sum(components[key] * WEIGHTS[key] for key in WEIGHTS)

    observations = (
        validation_pass
        + validation_fail
        + decision_total
        + execution_total
        + task_total
        + quarantine_total
    )
    confidence = min(1.0, observations / 30.0)
    coverage = sum(
        [
            1 if validation_pass + validation_fail else 0,
            1 if decision_total else 0,
            1 if execution_total else 0,
            1 if task_total else 0,
        ]
    ) / 4
    confidence = round(confidence * (0.6 + 0.4 * coverage), 4)

    if observations < settings.reliability_min_observations:
        level = "INSUFFICIENT"
    elif score >= settings.reliability_high_threshold:
        level = "HIGH"
    elif score >= settings.reliability_medium_threshold:
        level = "MEDIUM"
    elif score >= 40:
        level = "LOW"
    else:
        level = "CRITICAL"

    state = db.get(AgentState, agent.id)
    if state and state.operational_status == "QUARANTINED":
        level = "CRITICAL"

    previous = db.execute(
        select(ReliabilitySnapshot)
        .where(ReliabilitySnapshot.agent_id == agent.id)
        .order_by(ReliabilitySnapshot.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if previous is None:
        trend = "NO_HISTORY"
    elif score - previous.score >= 2:
        trend = "IMPROVING"
    elif previous.score - score >= 2:
        trend = "DEGRADING"
    else:
        trend = "STABLE"

    metrics = {
        "validation": {
            "passes": validation_pass,
            "failures": validation_fail,
            "rate": round(validation_success, 4),
            "weight": WEIGHTS["validation_success"],
        },
        "policy": {
            "decisions": decision_total,
            "denies": decision_denies,
            "compliance_rate": round(policy_compliance, 4),
            "weight": WEIGHTS["policy_compliance"],
        },
        "execution": {
            "executions": execution_total,
            "successes": execution_success,
            "success_rate": round(execution_success_rate, 4),
            "weight": WEIGHTS["execution_success"],
        },
        "tasks": {
            "total": task_total,
            "completed": task_completed,
            "completion_rate": round(task_completion, 4),
            "weight": WEIGHTS["task_completion"],
        },
        "approvals": {"decided": approval_total, "rejected": approval_rejected},
        "recovery": {
            "quarantine_events": quarantine_total,
            "releases": releases,
            "rate": round(recovery_success, 4),
            "weight": WEIGHTS["recovery_success"],
        },
        "components": {key: round(value, 4) for key, value in components.items()},
    }

    factors: list[str] = []
    if validation_pass + validation_fail == 0:
        factors.append("No validation evidence in the window; confidence discounted.")
    elif validation_fail:
        factors.append(f"{validation_fail} artifact validation failure(s) in {window} days.")
    if decision_denies:
        factors.append(f"{decision_denies} policy denial(s) out of {decision_total} decisions.")
    if execution_total - execution_success:
        factors.append(f"{execution_total - execution_success} tool execution failure(s).")
    if approval_rejected:
        factors.append(f"{approval_rejected} human-rejected approval request(s).")
    if quarantine_total and not releases:
        factors.append("Containment events without a successful recovery.")
    if not factors:
        factors.append("All observed components are within their expected ranges.")

    result = {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "score": round(score, 2),
        "confidence": confidence,
        "level": level,
        "observations": observations,
        "window_days": window,
        "metrics": metrics,
        "contributing_factors": factors,
        "trend": trend,
        "methodology": METHODOLOGY,
        "computed_at": utcnow(),
    }

    if persist:
        db.add(
            ReliabilitySnapshot(
                org_id=agent.org_id,
                agent_id=agent.id,
                window_days=window,
                observations=observations,
                score=result["score"],
                confidence=confidence,
                level=level,
                metrics=metrics,
                created_at=result["computed_at"],
            )
        )
        db.flush()

    return result
