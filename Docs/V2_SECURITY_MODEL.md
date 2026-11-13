# AgentGuard V2 — Security Model

This document states what AgentGuard V2 enforces, what it does not, and which
trust assumptions remain. It is written to be auditable rather than reassuring:
claims here correspond to code paths and tests in the repository.

---

## 1. Security invariants

1. **No execution without explicit authorization.** The SDK executes a tool only
   after an `ALLOW` decision, or after a valid approval followed by a fresh
   `ALLOW`. Every transport or parse failure is non-authorizing.
2. **DENY is final.** Policy `DENY` cannot be overridden by propagation,
   reliability, risk scoring, an approval, or a dashboard action. Propagation and
   reliability can only produce `REQUIRE_APPROVAL` or `DENY`.
3. **Approvals are scoped capabilities, not blanket grants.** They are bound to
   agent, payload hash, tool, target, policy/rule context, workflow execution,
   agent execution, and input artifact IDs. They expire, are single-use, and are
   revalidated against current policy **and current propagation state**.
4. **Tenant identity comes from credentials.** Read endpoints derive `org_id`
   from the agent key or bearer token. A client-supplied organization header is
   not trusted.
5. **Containment fails closed.** Quarantined agents and open circuit breakers are
   denied before policy evaluation. A quarantined agent cannot probe for
   allowances.
6. **Recovery is not authorization.** Releasing quarantine resets containment
   state; it does not grant tool permissions or bypass policy.
7. **Compensation is explicit.** Compensation is a new external operation and
   requires approval when configured. It is never described as a guaranteed
   rollback.
8. **Audit is append-only in application code.** V2 adds a hash chain and
   checkpoints to detect tampering when an external checkpoint is trusted.

---

## 2. Trust boundaries

| Boundary | Trusted? | Notes |
| --- | --- | --- |
| Agent credential | Yes, after hashing comparison | Stored as SHA-256 hash; raw key returned once. |
| Agent-supplied `agent_id`/`environment` | No | Must match the credential. |
| Agent-supplied workflow/artifact IDs | No | Must resolve inside the credential's tenant; cross-tenant IDs are not-found. |
| Agent-supplied artifact content | No | Treated as untrusted until validated or human-verified. |
| Dashboard bearer token | Yes, within role | Roles: `ADMIN`, `APPROVER`, `AUDITOR`, `DEVELOPER`. |
| Client organization header | No | Ignored for tenant resolution. |
| Upstream agent output | No | Validation status and provenance are evidence, not implicit trust. |
| External tool execution | Outside AgentGuard | Must be protected by network/tool-side controls for defense in depth. |

---

## 3. Identity and tenancy

- Agent keys are hashed; plaintext is shown exactly once at creation/rotation.
- Disabling an agent immediately denies decisions. Rotating a key invalidates the
  old key.
- All V2 records carry `org_id`.
- `get_org_id()` resolves a tenant from `X-Agent-Key` or a bearer user token. If
  authentication is disabled for local development and no credential is
  supplied, it falls back to the seeded admin's tenant. It never reads a tenant
  from a request header.
- Cross-tenant reads and writes return not-found to avoid existence leaks.
- The default organization exists for backward compatibility. Legacy rows are
  backfilled once by an additive migration; business rows are not deleted.

---

## 4. Decision and approval security

### Pre-approval

- Identity, environment, payload size, and tool schema are checked first.
- The operational gate runs before policy.
- Workflow context is validated before any approval shortcut.
- Policy `DENY` is preserved.
- Propagation is evaluated over the tenant's current graph.
- Reliability can add approval friction but cannot change a `DENY`.
- Risk aggregation is explainability only; it never authorizes.

### Approval creation

Approvals are created only when the effective decision is `REQUIRE_APPROVAL`.
They persist the payload hash and the exact workflow context required for
post-approval rechecks. `REQUIRE_APPROVAL` never returns an executable token to
the agent.

### Approval consumption

Before execution, AgentGuard checks:

- approval belongs to the agent and tenant;
- status is `APPROVED`, not expired, not previously consumed;
- payload hash matches the current request;
- operational gate still passes;
- current policy still allows (with the approved rule satisfied);
- current propagation no longer denies.

Only then is the approval consumed atomically. If any check fails, the approval
is not consumed and the tool must not run.

---

## 5. Provenance and validation

Validation is declarative and deterministic. Supported validators:

