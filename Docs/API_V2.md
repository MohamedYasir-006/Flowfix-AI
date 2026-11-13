# AgentGuard V2 — API Reference

All endpoints are under `/api/v1`. Interactive OpenAPI remains at `/api/docs`
and `/api/openapi.json`. V1 endpoints are unchanged; V2 adds routes and optional
fields.

---

## 1. Authentication and tenancy

| Caller | Credential | Used by |
| --- | --- | --- |
| Agent runtime | `X-Agent-Key: ag_...` | Decision evaluation, artifact production/consumption, workflow execution, step tracking, risk preview, benchmark creation. |
| Dashboard user | `Authorization: Bearer <token>` | Reads, administration, approvals, containment, incident resolution, audit checkpoints, compensation approval. |

- Agent-authenticated calls are rate-limited per agent.
- Tenant identity is derived from the credential. `X-Organization-Id` is ignored.
- When `AGENTGUARD_AUTH_REQUIRED=false` and no token is supplied, dashboard
  reads fall back to the seeded admin's tenant for local development. This
  fallback is disabled in production by enabling auth.
- Cross-tenant object IDs return `404` rather than revealing existence.

Common error shape:

```json
{
  "detail": "Artifact not found",
  "reason_codes": ["NOT_FOUND"]
}
```

Validation errors use FastAPI's standard `422` shape. Conflicts use `409` with
reason codes such as `DUPLICATE_STEP_IN_PROGRESS`, `RETRY_BUDGET_EXHAUSTED`, or
`UNRESOLVED_INVALID_OUTPUTS`.

---

## 2. Decision API extensions

`POST /decisions/evaluate` (agent key) accepts the V1 fields plus:

| Field | Type | Meaning |
| --- | --- | --- |
| `workflow_execution_id` | string? | Current workflow run. Required for propagation. |
| `agent_execution_id` | string? | Current agent participation. Requires workflow execution. |
| `input_artifact_ids` | string[] | Explicit upstream artifacts consumed by this action. Requires workflow execution. |

Example:

```json
{
  "session_id": "session-42",
  "tool": "send_email",
  "target": "customer@example.com",
  "arguments": {
    "to": "customer@example.com",
    "subject": "Account update",
    "body": "..."
  },
  "workflow_execution_id": "6e...",
  "agent_execution_id": "d1...",
  "input_artifact_ids": ["a7..."]
}
```

Response fields added in V2 (all optional for compatibility):

| Field | Meaning |
| --- | --- |
| `explanation` | Human-readable rationale. |
| `risk_score` | Aggregated 0–100 explainability score. Never authorizes. |
| `risk_assessment_id` | Link to the persisted `risk_assessments` row. |
| `propagation` | Full propagation result including effective policy and violations. |
| `operational_status` | Agent containment status at decision time. |

Decision values remain `ALLOW`, `DENY`, `REQUIRE_APPROVAL`.

---

## 3. Workflows and executions

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/workflows` | user | Create a workflow definition. |
| `GET` | `/workflows` | user/agent | List tenant workflows. |
| `GET` | `/workflows/{workflow_id}` | user/agent | Get one workflow. |
| `POST` | `/workflows/{workflow_id}/executions` | agent | Start a workflow execution. |
| `GET` | `/workflow-executions` | user/agent | List executions. |
| `GET` | `/workflow-executions/{execution_id}` | user/agent | Execution summary with agent executions. |
| `POST` | `/workflow-executions/{execution_id}/agent-executions` | agent | Start an agent execution. Body `workflow_execution_id` must match the path. |
| `POST` | `/agent-executions/{agent_execution_id}/complete` | agent | Complete with `COMPLETED`, `FAILED`, or `BLOCKED`. |
| `POST` | `/workflow-executions/{execution_id}/complete` | user | Complete/fail a workflow (`?status=COMPLETED`). |
| `GET` | `/workflow-executions/{execution_id}/graph` | user/agent | Nodes, edges, and detected cycles. |
| `GET` | `/workflow-executions/{execution_id}/timeline` | user/agent | Merged audit/artifact/risk/transaction timeline. |
| `POST` | `/workflow-executions/{execution_id}/pause` | user | Pause for containment. |
| `POST` | `/workflow-executions/{execution_id}/resume` | user | Resume a paused execution. |

Executing a workflow whose status is not `RUNNING` fails closed for propagation:
the action is denied with `WORKFLOW_NOT_RUNNING`.

---

## 4. Artifacts and validation

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/artifacts` | agent | Record an artifact. Computes `integrity_hash`, creates provenance edges. |
| `GET` | `/artifacts` | user/agent | Filter by `workflow_execution_id`, `validation_status`, `producer_agent_id`, `limit`. |
| `GET` | `/artifacts/{artifact_id}` | user/agent | Get artifact. |
| `POST` | `/artifacts/{artifact_id}/validate` | user/agent | Run configured or inline validators. |
| `POST` | `/artifacts/{artifact_id}/verify` | admin/approver | Human accept/reject. Body: `{"verified": true, "note": "..."}`. |
| `GET` | `/artifacts/{artifact_id}/lineage` | user/agent | Bounded parent lineage. |
| `POST` | `/artifacts/consumption` | agent | Record consumed artifact edges. |
| `POST` | `/validation-rules` | user | Create a reusable validation rule. |
| `GET` | `/validation-rules` | user | List rules. |
| `DELETE` | `/validation-rules/{rule_id}` | user | Disable a rule (204; does not delete history). |

