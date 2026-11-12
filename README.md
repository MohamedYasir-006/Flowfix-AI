# AgentGuard

**AI-agent governance, security, and observability control plane.**

AgentGuard is the layer that sits between an AI agent and the tools it can
call. Every proposed tool action is authenticated, schema-validated,
risk-scored, and checked against deterministic policy **before** the tool is
allowed to run. High-impact actions pause for a human decision, and every
outcome lands in an append-only, redacted audit trail.

> **The core proof:** an agent cannot perform a protected action unless
> AgentGuard explicitly authorizes it.

---

## Table of contents

- [Why AgentGuard](#why-agentguard)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
  - [Option A — Docker (recommended)](#option-a--docker-recommended)
  - [Option B — Windows launcher](#option-b--windows-launcher)
  - [Option C — Local development](#option-c--local-development)
- [Demo scenario](#demo-scenario)
- [Python SDK](#python-sdk)
- [Policy engine](#policy-engine)
  - [Decision precedence](#decision-precedence)
  - [Rule fields](#rule-fields)
  - [Example policy document](#example-policy-document)
  - [Example decision response](#example-decision-response)
- [Architecture](#architecture)
  - [System diagram](#system-diagram)
  - [Request lifecycle](#request-lifecycle)
  - [Critical security invariant](#critical-security-invariant)
  - [Data model](#data-model)
- [API reference](#api-reference)
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
- Investigate incidents with reliable traces and audit records.

AgentGuard provides a single policy decision point with three possible
outcomes for every action: **ALLOW**, **DENY**, or **REQUIRE_APPROVAL**.

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
VITE_USE_MOCK=false npm run dev   # proxies /api to localhost:8000
```

The dashboard defaults to an **in-browser demo dataset** so it works before the
backend exists. Set `VITE_USE_MOCK=false` to bind it to the live API. The mode is
shown in the sidebar footer.

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
6. Deterministic risk rules compute a risk category and reason list.
7. The policy engine evaluates permissions and all active policy rules.
8. The backend returns one of:
   - `ALLOW` — the SDK may execute the tool.
   - `DENY` — the SDK must not execute the tool.
   - `REQUIRE_APPROVAL` — the SDK must pause; nothing executes yet.
9. For approvals, the backend verifies the approver, payload hash, expiry, and
   current policy before returning a fresh `ALLOW`.
10. The SDK executes the approved action once and reports success/failure back.
11. The audit event is finalized and becomes visible in the dashboard.

### Critical security invariant

> **The tool must never execute merely because the agent asked for it.**
>
> Execution is permitted only after a valid `ALLOW` decision, or a valid
> approval followed by a fresh policy check. The SDK must treat timeouts,
> malformed responses, authentication failures, and policy-service errors as
> non-authorizing outcomes.

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

Timestamps are stored as UTC ISO-8601 strings and IDs as UUID strings so the
schema ports cleanly between SQLite and PostgreSQL.

---

## API reference

All endpoints are versioned under `/api/v1`. Full interactive documentation is
available at `/api/docs`.

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
`approval_id`, `idempotency_key`.

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

**Port mapping** (via the environment or `.env` at the repo root):

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKEND_PORT` | `8000` | Host port for the API |
| `FRONTEND_PORT` | `8080` | Host port for the dashboard |
| `POSTGRES_PORT` | `5432` | Host port for PostgreSQL (postgres profile) |

### Frontend environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_USE_MOCK` | `true` | Use the in-browser demo dataset instead of the API |
| `VITE_API_BASE_URL` | `/api/v1` | API base URL |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Dev-server proxy target |

---

## Testing

```bash
# Backend: 133 tests — policy precedence, decisions, approvals,
# API contract, rate limiting, SDK fail-closed behavior, import integrity
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

---

## Project structure

```
agentguard/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, exception handlers
│   │   ├── config.py            # Environment-driven settings
│   │   ├── db.py                # Engine, session factory, schema bootstrap
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── schemas.py           # Pydantic request/response contracts
│   │   ├── policy.py            # Deterministic policy engine
│   │   ├── risk.py              # Explainable risk scoring
│   │   ├── ratelimit.py         # Fixed-window rate limiter
│   │   ├── redaction.py         # Secret redaction before persistence
│   │   ├── validation.py        # Tool argument schema validation
│   │   ├── security.py          # Credential hashing, token issuance
│   │   ├── deps.py              # Auth dependencies and RBAC
│   │   ├── errors.py            # Typed errors with reason codes
│   │   ├── seed.py              # Demo workspace seed
│   │   ├── routers/             # HTTP endpoints
│   │   │   ├── agents.py  tools.py  policies.py
│   │   │   ├── decisions.py  approvals.py  events.py
│   │   │   ├── overview.py  auth.py  users.py  settings.py  health.py
│   │   └── services/            # Business logic
│   │       ├── agents.py  tools.py  policies.py
│   │       ├── decisions.py  approvals.py  audit.py  settings.py
│   ├── sdk/python/agentguard/   # Python SDK
│   │   ├── client.py            # HTTP client, fail-closed
│   │   ├── guard.py             # call_guarded, approval polling
│   │   └── exceptions.py        # Exception hierarchy
│   ├── scripts/
│   │   ├── demo_agent.py        # Sample agent + mock tools
│   │   └── demo_key.py          # Agent credential helper
│   └── tests/                   # pytest suite
├── frontend/
│   ├── src/
│   │   ├── pages/               # Overview, Agents, Tools, Policies,
│   │   │                        #   Approvals, Activity, Settings
│   │   ├── components/          # Layout, modal, UI primitives, toasts
│   │   ├── api/                 # HTTP client, mock layer, data context
│   │   ├── types/               # Shared TypeScript contracts
│   │   └── styles/              # Design tokens
│   ├── scripts/                 # Smoke test and Node loader hooks
│   ├── Dockerfile
│   └── nginx.conf.template      # Serves the SPA and proxies /api
├── Docs/
│   └── AgentGuard_Project_Blueprint.md   # Requirements, roadmap, threat model
├── docker-compose.yml           # backend + frontend + optional postgres
├── start.bat                    # Windows launcher
├── .gitignore
└── README.md
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

### Important limitation

**The SDK is not a complete security boundary if the agent can call tools
directly.** AgentGuard governs calls that go through the SDK or the HTTP API.
Protect the tool execution path itself — network egress controls and tool-side
authorization — for defense in depth.

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

### Release 2 — advanced governance

- [ ] Multi-tenancy with tenant IDs on all records.
- [ ] Optional model-assisted risk classification behind a defined timeout,
      never allowed to override a deterministic deny.
- [ ] Exportable audit records.
- [ ] SIEM / alerting integrations.
- [ ] Multi-approver and quorum rules.
- [ ] Policy simulation and dry-run mode.
- [ ] Additional agent-framework adapters.

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

MVP / demo-quality. The full requirements, roadmap, and threat model are in
[`Docs/AgentGuard_Project_Blueprint.md`](Docs/AgentGuard_Project_Blueprint.md).

Build the MVP around one proof: **an agent cannot perform a protected action
unless AgentGuard explicitly authorizes it.**
