# AgentGuard --- Product Requirements, Roadmap & Technical Architecture

> **Document type:** Build-ready project blueprint\
> **Version:** 1.0\
> **Status:** Proposed baseline --- validate assumptions with the
> hackathon brief and team before implementation\
> **Product:** AgentGuard, an AI-agent governance, security, and
> observability layer

------------------------------------------------------------------------

## 1. Executive Summary

AgentGuard is a control plane and runtime guardrail layer for
applications that use one or more AI agents and tools. It helps teams
understand what agents are doing, apply policy before risky actions,
detect unsafe behavior, retain auditable evidence, and intervene when
necessary.

The core idea is to place a policy-enforcement and observability layer
between an AI agent and the tools or systems it can access.

**Primary value proposition:** Make AI-agent activity visible,
controlled, and auditable without requiring teams to replace their agent
framework.

### 1.1 Problem

AI agents can plan and execute multi-step tasks, call external tools,
access data, and trigger consequential actions. Without a governance
layer, teams may struggle to:

-   Know which agent initiated an action and why.
-   Enforce consistent permissions across agents and tools.
-   Detect prompt injection, data leakage, unsafe tool calls, or policy
    violations.
-   Stop or require approval for high-impact actions.
-   Investigate incidents with reliable traces and audit records.

### 1.2 Proposed solution

AgentGuard provides:

1.  **Agent and tool registry** --- inventory of registered agents,
    tools, owners, and permissions.
2.  **Policy engine** --- evaluates proposed actions against
    configurable rules.
3.  **Runtime gateway / SDK** --- intercepts tool calls and routes them
    through policy checks.
4.  **Risk scoring** --- assigns a risk level to actions using
    explainable signals.
5.  **Human approval workflow** --- pauses selected actions until an
    authorized person approves or rejects them.
6.  **Audit trail and observability** --- records decisions, tool-call
    metadata, policy versions, and outcomes.
7.  **Admin dashboard** --- lets operators manage agents, policies,
    approvals, and incidents.

### 1.3 Product principles

-   **Default deny for unregistered or unauthorized actions.**
-   **Human approval for explicitly designated high-impact actions.**
-   **Explainability:** every block or approval should include a reason.
-   **Least privilege:** agents receive only the tools and scopes they
    need.
-   **Fail safely:** policy-service failure must not silently authorize
    sensitive actions.
-   **Privacy by design:** store the minimum data required; redact
    secrets and sensitive payloads.
-   **Framework-neutral core:** integrate through a documented API/SDK
    rather than coupling the policy engine to one agent framework.

------------------------------------------------------------------------

## 2. Goals, Non-Goals & Success Measures

### 2.1 Goals

-   Provide a single policy decision point for agent tool actions.
-   Support allow, deny, and require-human-approval decisions.
-   Provide traceability from agent → task/session → proposed action →
    policy decision → tool result.
-   Give administrators a clear view of agent activity and policy
    violations.
-   Make a working end-to-end demonstration possible with a sample agent
    and mock tools.

### 2.2 Non-goals for the first release

-   Building a foundation model or training a new LLM.
-   Guaranteeing detection of every prompt injection or hallucination.
-   Replacing the identity provider, secrets manager, SIEM, or
    enterprise IAM platform.
-   Automatically deciding whether arbitrary natural-language output is
    factually correct.
-   Supporting every agent framework on day one.
-   Executing arbitrary tools directly from the dashboard.

### 2.3 MVP success metrics

Set targets after measuring the first prototype. Suggested initial
acceptance targets:

  -----------------------------------------------------------------------
  Metric                                                   Initial target
  ------------------------------ ----------------------------------------
  Policy decision latency            p95 under 150 ms, excluding external
                                                              model calls

  Registered tool-call coverage            100% of calls made through the
                                                   AgentGuard SDK/gateway

  Audit completeness                   100% of intercepted actions have a
                                                          decision record

  Unauthorized action handling        Denied in all defined negative test
                                                                    cases

  Approval enforcement                No protected action executes before
                                                                 approval

  Dashboard freshness                 New events visible within 5 seconds

  Availability behavior           Sensitive actions fail closed if policy
                                                evaluation is unavailable
  -----------------------------------------------------------------------

These are engineering targets, not claims of achieved performance.

------------------------------------------------------------------------

## 3. Users & Personas

### Persona A --- AI application developer

Needs to integrate AgentGuard into an existing agent with minimal code
changes, understand SDK errors, and test policies locally.

### Persona B --- Security / governance administrator

Needs to define permissions, risk thresholds, approval requirements, and
review violations.

### Persona C --- Approver / business owner

Needs enough context to approve or reject a sensitive action, including
the requesting agent, intended action, target, and policy reason.

### Persona D --- Auditor / incident responder

Needs searchable, tamper-resistant records showing what happened, when,
under which policy version, and what decision was made.

------------------------------------------------------------------------

## 4. Core User Journeys

### Journey 1 --- Register an agent

1.  Administrator creates an agent record.
2.  Administrator assigns an owner and environment.
3.  Administrator registers permitted tools and scopes.
4.  Agent receives a client identity / API credential through a secure
    provisioning process.
5.  Agent sends a test request.
6.  Dashboard shows the agent as active.

### Journey 2 --- Authorize a normal tool call

