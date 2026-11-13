"""SQLAlchemy models for the AgentGuard data model.

Timestamps are stored as UTC ISO-8601 strings so the same schema works on
SQLite (local development) and PostgreSQL (deployment) without timezone
conversion surprises. IDs are UUID strings for portability.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .db import Base

DEFAULT_ORG_ID = "org-default"


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(255), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(String(32), nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False, default="")
    role = Column(String(20), nullable=False, default="DEVELOPER")
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(String(32), nullable=False, default=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
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
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
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
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
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
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
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
    workflow_execution_id = Column(String(36), nullable=True, index=True)
    agent_execution_id = Column(String(36), nullable=True, index=True)
    input_artifact_ids = Column(JSON, nullable=False, default=list)
    risk_assessment_id = Column(String(36), nullable=True)
    consumed_at = Column(String(32), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
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
    prev_hash = Column(String(80), nullable=True)
    event_hash = Column(String(80), nullable=True, index=True)
    chain_sequence = Column(Integer, nullable=True, index=True)
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
    # V2 intelligence configuration. JSON keeps the settings row portable.
    propagation_policy = Column(JSON, nullable=False, default=dict)
    reliability_enforcement = Column(Integer, nullable=False, default=1)
    containment_threshold = Column(Integer, nullable=False, default=3)
    transaction_compensation_requires_approval = Column(Integer, nullable=False, default=1)


# ---------------------------------------------------------------------------
# V2 — workflow identity, provenance, dependency graph
# ---------------------------------------------------------------------------


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(2000), nullable=False, default="")
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, PAUSED, ARCHIVED
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow)
    updated_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_workflows_org_name", "org_id", "name"),)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(String(36), primary_key=True, default=new_id)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=False, index=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    external_key = Column(String(255), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="RUNNING")  # RUNNING, PAUSED, COMPLETED, FAILED, BLOCKED
    started_at = Column(String(32), nullable=False, default=utcnow)
    ended_at = Column(String(32), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_execution_id = Column(
        String(36), ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="RUNNING")  # RUNNING, COMPLETED, FAILED, BLOCKED
    started_at = Column(String(32), nullable=False, default=utcnow)
    ended_at = Column(String(32), nullable=True)
    error = Column(String(2000), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_execution_id = Column(
        String(36), ForeignKey("workflow_executions.id"), nullable=True, index=True
    )
    producer_agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    producer_execution_id = Column(
        String(36), ForeignKey("agent_executions.id"), nullable=True, index=True
    )
    artifact_type = Column(String(120), nullable=False, default="generic")
    name = Column(String(255), nullable=False, default="")
    content = Column(JSON, nullable=False, default=dict)
    integrity_hash = Column(String(80), nullable=False)
    validation_status = Column(String(20), nullable=False, default="UNVERIFIED", index=True)
    version = Column(Integer, nullable=False, default=1)
    parent_artifact_ids = Column(JSON, nullable=False, default=list)
    expires_at = Column(String(32), nullable=True)
    trust_metadata = Column(JSON, nullable=False, default=dict)
    validation_results = Column(JSON, nullable=False, default=list)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)
    updated_at = Column(String(32), nullable=False, default=utcnow)


class ValidationRule(Base):
    __tablename__ = "validation_rules"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=True, index=True)
    artifact_type = Column(String(120), nullable=True, index=True)
    validator = Column(String(120), nullable=False)
    rule_version = Column(String(40), nullable=False, default="1")
    config = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (
        Index(
            "ix_validation_rules_scope",
            "org_id",
            "workflow_id",
            "artifact_type",
            "validator",
        ),
    )


class ArtifactValidation(Base):
    __tablename__ = "artifact_validations"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    artifact_id = Column(String(36), ForeignKey("artifacts.id"), nullable=False, index=True)
    validator = Column(String(120), nullable=False)
    rule_version = Column(String(40), nullable=False, default="1")
    status = Column(String(20), nullable=False)
    errors = Column(JSON, nullable=False, default=list)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)


class Dependency(Base):
    __tablename__ = "dependencies"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_execution_id = Column(
        String(36), ForeignKey("workflow_executions.id"), nullable=True, index=True
    )
    source_type = Column(String(20), nullable=False)  # agent, tool, artifact, workflow
    source_id = Column(String(36), nullable=False, index=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(String(36), nullable=False, index=True)
    relationship = Column(String(20), nullable=False)  # produced, consumed, invoked, validated, depends_on
    artifact_id = Column(String(36), nullable=True, index=True)
    validation_status = Column(String(20), nullable=False, default="UNVERIFIED")
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_dependencies_edge", "workflow_execution_id", "source_id", "target_id", "relationship"),
    )


# ---------------------------------------------------------------------------
# V2 — reliability, containment, risk, incidents
# ---------------------------------------------------------------------------


class AgentState(Base):
    __tablename__ = "agent_states"

    agent_id = Column(String(36), ForeignKey("agents.id"), primary_key=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    operational_status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, DEGRADED, QUARANTINED, RECOVERING
    quarantine_reason = Column(String(500), nullable=True)
    quarantined_at = Column(String(32), nullable=True)
    validation_failure_count = Column(Integer, nullable=False, default=0)
    decision_failure_count = Column(Integer, nullable=False, default=0)
    consecutive_successes = Column(Integer, nullable=False, default=0)
    last_failure_at = Column(String(32), nullable=True)
    updated_at = Column(String(32), nullable=False, default=utcnow)


class CircuitBreaker(Base):
    __tablename__ = "circuit_breakers"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False, default="*")
    state = Column(String(20), nullable=False, default="CLOSED")  # CLOSED, OPEN, HALF_OPEN
    failure_count = Column(Integer, nullable=False, default=0)
    threshold = Column(Integer, nullable=False, default=3)
    opened_at = Column(String(32), nullable=True)
    half_open_at = Column(String(32), nullable=True)
    updated_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("agent_id", "tool_name", name="uq_circuit_agent_tool"),
    )


class QuarantineEvent(Base):
    __tablename__ = "quarantine_events"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    action = Column(String(30), nullable=False)  # QUARANTINE, START_RECOVERY, RELEASE
    reason = Column(String(500), nullable=False, default="")
    actor_user_id = Column(String(36), nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)


class ReliabilitySnapshot(Base):
    __tablename__ = "reliability_snapshots"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    window_days = Column(Integer, nullable=False, default=30)
    observations = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    level = Column(String(20), nullable=False, default="INSUFFICIENT")
    metrics = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)


class RiskAssessmentRecord(Base):
    __tablename__ = "risk_assessments"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    action_id = Column(String(36), nullable=False, index=True)
    workflow_execution_id = Column(String(36), nullable=True, index=True)
    agent_execution_id = Column(String(36), nullable=True, index=True)
    agent_id = Column(String(36), nullable=True, index=True)
    decision = Column(String(20), nullable=False)
    risk_level = Column(String(20), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    rules = Column(JSON, nullable=False, default=list)
    evidence = Column(JSON, nullable=False, default=dict)
    propagation = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_execution_id = Column(String(36), nullable=True, index=True)
    origin_agent_id = Column(String(36), nullable=True, index=True)
    failure_type = Column(String(50), nullable=False)
    risk_level = Column(String(20), nullable=False, default="HIGH")
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN, ACKNOWLEDGED, RESOLVED
    summary = Column(String(2000), nullable=False, default="")
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)
    resolved_at = Column(String(32), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    kind = Column(String(40), nullable=False, default="containment")
    severity = Column(String(20), nullable=False, default="HIGH")
    title = Column(String(255), nullable=False)
    body = Column(String(2000), nullable=False, default="")
    incident_id = Column(String(36), nullable=True, index=True)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)
    read_at = Column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# V2 — transaction integrity
# ---------------------------------------------------------------------------


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    workflow_execution_id = Column(String(36), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="CREATED")
    idempotency_key = Column(String(255), nullable=True, unique=True, index=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow)
    updated_at = Column(String(32), nullable=False, default=utcnow)


class TransactionStep(Base):
    __tablename__ = "transaction_steps"

    id = Column(String(36), primary_key=True, default=new_id)
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=False, index=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    step_key = Column(String(120), nullable=False)
    sequence = Column(Integer, nullable=False, default=0)
    tool_name = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False, default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED, COMPENSATED, SKIPPED
    action_id = Column(String(36), nullable=True, index=True)
    idempotency_key = Column(String(255), nullable=True, unique=True, index=True)
    compensation_tool = Column(String(255), nullable=True)
    compensation_status = Column(String(30), nullable=False, default="NONE")
    compensation_action_id = Column(String(36), nullable=True, index=True)
    max_attempts = Column(Integer, nullable=False, default=1)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(2000), nullable=True)
    started_at = Column(String(32), nullable=True)
    completed_at = Column(String(32), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("transaction_id", "step_key", name="uq_transaction_step_key"),
    )


class CompensationAction(Base):
    __tablename__ = "compensation_actions"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=False, index=True)
    step_id = Column(String(36), ForeignKey("transaction_steps.id"), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False)
    action_id = Column(String(36), nullable=True)
    status = Column(String(30), nullable=False, default="PENDING")  # PENDING, APPROVED, EXECUTED, FAILED
    reason = Column(String(500), nullable=False, default="")
    created_at = Column(String(32), nullable=False, default=utcnow)
    completed_at = Column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# V2 — policy history, audit checkpoints, benchmarks
# ---------------------------------------------------------------------------


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    policy_id = Column(String(36), ForeignKey("policies.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    rules = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="DRAFT")
    created_by = Column(String(36), nullable=True)
    created_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint("policy_id", "version", name="uq_policy_version"),)


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    last_event_id = Column(String(36), nullable=False)
    last_sequence = Column(Integer, nullable=False)
    last_hash = Column(String(80), nullable=False)
    event_count = Column(Integer, nullable=False, default=0)
    created_at = Column(String(32), nullable=False, default=utcnow)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id = Column(String(36), primary_key=True, default=new_id)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, default=DEFAULT_ORG_ID, index=True)
    suite = Column(String(80), nullable=False, default="AFPB")
    scenario = Column(String(80), nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default=utcnow, index=True)