Artifact creation body:

```json
{
  "artifact_type": "customer_record",
  "name": "beneficiary",
  "content": {"account": "acct-1", "verified": false},
  "workflow_execution_id": "6e...",
  "agent_execution_id": "d1...",
  "parent_artifact_ids": ["a1..."],
  "expires_at": "2026-12-01T00:00:00+00:00",
  "trust_metadata": {}
}
```

Validation body (inline configs):

```json
{
  "mode": "configured",
  "configs": [
    {
      "validator": "required",
      "rule_version": "1",
      "config": {"fields": ["account"]}
    }
  ]
}
```

Validators: `schema`, `required`, `types`, `business_rules`, `provenance`,
`integrity`, `expiration`, `source_consistency`. See the V2 architecture and
security docs for semantics.

`mode: "configured"` uses `configs` when supplied; otherwise it uses the
tenant's enabled matching rules. An empty rule set leaves the artifact
`UNVERIFIED`.

---

## 5. Dependencies and impact

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/dependencies` | agent | Register one provenance edge. |
| `GET` | `/dependencies` | user/agent | Filter by workflow, source, target, artifact. |
| `GET` | `/dependencies/impact` | user/agent | Downstream impact for `agent_id` or `artifact_id`. |
| `GET` | `/agents/{agent_id}/impact` | user/agent | Convenience alias for agent impact. |

Edges are evidence only. Registering an edge never authorizes an action.

Example:

```json
{
  "workflow_execution_id": "6e...",
  "source_type": "artifact",
  "source_id": "a1...",
  "target_type": "agent",
  "target_id": "agent-support",
  "relationship": "consumed",
  "artifact_id": "a1...",
  "validation_status": "VALIDATED"
}
```

Allowed `relationship` values: `produced`, `consumed`, `invoked`, `validated`,
`depends_on`.

---

## 6. Risk preview

`POST /risk/evaluate` (agent key) is read-only and labelled `PREVIEW_ONLY`.

```json
{
  "workflow_execution_id": "6e...",
  "agent_execution_id": "d1...",
  "input_artifact_ids": ["a1..."],
  "tool": "send_email",
  "action_risk": "HIGH"
}
```

It returns a decision-shaped preview, risk level/score, triggered rules,
evidence, recommended action, and propagation result. It records no decision,
creates no approval, and never authorizes. `/decisions/evaluate` remains the
only enforcement point.

---

## 7. Operations and containment

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/agents/{agent_id}/health` | user/agent | Operational status, circuit state, reliability. |
| `GET` | `/agents/{agent_id}/reliability` | user/agent | Score with confidence, metrics, factors, trend. |
| `GET` | `/reliability` | user/agent | All tenant agents. |
| `GET` | `/containment/agents` | user/agent | Health for all agents. |
| `GET` | `/containment/circuits` | user/agent | Circuit breaker states. |
| `GET` | `/agents/{agent_id}/quarantine-events` | user/agent | Containment history. |
| `POST` | `/agents/{agent_id}/quarantine` | admin | Quarantine. Body: `{"reason": "...", "evidence": {}}`. |
| `POST` | `/agents/{agent_id}/recovery/start` | admin | Enter `RECOVERING`. |
| `POST` | `/agents/{agent_id}/recovery/complete` | admin | Release after checks. Body may include `{"confirm": true}`. |
| `GET` | `/notifications` | user/agent | Operational notifications (`?unread_only=true`). |
| `POST` | `/notifications/{id}/read` | user | Mark read. |

