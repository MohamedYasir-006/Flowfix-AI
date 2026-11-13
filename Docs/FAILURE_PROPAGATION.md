# AgentGuard V2 — Failure Propagation Semantics

Failure propagation is the core V2 differentiator. Policy answers whether an
agent is permitted to call a tool. Propagation answers whether the **evidence
that action depends on** is trustworthy and whether taking the action would
extend a known failure.

The engine is deterministic. It makes no model calls and performs no network
access. It never returns `ALLOW`; it can only leave a policy decision unchanged,
require approval, or deny.

---

## 1. Effect ladder

Effects are ordered:

```
NONE  <  REQUIRE_APPROVAL  <  DENY
```

The strongest applicable effect wins. A policy `DENY` is evaluated separately
and always wins over any propagation result. An explicit policy `ALLOW` can be
restricted by propagation, never the reverse.

---

## 2. Inputs

Propagation is applicable when the request supplies any of:

- `workflow_execution_id`;
- `agent_execution_id` (which requires a workflow execution);
- `input_artifact_ids` (which requires a workflow execution).

V1 requests without these fields behave exactly as before: propagation returns
`NONE` and is marked `applicable: false`.

The upstream set is built from:

1. the explicit `input_artifact_ids`, deduplicated;
2. artifacts this agent execution previously consumed;
3. `parent_artifact_ids` chains;
4. explicit `dependencies` rows with `relationship = depends_on`;
5. traversal repeats breadth-first until `max_depth`.

All traversal is tenant-scoped. An object from another tenant is treated as
missing and fails closed.

### Invalid workflow context

If the workflow execution does not exist in the tenant, or is `PAUSED`/`FAILED`,
the engine returns:

- effect `DENY`;
- reason `INVALID_WORKFLOW_CONTEXT` or `WORKFLOW_NOT_RUNNING`;
- risk `HIGH`.

This prevents an agent from attaching a stale or foreign execution to bypass
checks.

---

## 3. Rules

Default policy (overridable per tenant through `settings.propagation_policy`):

| Rule | Trigger | Default effect | Reason code |
| --- | --- | --- | --- |
| `invalid_upstream` | An upstream artifact is `INVALID` or `REJECTED` | `DENY` | `INVALID_UPSTREAM_ARTIFACT` |
| `quarantined_upstream` | An artifact is `QUARANTINED`, or its producer agent is quarantined | `DENY` | `QUARANTINED_UPSTREAM_ARTIFACT` / `QUARANTINED_UPSTREAM_AGENT` |
| `repeated_upstream_failures` | Producer's validation failure count meets the threshold | `DENY` | `REPEATED_UPSTREAM_FAILURES` |
| `excessive_dependency_depth` | Traversal exceeds `max_depth` | `DENY` | `EXCESSIVE_DEPENDENCY_DEPTH` |
| `missing_provenance` | A declared parent artifact does not exist in the tenant | `REQUIRE_APPROVAL` | `MISSING_PROVENANCE` |
| `conflicting_sources` | Two artifacts share type/name but have different integrity hashes | `REQUIRE_APPROVAL` | `CONFLICTING_UPSTREAM_INFORMATION` |
| `expired_upstream` | Artifact status is `EXPIRED` or `expires_at` is in the past | `REQUIRE_APPROVAL` | `EXPIRED_UPSTREAM_ARTIFACT` |
| `stale_upstream` | Artifact status is `STALE` | `REQUIRE_APPROVAL` | `STALE_UPSTREAM_ARTIFACT` |
| `unverified_high_impact` | A high-impact action consumes an `UNVERIFIED` artifact | `REQUIRE_APPROVAL` | `UNVERIFIED_HIGH_IMPACT_INPUT` |

Configuration keys:

```json
{
  "invalid_upstream": "DENY",
  "quarantined_upstream": "DENY",
  "repeated_upstream_failures": "DENY",
  "excessive_dependency_depth": "DENY",
  "missing_provenance": "REQUIRE_APPROVAL",
  "conflicting_sources": "REQUIRE_APPROVAL",
  "expired_upstream": "REQUIRE_APPROVAL",
  "stale_upstream": "REQUIRE_APPROVAL",
  "unverified_high_impact": "REQUIRE_APPROVAL",
  "high_impact_risk_levels": ["HIGH", "CRITICAL"],
  "max_depth": 12,
  "repeated_failure_threshold": 3
}
```

Only keys present in the default policy are honored. Unknown keys are ignored,
so configuration cannot inject a new authorization outcome. Setting a rule's
effect to `NONE` disables that rule. The effective policy is echoed in every
propagation result.

`high_impact_risk_levels` controls what counts as high impact for
`unverified_high_impact`. It does not change policy risk scoring.

---

## 4. Algorithm

1. Validate the workflow context and completion state.
2. Collect upstream artifacts and their maximum depth.
3. For each artifact:
   - register its workflow and producer in the blast radius;
   - check depth;
   - map validation status to a violation;
   - check `expires_at` independently of status;
   - verify each declared parent exists in the tenant;
   - check the producer's operational state and validation failure count.
