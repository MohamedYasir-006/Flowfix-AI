"""Pydantic contracts for AgentGuard V2 intelligence APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ValidationStatus = Literal[
    "UNVERIFIED",
    "VALIDATED",
    "INVALID",
    "STALE",
    "EXPIRED",
    "QUARANTINED",
    "REJECTED",
]

PropagationEffect = Literal["NONE", "REQUIRE_APPROVAL", "DENY"]


# ---------------------------------------------------------------------------
# Workflows and executions
# ---------------------------------------------------------------------------


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str


class WorkflowExecutionCreate(BaseModel):
    workflow_id: str
    external_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    org_id: str
    external_key: str | None = None
    status: str
    started_at: str
    ended_at: str | None = None


class AgentExecutionCreate(BaseModel):
    workflow_execution_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_execution_id: str
    agent_id: str
    org_id: str
    status: str
    started_at: str
    ended_at: str | None = None
    error: str | None = None


class AgentExecutionComplete(BaseModel):
    status: Literal["COMPLETED", "FAILED", "BLOCKED"] = "COMPLETED"
    error: str | None = None


# ---------------------------------------------------------------------------
# Artifacts, validation, dependencies
# ---------------------------------------------------------------------------


class ArtifactCreate(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=255)
    content: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    workflow_execution_id: str | None = None
    agent_execution_id: str | None = None
    parent_artifact_ids: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    trust_metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    workflow_execution_id: str | None = None
    producer_agent_id: str
    producer_execution_id: str | None = None
    artifact_type: str
    name: str
    content: Any = None
    integrity_hash: str
    validation_status: str
    version: int
    parent_artifact_ids: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    trust_metadata: dict[str, Any] = Field(default_factory=dict)
    validation_results: list[Any] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ValidationConfig(BaseModel):
    """A versioned validation rule set.

    ``config`` is intentionally declarative. Supported validators:
    schema, required, types, business_rules, provenance, integrity, expiration,
    source_consistency. No validator calls an LLM or the network.
    """

    validator: Literal[
        "schema",
        "required",
        "types",
        "business_rules",
        "provenance",
        "integrity",
        "expiration",
        "source_consistency",
    ]
    rule_version: str = "1"
    artifact_type: str | None = None
    workflow_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ValidateRequest(BaseModel):
    configs: list[ValidationConfig] | None = None
    mode: Literal["configured", "default"] = "configured"


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    validator: str
    rule_version: str
    status: str
    errors: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class HumanVerificationRequest(BaseModel):
    verified: bool
    note: str = ""


class DependencyCreate(BaseModel):
    workflow_execution_id: str | None = None
    source_type: Literal["agent", "tool", "artifact", "workflow"]
    source_id: str
    target_type: Literal["agent", "tool", "artifact", "workflow"]
    target_id: str
    relationship: Literal["produced", "consumed", "invoked", "validated", "depends_on"]
    artifact_id: str | None = None
    validation_status: str = "UNVERIFIED"


class DependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_execution_id: str | None = None
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relationship: str
    artifact_id: str | None = None
    validation_status: str
    created_at: str


class ConsumptionRecord(BaseModel):
    workflow_execution_id: str
    agent_execution_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    status: str = "ACTIVE"
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship: str
    validation_status: str
    artifact_id: str | None = None
    created_at: str


class WorkflowGraph(BaseModel):
    workflow_execution_id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    cycles: list[list[str]] = Field(default_factory=list)


class DownstreamImpact(BaseModel):
    origin_agent: str | None = None
    failure_type: str | None = None
    affected_agents: list[str] = Field(default_factory=list)
    affected_workflows: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    risk_level: str = "LOW"
    evidence: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk, reliability, containment
# ---------------------------------------------------------------------------


class RiskEvaluateRequest(BaseModel):
    workflow_execution_id: str | None = None
    agent_execution_id: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    tool: str | None = None
    action_risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"


class RiskEvaluationOut(BaseModel):
    decision: str
    risk_level: str
    risk_score: int
    triggered_rules: list[str]
    evidence: list[str]
    recommended_action: str
    propagation: dict[str, Any]


class ReliabilityOut(BaseModel):
    agent_id: str
    agent_name: str
    score: float
    confidence: float
    level: str
    observations: int
    window_days: int
    metrics: dict[str, Any]
    contributing_factors: list[str]
    trend: str
    methodology: str
    computed_at: str


class AgentHealthOut(BaseModel):
    agent_id: str
    agent_name: str
    status: str
    operational_status: str
    quarantine_reason: str | None = None
    quarantined_at: str | None = None
    circuit_state: str
    reliability: ReliabilityOut
    recent_failures: int


class QuarantineRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RecoveryRequest(BaseModel):
    confirm: bool = True
    evidence: dict[str, Any] = Field(default_factory=dict)


class QuarantineEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    action: str
    reason: str
    actor_user_id: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str


# ---------------------------------------------------------------------------
# Incidents and replay
# ---------------------------------------------------------------------------


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_execution_id: str | None = None
    origin_agent_id: str | None = None
    failure_type: str
    risk_level: str
    status: str
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    resolved_at: str | None = None


class TimelineEntry(BaseModel):
    timestamp: str
    kind: str
    actor: str | None = None
    summary: str
    evidence_ref: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class IncidentReport(BaseModel):
    incident: IncidentOut
    timeline: list[TimelineEntry] = Field(default_factory=list)
    affected_agents: list[str] = Field(default_factory=list)
    affected_workflows: list[str] = Field(default_factory=list)
    recommendation: str = ""


class WhatIfRequest(BaseModel):
    action_id: str
    hypothetical_decision: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = "ALLOW"


class WhatIfResult(BaseModel):
    action_id: str
    actual_decision: str
    hypothetical_decision: str
    would_execute: bool
    hypothetical_effect: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    note: str = (
        "Simulation only. No external operation is executed and no production "
        "state is modified."
    )


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionStepCreate(BaseModel):
    step_key: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=255)
    compensation_tool: str | None = None
    max_attempts: int = Field(default=1, ge=1, le=5)


class TransactionCreate(BaseModel):
    workflow_execution_id: str | None = None
    idempotency_key: str | None = None
    steps: list[TransactionStepCreate] = Field(min_length=1, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransactionStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    transaction_id: str
    step_key: str
    sequence: int
    tool_name: str
    status: str
    action_id: str | None = None
    idempotency_key: str | None = None
    compensation_tool: str | None = None
    compensation_status: str
    attempts: int
    last_error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_execution_id: str | None = None
    status: str
    idempotency_key: str | None = None
    created_at: str
    updated_at: str
    steps: list[TransactionStepOut] = Field(default_factory=list)


class StepStartRequest(BaseModel):
    action_id: str | None = None


class StepCompleteRequest(BaseModel):
    success: bool
    action_id: str | None = None
    error: str | None = None


class CompensationRequest(BaseModel):
    reason: str = ""
    approved: bool = False


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


class BenchmarkRunRequest(BaseModel):
    suite: str = "AFPB"
    scenarios: list[str] | None = None
    seed: int = 7
    repetitions: int = Field(default=1, ge=1, le=10)


class BenchmarkScenarioResult(BaseModel):
    scenario: str
    description: str
    baseline: dict[str, Any]
    agentguard_v2: dict[str, Any]
    metrics: dict[str, Any]
    passed: bool


class BenchmarkOut(BaseModel):
    run_id: str | None = None
    suite: str
    seed: int
    generated_at: str
    scenarios: list[BenchmarkScenarioResult]
    aggregate: dict[str, Any]
    methodology: str