1.  Agent proposes a tool call through the SDK.
2.  SDK sends the agent identity, session context, tool name, target,
    and validated arguments to AgentGuard.
3.  Policy engine checks registration, permissions, context, and risk
    rules.
4.  If allowed, SDK executes the tool and records the result metadata.
5.  Dashboard displays the event in the activity timeline.

### Journey 3 --- Require human approval

1.  Agent proposes a protected action.
2.  Policy engine returns `REQUIRE_APPROVAL`.
3.  SDK does not execute the action.
4.  AgentGuard creates a pending approval.
5.  An authorized approver reviews the action and context.
6.  Approver approves or rejects.
7.  If approved, the action is revalidated against current policy and
    executed once.
8.  The decision and outcome are audited.

### Journey 4 --- Block an unsafe action

1.  Agent proposes an unregistered or prohibited action.
2.  Policy engine returns `DENY`.
3.  Tool is not executed.
4.  A violation event is created with reason codes.
5.  Administrator can inspect the event and adjust policy if
    appropriate.

------------------------------------------------------------------------

## 5. Functional Requirements

Priority labels: **P0** = required for MVP, **P1** = important next,
**P2** = later.

### 5.1 Identity and agent registry

-   **FR-001 (P0):** Administrators can create, view, update, disable,
    and delete agent registrations.
-   **FR-002 (P0):** Each agent has a unique ID, name, owner,
    environment, status, and creation timestamp.
-   **FR-003 (P0):** Administrators can associate allowed tools and
    scopes with an agent.
-   **FR-004 (P1):** Support credential rotation and revocation.
-   **FR-005 (P1):** Support separate development, staging, and
    production environments.

### 5.2 Tool registry and action interception

-   **FR-010 (P0):** Register tools with a name, description, input
    schema, risk category, and execution adapter.
-   **FR-011 (P0):** SDK intercepts tool calls before execution.
-   **FR-012 (P0):** Unregistered tools are denied by default.
-   **FR-013 (P0):** Each intercepted action has a unique action ID and
    correlation ID.
-   **FR-014 (P1):** Provide adapters for selected agent frameworks and
    common tool interfaces.

### 5.3 Policy engine

-   **FR-020 (P0):** Evaluate each proposed action against agent
    permissions and policy rules.
-   **FR-021 (P0):** Return one of `ALLOW`, `DENY`, or
    `REQUIRE_APPROVAL`.
-   **FR-022 (P0):** Include machine-readable reason codes and
    human-readable explanations.
-   **FR-023 (P0):** Support rules by agent, tool, environment, target,
    action category, and risk level.
-   **FR-024 (P0):** Apply a default-deny policy when no applicable
    allow rule exists.
-   **FR-025 (P1):** Support policy versioning, draft/publish workflow,
    and rollback.
-   **FR-026 (P1):** Support time-bound and context-bound permissions.

### 5.4 Risk analysis

-   **FR-030 (P0):** Assign a baseline risk category using deterministic
    rules.
-   **FR-031 (P0):** Consider factors such as tool sensitivity, data
    classification, external destination, destructive operation, and
    privilege level.
-   **FR-032 (P0):** Explain which factors contributed to the risk
    result.
-   **FR-033 (P1):** Add optional model-assisted classification behind a
    clearly defined timeout and fallback policy.
-   **FR-034 (P1):** Never allow an LLM risk score alone to override a
    deterministic deny rule.

### 5.5 Human approvals

-   **FR-040 (P0):** Create approval requests for actions that require
    human review.
-   **FR-041 (P0):** Show agent, requested action, target, sanitized
    arguments, risk, and policy reason.
-   **FR-042 (P0):** Only authorized approvers can approve or reject.
-   **FR-043 (P0):** Expire approvals after a configurable time.
-   **FR-044 (P0):** Bind approval to the exact action payload hash and
    policy version.
-   **FR-045 (P0):** Re-evaluate policy immediately before execution
    after approval.
-   **FR-046 (P1):** Support multiple approvers or quorum rules.

### 5.6 Audit and observability

-   **FR-050 (P0):** Record every policy decision.
-   **FR-051 (P0):** Record agent ID, action ID, session ID, tool,
    decision, reason codes, timestamp, and policy version.
-   **FR-052 (P0):** Redact secrets and configured sensitive fields from
    logs.
-   **FR-053 (P0):** Provide searchable activity and violation views.
-   **FR-054 (P1):** Provide exportable audit records.
-   **FR-055 (P1):** Add trace correlation across multi-step agent
    tasks.

### 5.7 Dashboard and administration

-   **FR-060 (P0):** Dashboard displays registered agents, recent
    activity, pending approvals, and blocked actions.
-   **FR-061 (P0):** Admin can create and edit basic policies.
-   **FR-062 (P0):** Approver can inspect and decide pending approvals.
-   **FR-063 (P0):** Admin can disable an agent immediately.
-   **FR-064 (P1):** Add filters, pagination, charts, and incident
    detail pages.

------------------------------------------------------------------------

## 6. Non-Functional Requirements

-   **Security:** TLS in transit; encryption at rest; hashed or securely
    managed credentials; role-based access control.
-   **Reliability:** policy checks must be deterministic for the same
    policy version and normalized input.
