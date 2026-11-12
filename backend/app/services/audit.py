"""Append-only audit event storage."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditEvent, utcnow


def record_event(
    db: Session,
    *,
    event_type: str,
    action_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
    decision: str | None = None,
    risk_level: str | None = None,
    reason_codes: list[str] | None = None,
    policy_id: str | None = None,
    policy_version: int | None = None,
    payload_hash: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        action_id=action_id,
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        decision=decision,
        risk_level=risk_level,
        reason_codes=reason_codes or [],
        policy_id=policy_id,
        policy_version=policy_version,
        payload_hash=payload_hash,
        idempotency_key=idempotency_key,
        redacted_metadata=metadata or {},
        created_at=created_at or utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def find_event_by_idempotency_key(db: Session, key: str) -> AuditEvent | None:
    return db.execute(
        select(AuditEvent).where(AuditEvent.idempotency_key == key)
    ).scalar_one_or_none()


def find_execution_event(db: Session, action_id: str) -> AuditEvent | None:
    return db.execute(
        select(AuditEvent).where(
            AuditEvent.event_type == "execution",
            AuditEvent.action_id == action_id,
        )
    ).scalar_one_or_none()
