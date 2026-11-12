"""SQLAlchemy models for the AgentGuard data model.

Timestamps are stored as UTC ISO-8601 strings so the same schema works on
SQLite (local development) and PostgreSQL (deployment) without timezone
conversion surprises. IDs are UUID strings for portability.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, UniqueConstraint

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_id)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False, default="")
    role = Column(String(20), nullable=False, default="DEVELOPER")
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(String(32), nullable=False, default=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(255), unique=True, nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    environment = Column(String(20), nullable=False, default="dev")
    status = Column(String(20), nullable=False, default="ACTIVE")
    credential_hash = Column(String(128), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)
    updated_at = Column(String(32), nullable=False, default=utcnow)
    last_action_at = Column(String(32), nullable=True)


class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(String(2000), nullable=False, default="")
    input_schema = Column(JSON, nullable=False, default=dict)
    category = Column(String(20), nullable=False, default="read")
    default_risk = Column(String(20), nullable=False, default="LOW")
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(String(32), nullable=False, default=utcnow)


class AgentToolPermission(Base):
    __tablename__ = "agent_tool_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool"),)

    id = Column(String(36), primary_key=True, default=new_id)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    tool_id = Column(String(36), ForeignKey("tools.id"), nullable=False)
    scopes = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow)


class Policy(Base):
    __tablename__ = "policies"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(255), nullable=False)
    description = Column(String(2000), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    rules = Column(JSON, nullable=False, default=list)
    default_effect = Column(String(20), nullable=False, default="DENY")
    status = Column(String(20), nullable=False, default="DRAFT")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)
    updated_at = Column(String(32), nullable=False, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String(36), primary_key=True, default=new_id)
    action_id = Column(String(36), unique=True, nullable=False)
    payload_hash = Column(String(128), nullable=False)
    requested_by_agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    approver_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    expires_at = Column(String(32), nullable=False)
    decided_at = Column(String(32), nullable=True)
    reason = Column(String(255), nullable=False, default="")
    tool_name = Column(String(255), nullable=False)
    target = Column(String(255), nullable=False, default="")
    arguments_summary = Column(JSON, nullable=False, default=dict)
    risk_level = Column(String(20), nullable=False, default="MEDIUM")
    policy_id = Column(String(36), nullable=True)
    policy_version = Column(Integer, nullable=False, default=1)
    rule_id = Column(String(255), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=new_id)
    event_type = Column(String(20), nullable=False)
    action_id = Column(String(36), nullable=True, index=True)
    agent_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(255), nullable=True)
    tool_name = Column(String(255), nullable=True)
    decision = Column(String(20), nullable=True)
    risk_level = Column(String(20), nullable=True)
    reason_codes = Column(JSON, nullable=False, default=list)
    policy_id = Column(String(36), nullable=True)
    policy_version = Column(Integer, nullable=True)
    payload_hash = Column(String(128), nullable=True)
    idempotency_key = Column(String(255), nullable=True, index=True)
    redacted_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)


class Settings(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("id", name="uq_settings_single_row"),)

    id = Column(String(1), primary_key=True, default="1")
    workspace_name = Column(String(255), nullable=False, default="AgentGuard Workspace")
    default_environment = Column(String(20), nullable=False, default="prod")
    approval_ttl_minutes = Column(Integer, nullable=False, default=240)
    retention_days = Column(Integer, nullable=False, default=90)
    redact_secrets = Column(Integer, nullable=False, default=1)  # SQLite boolean
    redact_fields = Column(JSON, nullable=False, default=list)
    require_approval_for = Column(JSON, nullable=False, default=list)
    max_payload_bytes = Column(Integer, nullable=False, default=65536)
