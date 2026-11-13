# AgentGuard V2 — Architecture

AgentGuard V2 turns the policy decision point into a runtime security and
workflow-reliability control plane. V1 answered **"may this agent call this
tool?"**. V2 also answers **"is the information and upstream state this action
depends on trustworthy, and what happens downstream when it is not?"**

The design remains a modular monolith. No graph database, message broker, or
Redis instance is required to run V2. Those are deployment choices, not
architecture prerequisites, and are not claimed as implemented.

---

## 1. Design principles

1. **DENY always wins.** Policy denial is authoritative. Propagation,
   reliability, containment, and risk aggregation can only leave a decision
   unchanged or make it stricter. They never turn `DENY` into `ALLOW`.
2. **Determinism in the enforcement path.** No model calls, network calls, or
   sampling occur during decision evaluation. The same inputs, graph, and
   policy version produce the same result.
3. **Fail closed.** Missing workflow context, cross-tenant object IDs, broken
   circuit breakers, quarantined agents, and unresolved invalid outputs deny or
   require approval. Transport failure on the SDK side never executes a tool.
4. **Evidence over claims.** Every restriction carries machine-readable reason
   codes, human-readable evidence, effective configuration, and an audit link.
5. **Additive compatibility.** V1 clients keep working. Workflow and provenance
   fields on the decision API are optional and ignored when absent.
6. **Operational state is explicit.** Agent reliability, quarantine, circuit
   breakers, incidents, and compensation are persisted state machines, not
   dashboard-only decorations.

---

## 2. Component map

| Layer | Main modules | Responsibility |
| --- | --- | --- |
| HTTP API | `app/routers/*` | V1 routes plus V2 workflow, provenance, dependency, risk, operations, incident, transaction, benchmark, and audit routes. |
| Enforcement | `app/services/decisions.py` | Single policy decision point. Applies operational gate, policy, propagation, reliability friction, risk aggregation, approval creation, and post-approval rechecks. |
| Policy | `app/policy.py` | Deterministic rule precedence. Explicit policy `DENY` remains final. |
| Provenance | `app/services/provenance.py` | Artifact recording, integrity hashes, validation rules, human verification, consumption edges. |
| Dependency graph | `app/services/dependencies.py` | Bounded traversal over relational `dependencies` edges: lineage, downstream impact, cycle detection. |
| Propagation | `app/services/propagation.py` | Walks upstream artifacts and producers, maps violations to `REQUIRE_APPROVAL` or `DENY`. |
| Reliability | `app/services/reliability.py` | Confidence-aware, smoothed agent score. Adds friction only for workflow-scoped high-impact actions. |
| Containment | `app/services/containment.py` | Quarantine state machine, circuit breakers, recovery checks, workflow pause/resume. |
| Incidents | `app/services/incidents.py` | Incident creation, timeline reconstruction, report generation, read-only what-if simulation. |
| Transactions | `app/services/transactions.py` | Saga-style step tracking, idempotency, partial-failure states, explicit compensation approvals. |
| Risk | `app/services/risk_engine.py` | Explainable aggregation of policy risk, propagation evidence, reliability, and operational state. Never authorizes. |
| Audit | `app/services/audit.py` | Append-only events plus per-tenant SHA-256 hash chain and checkpoints. |
| Benchmarks | `app/services/benchmarks.py` | AFPB suite executed in an isolated temporary SQLite database. |
| Persistence | `app/models.py`, `app/migrations.py` | SQLAlchemy schema plus additive, versioned migrations. |

---

## 3. Decision lifecycle

`POST /api/v1/decisions/evaluate` executes in this order:

1. **Credential binding.** `agent_id` and `environment` supplied by the caller
   must match the authenticated agent.
2. **Idempotent replay.** A repeated idempotency key returns the original
   decision rather than creating a second effect.
3. **Payload bound and tool schema validation.**
4. **Operational gate.** Quarantined agents and open circuit breakers fail
   closed before policy is even evaluated.
5. **Workflow context validation.** When supplied, the workflow execution and
   agent execution must belong to the authenticated tenant and to each other.
   Consumed artifacts are recorded as provenance edges.
6. **Policy evaluation.** Explicit `DENY` wins; approval and allow rules follow
   the V1 precedence.
7. **Failure propagation.** The upstream artifact graph is traversed. The
   strongest applicable effect is applied.
8. **Reliability friction.** For workflow-scoped, high-impact actions only, a
   `LOW`/`CRITICAL` reliability level upgrades `ALLOW` to `REQUIRE_APPROVAL`.