-   **Performance:** keep deterministic policy evaluation local to the
    service; avoid model calls in the critical path for MVP.
-   **Scalability:** stateless API and policy workers; database indexes
    on event time, agent ID, and action ID.
-   **Privacy:** configurable retention; payload minimization; redaction
    before persistence.
-   **Auditability:** append-only event semantics; record policy version
    and actor for administrative changes.
-   **Maintainability:** typed API contracts, migrations, automated
    tests, structured logs, and clear module boundaries.
-   **Accessibility:** dashboard supports keyboard navigation, readable
    contrast, and clear decision states.

------------------------------------------------------------------------

## 7. Scope and Release Plan

### MVP --- End-to-end governance demo

Must include: - Agent registration. - Tool registration. - One SDK or
gateway integration. - Deterministic policy engine. - Allow / deny /
require-approval decisions. - Approval queue. - Audit event storage. -
Basic dashboard. - Sample agent and mock tools. - Tests demonstrating
that blocked and pending actions never execute prematurely.

### Release 1 --- Operational readiness

-   Credential rotation and revocation.
-   Policy versioning and rollback.
-   Better RBAC and tenant isolation.
-   Exportable audit logs.
-   Rate limiting and abuse controls.
-   Deployment monitoring and backup/restore.

### Release 2 --- Advanced governance

-   More framework adapters.
-   Optional model-assisted risk classification.
-   Data-loss prevention integrations.
-   SIEM / alerting integrations.
-   Advanced approval workflows.
-   Policy simulation and dry-run mode.

------------------------------------------------------------------------

## 8. Recommended Technical Stack

This is a practical default stack, not a mandatory constraint. Use the
team's existing strengths if they differ.

  -----------------------------------------------------------------------
  Layer                   Suggested technology    Responsibility
  ----------------------- ----------------------- -----------------------
  Web dashboard           React + TypeScript      Admin, activity,
                                                  approval UI

  API backend             Python + FastAPI        REST API, auth,
                                                  orchestration

  Policy engine           Python module           Deterministic policy
                          initially; separate     evaluation
                          service later           

  Database                PostgreSQL              Agents, tools,
                                                  policies, approvals,
                                                  audit events

  Cache / short-lived     Redis (optional for     Rate limits,
  state                   MVP)                    short-lived approval
                                                  state, caching

  SDK                     Python package          Intercept agent tool
                                                  calls

  Authentication          JWT/OIDC integration    User identity and roles

  Deployment              Docker Compose for      Repeatable runtime
                          development; cloud      
                          container platform for  
                          deployment              

  Observability           OpenTelemetry +         Traces, metrics, logs
                          structured logs         
  -----------------------------------------------------------------------

**Important:** Do not add Redis, a message broker, Kubernetes, or a
separate microservice for every module just to make the architecture
look sophisticated. Start with a modular monolith and split services
only when there is a measured reason.

------------------------------------------------------------------------

## 9. System Architecture

### 9.1 Logical architecture

``` text
+---------------------------+        +-----------------------------+
|      Admin / Approver     |        |      AI Agent Application   |
|       Web Dashboard       |        |  (LangChain / custom / etc.)|
+-------------+-------------+        +--------------+--------------+
              |                                     |
              v                                     v
+---------------------------+        +-----------------------------+
|       Frontend UI         |        |       AgentGuard SDK        |
| Agents / Policies / Queue |        | intercept_tool_call(...)    |
+-------------+-------------+        +--------------+--------------+
              | REST API                            | HTTPS
              v                                     v
+-------------------------------------------------------------------+
|                       AgentGuard Backend                          |
|                                                                   |
|  +----------------+  +----------------+  +---------------------+  |
|  | Auth & RBAC    |  | Agent/Tool     |  | Policy Decision     |  |
|  |                |  | Registry       |  | Engine              |  |
|  +----------------+  +----------------+  +----------+----------+  |
|                                                    |              |
|  +----------------+  +----------------+            |              |
|  | Approval       |  | Risk Rules     |<-----------+              |
|  | Workflow       |  | & Scoring      |                           |
|  +----------------+  +----------------+                           |
|                                                                   |
|  +----------------+  +----------------+  +---------------------+  |
|  | Audit Service  |  | Event / Trace  |  | Tool Execution      |  |
|  |                |  | Service        |  | Adapter (optional)  |  |
|  +----------------+  +----------------+  +---------------------+  |
+-------------------------------+-----------------------------------+
                                |
                                v
                    +---------------------------+
                    | PostgreSQL                |
                    | Registry / Policies /     |
                    | Approvals / Audit Events  |
                    +---------------------------+
```

### 9.2 Request lifecycle

1.  Agent calls the AgentGuard SDK with a proposed tool action.
2.  SDK creates or propagates a correlation ID.
3.  Backend authenticates the agent credential.
4.  Backend loads agent status, tool registration, and active policy
    version.
5.  Input is schema-validated and sensitive fields are redacted for
    logging.
6.  Deterministic risk rules calculate a risk category and reason list.
7.  Policy engine evaluates permissions and rules.
8.  Backend returns:
    -   `ALLOW`: SDK may execute the tool.
    -   `DENY`: SDK must not execute the tool.
    -   `REQUIRE_APPROVAL`: SDK must pause; no execution yet.