| Validator | What it checks |
| --- | --- |
| `schema` | JSON-Schema-like structural validation of content. |
| `required` | Required field paths are present and non-null. |
| `types` | Declared field types match. |
| `business_rules` | Field comparisons (`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, etc.). |
| `provenance` | Parent artifacts exist and belong to the tenant. |
| `integrity` | Content hash still matches the recorded integrity hash. |
| `expiration` | Artifact has not passed `expires_at`. |
| `source_consistency` | Duplicate logical artifacts do not disagree. |

No validator calls an LLM or the network. A validation failure records
evidence, updates dependent edges, and increments the producer's containment
failure counter. Repeated failures can open a circuit and quarantine the agent.

Human verification sets `VALIDATED` or `REJECTED` and is itself audited. It does
not erase the validation history.

**Limitation:** validation proves conformance to configured rules, not semantic
truth. A well-formed lie still requires provenance, source consistency, human
review, or downstream checks.

---

## 6. Containment and recovery

- Validation and execution failures are counted in `agent_states`.
- At the configured threshold, the circuit opens and the agent is quarantined.
- Quarantine records history, opens an incident, emits a notification, and
  writes an audit event.
- The operational gate denies quarantined agents and open breakers.
- `HALF_OPEN` permits one trial; success closes the breaker, failure reopens it.
- Recovery requires an authorized admin, explicit confirmation, and no
  unresolved invalid outputs.
- Recovery does not bypass policy or grant permissions.

**Limitation:** containment is state in this service. It cannot stop an agent
that bypasses AgentGuard entirely and calls a tool directly. Network egress
controls and tool-side authorization are still required.

---

## 7. Transactions and compensation

- Transaction creation is idempotent per tenant key.
- Step starts use compare-and-set updates so concurrent attempts cannot both
  start the same external operation.
- A completed step is treated as already executed exactly once on replay.
- Partial failure moves to `RECOVERY_REQUIRED`.
- Compensation is only requested by an admin or approver, only for completed
  steps that declare a compensation tool, and waits for approval unless
  explicitly approved.
- A failed compensation records a failure; it does not mark recovery complete.

**Limitation:** compensating actions are new external effects. They may fail,
partially compensate, or have irreversible side effects. AgentGuard records and
gates them; it cannot guarantee rollback.

---

## 8. Audit integrity and limitations

Events are append-only from application code and are redacted before
persistence. V2 chains events per organization using canonical JSON and SHA-256.
`GET /audit/verify` recomputes sequence, previous hash, and event hash.

What the chain proves:

- no individual event was modified without detection, assuming a trusted
  checkpoint;
- no event was inserted or removed without a sequence/hash break;
- the export matches the stored chain fields.

What it does **not** prove:

- immutability against an attacker with full database write access who rewrites
  the whole table and recomputes every hash;
- that the application never had a logic bug;
- that external systems told the truth.

For stronger evidence, export `POST /audit/checkpoint` hashes to an external
append-only store or WORM system.

---

## 9. Threat model additions

| Threat | V2 mitigation | Residual risk |
| --- | --- | --- |
| Stale or invalid upstream data drives a high-impact action | Deterministic propagation, validation status, expiry, parent checks | Dependencies not recorded cannot be enforced. |
| Compromised or failing agent keeps acting | Quarantine, circuit breakers, reliability friction | Agent outside AgentGuard can bypass controls. |
| Approval used with changed upstream evidence | Post-approval propagation recheck; approval not consumed on denial | Approver may still approve ambiguous evidence. |
| Cross-tenant data access via IDs or headers | Credential-derived tenant; tenant-scoped lookups | A compromised credential has that tenant's access. |
| Replay of an approval | Payload binding, expiry, single-use consumption | Replay of a new identical action still needs a new approval. |
| Duplicate external side effects | Transaction idempotency, duplicate step rejection | External tool must honor idempotency keys where available. |
| Audit tampering | Hash chain, checkpoints, tamper detection | Full-database rewrite without external anchoring. |
| Competing failures both mutate state | Conditional SQL updates on containment/transaction transitions | Database isolation semantics still apply. |
| Benchmark claims mistaken for certification | Explicit ablation methodology, isolated execution, documented non-claims | Scenarios are synthetic and limited. |

---

## 10. Deployment requirements and non-claims

For a production deployment:

- set `AGENTGUARD_AUTH_REQUIRED=true`;
- change `AGENTGUARD_AUTH_SECRET`;
- terminate TLS in front of the API;
- restrict CORS to trusted origins;
- protect the database and backups;
- anchor audit checkpoints externally;
- run one rate limiter per process or add a shared limiter before scaling out;
- enforce tool-side authorization and egress policy.

AgentGuard V2 is not certified against any standard. The OWASP/NIST references
in the README informed the design; they are not claims of compliance.
