"""Approval queue endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_token_user, resolve_approver
from ..errors import ConflictError, NotFoundError
from ..models import User
from ..schemas import ApprovalDecision, ApprovalOut
from ..services import approvals as approvals_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(status: str | None = None, db: Session = Depends(get_db)) -> list[ApprovalOut]:
    return [
        ApprovalOut.model_validate(approval)
        for approval in approvals_service.list_approvals(db, status)
    ]


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, db: Session = Depends(get_db)) -> ApprovalOut:
    approval = approvals_service.get_approval(db, approval_id)
    if approval is None:
        raise NotFoundError("Approval not found")
    return ApprovalOut.model_validate(approval)


def _decide(
    approval_id: str,
    input: ApprovalDecision,
    db: Session,
    user: User | None,
) -> ApprovalOut:
    approval = approvals_service.get_approval(db, approval_id)
    if approval is None:
        raise NotFoundError("Approval not found")
    approver = resolve_approver(db, user, input.approver_user_id)
    try:
        decided = approvals_service.decide(db, approval, approver.id, input)
    except ValueError as exc:
        raise ConflictError(str(exc), reason_codes=["APPROVAL_NOT_DECISIONABLE"]) from exc
    return ApprovalOut.model_validate(decided)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approve(
    approval_id: str,
    input: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_token_user),
) -> ApprovalOut:
    return _decide(approval_id, input, db, user)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def reject(
    approval_id: str,
    input: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_token_user),
) -> ApprovalOut:
    return _decide(approval_id, input, db, user)