Recovery refuses with `UNRESOLVED_INVALID_OUTPUTS` when the agent produced an
invalid artifact without a newer validated replacement of the same type/name.

---

## 8. Incidents and replay

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/incidents` | user/agent | List incidents (`?status=OPEN`). |
| `GET` | `/incidents/summary` | user/agent | Counts by status and risk. |
| `GET` | `/incidents/{incident_id}` | user/agent | Get incident. |
| `GET` | `/incidents/{incident_id}/report` | user/agent | Timeline, blast radius, recommendation. |
| `POST` | `/incidents/{incident_id}/resolve` | user | Resolve with `?resolution=...`. |
| `POST` | `/incidents/what-if` | user/agent | Read-only simulated decision change. |

What-if body:

```json
{"action_id": "action-uuid", "hypothetical_decision": "ALLOW"}
```

It reconstructs only recorded evidence. It does not replay model calls, execute
tools, write decisions, or alter containment.

---

## 9. Transactions

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/transactions` | agent | Create with idempotency key and steps. |
| `GET` | `/transactions` | user/agent | Filter by workflow/status. |
| `GET` | `/transactions/{transaction_id}` | user/agent | Detail with steps. |
| `GET` | `/transactions/{transaction_id}/recovery-plan` | user/agent | Partial-failure recovery plan. |
| `POST` | `/transactions/{transaction_id}/steps/{step_ref}/start` | agent | Start a step (by ID or key). |
| `POST` | `/transactions/{transaction_id}/steps/{step_ref}/complete` | agent | Complete step. |
| `POST` | `/transactions/{transaction_id}/compensate` | admin/approver | Request compensation. |
| `POST` | `/transactions/{transaction_id}/steps/{step_ref}/compensation/complete` | admin/approver | Record compensation result. |

Create body:

```json
{
  "workflow_execution_id": "6e...",
  "idempotency_key": "checkout-123",
  "steps": [
    {"step_key": "reserve", "tool_name": "reserve_funds", "compensation_tool": "release_funds"},
    {"step_key": "settle", "tool_name": "settle_transfer"}
  ]
}
```

Compensation body:

```json
{"reason": "settlement failed", "approved": true}
```

Without `approved: true`, compensation waits in `WAITING_APPROVAL`. AgentGuard
records and gates compensation; it never asserts that rollback succeeded.

---

## 10. Benchmarks

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/benchmarks/afpb/run` | user | Run AFPB in an isolated DB. |
| `GET` | `/benchmarks/runs` | user/agent | List recorded run summaries. |

Request:

```json
{"suite": "AFPB", "scenarios": null, "seed": 7, "repetitions": 1}
```

See [AFPB_BENCHMARK.md](AFPB_BENCHMARK.md) for methodology and non-claims.

---

## 11. Audit

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/audit/verify` | user/agent | Recompute tenant chain; report first break. |
| `POST` | `/audit/checkpoint` | admin | Pin the latest event hash. |
| `GET` | `/audit/checkpoints` | user/agent | List checkpoints. |
| `GET` | `/audit/events` | user/agent | Tenant-scoped redacted export (`event_type`, `decision`, `agent_id`, `limit`). |

`/audit/verify` returns `valid`, `checked`, and on failure the reason
(`SEQUENCE_GAP`, `PREV_HASH_MISMATCH`, or `EVENT_HASH_MISMATCH`) plus the first
offending event. A checkpoint should be stored outside this database.

---

## 12. SDK v2 quick reference

```python
from agentguard import AgentGuardClient, call_guarded

guard = AgentGuardClient(base_url="http://127.0.0.1:8000/api", api_key="ag_...")

workflow = guard.create_workflow(name="refund-flow")
execution = guard.start_workflow_execution(workflow["id"], external_key="case-42")
agent_run = guard.start_agent_execution(execution["id"])

artifact = guard.record_artifact(
    artifact_type="customer_record",
    name="beneficiary",
    content={"account": "acct-1"},
    workflow_execution_id=execution["id"],
    agent_execution_id=agent_run["id"],
)

result = call_guarded(
    guard,
    tool="send_email",
    arguments={"to": "customer@example.com", "subject": "Hi", "body": "Hello"},
    target="customer@example.com",
    execute=send_email,
    workflow_execution_id=execution["id"],
    agent_execution_id=agent_run["id"],
    input_artifact_ids=[artifact["id"]],
)

health = guard.agent_health("agent-support")
verify = guard.verify_audit_chain()
```

The SDK remains fail-closed: non-authorizing decisions and transport failures
raise, and the wrapped tool does not execute.