9. **Risk aggregation.** Stable score, triggered rules, evidence, and a
   recommended action are persisted with the decision.
10. **Incident and approval creation.** A propagation denial opens an incident
    and notification. A stricter decision creates a payload-bound approval.
11. **Audit.** The decision is written into the tenant hash chain.

### Post-approval lifecycle

An approval is not a capability token. On `POST /decisions/evaluate` with an
`approval_id`, AgentGuard:

1. verifies the approval belongs to the authenticated agent and tenant;
2. verifies it is `APPROVED`, not expired, not consumed, and bound to the same
   canonical payload;
3. re-applies the operational gate;
4. re-evaluates the **current** policy;
5. re-evaluates **current** propagation, using the workflow context stored on
   the approval;
6. atomically consumes the approval only if every check passes.

If an upstream artifact became invalid after the human approved, the approval is
not consumed and the action is denied with
`PROPAGATION_BLOCKED_AFTER_APPROVAL`. Human approval acknowledges evidence; it
does not freeze it.

---

## 4. Data model additions

All new tables carry `org_id` and all reads/writes are tenant-scoped using the
credential-derived organization. Tables added in V2:

| Table | Purpose |
| --- | --- |
| `organizations` | Tenant registry. Legacy rows default to `org-default`. |
| `workflows` | Named workflow definitions. |
| `workflow_executions` | One run of a workflow. Status: `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `BLOCKED`. |
| `agent_executions` | An agent's participation in a workflow execution. |
| `artifacts` | Agent outputs with content hash, validation status, expiry, parents, and trust metadata. |
| `validation_rules` | Versioned declarative validation configuration. |
| `artifact_validations` | Per-run validator results and evidence. |
| `dependencies` | Relational provenance edges: produced, consumed, invoked, validated, depends_on. |
| `agent_states` | Operational status and failure counters. |
| `circuit_breakers` | Per-agent/per-tool breaker state (`CLOSED`, `OPEN`, `HALF_OPEN`). |
| `quarantine_events` | Audit-style containment history. |
| `reliability_snapshots` | Persisted score, confidence, level, and component metrics. |
| `risk_assessments` | Explainable risk record for each decision. |
| `incidents` | Failure records with origin, risk, evidence, and resolution. |
| `notifications` | Operational notifications generated by containment. |
| `transactions` / `transaction_steps` / `compensation_actions` | Saga intent, step state, and compensation approvals. |
| `policy_versions` | Immutable policy version history support. |
| `audit_checkpoints` | Pinned audit-chain hashes. |
| `benchmark_runs` | Recorded AFPB run summaries. |

V1 columns on `users`, `agents`, `tools`, `policies`, `approvals`, and
`audit_events` were extended additively with `org_id`; approvals also gained
workflow context (`workflow_execution_id`, `agent_execution_id`,
`input_artifact_ids`, `risk_assessment_id`, `consumed_at`). Existing databases
are migrated in place. See [V2_MIGRATION.md](V2_MIGRATION.md).

---

## 5. Failure propagation

The propagation engine is the central differentiator. It is described in depth
in [FAILURE_PROPAGATION.md](FAILURE_PROPAGATION.md). In architecture terms:

- Inputs are the action's `workflow_execution_id`, `agent_execution_id`, and
  explicit `input_artifact_ids`.
- The engine discovers upstream artifacts through `parent_artifact_ids` and
  `dependencies.relationship = depends_on`, bounded by `max_depth`.
- Each artifact's validation status, expiry, parents, producer operational state,
  and producer failure count is checked.
- Conflicting payloads with the same artifact type/name are detected by hash.
- The strongest effect among applicable rules is returned: `NONE`,
  `REQUIRE_APPROVAL`, or `DENY`.

The engine cannot allow. If it finds no violation, policy remains the sole
authorization source.

---

## 6. Reliability model

`compute_reliability` produces a score from observed rates:

| Component | Weight | Source |
| --- | --- | --- |
| Validation success | 0.35 | Artifact validation pass/fail |
| Execution success | 0.20 | Execution result events |
| Policy compliance | 0.20 | Decision denies vs. total decisions |
| Task completion | 0.15 | Agent execution completion |
| Recovery success | 0.10 | Quarantine releases vs. containment events |

Each rate uses Beta-style smoothing with a configurable prior so small samples
cannot produce extreme scores. Confidence is `min(1, observations / 30)`,
discounted when validation coverage is missing. `INSUFFICIENT` is a first-class
level below the minimum observation count: a new agent is **not** treated as
trusted.

Only a `LOW` or `CRITICAL` level on a high-impact, workflow-scoped action adds
friction, and only `ALLOW → REQUIRE_APPROVAL`. A quarantined agent is reported
as `CRITICAL` and is denied by the operational gate before policy runs.

---

## 7. Containment and recovery

- Validation failures and execution failures increment per-agent counters.
- The configured threshold opens the agent's circuit and quarantines the agent.
- Quarantine opens all circuits, records a `QuarantineEvent`, opens an incident,
  emits a notification, and writes an audit event.
- A quarantined agent is denied immediately, before policy evaluation.
- Circuit breakers transition `CLOSED → OPEN → HALF_OPEN`; a successful
  half-open trial closes the breaker, a failure reopens it.
- Recovery requires an authorized admin, an explicit `confirm`, and no
  unresolved invalid outputs. Releasing an agent resets counters and closes
  circuits; it does **not** grant permissions or bypass policy.

---

## 8. Saga-style transaction integrity

The transaction manager does not execute tools. It records intent and enforces:

- idempotent transaction creation by `(org_id, idempotency_key)`;
- unique step keys and ordered steps;
- `PENDING → RUNNING → COMPLETED/FAILED` transitions with compare-and-set SQL;
- rejection of duplicate in-flight external operations;
- retry budgets;
- `RECOVERY_REQUIRED` when a step fails after prior steps completed;
- explicit compensation planning and approval.

**Compensation is a new external operation, not a guaranteed rollback.** It is
never fired blindly. Unless an authorized approver explicitly marks it
approved, compensation waits in `WAITING_APPROVAL`. A failed compensation moves
the transaction back to `RECOVERY_REQUIRED`; it does not pretend success.

---

## 9. Incidents, timeline, and what-if

A deterministic propagation denial creates an incident with the origin,
affected agents/workflows, upstream artifact IDs, and violated rules. The
timeline combines audit events, artifacts, risk records, transactions, and step
events. The incident report adds downstream impact and a recommendation.

`POST /incidents/what-if` is read-only. It reconstructs the recorded decision and
describes what a different decision would have meant. It does not call tools,
write records, replay nondeterministic model output, or change containment.

---

## 10. Audit integrity

Audit events remain append-only from the application's perspective. V2 adds:

- per-organization monotonic `chain_sequence`;
- `prev_hash` and `event_hash` (`sha256:` over canonical JSON);
- `GET /audit/verify`, which recomputes the chain and reports the first broken
  link;
- `POST /audit/checkpoint`, which pins the latest hash for external storage;
- tenant-scoped `GET /audit/events` export.

**Limitation:** a valid chain proves internal consistency, not immutability
against a privileged attacker who can rewrite the entire table and recompute
every hash. External anchoring or WORM storage is required for stronger
guarantees. See [V2_SECURITY_MODEL.md](V2_SECURITY_MODEL.md).

---

## 11. Tenancy

- Every V2 table has `org_id`.
- Operational reads resolve the tenant from the agent key or user token. A
  client-supplied `X-Organization-Id` header is ignored.
- Cross-tenant object IDs return not-found rather than leaking existence.
- The default organization is seeded for compatibility; legacy rows are
  backfilled once.

---

## 12. Compatibility and operations

- V1 endpoints and response fields remain available.
- New decision fields (`explanation`, `risk_score`, `risk_assessment_id`,
  `propagation`, `operational_status`) are optional.
- `EvaluateRequest` accepts optional workflow context without requiring it.
- Schema changes are additive and idempotent; `init_db()` still runs
  `create_all()` first, then pending migrations, and never drops data.
- The system remains a single FastAPI process with a relational database. Bounded
  graph traversal avoids a premature graph-database dependency. Multi-instance
  rate limiting and external anchoring are deployment concerns, not implemented
  claims.

---

## 13. Known architectural limitations

- Reliability is advisory friction, not proof of correctness.
- Validation is declarative and deterministic; it cannot detect every semantic
  falsehood in an otherwise well-formed artifact.
- Propagation reasons over recorded provenance. Unrecorded dependencies cannot
  be enforced.
- Compensation cannot guarantee the external world is restored.
- The audit chain requires an external checkpoint to detect full-database
  rewrite.
- The benchmark measures this implementation's scenarios; it is not a
  third-party certification or a claim about production traffic.
- PostgreSQL support exists in the schema and compose profile but SQLite is the
  exercised default in this repository's verification.
