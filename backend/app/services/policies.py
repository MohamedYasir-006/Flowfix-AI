"""Policy management: drafts, publishing, and version history."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Policy, User, utcnow
from ..schemas import PolicyCreate, PolicyUpdate
from .audit import record_event


def list_policies(db: Session) -> list[Policy]:
    return list(db.execute(select(Policy).order_by(Policy.version.desc())).scalars())


def get_policy(db: Session, policy_id: str) -> Policy | None:
    return db.get(Policy, policy_id)


def create_policy(db: Session, input: PolicyCreate, created_by: str | None) -> Policy:
    max_version = db.execute(select(Policy.version).order_by(Policy.version.desc())).scalars().first()
    policy = Policy(
        name=input.name,
        description=input.description,
        version=(max_version or 0) + 1,
        rules=[rule.model_dump(exclude_none=True) for rule in input.rules],
        default_effect=input.default_effect,
        status="DRAFT",
        created_by=created_by,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(policy)
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{policy.id}",
        reason_codes=["POLICY_CREATED"],
        policy_id=policy.id,
        policy_version=policy.version,
        metadata={"actorUserId": created_by, "status": policy.status},
    )
    db.commit()
    db.refresh(policy)
    return policy


def update_policy(db: Session, policy: Policy, input: PolicyUpdate, actor_user_id: str | None) -> Policy:
    """Replace a draft's contents. Only drafts may be edited."""
    if policy.status != "DRAFT":
        raise ValueError("Only draft policies can be edited; publish a new version instead")

    data = input.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(policy, key, value)
    policy.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{policy.id}",
        reason_codes=["POLICY_UPDATED"],
        policy_id=policy.id,
        policy_version=policy.version,
        metadata={"actorUserId": actor_user_id, "status": policy.status},
    )
    db.commit()
    db.refresh(policy)
    return policy


def publish_policy(db: Session, policy: Policy, actor_user_id: str | None) -> Policy:
    previous_version = policy.version
    policy.status = "ACTIVE"
    policy.version += 1
    policy.updated_at = utcnow()
    db.flush()

    record_event(
        db,
        event_type="admin",
        action_id=f"act-{policy.id}",
        reason_codes=["POLICY_PUBLISHED"],
        policy_id=policy.id,
        policy_version=policy.version,
        metadata={"actorUserId": actor_user_id, "previousVersion": previous_version},
    )
    db.commit()
    db.refresh(policy)
    return policy


def creator_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.display_name if user else None
