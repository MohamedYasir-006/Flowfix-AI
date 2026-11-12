"""Policy management endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import ConflictError, NotFoundError
from ..models import User
from ..schemas import PolicyCreate, PolicyOut, PolicyUpdate
from ..services import policies as policies_service

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=list[PolicyOut])
def list_policies(db: Session = Depends(get_db)) -> list[PolicyOut]:
    return [PolicyOut.model_validate(policy) for policy in policies_service.list_policies(db)]


@router.post("", response_model=PolicyOut, status_code=201)
def create_policy(
    input: PolicyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut:
    return PolicyOut.model_validate(policies_service.create_policy(db, input, user.id))


@router.get("/{policy_id}", response_model=PolicyOut)
def get_policy(policy_id: str, db: Session = Depends(get_db)) -> PolicyOut:
    policy = policies_service.get_policy(db, policy_id)
    if policy is None:
        raise NotFoundError("Policy not found")
    return PolicyOut.model_validate(policy)


@router.put("/{policy_id}", response_model=PolicyOut)
def update_policy(
    policy_id: str,
    input: PolicyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut:
    policy = policies_service.get_policy(db, policy_id)
    if policy is None:
        raise NotFoundError("Policy not found")
    try:
        updated = policies_service.update_policy(db, policy, input, user.id)
    except ValueError as exc:
        raise ConflictError(str(exc), reason_codes=["POLICY_NOT_EDITABLE"]) from exc
    return PolicyOut.model_validate(updated)


@router.post("/{policy_id}/publish", response_model=PolicyOut)
def publish_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut:
    policy = policies_service.get_policy(db, policy_id)
    if policy is None:
        raise NotFoundError("Policy not found")
    return PolicyOut.model_validate(policies_service.publish_policy(db, policy, user.id))
