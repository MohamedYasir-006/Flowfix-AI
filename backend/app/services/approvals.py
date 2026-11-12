"""Approval state machine: create, expire, decide, and consume approvals."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Approval, utcnow
from ..schemas import ApprovalDecision
from .audit import record_event


def _parse(ts: str) -> datetime:
    value = datetime.fromisoformat(ts)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def expiry_from_now(settings) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=settings.approval_ttl_minutes)).isoformat()


def create_approval(
    db: Session,
    *,
    agent_id: str,
    action_id: str,
    tool_name: str,
    target: str,
    payload_hash: str,
    arguments_summary: dict[str, Any],
    risk_level: str,
    policy_id: str | None,
    policy_version: int,
    rule_id: str | None,
    reason: str,
    settings,
) -> Approval:
    approval = Approval(
        action_id=action_id,
        payload_hash=payload_hash,
        requested_by_agent_id=agent_id,
        status="PENDING",
        expires_at=expiry_from_now(settings),
        reason=reason,
        tool_name=tool_name,
        target=target or "",
        arguments_summary=arguments_summary,
        risk_level=risk_level,
        policy_id=policy_id,
        policy_version=policy_version,
        rule_id=rule_id,
        created_at=utcnow(),
    )
    db.add(approval)
    db.flush()

    record_event(
        db,
        event_type="approval",
        action_id=action_id,
        agent_id=agent_id,
        tool_name=tool_name,
        decision="REQUIRE_APPROVAL",
        risk_level=risk_level,
        reason_codes=["APPROVAL_CREATED"],
        policy_version=policy_version,
        metadata={"approvalId": approval.id, "expiresAt": approval.expires_at},
        created_at=approval.created_at,
    )
    return approval


def list_approvals(db: Session, status: str | None = None) -> list[Approval]:
    expire_overdue(db)
    query = select(Approval)
    if status:
        query = query.where(Approval.status == status)
    query = query.order_by(Approval.created_at.desc())
    return list(db.execute(query).scalars())


def get_approval(db: Session, approval_id: str) -> Approval | None:
    expire_overdue(db)
    return db.get(Approval, approval_id)


def expire_overdue(db: Session) -> int:
    """Mark pending approvals past their expiry as EXPIRED. Returns the count."""
    now = datetime.now(timezone.utc)
    pending = db.execute(
        select(Approval).where(Approval.status == "PENDING")
    ).scalars().all()
    expired_ids: list[str] = []
    for approval in pending:
        if _parse(approval.expires_at) < now:
            expired_ids.append(approval.id)
    if not expired_ids:
        return 0

    db.execute(
        update(Approval).where(Approval.id.in_(expired_ids)).values(status="EXPIRED")
    )
    for approval_id in expired_ids:
        approval = db.get(Approval, approval_id)
        record_event(
            db,
            event_type="approval",
            action_id=approval.action_id,
            agent_id=approval.requested_by_agent_id,
            tool_name=approval.tool_name,
            decision="REQUIRE_APPROVAL",
            risk_level=approval.risk_level,
            reason_codes=["APPROVAL_EXPIRED"],
            policy_version=approval.policy_version,
            metadata={"approvalId": approval.id},
        )
    db.commit()
    return len(expired_ids)


def decide(
    db: Session,
    approval: Approval,
    approver_user_id: str,
    decision: ApprovalDecision,
) -> Approval:
    """Approve or reject a pending approval. Caller must validate authorization."""
    if approval.status == "EXPIRED" or _parse(approval.expires_at) < datetime.now(timezone.utc):
        approval.status = "EXPIRED"
        db.commit()
        raise ValueError("Approval has expired")
    if approval.status != "PENDING":
        raise ValueError(f"Approval is already {approval.status.lower()}")

    approval.status = decision.decision
    approval.approver_user_id = approver_user_id
    approval.decided_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="approval",
        action_id=approval.action_id,
        agent_id=approval.requested_by_agent_id,
        tool_name=approval.tool_name,
        decision="REQUIRE_APPROVAL",
        risk_level=approval.risk_level,
        reason_codes=[
            "APPROVAL_GRANTED" if decision.decision == "APPROVED" else "APPROVAL_REJECTED"
        ],
        policy_version=approval.policy_version,
        metadata={
            "approvalId": approval.id,
            "approverUserId": approver_user_id,
            "reason": decision.reason,
        },
    )
    db.commit()
    db.refresh(approval)
    return approval


def consume(db: Session, approval: Approval) -> bool:
    """Atomically mark an approved approval as consumed. False if not possible."""
    result = db.execute(
        update(Approval)
        .where(Approval.id == approval.id, Approval.status == "APPROVED")
        .values(status="CONSUMED")
    )
    return result.rowcount == 1
