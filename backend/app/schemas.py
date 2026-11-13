"""Pydantic request/response contracts for the `/api/v1` surface.

Field names follow the snake_case wire format used by the dashboard client.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Decision = Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]
Environment = Literal["dev", "staging", "prod"]


class RiskAssessment(BaseModel):
    level: RiskLevel
    reasons: list[str] = Field(default_factory=list)


class PolicyRef(BaseModel):
    id: str
    version: int


class PolicyRule(BaseModel):
    id: str
    effect: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]
    agent: str | None = None
    tool: str | None = None
    environment: Environment | None = None
    target: str | None = None
    category: Literal["read", "write", "external", "destructive"] | None = None
    risk_max: RiskLevel | None = Field(default=None, alias="riskMax")

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: Literal["ADMIN", "APPROVER", "AUDITOR", "DEVELOPER"]
    status: Literal["ACTIVE", "DISABLED"]
    created_at: str


class LoginRequest(BaseModel):
    email: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------------------
# Agents and tools
# ---------------------------------------------------------------------------


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    owner_user_id: str
    environment: str
    status: str
    tool_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    last_action_at: str | None = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    owner_user_id: str
    environment: Environment = "dev"


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    owner_user_id: str | None = None
    environment: Environment | None = None


class AgentCreated(AgentOut):
    """Returned once by POST /agents; carries the plaintext API key."""

    api_key: str


class PermissionsUpdate(BaseModel):
    tool_ids: list[str] = Field(default_factory=list)
    scopes: dict[str, Any] | None = None


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    category: str
    default_risk: str
    status: str
    created_at: str


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    category: Literal["read", "write", "external", "destructive"] = "read"
    default_risk: RiskLevel = "LOW"
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    version: int
    default_effect: str
    rules: list[dict[str, Any]]
    status: str
    created_by: str | None = None
    created_at: str
    updated_at: str | None = None


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    default_effect: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = "DENY"
    rules: list[PolicyRule] = Field(default_factory=list)


class PolicyUpdate(BaseModel):
    """Replaces a draft's contents. Publishing creates a new version."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    default_effect: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] | None = None
    rules: list[PolicyRule] | None = None


# ---------------------------------------------------------------------------
# Decisions, approvals, execution
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    session_id: str | None = None
    tool: str
    target: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    environment: Environment | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    # Optional, but when supplied it must match the authenticated agent.
    agent_id: str | None = None
    # V2 workflow context. When supplied, the action is evaluated against the
    # provenance/dependency graph in addition to action-level policy.
    workflow_execution_id: str | None = None
    agent_execution_id: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)


class DecisionResponse(BaseModel):
    action_id: str
    decision: Decision
    risk: RiskAssessment
    reason_codes: list[str]
    policy: PolicyRef | None = None
    approval_id: str | None = None
    expires_at: str | None = None
    # V2 explainability. Optional so V1 clients remain compatible.
    explanation: str = ""
    risk_score: int | None = None
    risk_assessment_id: str | None = None
    propagation: dict[str, Any] | None = None
    operational_status: str | None = None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    payload_hash: str
    requested_by_agent_id: str
    status: str
    approver_user_id: str | None = None
    expires_at: str
    decided_at: str | None = None
    reason: str
    tool_name: str
    target: str
    arguments_summary: dict[str, Any]
    risk_level: str
    policy_version: int
    created_at: str


class ApprovalDecision(BaseModel):
    approver_user_id: str | None = None
    decision: Literal["APPROVED", "REJECTED"]
    reason: str | None = None


class ActionResultRequest(BaseModel):
    success: bool
    error: str | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Audit, overview, settings
# ---------------------------------------------------------------------------


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    action_id: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    session_id: str | None = None
    tool_name: str | None = None
    decision: str | None = None
    risk_level: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    policy_id: str | None = None
    policy_version: int | None = None
    payload_hash: str | None = None
    # ``metadata`` is the wire name; the ORM column is ``redacted_metadata``.
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias="redacted_metadata"
    )
    created_at: str


class OverviewStats(BaseModel):
    active_agents: int
    total_agents: int
    actions_today: int
    blocked_today: int
    pending_approvals: int
    decisions_today: dict[str, int]
    recent_events: list[EventOut]


class SettingsOut(BaseModel):
    workspace_name: str
    default_environment: Environment
    approval_ttl_minutes: int
    retention_days: int
    redact_secrets: bool
    redact_fields: list[str]
    require_approval_for: list[RiskLevel]
    max_payload_bytes: int


class SettingsUpdate(BaseModel):
    workspace_name: str | None = None
    default_environment: Environment | None = None
    approval_ttl_minutes: int | None = Field(default=None, ge=1)
    retention_days: int | None = Field(default=None, ge=1)
    redact_secrets: bool | None = None
    redact_fields: list[str] | None = None
    require_approval_for: list[RiskLevel] | None = None
    max_payload_bytes: int | None = Field(default=None, ge=1024)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
