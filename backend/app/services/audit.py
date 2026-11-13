"""Append-only audit storage with an optional hash-linked chain.

Every event is written once and never updated by application code. V2 adds a
per-organization hash chain: each event stores the previous event hash and a
monotonic sequence. A checkpoint endpoint can pin the latest hash externally.

Limitations (documented, not hidden): hash chaining detects modification of
individual records when an external checkpoint is trusted. It does **not**
prevent a privileged attacker with write access from rewriting the entire
table and recomputing every hash. Stronger guarantees require external
anchoring/WORM storage.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DEFAULT_ORG_ID, AuditCheckpoint, AuditEvent, utcnow
from ..utils import canonical_json

GENESIS_HASH = "GENESIS"


def _fields(
    *,
    event_id: str,
    org_id: str,
    event_type: str,
    action_id: str | None,
    agent_id: str | None,
    session_id: str | None,
    tool_name: str | None,
    decision: str | None,
    risk_level: str | None,
    reason_codes: list[str],
    policy_id: str | None,
    policy_version: int | None,
    payload_hash: str | None,
    idempotency_key: str | None,
    metadata: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "org_id": org_id,
        "event_type": event_type,
        "action_id": action_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "decision": decision,
        "risk_level": risk_level,
        "reason_codes": reason_codes,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "payload_hash": payload_hash,
        "idempotency_key": idempotency_key,
        "metadata": metadata,
        "created_at": created_at,
    }


def compute_event_hash(fields: dict[str, Any], prev_hash: str, sequence: int) -> str:
    body = canonical_json({"event": fields, "prev_hash": prev_hash, "sequence": sequence})
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _last_chained_event(db: Session, org_id: str) -> AuditEvent | None:
    return db.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id, AuditEvent.chain_sequence.isnot(None))
        .order_by(AuditEvent.chain_sequence.desc())
        .limit(1)
    ).scalar_one_or_none()


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
    org_id: str = DEFAULT_ORG_ID,
) -> AuditEvent:
    import uuid

    event_id = str(uuid.uuid4())
    created = created_at or utcnow()
    codes = list(reason_codes or [])
    meta = metadata or {}

    last = _last_chained_event(db, org_id)
    prev_hash = last.event_hash if last and last.event_hash else GENESIS_HASH
    sequence = (last.chain_sequence or 0) + 1 if last else 1
    fields = _fields(
        event_id=event_id,
        org_id=org_id,
        event_type=event_type,
        action_id=action_id,
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        decision=decision,
        risk_level=risk_level,
        reason_codes=codes,
        policy_id=policy_id,
        policy_version=policy_version,
        payload_hash=payload_hash,
        idempotency_key=idempotency_key,
        metadata=meta,
        created_at=created,
    )
    event = AuditEvent(
        id=event_id,
        org_id=org_id,
        event_type=event_type,
        action_id=action_id,
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        decision=decision,
        risk_level=risk_level,
        reason_codes=codes,
        policy_id=policy_id,
        policy_version=policy_version,
        payload_hash=payload_hash,
        idempotency_key=idempotency_key,
        redacted_metadata=meta,
        prev_hash=prev_hash,
        event_hash=compute_event_hash(fields, prev_hash, sequence),
        chain_sequence=sequence,
        created_at=created,
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


def verify_chain(db: Session, org_id: str = DEFAULT_ORG_ID) -> dict[str, Any]:
    """Recompute the chain and report the first broken link, if any."""
    events = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id, AuditEvent.chain_sequence.isnot(None))
            .order_by(AuditEvent.chain_sequence.asc())
        ).scalars()
    )
    prev = GENESIS_HASH
    expected_sequence = 1
    for event in events:
        if event.chain_sequence != expected_sequence:
            return {
                "valid": False,
                "checked": expected_sequence - 1,
                "reason": "SEQUENCE_GAP",
                "event_id": event.id,
            }
        if (event.prev_hash or GENESIS_HASH) != prev:
            return {
                "valid": False,
                "checked": event.chain_sequence - 1,
                "reason": "PREV_HASH_MISMATCH",
                "event_id": event.id,
            }
        fields = _fields(
            event_id=event.id,
            org_id=event.org_id,
            event_type=event.event_type,
            action_id=event.action_id,
            agent_id=event.agent_id,
            session_id=event.session_id,
            tool_name=event.tool_name,
            decision=event.decision,
            risk_level=event.risk_level,
            reason_codes=list(event.reason_codes or []),
            policy_id=event.policy_id,
            policy_version=event.policy_version,
            payload_hash=event.payload_hash,
            idempotency_key=event.idempotency_key,
            metadata=event.redacted_metadata or {},
            created_at=event.created_at,
        )
        expected = compute_event_hash(fields, prev, event.chain_sequence)
        if expected != event.event_hash:
            return {
                "valid": False,
                "checked": event.chain_sequence - 1,
                "reason": "EVENT_HASH_MISMATCH",
                "event_id": event.id,
            }
        prev = event.event_hash
        expected_sequence += 1

    unchained = db.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id, AuditEvent.chain_sequence.is_(None)
        )
    ).scalars().all()
    return {
        "valid": True,
        "checked": len(events),
        "unchained_legacy_events": len(unchained),
        "last_hash": prev,
        "limitation": (
            "A valid chain proves internal consistency, not that a privileged "
            "attacker with full database access has not rewritten it. Anchor "
            "checkpoints externally for stronger evidence."
        ),
    }


def create_checkpoint(db: Session, org_id: str = DEFAULT_ORG_ID) -> AuditCheckpoint:
    last = _last_chained_event(db, org_id)
    if last is None:
        raise ValueError("No chained audit events available for a checkpoint")
    count = db.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id, AuditEvent.chain_sequence.isnot(None)
        )
    ).scalars().all()
    checkpoint = AuditCheckpoint(
        org_id=org_id,
        last_event_id=last.id,
        last_sequence=last.chain_sequence or 0,
        last_hash=last.event_hash or "",
        event_count=len(count),
        created_at=utcnow(),
    )
    db.add(checkpoint)
    db.flush()
    return checkpoint
