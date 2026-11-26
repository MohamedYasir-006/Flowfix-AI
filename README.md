# AgentGuard

**Multi-agent runtime security, workflow reliability, and failure-propagation
intelligence.**

AgentGuard is the control plane between AI agents and the tools they can call.
Every proposed action is authenticated, schema-validated, risk-scored, and
checked against deterministic policy **before** it runs. V2 also evaluates the
provenance and trustworthiness of the upstream information an action depends on,
contains failing agents, tracks saga-style transactions, and explains the
result. High-impact actions pause for a human decision, and every outcome lands
in an append-only, redacted, hash-chained audit trail.

> **The core proof:** an agent cannot perform a protected action unless
> AgentGuard explicitly authorizes it — and a policy `DENY` can never be
> overridden by propagation, reliability, risk scoring, or an approval.

V2 documentation:

- [V2 architecture](Docs/V2_ARCHITECTURE.md)
- [Security model and limitations](Docs/V2_SECURITY_MODEL.md)
- [Failure-propagation semantics](Docs/FAILURE_PROPAGATION.md)
- [AFPB benchmark methodology and verified run](Docs/AFPB_BENCHMARK.md)
- [V2 API reference](Docs/API_V2.md)
- [Migration guide](Docs/V2_MIGRATION.md)
- [Final engineering report](Docs/V2_ENGINEERING_REPORT.md)

---

## Table of contents