9.  On approval, backend verifies approver authorization, payload hash,
    expiry, and current policy.
10. SDK executes the approved action and reports success/failure
    metadata.
11. Audit event is finalized and visible in the dashboard.

### 9.3 Critical security invariant

**The tool must never execute merely because the agent asked for it.**
Execution is permitted only after a valid `ALLOW` decision or a valid
approval followed by a fresh policy check. The SDK must treat timeouts,
malformed responses, authentication failures, and policy-service errors
as non-authorizing outcomes.

For the MVP, a `REQUIRE_APPROVAL` response must not return an executable
approval token to the agent. The SDK should poll or receive a
server-side status update, then request a fresh decision.

------------------------------------------------------------------------

## 10. Backend Module Design

Recommended initial repository structure:

``` text
agentguard/
├── README.md
├── LICENSE
├── .env.example
├── docker-compose.yml
├── pyproject.toml
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   │       ├── agents.py
│   │       ├── tools.py
│   │       ├── policies.py
│   │       ├── decisions.py
│   │       ├── approvals.py
│   │       ├── events.py
│   │       └── health.py
│   └── dashboard/
│       ├── src/
│       └── package.json
├── agentguard_core/
│   ├── auth/
│   ├── registry/
│   ├── policy/
│   │   ├── evaluator.py
│   │   ├── rules.py
│   │   └── schemas.py
│   ├── risk/
│   ├── approvals/
│   ├── audit/
│   ├── execution/
│   └── redaction/
├── sdk/
│   └── python/
│       ├── agentguard/
│       │   ├── client.py
│       │   ├── guard.py
│       │   └── exceptions.py
│       └── pyproject.toml
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── security/
└── docs/
    ├── PRD.md
    ├── ARCHITECTURE.md
    ├── API.md
    ├── THREAT_MODEL.md
    └── ROADMAP.md
```

### Module responsibilities

-   `auth`: authenticate agents and dashboard users; enforce roles.
-   `registry`: manage agents, tools, owners, and scopes.
-   `policy`: normalize requests and evaluate deterministic rules.
-   `risk`: calculate explainable risk levels.
-   `approvals`: create, expire, approve, reject, and consume approvals.
-   `audit`: write append-only decision and outcome records.
-   `redaction`: remove secrets and sensitive data before persistence.
-   `execution`: optional adapters that execute tools after
    authorization.
-   `sdk`: provide a safe developer-facing interception interface.

------------------------------------------------------------------------

## 11. Data Model

Use UUID primary keys and UTC timestamps. Store policy documents as
JSONB only where flexibility is useful; keep frequently queried fields
relational and indexed.

### 11.1 Core entities

#### `users`

  Field          Type          Notes
  -------------- ------------- ---------------------------------------------
  id             UUID          Primary key
  email          text          Unique
  display_name   text          
  role           enum          `ADMIN`, `APPROVER`, `AUDITOR`, `DEVELOPER`
  status         enum          `ACTIVE`, `DISABLED`
  created_at     timestamptz   

#### `agents`

  Field             Type          Notes
  ----------------- ------------- -------------------------
  id                UUID          Primary key
  name              text          
  owner_user_id     UUID          FK users
  environment       text          dev / staging / prod
  status            enum          `ACTIVE`, `DISABLED`
  credential_hash   text          Never store raw API key
  created_at        timestamptz   
  updated_at        timestamptz   

