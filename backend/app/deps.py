"""FastAPI dependencies: agent authentication and dashboard user resolution."""

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import ForbiddenError, UnauthorizedError
from .models import Agent, User
from .ratelimit import RateLimiter, check_rate_limit
from .security import verify_access_token


def get_current_agent(
    request: Request,
    db: Session = Depends(get_db),
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
) -> Agent:
    """Authenticate an agent from its API key. Fails closed.

    Successful authentication is also subject to the per-agent decision rate
    limit, so a compromised or runaway agent cannot flood the policy engine.
    """
    from .services import agents as agents_service

    agent = agents_service.authenticate(db, x_agent_key)
    if agent is None:
        raise UnauthorizedError("Missing or invalid agent API key")

    limiter: RateLimiter | None = getattr(request.app.state, "agent_decision_limiter", None)
    if limiter is not None:
        check_rate_limit(limiter, request, identifier=f"agent:{agent.id}")
    return agent


def get_token_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Return the token's user when a valid bearer token is present."""
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    user_id = verify_access_token(header[7:].strip())
    if not user_id:
        return None
    return db.get(User, user_id)


def get_current_user(
    user: User | None = Depends(get_token_user),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the acting dashboard user.

    When ``AGENTGUARD_AUTH_REQUIRED`` is false (local development) and no token
    is supplied, the seeded admin is used so the console works out of the box.
    """
    settings = get_settings()
    if settings.auth_required:
        if user is None:
            raise UnauthorizedError("A valid bearer token is required")
        return user
    if user is None:
        user = db.query(User).filter(User.role == "ADMIN").first()
        if user is None:
            raise UnauthorizedError("No admin user is available")
    return user


def resolve_approver(
    db: Session,
    user: User | None,
    requested_user_id: str | None,
) -> User:
    """Resolve and authorize the approver for an approval decision."""
    settings = get_settings()
    approver: User | None

    if settings.auth_required:
        if user is None:
            raise UnauthorizedError("A valid bearer token is required")
        approver = user
    else:
        approver = None
        if requested_user_id:
            approver = db.get(User, requested_user_id)
            if approver is None:
                raise ForbiddenError("Unknown approver")
        else:
            approver = db.query(User).filter(User.role == "APPROVER").first()

    if approver is None or approver.status != "ACTIVE":
        raise ForbiddenError("Only an active authorized approver can decide")
    if approver.role not in ("APPROVER", "ADMIN"):
        raise ForbiddenError("User role is not permitted to approve actions")
    return approver


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "ADMIN":
        raise ForbiddenError("Administrator role required")
    return user