- [Why AgentGuard](#why-agentguard)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
  - [Option A — Docker (recommended)](#option-a--docker-recommended)
  - [Option B — Windows launcher](#option-b--windows-launcher)
  - [Option C — Local development](#option-c--local-development)
- [Demo scenario](#demo-scenario)
  - [V2 failure-propagation demo](#v2-failure-propagation-demo)
- [Python SDK](#python-sdk)
- [Policy engine](#policy-engine)
  - [Decision precedence](#decision-precedence)
  - [Rule fields](#rule-fields)
  - [Example policy document](#example-policy-document)
  - [Example decision response](#example-decision-response)
- [Architecture](#architecture)
  - [V2 intelligence layer](#v2-intelligence-layer)
  - [System diagram](#system-diagram)
  - [Request lifecycle](#request-lifecycle)
  - [Critical security invariant](#critical-security-invariant)
  - [Data model](#data-model)
- [API reference](#api-reference)
  - [V1 endpoints](#v1-endpoints)
  - [V2 endpoints](#v2-endpoints)
- [Configuration](#configuration)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Security model](#security-model)
- [Roadmap and known gaps](#roadmap-and-known-gaps)
- [Design references](#design-references)

---

## Why AgentGuard

AI agents can plan and execute multi-step tasks, call external tools, access
data, and trigger consequential actions. Without a governance layer, teams
struggle to:

- Know which agent initiated an action and why.
- Enforce consistent permissions across agents and tools.
- Detect prompt injection, data leakage, unsafe tool calls, or policy violations.
- Stop — or require approval for — high-impact actions.
- Know whether the data an action depends on is valid, fresh, and from a
  trustworthy producer.
- Contain a failing agent before its bad output cascades into other agents and
  workflows.
- Investigate incidents with reliable traces and audit records.

AgentGuard provides a single policy decision point with three possible
outcomes for every action: **ALLOW**, **DENY**, or **REQUIRE_APPROVAL**. V2 adds
a second, deterministic question over the same action: **is its upstream
evidence trustworthy, and what breaks if it is not?**

### Non-goals

- Building or training a foundation model.
- Guaranteeing detection of every prompt injection or hallucination.
- Replacing the identity provider, secrets manager, SIEM, or enterprise IAM.
- Executing arbitrary tools directly from the dashboard.
- Supporting every agent framework on day one (the core is framework-neutral;
  integration happens through the SDK or HTTP API).

---

## What it does

| Capability | Detail |
| --- | --- |
| **Agent registry** | Create, view, update, enable/disable, and delete agents. Each has a unique ID, name, owner, environment, status, and a hashed credential. Credential rotation supported. |
| **Tool registry** | Register tools with a name, description, input schema, risk category, and default risk level. Tools can be disabled individually. |
| **Least privilege** | Per-agent tool permissions. Unregistered tools and unpermitted tools are denied by default. |
| **Policy engine** | Deterministic evaluation with `ALLOW` / `DENY` / `REQUIRE_APPROVAL`. Every decision carries machine-readable reason codes and a human-readable explanation. |
| **Risk scoring** | Explainable signals: tool category, declared risk, environment, and destination. No model calls in the critical path, so evaluation stays fast and deterministic. |
| **Human approvals** | Approval requests bound to a canonical payload hash, expiring after a configurable TTL, consumable exactly once, and re-validated against current policy before execution. |
| **Audit trail** | Every decision, approval, execution, and administrative change is recorded with redaction applied before persistence. |
| **Dashboard** | Overview, Agents, Tools, Policies, Approvals, Activity, and Settings screens. |
| **Python SDK** | Fail-closed interception. Timeouts, connection errors, malformed responses, and pending approvals all raise — nothing executes unless an explicit `ALLOW` is returned. |
| **Rate limiting** | Fixed-window per-agent limiter on the decision endpoint. Exceeding it returns `429` with a `Retry-After` header. |
| **V2 — Provenance** | Agent outputs are recorded with integrity hashes, parents, expiry, and validation status. Declarative validators and human verification produce auditable evidence. |
| **V2 — Failure propagation** | The decision service walks the upstream artifact/dependency graph. Invalid, quarantined, expired, stale, conflicting, or unverified high-impact inputs restrict the action. It can only deny or require approval. |
| **V2 — Reliability and containment** | Confidence-aware reliability scoring, automatic quarantine, circuit breakers, and an explicit recovery gate. Quarantined agents are denied before policy runs. |
| **V2 — Transactions** | Saga-style step tracking with idempotency, partial-failure state, recovery plans, and explicitly approved compensation. Compensation is not claimed as guaranteed rollback. |
| **V2 — Incidents and replay** | Incidents preserve origin, blast radius, and evidence. Timelines merge audit/artifact/risk/transaction events. What-if simulation is read-only. |
| **V2 — Tenancy and audit integrity** | Tenant-scoped records derived from credentials, per-tenant SHA-256 audit hash chain, checkpoints, and export. |
| **V2 — AFPB benchmark** | Eight real, isolated failure-propagation scenarios comparing policy-only ablation with the full V2 service. |

---

## Quick start

### Option A — Docker (recommended)

Requires Docker Desktop (or Docker Engine + the Compose plugin).

```bash
# from the repository root
docker compose up --build
```

Then open:

| URL | Purpose |
| --- | --- |
| <http://localhost:8080> | Dashboard |
| <http://localhost:8000/api/docs> | Interactive API documentation |
| <http://localhost:8000/api/v1/health> | Health check |

The default profile uses **SQLite**, stored on a named volume, so the stack runs
with no external dependencies. Data survives container restarts.

To use **PostgreSQL** instead:

```bash
docker compose --profile postgres up --build
```

Then point the backend at it:

```bash
export AGENTGUARD_DATABASE_URL=postgresql+psycopg2://agentguard:agentguard@localhost:5432/agentguard
```

Useful commands:

```bash
docker compose ps              # status of both services
docker compose logs -f backend # follow backend logs
docker compose stop            # stop the stack
docker compose down -v         # stop and delete all data
```

### Option B — Windows launcher

Double-click **`start.bat`**, or run it from a terminal. The script:

1. Checks that Docker is installed, the daemon is running, and the Compose
   plugin is available.
2. Starts the stack (building images if requested).
3. Polls the backend health endpoint until it responds.
4. Waits for the dashboard.
5. Opens the dashboard in your default browser.

```bat
start.bat                    REM normal start (SQLite)
start.bat --build            REM rebuild images first
start.bat --postgres         REM use PostgreSQL instead of SQLite
start.bat --build --postgres REM both
start.bat --stop             REM stop the stack
start.bat --clean            REM stop and delete volumes
```

### Option C — Local development

**Backend:**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev                       # proxies /api to localhost:8000
```

The dashboard connects to the **live AgentGuard API** by default. Set
`VITE_USE_MOCK=true` to use the in-browser demo dataset when the backend is not
running. The mode is shown in the sidebar footer.

If port `8000` is already used by another application, either stop that process
or start the backend on another port and point Vite at it:

```bash
VITE_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

`start.bat --local` performs this port selection automatically and passes the
chosen target to Vite.

---

## Demo scenario

The seeded workspace implements the blueprint's worked example: a support agent
that can search a knowledge base, must get a human to approve outbound email,
and is prohibited from deleting customer records.

### Seeded entities

| Entity | Name | Notes |
| --- | --- | --- |
| Agent | `support-agent` | prod, active, owns 4 tools |
| Agent | `data-analyst-agent` | prod, active |
| Agent | `dev-scout-agent` | dev, active |
| Agent | `legacy-reporter-agent` | staging, **disabled** |
| Tool | `search_knowledge_base` | read, LOW risk |
| Tool | `send_email` | external, HIGH risk |
| Tool | `delete_customer_record` | destructive, CRITICAL risk |
| Tool | `query_sales_db` | read, MEDIUM risk |
| Tool | `create_jira_ticket` | write, MEDIUM risk |
| Tool | `deploy_service` | write, HIGH risk, **disabled** |

### Run the sample agent

```bash
cd backend

# Print a fresh API key for the support agent
python scripts/demo_key.py

export AGENTGUARD_API_KEY=<that key>
export AGENTGUARD_BASE_URL=http://127.0.0.1:8000/api

# Against the Docker stack
PYTHONPATH=../sdk/python python scripts/demo_agent.py
```

### Expected output

```
======================================================================
AgentGuard demo scenario
======================================================================

▶ agent proposes: search_knowledge_base({'query': 'refund policy'})
  ✅ ALLOW — tool executed, result: {'results': [...], 'count': 1}

▶ agent proposes: send_email({'to': 'customer@example.com', ...})
  ⏸ REQUIRE_APPROVAL — tool did NOT execute. approval_id=... expires_at=...

▶ agent proposes: delete_customer_record({'customer_id': 'cust-8812', ...})
  ⛔ DENY — tool did NOT execute.
     reason_codes=['EXPLICIT_DENY_RULE', 'DESTRUCTIVE_OPERATION',
                   'PRODUCTION_ENVIRONMENT', 'PRIVILEGED_TOOL']

======================================================================
Execution log (proof of what actually ran):
  • search_knowledge_base(query='refund policy')

✅ Enforcement verified: the destructive tool never executed.
```

The execution log is the point: only the allowed tool ran. The script exits
non-zero if the prohibited tool ever executes.

### V2 failure-propagation demo

The V1 demo proves policy enforcement. The V2 demo proves the additional
runtime guarantees using real service code in an isolated temporary SQLite
database (it does not touch your workspace database and does not execute tools):

```bash
cd backend
python scripts/demo_v2.py
```

It verifies:

1. an action depending on an `INVALID` upstream artifact is `DENY`ed;
2. an `UNVERIFIED` high-impact input requires approval, and if the artifact
   becomes `INVALID` after the human approval, the retry is denied with
   `PROPAGATION_BLOCKED_AFTER_APPROVAL` and the approval is **not consumed**;
3. a quarantined agent is denied before policy evaluation, then returns to
   `ACTIVE` through the explicit recovery gate;
4. a saga transaction reaches `RECOVERY_REQUIRED`, compensation waits for
   approval, then completes and records per-step compensation status;
5. the tenant audit hash chain verifies.

Expected final line:

```
Result: 17 passed, 0 failed
```

See [FAILURE_PROPAGATION.md](Docs/FAILURE_PROPAGATION.md) and
[V2_ARCHITECTURE.md](Docs/V2_ARCHITECTURE.md) for the semantics behind each
check.

### Walkthrough in the dashboard

1. Open <http://localhost:8080> → **Overview** shows active agents, actions
   today, blocked today, and pending approvals.
2. Run the demo agent (above).
3. Open **Approvals** → the `send_email` request is `PENDING`, with a redacted
   argument summary and its payload hash.
4. Open it and choose **Approve and allow execution**.
5. Re-run the demo agent — the email now executes, and the approval is
   consumed. Re-running again cannot reuse it.
6. Open **Activity** to see the full trail: the ALLOW, the
   REQUIRE_APPROVAL, the approval decision, the DENY, and the execution result.

---

## Python SDK

The SDK is the enforcement boundary an agent actually calls.

### Installation

```bash
pip install -e backend/sdk/python
```

### Basic usage

```python
from agentguard import AgentGuardClient, GuardDenied, ApprovalRequired, call_guarded

guard = AgentGuardClient(
    base_url="http://127.0.0.1:8000/api",
    api_key="ag_...",
)

try:
    result = call_guarded(
        guard,
        tool="search_knowledge_base",
        arguments={"query": "refund policy"},
        execute=search_knowledge_base,
    )
except GuardDenied as exc:
    # The tool did NOT run. exc.reason_codes explains why.
    print("Denied:", exc.reason_codes)
except ApprovalRequired as exc:
    # Paused. exc.approval_id can be shown to a human approver.
    print("Needs approval:", exc.approval_id)
```

### Waiting for an approval

`call_guarded` can poll for an approval and then re-evaluate before executing
exactly once:

```python
result = call_guarded(
    guard,
    tool="send_email",
    arguments={"to": "customer@example.com", "subject": "Hi", "body": "..."},
    target="customer@example.com",
    execute=send_email,
    approval_timeout=300,   # wait up to 5 minutes
    poll_interval=3,
)
```

The flow is: evaluate → `REQUIRE_APPROVAL` → poll → approved → **fresh policy
check** → execute once. If policy changed to deny in the meantime, the action is
refused and the approval is not consumed.

### Exception hierarchy

| Exception | Meaning | Tool executed? |
| --- | --- | --- |
| `GuardDenied` | Policy returned `DENY` | No |
| `ApprovalRequired` | Action paused pending approval | No |
| `GuardTransportError` | Unreachable, timeout, or malformed response | No |
| `AgentGuardError` | Base class for all of the above | — |

### Fail-closed contract

The SDK treats every non-authorizing outcome as "do not execute":

- connection refused / DNS failure → `GuardTransportError`
- request timeout → `GuardTransportError`
- HTTP 4xx/5xx → `GuardTransportError`
- malformed JSON → `GuardTransportError`
- missing `action_id` → `KeyError` (response is invalid)
- `REQUIRE_APPROVAL` → `ApprovalRequired`
- `DENY` → `GuardDenied`

### V2 workflow and provenance usage

The SDK can create workflow context, record artifacts, and pass that context to
the guarded call. Propagation is evaluated only when workflow context is
supplied; V1 calls keep working unchanged.

```python
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

try:
    result = call_guarded(
        guard,
        tool="send_email",
        arguments={"to": "customer@example.com", "subject": "Hi", "body": "..."},
        target="customer@example.com",
        execute=send_email,
        workflow_execution_id=execution["id"],
        agent_execution_id=agent_run["id"],
        input_artifact_ids=[artifact["id"]],
    )
except GuardDenied as exc:
    # Includes propagation reasons such as INVALID_UPSTREAM_ARTIFACT.
    print(exc.reason_codes)
```

Additional v2 methods include `validate_artifact`, `verify_artifact`,
`artifact_lineage`, `downstream_impact`, `preview_risk`, `agent_health`,
`agent_reliability`, `list_incidents`, `incident_report`, `what_if`,
`create_transaction`, `start_transaction_step`, `complete_transaction_step`,
`compensation_plan`, `verify_audit_chain`, and `run_afpb_benchmark`. The SDK
version is `0.2.0`.

---

## Policy engine

The engine is deterministic: the same policy version and normalized input
always produces the same decision. No model calls are involved.

### Decision precedence

Evaluated top to bottom; the first match wins.

| # | Condition | Decision |
| --- | --- | --- |
| 1 | Disabled agent | `DENY` |
| 2 | Disabled or unregistered tool | `DENY` |
| 3 | Missing agent-tool permission | `DENY` |
| 4 | No active policy published | `DENY` |
| 5 | Explicit deny rule matches | `DENY` |
| 6 | Approval rule matches | `REQUIRE_APPROVAL` |
| 7 | Allow rule matches and risk is within its ceiling | `ALLOW` |
| 8 | Risk level requires approval under workspace settings | `REQUIRE_APPROVAL` |
| 9 | No matching allow rule | `DENY` (default deny) |

Two invariants always hold:

- **An explicit deny overrides an allow.** A deny rule in any active policy
  wins, even when an allow rule also matches.
- **A human approval never overrides a hard deny.** Approval rules are skipped
  when a deny rule matches.

### Rule fields

A rule matches when **every field it specifies** matches the request. Unset
fields are wildcards.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Unique rule identifier, used in reason codes |
| `effect` | `ALLOW` \| `DENY` \| `REQUIRE_APPROVAL` | Outcome when matched |
| `agent` | string | Agent name |
| `tool` | string | Tool name |
| `environment` | `dev` \| `staging` \| `prod` | Agent environment |
| `category` | `read` \| `write` \| `external` \| `destructive` | Tool category |
| `riskMax` | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` | Ceiling for `ALLOW` rules |

### Example policy document

```json
{
  "name": "Default production policy",
  "version": 3,
  "default_effect": "DENY",
  "rules": [
    {
      "id": "allow-read-docs",
      "effect": "ALLOW",
      "agent": "support-agent",
      "tool": "search_knowledge_base",
      "riskMax": "MEDIUM"
    },
    {
      "id": "approve-outbound-email",
      "effect": "REQUIRE_APPROVAL",
      "tool": "send_email",
      "environment": "prod"
    },
    {
      "id": "allow-email-after-approval",
      "effect": "ALLOW",
      "tool": "send_email",
      "environment": "prod"
    },
    {
      "id": "deny-delete",
      "effect": "DENY",
      "tool": "delete_customer_record"
    }
  ]
}
```

The `allow-email-after-approval` rule is what lets an approved email execute:
once the approval satisfies the approval rule, the engine falls through to the
matching allow rule.

### Example decision response

```json
{
  "action_id": "8a5b9e9a-0000-4000-8000-000000000001",
  "decision": "REQUIRE_APPROVAL",
  "risk": {
    "level": "HIGH",
    "reasons": ["EXTERNAL_COMMUNICATION", "PRODUCTION_ENVIRONMENT"]
  },
  "reason_codes": ["POLICY_APPROVAL_REQUIRED"],
  "policy": { "id": "policy-uuid", "version": 3 },
  "approval_id": "approval-uuid",
  "expires_at": "2026-11-10T12:30:00Z"
}
```

### Risk scoring

Risk is `max(tool category baseline, tool default_risk, environment floor)`:

| Signal | Effect |
| --- | --- |
| `destructive` category | CRITICAL |
| `external` category | HIGH |
| `write` category | MEDIUM |
| `read` category | LOW |
| `prod` environment | at least MEDIUM |
| `to` / `recipient` containing `@` | adds `EXTERNAL_DESTINATION` |

Workspace settings can elevate any action whose risk level is in
`require_approval_for` (default `["HIGH", "CRITICAL"]`) to `REQUIRE_APPROVAL`,
even when an allow rule matches.

---

## Architecture

### V2 intelligence layer

V2 keeps the modular monolith and adds deterministic intelligence around the
existing policy decision point:

```
                    ┌──────────────────────────────────────────┐
Agent action ──────►│  Identity + schema + payload checks      │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Operational gate                        │
                    │  quarantine / circuit breaker            │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Workflow context + provenance edges      │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Deterministic policy                    │
                    │  explicit DENY always wins                │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Failure propagation                     │
                    │  NONE / REQUIRE_APPROVAL / DENY          │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Reliability friction (approval only)     │
                    │  explainable risk + incident + audit      │
                    └──────────────────┬───────────────────────┘
                                       ▼
                         Effective decision (DENY final)
```

Propagation, reliability, containment, and risk aggregation can only restrict an
action. They never turn a policy `DENY` into `ALLOW`. See
[V2_ARCHITECTURE.md](Docs/V2_ARCHITECTURE.md).

### System diagram

```
┌───────────────────────┐        ┌──────────────────────────────┐
│   Admin / Approver    │        │     AI Agent Application     │
│    Web Dashboard      │        │  (LangChain / custom / etc.) │
└───────────┬───────────┘        └──────────────┬───────────────┘
            │  bearer token                    │  X-Agent-Key
            ▼                                   ▼
┌───────────────────────┐        ┌──────────────────────────────┐
│   React dashboard     │        │      AgentGuard SDK          │
│  Overview/Agents/...  │        │  evaluate() / call_guarded() │
└───────────┬───────────┘        └──────────────┬───────────────┘
            │ REST /api/v1                     │ HTTPS
            ▼                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentGuard backend (FastAPI)             │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Auth & RBAC  │  │ Agent / Tool │  │ Policy decision  │  │
│  │              │  │ registry     │  │ engine           │  │
│  └──────────────┘  └──────────────┘  └────────┬─────────┘  │
│                                              │            │
│  ┌──────────────┐  ┌──────────────┐           │            │
│  │ Approval     │  │ Risk rules   │◄──────────┘            │
│  │ workflow     │  │ & scoring    │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Audit        │  │ Redaction    │  │ Rate limiting    │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
                 ┌────────────────────────┐
                 │  SQLite (default) or   │
                 │  PostgreSQL            │
                 └────────────────────────┘
```

### Request lifecycle

1. The agent calls the AgentGuard SDK with a proposed tool action.
2. The SDK sends the agent credential, session context, tool name, target, and
   validated arguments to `/api/v1/decisions/evaluate`.
3. The backend authenticates the agent credential. A client-supplied
   `agent_id` that does not match the credential is denied.
4. The backend resolves the tool registration and the agent's environment.
5. Arguments are checked against the tool's input schema; oversized payloads
   are rejected.
6. The operational gate denies quarantined agents and open circuit breakers.
7. Workflow context is validated and consumed artifacts are recorded as
   provenance edges.
8. Deterministic risk rules compute a risk category and reason list; the policy
   engine evaluates permissions and all active policy rules.
9. Failure propagation evaluates the trusted state of upstream artifacts and
   producers. It can only leave the decision unchanged, require approval, or
   deny.
10. Reliability can add approval friction for workflow-scoped high-impact
    actions. It cannot override a denial.
11. The backend returns one of:
    - `ALLOW` — the SDK may execute the tool.
    - `DENY` — the SDK must not execute the tool.
    - `REQUIRE_APPROVAL` — the SDK must pause; nothing executes yet.
12. For approvals, the backend verifies the approver, payload hash, expiry,
    current policy, **and current propagation state** before returning a fresh
    `ALLOW`.
13. The SDK executes the approved action once and reports success/failure back.
14. The decision, risk evidence, and — for propagation denials — the incident
    are recorded. The audit event is finalized and joins the tenant hash chain.

### Critical security invariant

> **The tool must never execute merely because the agent asked for it.**
>
> Execution is permitted only after a valid `ALLOW` decision, or a valid
> approval followed by a fresh policy **and propagation** check. The SDK must
> treat timeouts, malformed responses, authentication failures, and
> policy-service errors as non-authorizing outcomes.
>
> **A policy `DENY` is final.** Propagation, reliability, risk scoring, and
> approvals may make a decision stricter, never more permissive.

A `REQUIRE_APPROVAL` response never returns an executable approval token to
the agent. The SDK polls for status and then requests a fresh decision.

### Data model

| Table | Purpose |
| --- | --- |
| `users` | Dashboard users with roles: `ADMIN`, `APPROVER`, `AUDITOR`, `DEVELOPER` |
| `agents` | Registered agents; stores a **hashed** credential, never the raw key |
| `tools` | Tool registry with input schema, category, and default risk |
| `agent_tool_permissions` | Many-to-many join granting agents access to tools |
| `policies` | Policy versions with rules as JSON, status `DRAFT` / `ACTIVE` / `ARCHIVED` |
| `approvals` | Approval state machine with payload hash and expiry |
| `audit_events` | Append-only decision, approval, execution, and admin records |
| `settings` | Single-row workspace configuration |

V2 adds tenant and intelligence tables: `organizations`, `workflows`,
`workflow_executions`, `agent_executions`, `artifacts`, `validation_rules`,
`artifact_validations`, `dependencies`, `agent_states`, `circuit_breakers`,
`quarantine_events`, `reliability_snapshots`, `risk_assessments`, `incidents`,
`notifications`, `transactions`, `transaction_steps`, `compensation_actions`,
`policy_versions`, `audit_checkpoints`, and `benchmark_runs`. Existing tables
gained additive `org_id` and approval workflow-context columns. See
[V2_ARCHITECTURE.md](Docs/V2_ARCHITECTURE.md) and
[V2_MIGRATION.md](Docs/V2_MIGRATION.md).

Timestamps are stored as UTC ISO-8601 strings and IDs as UUID strings so the
schema ports cleanly between SQLite and PostgreSQL.

---

## API reference

All endpoints are versioned under `/api/v1`. Full interactive documentation is
available at `/api/docs`. See [API_V2.md](Docs/API_V2.md) for complete V2
contracts and examples.

### V1 endpoints

### Agents and tools

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/agents` | List agents |
| `POST` | `/agents` | Register an agent (returns the plaintext API key **once**) |
| `GET` | `/agents/{id}` | Get an agent |
| `PATCH` | `/agents/{id}` | Update name, owner, or environment |
| `POST` | `/agents/{id}/disable` | Disable an agent (immediate deny) |
| `POST` | `/agents/{id}/enable` | Re-enable an agent |
| `PUT` | `/agents/{id}/permissions` | Replace the agent's tool permissions |
| `POST` | `/agents/{id}/rotate-key` | Rotate the credential (old key stops working) |
| `GET` | `/tools` | List tools |
| `POST` | `/tools` | Register a tool |
| `GET` | `/tools/{id}` | Get a tool |

### Policies and decisions

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/policies` | List policies |
| `POST` | `/policies` | Create a policy draft |
| `GET` | `/policies/{id}` | Get a policy |
| `PUT` | `/policies/{id}` | Edit a draft (published versions are immutable) |
| `POST` | `/policies/{id}/publish` | Publish a draft (increments the version) |
| `POST` | `/decisions/evaluate` | Evaluate a proposed action *(agent-authenticated)* |
| `POST` | `/actions/{id}/result` | Report an execution result *(agent-authenticated)* |

### Approvals and audit

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/approvals` | List approvals (`?status=PENDING`) |
| `GET` | `/approvals/{id}` | Approval detail |
| `POST` | `/approvals/{id}/approve` | Approve |
| `POST` | `/approvals/{id}/reject` | Reject |
| `GET` | `/events` | Search audit events (filters: `decision`, `agent_id`, `tool_name`, `event_type`, `q`) |

### Overview, auth, settings

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/overview` | Dashboard statistics and recent events |
| `POST` | `/auth/login` | Exchange an email for a bearer token |
| `GET` | `/auth/me` | Current user |
| `GET` | `/users` | List users |
| `GET` / `PATCH` | `/settings` | Read / update workspace configuration |
| `GET` | `/health` | Liveness and database check |

### V2 endpoints

| Area | Representative endpoints |
| --- | --- |
| Workflows | `POST/GET /workflows`, `POST /workflows/{id}/executions`, `GET /workflow-executions/{id}`, `POST .../pause`, `.../resume`, `GET .../graph`, `GET .../timeline` |
| Artifacts | `POST/GET /artifacts`, `POST /artifacts/{id}/validate`, `POST /artifacts/{id}/verify`, `GET /artifacts/{id}/lineage`, `POST /artifacts/consumption` |
| Validation rules | `POST/GET /validation-rules`, `DELETE /validation-rules/{id}` |
| Dependencies | `POST/GET /dependencies`, `GET /dependencies/impact`, `GET /agents/{id}/impact` |
| Risk preview | `POST /risk/evaluate` — read-only, labelled `PREVIEW_ONLY` |
| Operations | `GET /agents/{id}/health`, `GET /reliability`, `GET /containment/circuits`, `POST /agents/{id}/quarantine`, `POST /agents/{id}/recovery/start`, `POST .../recovery/complete` |
| Incidents | `GET /incidents`, `GET /incidents/summary`, `GET /incidents/{id}/report`, `POST /incidents/{id}/resolve`, `POST /incidents/what-if` |
| Transactions | `POST/GET /transactions`, `GET /transactions/{id}/recovery-plan`, `POST .../steps/{ref}/start`, `.../complete`, `POST .../compensate` |
| Benchmarks | `POST /benchmarks/afpb/run`, `GET /benchmarks/runs` |
| Audit | `GET /audit/verify`, `POST /audit/checkpoint`, `GET /audit/checkpoints`, `GET /audit/events` |

The decision endpoint also accepts optional `workflow_execution_id`,
`agent_execution_id`, and `input_artifact_ids`. Responses add optional
`explanation`, `risk_score`, `risk_assessment_id`, `propagation`, and
`operational_status` fields.

### Evaluate request

```json
{
  "session_id": "session-123",
  "tool": "send_email",
  "target": "customer@example.com",
  "arguments": {
    "to": "customer@example.com",
    "subject": "Account update",
    "body": "..."
  }
}
```

Optional fields: `environment`, `agent_id` (must match the credential),
`approval_id`, `idempotency_key`, and the V2 workflow context
`workflow_execution_id`, `agent_execution_id`, and `input_artifact_ids`.

---

## Configuration

All backend settings are environment variables prefixed `AGENTGUARD_`. See
[`backend/.env.example`](backend/.env.example) for a ready-to-copy template.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./agentguard.db` | SQLAlchemy connection string |
| `AUTH_REQUIRED` | `false` | Require bearer tokens for dashboard endpoints |
| `AUTH_SECRET` | `dev-secret-change-me` | HMAC secret for dashboard tokens (**change in production**) |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated allowed browser origins |
| `SEED_DEMO_DATA` | `true` | Seed the demo workspace on startup |
| `DECISION_RATE_LIMIT` | `60` | Decisions allowed per agent per window |
| `DECISION_RATE_WINDOW_SECONDS` | `60` | Rate-limit window length |
| `APPROVAL_TTL_MINUTES` | `240` | Approval expiry |
| `MAX_PAYLOAD_BYTES` | `65536` | Reject larger tool argument payloads |
| `REDACT_SECRETS` | `true` | Redact secrets before persistence |
| `RETENTION_DAYS` | `90` | Audit retention (stored; enforcement is a roadmap item) |

V2 intelligence settings (all policy defaults, echoed in decision evidence):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PROPAGATION_MAX_DEPTH` | `12` | Maximum upstream traversal depth. |
| `PROPAGATION_REPEATED_FAILURE_THRESHOLD` | `3` | Producer failure count treated as repeated failure. |
| `CONTAINMENT_FAILURE_THRESHOLD` | `3` | Failures before quarantine/circuit open. |
| `CIRCUIT_OPEN_SECONDS` | `60` | Cooldown before `OPEN → HALF_OPEN`. |
| `RELIABILITY_WINDOW_DAYS` | `30` | Reliability observation window. |
| `RELIABILITY_MIN_OBSERVATIONS` | `5` | Below this, level is `INSUFFICIENT` (never trusted). |
| `RELIABILITY_MEDIUM_THRESHOLD` | `60.0` | Medium score threshold. |
| `RELIABILITY_HIGH_THRESHOLD` | `80.0` | High score threshold. |
| `RELIABILITY_PRIOR_MEAN` | `0.8` | Beta-style smoothing prior mean. |
| `RELIABILITY_PRIOR_STRENGTH` | `5.0` | Smoothing prior strength. |
| `ARTIFACT_DEFAULT_TTL_MINUTES` | `1440` | Default artifact TTL setting. |
| `BENCHMARK_TIMEOUT_SECONDS` | `120` | Benchmark run timeout setting. |
| `TRANSACTION_COMPENSATION_REQUIRES_APPROVAL` | `true` | Gate compensation behind explicit approval. |

Per-tenant propagation effects are configurable through
`settings.propagation_policy`; unknown keys are ignored. Effective values are
returned in each propagation result.

**Port mapping** (via the environment or `.env` at the repo root):

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKEND_PORT` | `8000` | Host port for the API |
| `FRONTEND_PORT` | `8080` | Host port for the dashboard |
| `POSTGRES_PORT` | `5432` | Host port for PostgreSQL (postgres profile) |

### Frontend environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_USE_MOCK` | `false` | Use the in-browser demo dataset instead of the API |
| `VITE_API_BASE_URL` | `/api/v1` | API base URL |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Dev-server proxy target |

---

## Testing

```bash
# Backend: 171 tests — policy precedence, decisions, approvals,
# API contract, rate limiting, SDK fail-closed behavior, import integrity,
# and V2 provenance/propagation/containment/saga/tenancy/audit-chain invariants
cd backend
pip install -e ".[dev]"
pytest

# Frontend: renders the real app into jsdom and asserts the shell works
cd frontend
npm run smoke

# Production build with type checking
npm run build

# Lint
npm run lint

# V2 end-to-end behavior demo (isolated database, no external tools)
cd backend
python scripts/demo_v2.py

# V2 AFPB benchmark (via a running API)
curl -X POST http://127.0.0.1:8000/api/v1/benchmarks/afpb/run \
  -H "Content-Type: application/json" -d '{"suite":"AFPB","seed":7}'
```

### Test coverage areas

- **Policy** — every precedence rule, rule matching, `riskMax` ceilings, risk
  ordering, approval-rule suppression after a grant.
- **Decisions** — allow/deny, unregistered and disabled agents and tools,
  missing permissions, agent-ID and environment mismatch, schema validation,
  idempotency replay, audit completeness, redaction.
- **Approvals** — creation, rejection, approval, single-use consumption,
  payload-hash binding, expiry, cross-agent reuse, deny-after-approval.
- **API** — authentication, RBAC, credential rotation, registry CRUD,
  approvals queue, event search, overview shape.
- **Rate limiting** — limiter mechanics and the 429 path.
- **SDK** — decision parsing, fail-closed on every transport failure, no
  execution on deny or pending approval, result reporting, approval polling.
- **Import integrity** — every module imported in a fresh interpreter with all
  annotations resolved, which catches missing imports that local tests can mask.
- **V2 provenance** — validation evidence, invalid status, lineage, integrity
  and expiry behavior.
- **V2 propagation** — invalid/quarantined upstream denial, unverified
  high-impact approval, clean upstream control, post-approval re-denial.
- **V2 containment** — quarantine denial, recovery authorization, unresolved
  invalid output blocking release.
- **V2 transactions** — idempotent creation, duplicate in-flight rejection,
  partial failure, compensation approval and completion.
- **V2 tenancy and audit** — cross-tenant context rejection, ignored
  organization header, hash-chain verification, tamper detection, checkpoints.
- **V2 API and benchmark** — health/reliability/audit/incident endpoints and a
  real AFPB run through the test client.

### Acceptance checklist

- [x] Unregistered agent is denied
- [x] Disabled agent is denied
- [x] Unregistered tool is denied
- [x] Agent without tool permission is denied
- [x] Explicit deny overrides allow
- [x] No matching allow rule results in deny
- [x] Approval-required action is not executed while pending
- [x] Rejected and expired approvals cannot execute
- [x] Modified payload cannot reuse approval
- [x] Approved action is re-evaluated before execution
- [x] Every decision creates an audit record
- [x] Secrets are redacted from stored events
- [x] Dashboard roles prevent unauthorized approval
- [x] Invalid upstream artifact denies a policy-allowed action
- [x] Quarantined upstream producer denies a dependent action
- [x] Unverified high-impact input requires approval
- [x] Post-approval propagation denial does not consume the approval
- [x] A quarantined agent is denied before policy evaluation
- [x] Recovery refuses unresolved invalid outputs
- [x] Partial transaction failure requires recovery
- [x] Compensation requires explicit approval and records step status
- [x] Cross-tenant workflow/artifact IDs are rejected
- [x] Audit chain verifies and detects tampering
- [x] AFPB scenario suite passes against real service code

---

## Project structure

```
agentguard/
|-- backend/
|   |-- app/
|   |   |-- main.py              # FastAPI app, lifespan, exception handlers
|   |   |-- config.py            # Environment-driven settings (V1 + V2)
|   |   |-- db.py                # Engine, session factory, schema bootstrap
|   |   |-- migrations.py        # Additive, versioned V2 migrations
|   |   |-- models.py            # V1 + V2 SQLAlchemy models
|   |   |-- schemas.py           # V1 contracts + optional V2 decision fields
|   |   |-- schemas_v2.py        # V2 workflow/provenance/ops contracts
|   |   |-- policy.py            # Deterministic policy engine
|   |   |-- risk.py              # V1 risk scoring
|   |   |-- deps.py              # Auth, tenant resolution, RBAC
|   |   |-- routers/             # V1 + V2 HTTP endpoints
|   |   |   |-- agents.py  tools.py  policies.py  decisions.py
|   |   |   |-- approvals.py  events.py  overview.py  auth.py
|   |   |   |-- users.py  settings.py  health.py
|   |   |   |-- workflows.py  artifacts.py  dependencies.py
|   |   |   |-- risk.py  operations.py  incidents.py
|   |   |   |-- transactions.py  benchmarks.py  audit.py
|   |   |-- services/            # Business logic
|   |       |-- agents.py  tools.py  policies.py  approvals.py
|   |       |-- decisions.py     # Central decision point (V1 + V2)
|   |       |-- provenance.py  dependencies.py  propagation.py
|   |       |-- reliability.py  containment.py  risk_engine.py
|   |       |-- incidents.py  transactions.py  benchmarks.py
|   |       |-- audit.py         # Append-only events + hash chain
|   |       |-- settings.py
|   |-- sdk/python/agentguard/   # Python SDK 0.2.0
|   |   |-- client.py            # Fail-closed HTTP client + V2 methods
|   |   |-- guard.py             # call_guarded, approval polling, context
|   |   |-- exceptions.py        # Exception hierarchy
|   |-- scripts/
|   |   |-- demo_agent.py        # V1 policy enforcement demo
|   |   |-- demo_v2.py           # V2 propagation/containment/saga/audit demo
|   |   |-- demo_key.py          # Agent credential helper
|   |-- tests/                   # pytest suite (V1 + V2)
|-- frontend/
|   |-- src/
|   |   |-- pages/               # Overview, Agents, Tools, Policies,
|   |   |                        #   Approvals, Activity, Settings,
|   |   |                        #   Operations, Provenance, Incidents,
|   |   |                        #   Transactions, Benchmarks
|   |   |-- components/          # Layout, modal, UI primitives, toasts
|   |   |-- api/                 # HTTP client (v1 + v2), mock layer
|   |   |-- types/               # Shared TypeScript contracts
|   |   |-- styles/              # Design tokens
|   |-- scripts/                 # Smoke test and Node loader hooks
|   |-- Dockerfile
|   |-- nginx.conf.template      # Serves the SPA and proxies /api
|-- Docs/
|   |-- AgentGuard_Project_Blueprint.md
|   |-- PHASE0_REPOSITORY_AUDIT.md
|   |-- V2_ARCHITECTURE.md
|   |-- V2_SECURITY_MODEL.md
|   |-- FAILURE_PROPAGATION.md
|   |-- AFPB_BENCHMARK.md
|   |-- API_V2.md
|   |-- V2_MIGRATION.md
|   |-- V2_ENGINEERING_REPORT.md
|-- docker-compose.yml           # backend + frontend + optional postgres
|-- start.bat                    # Windows launcher
|-- .gitignore
|-- README.md
```

---

## Security model

### Guarantees

- Agent API keys are **SHA-256 hashed**; plaintext is returned exactly once.
- Tool arguments are **schema-validated** before policy evaluation.
- Payloads are **bounded** in size before evaluation.
- Approvals are bound to a **canonical payload hash** and **consumed once**.
- Policy is **re-evaluated immediately before** any approved execution.
- Secrets are **redacted** before anything is written to the audit store.
- The decision endpoint is **rate-limited per agent**.
- Client-supplied `agent_id` and `environment` are verified against the
  authenticated credential, never trusted.
- Idempotency keys prevent duplicate decision records on retry.
- V2 tenant identity is derived from the credential; organization headers are
  ignored.
- V2 approvals are revalidated against current policy **and current propagation
  state** before execution.
- V2 workflow context and artifact IDs are tenant-scoped; cross-tenant IDs are
  rejected.
- V2 containment denies quarantined agents before policy evaluation.
- V2 recovery requires an authorized admin, explicit confirmation, and no
  unresolved invalid outputs.
- V2 audit events are hash-chained per tenant; checkpoints can be anchored
  externally.

See [V2_SECURITY_MODEL.md](Docs/V2_SECURITY_MODEL.md) for the full trust model,
residual risks, and explicit limitations.

### Threat model

| Threat | Mitigation |
| --- | --- |
| Spoofing (stolen agent key) | Hashed credentials, rotation, revocation by disable |
| Tampering (action changed after approval) | Canonical payload hash binding |
| Repudiation | Append-only audit events with actor and timestamps |
| Information disclosure | Redaction, allowlisted metadata, bounded payloads |
| Denial of service | Per-agent rate limiting, request size limits |
| Elevation of privilege | Default deny, least privilege, explicit scopes |
| Prompt injection | Tool output treated as untrusted; permissions enforced outside the model |
| Replay | One-time approval consumption, expiry, idempotency keys |
| Policy bypass | Unregistered tools denied; gateway-side enforcement recommended |
| Approval abuse | Payload hash binding and re-evaluation before execution |
| Stale/invalid upstream data | Deterministic propagation over recorded provenance; deny or approval |
| Failing agent cascade | Quarantine, circuit breakers, reliability friction, incidents |
| Cross-tenant access | Credential-derived tenant; tenant-scoped lookups; ignored org header |
| Duplicate external effects | Transaction idempotency and duplicate step rejection |
| Audit tampering | Per-tenant hash chain, checkpoints, tamper detection (external anchoring required for stronger proof) |
| Competing state transitions | Conditional SQL updates for containment and transaction state |

### Important limitation

**The SDK is not a complete security boundary if the agent can call tools
directly.** AgentGuard governs calls that go through the SDK or the HTTP API.
Protect the tool execution path itself — network egress controls and tool-side
authorization — for defense in depth.

**V2 limitations:** propagation can only reason over provenance the runtime
records; validation proves rule conformance, not semantic truth; compensation is
a new external operation, not a guaranteed rollback; and a hash chain detects
tampering only when an external checkpoint is trusted. These are documented, not
hidden.

---

## Roadmap and known gaps

### Release 1 — operational readiness

- [ ] **Retention enforcement** — `retention_days` is stored and displayed but
      no job purges expired audit events yet.
- [ ] **Dashboard login UI** — bearer tokens and `AUTH_REQUIRED` work, but the
      UI has no login screen; it relies on the seeded-admin fallback when auth
      is off.
- [ ] **User management API** — users can be listed but not created or edited.
- [ ] **Tool create/edit UI** — tools are listed but not created from the
      dashboard.
- [ ] **CI pipeline** — no GitHub Actions workflow yet.
- [ ] **Distributed rate limiting** — the limiter is process-local, correct for
      one uvicorn worker; a multi-instance deployment needs Redis.
- [ ] **PostgreSQL end-to-end validation** — the compose profile and portable
      schema exist, but only SQLite has been exercised in the running stack.

### Release 2 - advanced governance (V2 delivered)

- [x] Multi-tenancy with tenant IDs on V2 records and additive legacy backfill.
- [x] Tenant-scoped audit export.
- [x] Provenance, validation, dependency graph, and failure propagation.
- [x] Reliability scoring, containment, circuit breakers, and recovery gate.
- [x] Saga-style transactions, idempotency, and approved compensation.
- [x] Incidents, timelines, and read-only what-if simulation.
- [x] Audit hash chain, checkpoints, and tamper detection.
- [x] AFPB benchmark with a policy-only ablation and isolated execution.

### Remaining gaps

- [ ] **External audit anchoring** - checkpoints exist, but storing them in an
      external append-only/WORM system is deployment work, not implemented here.
- [ ] **Retention job** - `retention_days` is still stored but not enforced by a
      purge job.
- [ ] **Multi-approver and quorum rules.**
- [ ] **SIEM / alerting integrations** - notifications exist; external delivery
      does not.
- [ ] **Optional model-assisted risk classification** behind a timeout, never
      allowed to override a deterministic deny.
- [ ] **Additional agent-framework adapters.**
- [ ] **Distributed graph/state backend** - only if measured traversal or
      multi-instance contention requires it.

---

## Design references

These informed the design; they are not claims of certification.

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP GenAI Security Project](https://genai.owasp.org/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Playbook](https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook)
- [OpenTelemetry](https://opentelemetry.io/docs/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL documentation](https://www.postgresql.org/docs/)

---

## Status

AgentGuard V2 is implemented and verified in this repository: backend tests,
frontend production build, SDK compilation, the V2 demo, and the AFPB benchmark.
It remains a production-oriented engineering implementation, not a certified
product. The full requirements, roadmap, and threat model are in
[`Docs/AgentGuard_Project_Blueprint.md`](Docs/AgentGuard_Project_Blueprint.md);
V2 behavior and limitations are in the V2 docs linked at the top.

Build around one proof: **an agent cannot perform a protected action unless
AgentGuard explicitly authorizes it — and a `DENY` cannot be overridden.**