#### `tools`

  Field          Type    Notes
  -------------- ------- ------------------------------------------------
  id             UUID    Primary key
  name           text    Unique within tenant/environment as applicable
  description    text    
  input_schema   JSONB   Validation schema
  category       text    e.g. read, write, external, destructive
  default_risk   enum    `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
  status         enum    `ACTIVE`, `DISABLED`

#### `agent_tool_permissions`

  Field        Type          Notes
  ------------ ------------- --------------------------
  id           UUID          Primary key
  agent_id     UUID          FK agents
  tool_id      UUID          FK tools
  scopes       JSONB         Narrow permission scopes
  created_at   timestamptz   

#### `policies`

  Field         Type          Notes
  ------------- ------------- -------------------------------
  id            UUID          Primary key
  name          text          
  description   text          
  version       integer       Monotonically increasing
  rules         JSONB         Validated policy DSL/document
  status        enum          `DRAFT`, `ACTIVE`, `ARCHIVED`
  created_by    UUID          FK users
  created_at    timestamptz   

#### `approvals`

  -----------------------------------------------------------------------
  Field                   Type                    Notes
  ----------------------- ----------------------- -----------------------
  id                      UUID                    Primary key

  action_id               UUID                    Unique action reference

  payload_hash            text                    Binds approval to exact
                                                  payload

  requested_by_agent_id   UUID                    FK agents

  status                  enum                    `PENDING`, `APPROVED`,
                                                  `REJECTED`, `EXPIRED`,
                                                  `CONSUMED`

  approver_user_id        UUID                    Nullable until decision

  expires_at              timestamptz             

  decided_at              timestamptz             Nullable

  reason                  text                    
  -----------------------------------------------------------------------

#### `audit_events`

  Field               Type          Notes
  ------------------- ------------- ---------------------------------------------
  id                  UUID          Primary key
  event_type          text          decision, approval, execution, admin change
  action_id           UUID          Correlation
  agent_id            UUID          Nullable for admin events
  session_id          text          
  tool_name           text          
  decision            text          ALLOW / DENY / REQUIRE_APPROVAL
  risk_level          text          
  reason_codes        JSONB         
  policy_id           UUID          
  policy_version      integer       
  payload_hash        text          
  redacted_metadata   JSONB         No secrets
  created_at          timestamptz   

### 11.2 Data relationships

``` text
users 1---many agents
users 1---many policies (created_by)
agents many---many tools through agent_tool_permissions
agents 1---many approvals
agents 1---many audit_events
policies 1---many audit_events (by policy/version reference)
approvals 1---many audit_events
```

### 11.3 Database rules

-   Add indexes on `audit_events(created_at)`,
    `audit_events(agent_id, created_at)`, `audit_events(action_id)`,
    `approvals(status, expires_at)`.
-   Enforce unique constraints for agent identity and tool registration
    within the appropriate tenant.
-   Use database transactions when creating an approval and its
    corresponding audit event.
-   Do not store raw credentials, full secrets, or unredacted sensitive
    tool payloads.
-   Consider partitioning audit events by time only after volume
    justifies it.
-   Add tenant IDs to all tenant-owned records before implementing
    multi-tenancy.

------------------------------------------------------------------------

## 12. Policy Model

Start with a small, deterministic policy format. Avoid building a
complex general-purpose policy language in the hackathon MVP.

### 12.1 Decision precedence

1.  Disabled agent → `DENY`.
2.  Disabled or unregistered tool → `DENY`.
3.  Missing agent-tool permission → `DENY`.
4.  Explicit deny rule → `DENY`.
5.  Protected action matching an approval rule → `REQUIRE_APPROVAL`.
6.  Matching allow rule and valid scope → `ALLOW`.
7.  No matching allow rule → `DENY`.

An explicit deny must always override an allow. A human approval must
not override a hard deny.

### 12.2 Example policy document

``` json
{
  "name": "Default production policy",
  "version": 1,
  "default_effect": "DENY",
  "rules": [
    {
      "id": "allow-read-docs",
      "effect": "ALLOW",
      "agent": "support-agent",
      "tool": "search_knowledge_base",
      "risk_max": "MEDIUM"
    },
    {
      "id": "approve-outbound-email",
      "effect": "REQUIRE_APPROVAL",
      "tool": "send_email",
      "environment": "production"
    },
    {
      "id": "deny-delete",
      "effect": "DENY",
      "tool": "delete_customer_record"
    }
  ]
}
```

### 12.3 Example decision response

``` json
{
  "action_id": "8a5b9e9a-0000-4000-8000-000000000001",
  "decision": "REQUIRE_APPROVAL",
  "risk": {
    "level": "HIGH",
    "reasons": ["EXTERNAL_COMMUNICATION", "PRODUCTION_ENVIRONMENT"]
  },
  "reason_codes": ["POLICY_APPROVAL_REQUIRED"],
  "policy": {
    "id": "policy-uuid",
    "version": 3
  },
  "approval_id": "approval-uuid",
  "expires_at": "2026-11-10T12:30:00Z"
}
```

Use generated IDs and real timestamps in implementation; the values
above are illustrative.

------------------------------------------------------------------------

## 13. API Design

Use versioned REST endpoints under `/api/v1`. Publish an OpenAPI
specification from the backend.

### 13.1 Agent and tool administration

  Method   Endpoint                            Purpose
  -------- ----------------------------------- ----------------------
  POST     `/api/v1/agents`                    Register agent
  GET      `/api/v1/agents`                    List agents
  GET      `/api/v1/agents/{id}`               Get agent
  PATCH    `/api/v1/agents/{id}`               Update agent
  POST     `/api/v1/agents/{id}/disable`       Disable agent
  POST     `/api/v1/tools`                     Register tool
  GET      `/api/v1/tools`                     List tools
  PUT      `/api/v1/agents/{id}/permissions`   Set tool permissions

### 13.2 Policy and decisions

  Method   Endpoint                          Purpose
  -------- --------------------------------- --------------------------
  POST     `/api/v1/policies`                Create policy draft
  GET      `/api/v1/policies`                List policies
  POST     `/api/v1/policies/{id}/publish`   Publish policy
  POST     `/api/v1/decisions/evaluate`      Evaluate proposed action

### 13.3 Approval and audit

  Method   Endpoint                           Purpose
  -------- ---------------------------------- -------------------------
  GET      `/api/v1/approvals`                List pending approvals
  GET      `/api/v1/approvals/{id}`           Approval detail
  POST     `/api/v1/approvals/{id}/approve`   Approve
  POST     `/api/v1/approvals/{id}/reject`    Reject
  POST     `/api/v1/actions/{id}/result`      Report execution result
  GET      `/api/v1/events`                   Search audit events

### 13.4 Evaluate request example

``` json
{
  "agent_id": "agent-uuid",
  "session_id": "session-123",
  "tool": "send_email",
  "target": "customer@example.com",
  "arguments": {
    "subject": "Account update",
    "body": "..."
  },
  "environment": "production"
}
```

### 13.5 SDK pseudocode

``` python
from agentguard import AgentGuardClient, GuardDenied, ApprovalRequired

