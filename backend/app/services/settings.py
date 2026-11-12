"""Workspace settings persistence."""

from sqlalchemy.orm import Session

from ..models import Settings
from ..schemas import SettingsOut, SettingsUpdate

DEFAULT_SETTINGS = {
    "workspace_name": "AgentGuard Workspace",
    "default_environment": "prod",
    "approval_ttl_minutes": 240,
    "retention_days": 90,
    "redact_secrets": True,
    "redact_fields": ["password", "token", "api_key", "authorization", "body"],
    "require_approval_for": ["HIGH", "CRITICAL"],
    "max_payload_bytes": 65536,
}


def get_or_create(db: Session) -> Settings:
    row = db.get(Settings, "1")
    if row is None:
        row = Settings(id="1", **DEFAULT_SETTINGS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update(db: Session, patch: SettingsUpdate) -> Settings:
    row = get_or_create(db)
    data = patch.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in data.items():
        if key == "redact_secrets":
            setattr(row, key, 1 if value else 0)
        else:
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def to_out(row: Settings) -> SettingsOut:
    return SettingsOut(
        workspace_name=row.workspace_name,
        default_environment=row.default_environment,
        approval_ttl_minutes=row.approval_ttl_minutes,
        retention_days=row.retention_days,
        redact_secrets=bool(row.redact_secrets),
        redact_fields=list(row.redact_fields or []),
        require_approval_for=list(row.require_approval_for or []),
        max_payload_bytes=row.max_payload_bytes,
    )