4. Group artifacts by `(artifact_type, name)` and compare integrity hashes. More
   than one hash is a conflicting-source violation.
5. Add consumer agents from explicit dependency edges in the workflow.
6. Reduce violations using the effect ladder.
7. Derive risk level, recommended action, evidence, and origin/affected sets.

The result shape includes:

```json
{
  "applicable": true,
  "effect": "DENY",
  "violated_rules": [
    {
      "rule": "invalid_upstream",
      "effect": "DENY",
      "reason_code": "INVALID_UPSTREAM_ARTIFACT",
      "evidence": "Artifact beneficiary is INVALID",
      "artifact_id": "..."
    }
  ],
  "reason_codes": ["INVALID_UPSTREAM_ARTIFACT"],
  "origin_agents": ["agent-support"],
  "affected_agents": ["agent-support"],
  "affected_workflows": ["..."],
  "upstream_artifact_ids": ["..."],
  "risk_level": "HIGH",
  "recommended_action": "Block the action, contain downstream agents, and revalidate or replace the failing upstream artifacts before retrying.",
  "evidence": ["Artifact beneficiary is INVALID"],
  "effective_policy": { "...": "..." }
}
```

---

## 5. Decision integration

Policy is evaluated first. Then:

- propagation `DENY` + policy not `DENY` → `DENY`;
- propagation `REQUIRE_APPROVAL` + policy `ALLOW` → `REQUIRE_APPROVAL`;
- propagation `REQUIRE_APPROVAL` + policy `REQUIRE_APPROVAL` → unchanged;
- propagation `NONE` → policy unchanged.

A policy `DENY` is never weakened, even if propagation is `NONE`.

Reliability runs after propagation and can only upgrade `ALLOW` to
`REQUIRE_APPROVAL` for workflow-scoped high-impact actions. It cannot downgrade
a propagation denial.

Every propagation denial that has a workflow execution creates an incident and
notification, with origin, affected agents/workflows, upstream artifacts, and
violated rules preserved as evidence. The resulting `risk_assessments` row
contains the full propagation payload.

---

## 6. Approval interaction

Propagation is re-evaluated after approval. This is deliberate:

1. The initial decision may be `REQUIRE_APPROVAL` because an artifact was
   `UNVERIFIED`.
2. A human approves the specific payload.
3. Before execution, the artifact becomes `INVALID`, the producer is quarantined,
   or the workflow is paused.
4. The retry returns `DENY` with `PROPAGATION_BLOCKED_AFTER_APPROVAL`.
5. The approval is not consumed.

If propagation still requires approval after the human grant, the approved
context satisfies that requirement and the action may proceed; the reason code
`PROPAGATION_APPROVAL_SATISFIED` documents it. Policy is still re-evaluated and
an explicit deny still wins.

An approval is bound to the workflow execution, agent execution, and input
artifact IDs that existed at request time. Supplying an approval without that
context cannot bypass propagation.

---

## 7. Worked example

Scenario: a support agent proposes an outbound email using a beneficiary record.

1. The record is recorded as an artifact with status `UNVERIFIED`.
2. Policy allows `send_email` after approval.
3. Propagation sees a high-impact action consuming unverified data:
   `REQUIRE_APPROVAL`, reason `UNVERIFIED_HIGH_IMPACT_INPUT`.
4. A human approves.
5. Before execution, validation marks the record `INVALID`.
6. Post-approval propagation returns `DENY` with
   `INVALID_UPSTREAM_ARTIFACT` and `PROPAGATION_BLOCKED_AFTER_APPROVAL`.
7. The email does not run and the approval remains unconsumed.
8. An incident lists the artifact, producer, workflow, and recommended repair.

The opposite control case: a fully `VALIDATED`, non-expired artifact with
consistent provenance produces `NONE`; policy decides normally.

---

## 8. Relationship to policy

| Question | Owner |
| --- | --- |
| Is this agent allowed to use this tool? | Policy |
| Is the environment acceptable? | Policy/identity checks |
| Is the payload schema valid? | Validation |
| Is the agent currently contained? | Operational gate |
| Is the upstream evidence trustworthy? | Propagation |
| Should a borderline reliable agent get extra review? | Reliability friction |
| What explains the risk? | Risk aggregation |
| May the tool execute now? | Effective decision, with `DENY` final |

Propagation is not a second policy engine. It cannot create an allow and does
not inspect tool permissions. It only restricts.

---

## 9. Limitations

- Only recorded provenance can be enforced. A dependency the runtime never
  records is invisible.
- Validation status is evidence, not truth.
- Conflicting-source detection is intentionally simple: same type/name with
  different content hashes. It does not attempt semantic reconciliation.
- Depth limits are a safety valve; a very deep but valid graph can hit the
  configured bound and be denied.
- Propagation is per-action and synchronous. It is not a distributed
  snapshot-isolation mechanism across concurrent writers.
- Human approval acknowledges reviewed evidence; it does not make future
  evidence trustworthy, which is why post-approval rechecks exist.