guard = AgentGuardClient(
    base_url="https://agentguard.example/api",
    api_key="load-from-secret-manager"
)

def guarded_tool_call(tool_name, arguments, execute_tool):
    decision = guard.evaluate(
        tool=tool_name,
        arguments=arguments
    )

    if decision.status == "DENY":
        raise GuardDenied(decision.reason)

    if decision.status == "REQUIRE_APPROVAL":
        raise ApprovalRequired(decision.approval_id)

    # Execute only after an explicit ALLOW response.
    result = execute_tool(**arguments)

    guard.report_result(
        action_id=decision.action_id,
        success=True
    )
    return result
```

This is interface pseudocode. The production SDK must also handle
network timeouts, retries, idempotency, response validation, and safe
error behavior.

------------------------------------------------------------------------

## 14. Security & Threat Model

Use STRIDE as a starting framework and validate it against the actual
deployment.

  -----------------------------------------------------------------------
  Threat                  Example                 Mitigation
  ----------------------- ----------------------- -----------------------
  Spoofing                Attacker uses a stolen  Hashed credentials,
                          agent key               rotation, revocation,
                                                  TLS, scoped keys

  Tampering               Agent modifies action   Canonical payload hash;
                          after approval          bind approval to exact
                                                  payload

  Repudiation             User denies approving   Immutable-style audit
                          an action               events, actor identity,
                                                  timestamps

  Information disclosure  Tool arguments leak     Redaction, allowlisted
                          secrets to logs         metadata, encryption,
                                                  retention limits

  Denial of service       Agent floods decision   Rate limits, quotas,
                          endpoint                request limits,
                                                  monitoring

  Elevation of privilege  Agent calls an          Default deny, least
                          unapproved admin tool   privilege, explicit
                                                  scopes

  Prompt injection        Untrusted content       Treat model output as
                          instructs agent to      untrusted; enforce tool
                          exfiltrate data         permissions outside the
                                                  model

  Replay                  Previously approved     One-time approval
                          request is replayed     consumption, expiry,
                                                  nonce/idempotency key

  Policy bypass           Agent calls tool        Network egress
                          directly, outside SDK   controls, tool-side
                                                  authorization, gateway
                                                  enforcement

  Approval abuse          Approver approves a     Payload hash binding
                          changed request         and re-evaluation
                                                  before execution
  -----------------------------------------------------------------------

### Security requirements that must not be skipped

-   The SDK is not a complete security boundary if the agent can call
    tools directly. Protect the tool execution path itself.
-   Never trust `agent_id` supplied by the client without binding it to
    the authenticated credential.
-   Validate tool arguments against registered schemas.
-   Use idempotency keys for action submission and execution reporting.
-   Protect against approval replay and double execution.
-   Use strict timeouts and bounded request sizes.
-   Do not put secrets in logs, traces, browser storage, or source
    control.
-   Keep administrative actions auditable.
-   Restrict CORS and dashboard sessions appropriately.
-   Use dependency scanning and secret scanning in CI.

------------------------------------------------------------------------

## 15. Frontend Information Architecture

### Main navigation

1.  **Overview**
    -   Active agents
    -   Actions today
    -   Blocked actions
    -   Pending approvals
    -   Recent incidents
2.  **Agents**
    -   Agent list
    -   Agent details
    -   Status and owner
    -   Tool permissions
    -   Activity history
3.  **Tools**
    -   Tool registry
    -   Input schema
    -   Risk category
    -   Enabled / disabled state
4.  **Policies**
    -   Policy list
    -   Policy editor
    -   Rule detail
    -   Version history
    -   Publish / rollback
5.  **Approvals**
    -   Pending
    -   Approved
    -   Rejected
    -   Expired
    -   Approval detail and payload summary
6.  **Activity**
    -   Event timeline
    -   Filters
    -   Decision detail
    -   Correlation / trace view
7.  **Settings**
    -   Users and roles
    -   Environment settings
    -   Retention and redaction
    -   Credential management

### UX rules

-   Use clear labels: Allowed, Blocked, Waiting for approval, Failed.
-   Show the reason for every non-allow decision.
-   Never show unredacted secrets in the UI.
-   Require confirmation for disabling agents or publishing production
    policies.
-   Distinguish a policy denial from a tool execution failure.

------------------------------------------------------------------------

## 16. Development Roadmap

A suggested six-week plan for a small student/hackathon team. Adjust
duration to the actual deadline and team size.

### Phase 0 --- Discovery and design (Days 1--2)

**Tasks** - Confirm the exact hackathon problem statement and judging
criteria. - Finalize target users and one demo scenario. - Agree on MVP
scope and success criteria. - Draw request lifecycle and threat model. -
Define API contracts and database schema.

**Deliverables** - Approved PRD. - Architecture diagram. - Initial
threat model. - Backlog with P0/P1 labels.

**Exit criteria** - Team can explain what is intercepted, what is
protected, and what happens on allow/deny/approval.

### Phase 1 --- Project foundation (Days 3--5)

**Tasks** - Create repository and branch strategy. - Set up FastAPI
project and React dashboard. - Configure PostgreSQL and migrations. -
Add environment configuration and Docker Compose. - Add linting,
formatting, unit-test runner, and CI.

**Deliverables** - Running local stack. - Health endpoint. - Initial
schema migrations. - CI pipeline.

**Exit criteria** - A developer can clone the repository, configure
`.env`, and run the application locally.

### Phase 2 --- Registry and authentication (Week 2)

**Tasks** - Implement user authentication and basic roles. - Implement
agent CRUD. - Implement tool registry. - Implement agent-tool
permissions. - Add credential hashing and disable/revoke behavior.

**Deliverables** - Agent and tool APIs. - Registry dashboard pages. -
Integration tests.

**Exit criteria** - Only registered, active agents can request
decisions.

### Phase 3 --- Policy and SDK (Week 3)

**Tasks** - Implement policy schema and validation. - Implement
deterministic risk rules. - Implement decision precedence. - Build
Python SDK interception method. - Add mock tools and a sample agent. -
Add fail-closed behavior.

**Deliverables** - Working `ALLOW` and `DENY` flow. - SDK
documentation. - Policy unit tests.

**Exit criteria** - A blocked tool call demonstrably does not execute.

### Phase 4 --- Approval and audit (Week 4)

**Tasks** - Implement approval creation and expiry. - Build approver
queue and decision APIs. - Bind approval to action payload hash. -
Re-evaluate policy before execution. - Implement audit events and
redaction. - Add idempotency and replay tests.

**Deliverables** - Working `REQUIRE_APPROVAL` flow. - Activity and
approval dashboard. - Audit records for every decision.

**Exit criteria** - Protected action cannot execute before approval;
changed or expired requests cannot reuse approval.

### Phase 5 --- Dashboard, hardening and integration (Week 5)

**Tasks** - Complete overview, agent, policy, approval, and activity
screens. - Add pagination, filters, and useful empty/error states. - Add
rate limits and request validation. - Add structured logs and basic
metrics. - Run security and integration test suites. - Test service
failure behavior.

**Deliverables** - Integrated MVP. - Test report. - Deployment
configuration. - Demo dataset.

**Exit criteria** - End-to-end flow works reliably from dashboard to
agent SDK to policy engine and audit record.

### Phase 6 --- Demo and final validation (Week 6)

**Tasks** - Deploy to a stable demo environment. - Prepare seed data and
repeatable demo script. - Test clean installation and recovery. -
Prepare architecture and product presentation. - Record backup demo
video if useful. - Fix only high-impact defects; freeze scope.

**Deliverables** - Deployed demo. - Final README and setup guide. -
Final architecture and PRD. - Demo script and presentation.

**Exit criteria** - Demo can be repeated from a clean state and clearly
proves allow, deny, approval, and audit flows.

### Suggested sprint board

  Workstream                            Owner role                     Priority
  ------------------------------------- ------------------------------ ----------
  Backend API and database              Backend developer              P0
  Policy engine and risk rules          Backend / security developer   P0
  Python SDK and sample agent           AI / integration developer     P0
  Dashboard                             Frontend developer             P0
  Tests, deployment, demo               Shared / DevOps                P0
  Advanced analytics and integrations   As available                   P1

------------------------------------------------------------------------

## 17. Testing Strategy

### Unit tests

-   Policy precedence and default deny.
-   Risk categorization.
-   Schema validation.
-   Credential verification.
-   Redaction behavior.
-   Approval expiry and payload hash matching.

### Integration tests

-   Register agent → register tool → grant permission → evaluate action.
-   Allowed action → execute mock tool → report result.
-   Denied action → assert mock tool was not called.
-   Approval required → pending → approve → re-evaluate → execute once.
-   Reject or expire approval → assert tool was not called.
-   Disable agent → subsequent action denied.

### Security tests

-   Missing, invalid, revoked, and wrong-agent credentials.
-   Forged `agent_id`.
-   Replay of approval and action requests.
-   Payload changed after approval.
-   Unauthorized user attempting approval.
-   Oversized or malformed input.
-   Direct tool invocation bypassing SDK.
-   Secret leakage in logs and API responses.
-   Policy service unavailable / timeout.

### Acceptance test checklist

-   [ ] Unregistered agent is denied.
-   [ ] Disabled agent is denied.
-   [ ] Unregistered tool is denied.
-   [ ] Agent without tool permission is denied.
-   [ ] Explicit deny overrides allow.
-   [ ] No matching allow rule results in deny.
-   [ ] Approval-required action is not executed while pending.
-   [ ] Rejected and expired approvals cannot execute.
-   [ ] Modified payload cannot reuse approval.
-   [ ] Approved action is re-evaluated before execution.
-   [ ] Every decision creates an audit record.
-   [ ] Secrets are redacted from stored events.
-   [ ] Dashboard roles prevent unauthorized actions.

------------------------------------------------------------------------

## 18. Deployment & Operations

### Local development

Use Docker Compose for: - API container. - Dashboard container. -
PostgreSQL container. - Optional Redis container only if required.

Provide `.env.example` with placeholder values. Never commit real
credentials.

### Production baseline

-   Deploy API and dashboard behind HTTPS.
-   Use managed PostgreSQL with backups and restricted network access.
-   Store API credentials in a secret manager.
-   Use environment-specific configuration.
-   Configure health and readiness endpoints.
-   Centralize logs and metrics.
-   Configure database migration process.
-   Set retention and backup policies.
-   Restrict administrative access.

### Operational alerts

-   Sudden increase in denied actions.
-   Unusual agent request volume.
-   Repeated authentication failures.
-   Policy decision latency or error-rate increase.
-   Approval backlog or expiry spike.
-   Database storage / connection saturation.

------------------------------------------------------------------------

## 19. Demo Scenario

Use a single coherent business scenario to prove the product.

**Scenario:** A customer-support agent can search a knowledge base, but
sending an external email requires approval and deleting a customer
record is prohibited.

1.  Register `support-agent`.
2.  Register tools:
    -   `search_knowledge_base` --- low risk.
    -   `send_email` --- high risk.
    -   `delete_customer_record` --- critical risk.
3.  Grant the agent permission to use the tools, while applying policy
    restrictions.
4.  Ask the sample agent to search the knowledge base.
    -   Expected: `ALLOW`; mock search executes.
5.  Ask the agent to send an email.
    -   Expected: `REQUIRE_APPROVAL`; no email is sent yet.
6.  Approver reviews and approves.
    -   Expected: policy is rechecked; mock email executes once.
7.  Ask the agent to delete a customer record.
    -   Expected: `DENY`; tool is never called.
8.  Open the activity page.
    -   Expected: all three actions and their outcomes are visible with
        reasons.

The demo should show actual enforcement, not merely a dashboard
displaying simulated risk labels.

------------------------------------------------------------------------

## 20. Key Risks, Assumptions & Open Decisions

### Risks

-   **SDK bypass:** An agent may call a tool directly. Mitigate with
    gateway-side or tool-side authorization.
-   **Overly broad scope:** Too many integrations can prevent
    completion. Keep MVP to one SDK and mock tools.
-   **False positives:** Risk rules may block legitimate work. Provide
    clear reasons and policy simulation later.
-   **False negatives:** A deterministic ruleset cannot understand every
    semantic threat. Do not market it as complete prompt-injection
    prevention.
-   **Approval race conditions:** Policy may change while an action
    waits. Re-evaluate immediately before execution.
-   **Sensitive audit data:** Logging complete prompts and tool
    arguments can create a data leak. Store redacted metadata and
    hashes.

### Assumptions to confirm

-   The initial product is a governance layer for AI agents, not an AI
    model itself.
-   The first integration will be a Python SDK and a sample agent.
-   PostgreSQL is acceptable for the MVP.
-   The hackathon demonstration can use mock tools rather than real
    customer systems.
-   The first release targets one organization / workspace unless
    multi-tenancy is explicitly required.

### Decisions the team must make

1.  Which agent framework will the demo use?
2.  Will tools execute inside the sample application or through an
    AgentGuard-hosted execution adapter?
3.  Is authentication required for the hackathon demo, or is a
    controlled demo credential sufficient?
4.  What exact action should require human approval?
5.  What is the required hosting environment and deadline?
6.  Does the judging rubric require a specific technology or
    integration?

------------------------------------------------------------------------

## 21. Definition of Done

The MVP is complete only when:

-   A developer can run the full stack using documented instructions.
-   A sample agent can call tools through the AgentGuard SDK.
-   The backend authenticates the agent and validates the proposed
    action.
-   The policy engine produces explainable allow, deny, and approval
    decisions.
-   No protected tool executes before authorization.
-   Approval is bound to the exact action and cannot be replayed.
-   Every decision and result is recorded with redaction.
-   The dashboard displays agents, policies, approvals, and activity.
-   Automated tests cover the critical security invariants.
-   The demo can be repeated reliably from a clean environment.

------------------------------------------------------------------------

## 22. Build Order --- The Shortest Safe Path

If time is limited, implement in this order:

1.  Database schema and health endpoint.
2.  Agent credential verification.
3.  Tool registry and agent permissions.
4.  Deterministic policy evaluator.
5.  Decision API.
6.  SDK wrapper around one mock tool.
7.  Audit event creation.
8.  Approval state machine.
9.  Dashboard approval queue.
10. Agent and activity pages.
11. Security tests for bypass, replay, expiry, and fail-closed behavior.
12. Deployment and demo script.

Do not begin with advanced AI risk classification, complex analytics, or
multiple framework integrations. First prove that the control point
genuinely prevents unauthorized tool execution.

------------------------------------------------------------------------

## 23. Reference Standards & Further Reading

Use these as design references, not as claims of certification:

-   OWASP Top 10 for LLM Applications:
    https://owasp.org/www-project-top-10-for-large-language-model-applications/
-   OWASP GenAI Security Project: https://genai.owasp.org/
-   NIST AI Risk Management Framework:
    https://www.nist.gov/itl/ai-risk-management-framework
-   NIST AI RMF Playbook:
    https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook
-   OpenTelemetry: https://opentelemetry.io/docs/
-   FastAPI documentation: https://fastapi.tiangolo.com/
-   PostgreSQL documentation: https://www.postgresql.org/docs/

------------------------------------------------------------------------

## 24. Final Product Statement

**AgentGuard is an AI-agent governance and runtime security layer that
gives organizations visibility and control over agent tool use through
least-privilege permissions, deterministic policy enforcement, human
approvals, and auditable activity records.**

Build the MVP around one proof: **an agent cannot perform a protected
action unless AgentGuard explicitly authorizes it.**
