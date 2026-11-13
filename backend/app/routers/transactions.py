"""Saga transaction integrity endpoints.

The API records intent and state transitions. It never executes a tool or
compensation action itself; external execution belongs to the agent runtime.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (
    get_current_agent,
    get_org_id,
    require_admin_or_approver,
)
from ..errors import NotFoundError
from ..models import Agent, Transaction, User
from ..schemas_v2 import (
    CompensationRequest,
    StepCompleteRequest,
    StepStartRequest,
    TransactionCreate,
    TransactionOut,
)
from ..services import transactions as transaction_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _require(db: Session, org_id: str, transaction_id: str) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.org_id != org_id:
        raise NotFoundError("Transaction not found")
    return transaction


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(
    input: TransactionCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    transaction, _ = transaction_service.create_transaction(
        db, org_id=agent.org_id, input=input
    )
    db.commit()
    db.refresh(transaction)
    return transaction_service.transaction_out(db, transaction)


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    workflow_execution_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    query = select(Transaction).where(Transaction.org_id == org_id)
    if workflow_execution_id:
        query = query.where(Transaction.workflow_execution_id == workflow_execution_id)
    if status:
        query = query.where(Transaction.status == status)
    query = query.order_by(Transaction.created_at.desc()).limit(max(1, min(limit, 500)))
    return [
        transaction_service.transaction_out(db, transaction)
        for transaction in db.execute(query).scalars()
    ]


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    transaction = _require(db, org_id, transaction_id)
    return transaction_service.transaction_out(db, transaction)


@router.get("/{transaction_id}/recovery-plan")
def recovery_plan(
    transaction_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    transaction = _require(db, org_id, transaction_id)
    return transaction_service.recovery_plan(db, transaction)


@router.post("/{transaction_id}/steps/{step_ref}/start", response_model=TransactionOut)
def start_step(
    transaction_id: str,
    step_ref: str,
    input: StepStartRequest | None = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    transaction = _require(db, agent.org_id, transaction_id)
    transaction_service.start_step(
        db,
        transaction=transaction,
        step_ref=step_ref,
        action_id=input.action_id if input else None,
    )
    db.commit()
    db.refresh(transaction)
    return transaction_service.transaction_out(db, transaction)


@router.post("/{transaction_id}/steps/{step_ref}/complete", response_model=TransactionOut)
def complete_step(
    transaction_id: str,
    step_ref: str,
    input: StepCompleteRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    transaction = _require(db, agent.org_id, transaction_id)
    transaction_service.complete_step(
        db,
        transaction=transaction,
        step_ref=step_ref,
        success=input.success,
        action_id=input.action_id,
        error=input.error,
    )
    db.commit()
    db.refresh(transaction)
    return transaction_service.transaction_out(db, transaction)


@router.post("/{transaction_id}/compensate", response_model=TransactionOut)
def request_compensation(
    transaction_id: str,
    input: CompensationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_approver),
):
    """Request compensation for a failed or explicitly completed transaction.

    Compensation is a new external operation. It is never automatic, and it is
    held for approval unless an authorized approver sets ``approved``.
    """
    transaction = _require(db, user.org_id, transaction_id)
    transaction_service.request_compensation(
        db, transaction=transaction, reason=input.reason, approved=input.approved
    )
    db.commit()
    db.refresh(transaction)
    return transaction_service.transaction_out(db, transaction)


@router.post(
    "/{transaction_id}/steps/{step_ref}/compensation/complete",
    response_model=TransactionOut,
)
def complete_compensation(
    transaction_id: str,
    step_ref: str,
    input: StepCompleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_approver),
):
    transaction = _require(db, user.org_id, transaction_id)
    transaction_service.complete_compensation(
        db,
        transaction=transaction,
        step_ref=step_ref,
        success=input.success,
        error=input.error,
    )
    db.commit()
    db.refresh(transaction)
    return transaction_service.transaction_out(db, transaction)
