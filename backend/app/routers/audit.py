"""Audit chain verification, checkpoints, and tenant-scoped event export."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_org_id, require_admin
from ..models import AuditCheckpoint, AuditEvent, User
from ..services import audit as audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify")
def verify_audit_chain(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Recompute the tenant's hash chain and report the first broken link."""
    return audit_service.verify_chain(db, org_id)


@router.post("/checkpoint")
def create_audit_checkpoint(
    db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """Pin the latest chain hash. Store the returned hash externally."""
    checkpoint = audit_service.create_checkpoint(db, user.org_id)
    db.commit()
    db.refresh(checkpoint)
    return {
        "id": checkpoint.id,
        "last_event_id": checkpoint.last_event_id,
        "last_sequence": checkpoint.last_sequence,
        "last_hash": checkpoint.last_hash,
        "event_count": checkpoint.event_count,
        "created_at": checkpoint.created_at,
    }


@router.get("/checkpoints")
def list_checkpoints(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    rows = db.execute(
        select(AuditCheckpoint)
        .where(AuditCheckpoint.org_id == org_id)
        .order_by(AuditCheckpoint.created_at.desc())
        .limit(200)
    ).scalars()
    return [
        {
            "id": row.id,
            "last_event_id": row.last_event_id,
            "last_sequence": row.last_sequence,
            "last_hash": row.last_hash,
            "event_count": row.event_count,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/events")
def export_events(
    event_type: str | None = None,
    decision: str | None = None,
    agent_id: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Tenant-scoped audit export using the same redacted records the chain covers."""
    query = select(AuditEvent).where(AuditEvent.org_id == org_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if decision:
        query = query.where(AuditEvent.decision == decision)
    if agent_id:
        query = query.where(AuditEvent.agent_id == agent_id)
    query = query.order_by(AuditEvent.created_at.desc()).limit(max(1, min(limit, 2000)))
    return [
        {
            "id": event.id,
            "org_id": event.org_id,
            "event_type": event.event_type,
            "action_id": event.action_id,
            "agent_id": event.agent_id,
            "session_id": event.session_id,
            "tool_name": event.tool_name,
            "decision": event.decision,
            "risk_level": event.risk_level,
            "reason_codes": event.reason_codes,
            "policy_id": event.policy_id,
            "policy_version": event.policy_version,
            "payload_hash": event.payload_hash,
            "idempotency_key": event.idempotency_key,
            "metadata": event.redacted_metadata,
            "chain_sequence": event.chain_sequence,
            "prev_hash": event.prev_hash,
            "event_hash": event.event_hash,
            "created_at": event.created_at,
        }
        for event in db.execute(query).scalars()
    ]
