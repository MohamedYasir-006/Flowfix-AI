"""Saga-inspired transaction integrity.

The manager does not execute external tools. It records intent, enforces
idempotency, tracks partial failure, and gates compensation actions. A
compensation is a new external operation, not a true rollback, so it requires
explicit policy/authorization and is never fired blindly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ConflictError, NotFoundError
from ..models import (
    CompensationAction,
    Transaction,
    TransactionStep,
    WorkflowExecution,
    utcnow,
)
from ..schemas_v2 import TransactionCreate
from . import audit as audit_service

FINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}


def _get(db: Session, org_id: str, transaction_id: str) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.org_id != org_id:
        raise NotFoundError("Transaction not found")
    return transaction


def _steps(db: Session, transaction_id: str) -> list[TransactionStep]:
    return list(
        db.execute(
            select(TransactionStep)
            .where(TransactionStep.transaction_id == transaction_id)
            .order_by(TransactionStep.sequence.asc())
        ).scalars()
    )


def transaction_out(db: Session, transaction: Transaction) -> dict[str, Any]:
    steps = _steps(db, transaction.id)
    return {
        "id": transaction.id,
        "workflow_execution_id": transaction.workflow_execution_id,
        "status": transaction.status,
        "idempotency_key": transaction.idempotency_key,
        "created_at": transaction.created_at,
        "updated_at": transaction.updated_at,
        "steps": [
            {
                "id": step.id,
                "transaction_id": step.transaction_id,
                "step_key": step.step_key,
                "sequence": step.sequence,
                "tool_name": step.tool_name,
                "status": step.status,
                "action_id": step.action_id,
                "idempotency_key": step.idempotency_key,
                "compensation_tool": step.compensation_tool,
                "compensation_status": step.compensation_status,
                "attempts": step.attempts,
                "last_error": step.last_error,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "created_at": step.created_at,
            }
            for step in steps
        ],
    }


def create_transaction(
    db: Session, *, org_id: str, input: TransactionCreate
) -> tuple[Transaction, bool]:
    """Create a transaction. Returns (transaction, created_now)."""
    if input.idempotency_key:
        existing = db.execute(
            select(Transaction).where(
                Transaction.org_id == org_id,
                Transaction.idempotency_key == input.idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

    if input.workflow_execution_id:
        execution = db.get(WorkflowExecution, input.workflow_execution_id)
        if execution is None or execution.org_id != org_id:
            raise NotFoundError("Workflow execution not found")

    keys = [step.step_key for step in input.steps]
    if len(keys) != len(set(keys)):
        raise ConflictError(
            "Duplicate step_key in transaction", reason_codes=["DUPLICATE_STEP_KEY"]
        )

    transaction = Transaction(
        org_id=org_id,
        workflow_execution_id=input.workflow_execution_id,
        status="CREATED",
        idempotency_key=input.idempotency_key,
        metadata_json=input.metadata,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(transaction)
    db.flush()

    for index, step_input in enumerate(input.steps):
        db.add(
            TransactionStep(
                transaction_id=transaction.id,
                org_id=org_id,
                step_key=step_input.step_key,
                sequence=index,
                tool_name=step_input.tool_name,
                status="PENDING",
                idempotency_key=f"{transaction.id}:{step_input.step_key}",
                compensation_tool=step_input.compensation_tool,
                max_attempts=step_input.max_attempts,
                created_at=utcnow(),
            )
        )
    db.flush()
    audit_service.record_event(
        db,
        event_type="transaction",
        reason_codes=["TRANSACTION_CREATED"],
        risk_level="MEDIUM",
        metadata={
            "transactionId": transaction.id,
            "workflowExecutionId": transaction.workflow_execution_id,
            "steps": keys,
        },
        org_id=org_id,
    )
    return transaction, True


def _find_step(
    db: Session, transaction: Transaction, step_ref: str
) -> TransactionStep:
    step = db.get(TransactionStep, step_ref)
    if step is not None and step.transaction_id == transaction.id:
        return step
    step = db.execute(
        select(TransactionStep).where(
            TransactionStep.transaction_id == transaction.id,
            TransactionStep.step_key == step_ref,
        )
    ).scalar_one_or_none()
    if step is None:
        raise NotFoundError("Transaction step not found")
    return step


def start_step(
    db: Session, *, transaction: Transaction, step_ref: str, action_id: str | None = None
) -> TransactionStep:
    if transaction.status in FINAL_STATES:
        raise ConflictError("Transaction is already final")
    step = _find_step(db, transaction, step_ref)

    if step.status == "COMPLETED":
        # Idempotent replay: the external effect already happened exactly once.
        return step
    if step.status == "RUNNING":
        raise ConflictError(
            "Step is already running; refusing a duplicate external operation",
            reason_codes=["DUPLICATE_STEP_IN_PROGRESS"],
        )
    if step.attempts >= step.max_attempts:
        raise ConflictError(
            "Step retry budget exhausted", reason_codes=["RETRY_BUDGET_EXHAUSTED"]
        )

    result = db.execute(
        update(TransactionStep)
        .where(
            TransactionStep.id == step.id,
            TransactionStep.status.in_(["PENDING", "FAILED"]),
            TransactionStep.attempts < TransactionStep.max_attempts,
        )
        .values(
            status="RUNNING",
            attempts=TransactionStep.attempts + 1,
            started_at=utcnow(),
            action_id=action_id or step.action_id,
        )
    )
    if result.rowcount != 1:
        raise ConflictError(
            "Step state changed concurrently", reason_codes=["STEP_STATE_CONFLICT"]
        )
    db.execute(
        update(Transaction)
        .where(Transaction.id == transaction.id)
        .values(status="RUNNING", updated_at=utcnow())
    )
    db.flush()
    db.refresh(step)
    db.refresh(transaction)
    audit_service.record_event(
        db,
        event_type="transaction",
        action_id=action_id,
        reason_codes=["TRANSACTION_STEP_STARTED"],
        risk_level="MEDIUM",
        metadata={
            "transactionId": transaction.id,
            "stepId": step.id,
            "stepKey": step.step_key,
            "attempt": step.attempts,
        },
        org_id=transaction.org_id,
    )
    return step


def complete_step(
    db: Session,
    *,
    transaction: Transaction,
    step_ref: str,
    success: bool,
    action_id: str | None = None,
    error: str | None = None,
) -> TransactionStep:
    step = _find_step(db, transaction, step_ref)
    if step.status == "COMPLETED":
        return step
    if step.status != "RUNNING":
        raise ConflictError(
            "Step is not running", reason_codes=["STEP_NOT_RUNNING"]
        )

    new_status = "COMPLETED" if success else "FAILED"
    db.execute(
        update(TransactionStep)
        .where(TransactionStep.id == step.id, TransactionStep.status == "RUNNING")
        .values(
            status=new_status,
            completed_at=utcnow(),
            last_error=None if success else (error or "step failed"),
            action_id=action_id or step.action_id,
        )
    )
    db.flush()
    db.refresh(step)

    steps = _steps(db, transaction.id)
    if not success:
        partial = any(other.status == "COMPLETED" for other in steps)
        transaction.status = "RECOVERY_REQUIRED" if partial else "FAILED"
    elif all(other.status == "COMPLETED" for other in steps):
        transaction.status = "COMPLETED"
    else:
        transaction.status = "RUNNING"
    transaction.updated_at = utcnow()
    db.flush()

    audit_service.record_event(
        db,
        event_type="transaction",
        action_id=action_id or step.action_id,
        reason_codes=[
            "TRANSACTION_STEP_COMPLETED" if success else "TRANSACTION_STEP_FAILED"
        ],
        risk_level="LOW" if success else "HIGH",
        metadata={
            "transactionId": transaction.id,
            "stepId": step.id,
            "stepKey": step.step_key,
            "error": error,
            "transactionStatus": transaction.status,
        },
        org_id=transaction.org_id,
    )
    return step


def request_compensation(
    db: Session, *, transaction: Transaction, reason: str, approved: bool
) -> Transaction:
    if transaction.status not in (
        "RECOVERY_REQUIRED",
        "FAILED",
        "COMPLETED",
        "WAITING_APPROVAL",
    ):
        raise ConflictError(
            "Compensation is only allowed for failed, partially completed, or explicitly completed transactions",
            reason_codes=["COMPENSATION_NOT_ALLOWED"],
        )
    steps = _steps(db, transaction.id)
    compensable = [
        step for step in steps if step.status == "COMPLETED" and step.compensation_tool
    ]
    if not compensable:
        raise ConflictError(
            "No completed step has a configured compensation action",
            reason_codes=["NO_COMPENSABLE_STEPS"],
        )

    settings = get_settings()
    requires_approval = bool(settings.transaction_compensation_requires_approval) and not approved
    if requires_approval:
        transaction.status = "WAITING_APPROVAL"
        for step in compensable:
            step.compensation_status = "PENDING"
            existing = db.execute(
                select(CompensationAction).where(
                    CompensationAction.transaction_id == transaction.id,
                    CompensationAction.step_id == step.id,
                    CompensationAction.status == "PENDING",
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    CompensationAction(
                        org_id=transaction.org_id,
                        transaction_id=transaction.id,
                        step_id=step.id,
                        tool_name=step.compensation_tool or "",
                        action_id=step.action_id,
                        status="PENDING",
                        reason=reason,
                        created_at=utcnow(),
                    )
                )
    else:
        transaction.status = "COMPENSATING"
        for step in compensable:
            if step.compensation_status == "COMPLETED":
                continue
            step.compensation_status = "APPROVED"
            pending = db.execute(
                select(CompensationAction).where(
                    CompensationAction.transaction_id == transaction.id,
                    CompensationAction.step_id == step.id,
                    CompensationAction.status == "PENDING",
                )
            ).scalar_one_or_none()
            if pending is not None:
                pending.status = "APPROVED"
                pending.reason = reason
                continue
            db.add(
                CompensationAction(
                    org_id=transaction.org_id,
                    transaction_id=transaction.id,
                    step_id=step.id,
                    tool_name=step.compensation_tool or "",
                    action_id=step.action_id,
                    status="APPROVED",
                    reason=reason,
                    created_at=utcnow(),
                )
            )
    transaction.updated_at = utcnow()
    db.flush()
    audit_service.record_event(
        db,
        event_type="transaction",
        reason_codes=[
            "COMPENSATION_AWAITING_APPROVAL"
            if requires_approval
            else "COMPENSATION_APPROVED"
        ],
        risk_level="HIGH",
        metadata={
            "transactionId": transaction.id,
            "reason": reason,
            "status": transaction.status,
        },
        org_id=transaction.org_id,
    )
    return transaction


def complete_compensation(
    db: Session, *, transaction: Transaction, step_ref: str, success: bool, error: str | None = None
) -> TransactionStep:
    step = _find_step(db, transaction, step_ref)
    if step.compensation_status not in ("PENDING", "APPROVED"):
        raise ConflictError("Step is not in a compensable state")
    step.compensation_status = "COMPLETED" if success else "FAILED"
    action = db.execute(
        select(CompensationAction).where(
            CompensationAction.transaction_id == transaction.id,
            CompensationAction.step_id == step.id,
            CompensationAction.status.in_(["PENDING", "APPROVED"]),
        )
    ).scalars().first()
    if action:
        action.status = "EXECUTED" if success else "FAILED"
        action.completed_at = utcnow()
    if success:
        step.status = "COMPENSATED"
    else:
        step.last_error = error or "compensation failed"

    steps = _steps(db, transaction.id)
    remaining = [
        s for s in steps if s.status == "COMPLETED" and s.compensation_tool
    ]
    if any(s.compensation_status == "FAILED" for s in steps):
        transaction.status = "RECOVERY_REQUIRED"
    elif not remaining:
        transaction.status = "COMPLETED"
    transaction.updated_at = utcnow()
    db.flush()
    audit_service.record_event(
        db,
        event_type="transaction",
        reason_codes=[
            "COMPENSATION_COMPLETED" if success else "COMPENSATION_FAILED"
        ],
        risk_level="MEDIUM" if success else "CRITICAL",
        metadata={
            "transactionId": transaction.id,
            "stepId": step.id,
            "stepKey": step.step_key,
            "error": error,
        },
        org_id=transaction.org_id,
    )
    return step


def recovery_plan(db: Session, transaction: Transaction) -> dict[str, Any]:
    steps = _steps(db, transaction.id)
    completed = [s for s in steps if s.status == "COMPLETED"]
    failed = [s for s in steps if s.status == "FAILED"]
    pending = [s for s in steps if s.status in ("PENDING", "RUNNING")]
    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "failed_steps": [s.step_key for s in failed],
        "completed_steps": [s.step_key for s in completed],
        "pending_steps": [s.step_key for s in pending],
        "compensation_candidates": [
            {"step": s.step_key, "tool": s.compensation_tool}
            for s in completed
            if s.compensation_tool
        ],
        "requires_approval": bool(get_settings().transaction_compensation_requires_approval),
        "note": (
            "Compensation is a new external operation, not a guaranteed rollback. "
            "It must be approved and executed explicitly."
        ),
    }
