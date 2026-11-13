# AgentGuard — Memory & Handover

Working notes for the AgentGuard build. The authoritative product requirements
live in `Docs/AgentGuard_Project_Blueprint.md`; this file records what was
actually built, what was broken, and what remains. V2 architecture and
limitations are documented in `Docs/V2_ARCHITECTURE.md`,
`Docs/V2_SECURITY_MODEL.md`, and the other V2 docs.

Last updated: 2026-11-13

---

## 1. What AgentGuard is

A control plane and runtime guardrail layer for AI agents. Every proposed tool
action passes through AgentGuard before execution: authentication, schema
validation, deterministic risk scoring, policy evaluation, provenance-aware
failure propagation, containment checks, and (when required) human approval. All
outcomes are written to a redacted, append-only, hash-chained audit trail.

Core invariant: **a tool never executes merely because the agent asked for it.**
Execution is permitted only after an explicit `ALLOW`, or a valid approval
followed by a fresh policy **and propagation** check. Transport errors, timeouts,
malformed responses, and auth failures are all non-authorizing.

V2 adds a second invariant: **a policy `DENY` is final.** Propagation,
reliability, risk aggregation, containment, and approvals may make a decision
stricter, never more permissive.

---

## 2. Current state

### Working and verified

| Area | Status |
| --- | --- |
| Backend API | FastAPI, `/api/v1`, OpenAPI at `/api/openapi.json`; V1 + V2 routes |
| Policy engine | Deterministic, blueprint §12.1 precedence, explainable reason codes; `DENY` final |
| Policy editor | Create/edit drafts, publish versions; published versions immutable |
| Risk scoring | V1 signals + V2 explainable aggregation (policy, propagation, reliability, ops state) |
| Approvals | Payload-hash bound, expiring, single-use; policy **and propagation** revalidated before execution |
| Audit | Every decision / approval / execution / admin change, redacted; per-tenant SHA-256 chain + checkpoints |
| Redaction | Configurable field list + secret patterns, applied before persistence |
| Agent registry | CRUD, enable/disable, credential rotate, per-agent tool permissions |
| Tool registry | CRUD with JSON-Schema-ish validation |
| Dashboard | React + TS: V1 pages plus Agent health, Provenance, Incidents, Transactions, Benchmarks |
| Python SDK | Fail-closed client 0.2.0, `call_guarded`, approval polling, V2 workflow/provenance/ops methods |
| Tests | 171 backend tests passing; frontend production build passing |
| Rate limiting | Fixed-window per-agent limiter on agent-authenticated endpoints, 429 + Retry-After |
| Docker | `docker-compose.yml` (backend + frontend + optional postgres), both images build |
| Windows launcher | `start.bat` — preflight, start, health-wait, open browser |
| V2 provenance | Artifacts with integrity hash, parents, expiry, validation rules, human verification, lineage |
| V2 failure propagation | Deterministic rule engine; invalid/quarantined/expired/stale/conflicting/unverified inputs restrict actions |
| V2 containment | Quarantine, circuit breakers, explicit recovery gate, incidents, notifications |
| V2 reliability | Confidence-aware smoothed score; `INSUFFICIENT` never implies trust |
| V2 transactions | Saga step state machine, idempotency, recovery plan, approved compensation |
| V2 tenancy | Credential-derived tenant, cross-tenant lookups rejected, org header ignored |
| V2 benchmark | AFPB 8 scenarios, isolated DB, real service code; verified 8/8 |

### Known gaps (not yet done)

- **External audit anchoring** — checkpoints exist, but no external WORM/append-only
  store is integrated. A privileged database rewrite is not prevented.
- **Retention enforcement** — `retention_days` is stored but no purge job runs.
- **Dashboard auth UI** — bearer tokens and `AUTH_REQUIRED` work, but the UI has
  no login screen. It relies on the seeded-admin fallback when auth is off.
- **User management API** — users can be listed but not created or edited.
- **Tool create/edit UI** — tools are listed but not created from the dashboard.
- **Postgres path untested end-to-end** — portable schema and compose profile
  exist, but only SQLite has been exercised in this verification.
- **No CI pipeline** — no GitHub Actions workflow.
- **Rate limiter is process-local** — correct for one uvicorn worker; a
  multi-instance deployment needs a shared limiter such as Redis.
- **Multi-approver/quorum and SIEM delivery** — not implemented.
- **Benchmark scope** — eight synthetic scenarios; not a certification or a
  production-traffic measurement.

---

## 3. Bugs found and fixed during this pass

These were real defects that only appeared when the code was actually executed.

1. **`app/db.py` — `init_db()` was not idempotent.**
   `Engine`/`SessionLocal` were module globals set by `init_db()`, but
   `from app.db import SessionLocal` binds the import-time value (`None`).
   The lifespan called `init_db()`, then `get_db` called it again, and the
   second call's `from . import models` shadowed the name. Fix: initialize at
   import time and make `init_db()` a no-op once initialized.

2. **`app/services/decisions.py` — REQUIRE_APPROVAL always 500'd.**
   `create_approval()` requires `policy_id` and `rule_id` keyword arguments, but
   `evaluate_decision()` never passed them. Every approval-required action
   crashed. Fix: pass `decision.policy_id` and `decision.rule_id`.

3. **`app/policy.py` — approved actions could never execute.**
   After approval, `_execute_approved()` re-evaluated policy, which re-matched
   the same `REQUIRE_APPROVAL` rule and returned `DENY` with
   `POLICY_REVALIDATION_DENIED`. Fix: added `satisfied_approval_rule_ids` to
   the evaluation context; the granted rule now resolves to `ALLOW` while an
   explicit deny still wins.

4. **`app/seed.py` — demo policy could not complete its own scenario.**
   The production policy had a `REQUIRE_APPROVAL` rule for `send_email` but no
   matching `ALLOW` rule, so an approved email always fell through to default
   deny. Fix: added `allow-email-after-approval`.

5. **`frontend/scripts/smoke.tsx` — could not resolve `@/` or `.css`.**
   The `@/` alias and CSS imports are Vite concepts. Fix: added Node ESM loader
   hooks (`scripts/tsx-hooks-register.mjs`, `tsconfig-alias.mjs`,
   `css-stub.mjs`) and `npm run smoke`.

6. **Stale dev servers on ports 8000-8003.** Multiple orphaned uvicorn
   processes from earlier sessions were serving old code, which made fixes look
   like they had no effect. Fix: killed them and used a single known port.

7. **`app/services/policies.py` — `update_policy` crashed on the rules field.**
   `model_dump()` already converts nested `PolicyRule` objects to dicts, so the
   extra `rule.model_dump()` pass hit a plain dict. Fix: dump once and assign.

8. **`app/services/policies.py` — `PolicyUpdate` was used but never imported.**
   With `from __future__ import annotations` the annotation is a lazy string,
   so the module imported fine and the name only failed when something resolved
   the annotation. The container crashed on it while the local test suite
   passed, because a test module had imported `PolicyUpdate` into its own
   namespace first. Fix: import it. Added
   `tests/test_imports.py`, which imports every module in a **fresh
   interpreter subprocess** and resolves all annotations with
   `typing.get_type_hints`, so this class of bug now fails in CI.

9. **Stale local uvicorn processes shadowing the Docker port.**
   Two orphaned `uvicorn ... --port 8000` processes from earlier sessions were
   still bound to `127.0.0.1:8000`, competing with the Docker container's port
   mapping. Requests were served by whichever process won the race, so the same
   API key returned `ALLOW` from curl (hitting the container) and `401` from
   httpx (hitting a stale process with an old database). Symptom looked exactly
   like an SDK header bug. Fix: kill orphaned servers before testing. **If
   behaviour differs between clients, check `netstat -ano | grep :8000` for
   duplicate listeners before debugging the client.**

10. **`docker-compose.yml` — dependency cycle.**
    `backend` depended on `frontend` and `frontend` on `backend`, so
    `docker compose` refused to start ("dependency cycle detected"). The
    backend has no real dependency on the dashboard; removed it.

11. **nginx could not resolve `backend` at startup.**
    A literal `proxy_pass http://backend:8000` makes nginx resolve the name
    once at config-load time and exit if it fails. Fix: resolve at request time
    with Docker's embedded DNS (`resolver 127.0.0.11`) plus a variable, and
    supply the host through the nginx `envsubst` template mechanism
    (`nginx.conf.template` + `ENV BACKEND_HOST=backend`).

### V2 defects found and fixed

12. **Missing `transaction_compensation_requires_approval` setting.**
    The compensation service read a config attribute that did not exist on
    `Settings`, so compensation approval would fail at runtime. Fix: added the
    setting with a fail-safe default of `True`.
13. **Compensation state machine could not resume from `WAITING_APPROVAL`.**
    `request_compensation` only allowed failed/partial/completed transactions,
    so an approval could never move `WAITING_APPROVAL → COMPENSATING`. Fix:
    allow `WAITING_APPROVAL` as an input state and set step compensation
    statuses explicitly on approval.
14. **Post-approval propagation could be bypassed by missing context.**
    The approved path must re-run propagation using the context stored on the
    approval; otherwise a human decision could outlive an upstream failure.
    Fix: re-evaluate with approval-bound workflow/agent/artifact context and do
    not consume the approval when propagation denies.
15. **Legacy test isolation deleted the wrong tenant.** The V2 test setup now
    preserves only `org-default`, removes other organizations, and deletes all
    registered tables in reverse metadata order so V2 state does not leak
    between tests.

---

## 4. How to run it

### Docker (recommended)

```bash
docker compose up --build
```

- Dashboard: http://localhost:8080
- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/api/v1/health

Postgres instead of SQLite:

```bash
docker compose --profile postgres up --build
export AGENTGUARD_DATABASE_URL=postgresql+psycopg2://agentguard:agentguard@localhost:5432/agentguard
```

### Windows launcher

Double-click `start.bat`. Flags: `--build`, `--postgres`, `--stop`, `--clean`.

```bat
start.bat                    REM normal start (SQLite)
start.bat --build            REM rebuild images first
start.bat --postgres         REM use PostgreSQL instead of SQLite
start.bat --stop             REM stop the stack
start.bat --clean            REM stop and delete volumes
```

### Local development

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

cd frontend && npm install && VITE_USE_MOCK=false npm run dev
```

### Demo agent

```bash
cd backend
python scripts/demo_key.py            # prints an agent API key
set AGENTGUARD_API_KEY=<key>
set AGENTGUARD_BASE_URL=http://127.0.0.1:8000/api
PYTHONPATH=../sdk/python python scripts/demo_agent.py
```

### V2 demo (isolated, no external tools)

```bash
cd backend
python scripts/demo_v2.py
```

Expected: `Result: 17 passed, 0 failed`. It verifies invalid-upstream denial,
post-approval propagation denial without approval consumption, quarantine and
recovery, compensation approval, and audit-chain verification.

### Tests

```bash
cd backend && pytest                  # 171 tests
cd frontend && npm run smoke          # renders the app, 18 assertions
cd frontend && npm run build          # type-check + bundle
```

---

## 5. Configuration

Environment variables, prefix `AGENTGUARD_`. Full list in
`backend/.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./agentguard.db` | SQLAlchemy connection |
| `AUTH_REQUIRED` | `false` | Require bearer tokens for dashboard endpoints |
| `AUTH_SECRET` | `dev-secret-change-me` | HMAC secret for dashboard tokens |
| `CORS_ORIGINS` | localhost dev origins | Allowed browser origins |
| `SEED_DEMO_DATA` | `true` | Seed the demo workspace on startup |
| `DECISION_RATE_LIMIT` | `60` | Decisions per agent per window |
| `DECISION_RATE_WINDOW_SECONDS` | `60` | Rate-limit window |
| `APPROVAL_TTL_MINUTES` | `240` | Approval expiry |
| `MAX_PAYLOAD_BYTES` | `65536` | Reject larger tool arguments |
| `REDACT_SECRETS` | `true` | Redact secrets before persistence |
| `RETENTION_DAYS` | `90` | Stored but not yet enforced |

V2 intelligence defaults (see `README.md` and `Docs/API_V2.md` for the full
list): `PROPAGATION_MAX_DEPTH=12`,
`PROPAGATION_REPEATED_FAILURE_THRESHOLD=3`,
`CONTAINMENT_FAILURE_THRESHOLD=3`, `CIRCUIT_OPEN_SECONDS=60`,
`RELIABILITY_WINDOW_DAYS=30`, `RELIABILITY_MIN_OBSERVATIONS=5`,
`RELIABILITY_MEDIUM_THRESHOLD=60.0`, `RELIABILITY_HIGH_THRESHOLD=80.0`,
`TRANSACTION_COMPENSATION_REQUIRES_APPROVAL=true`.
Per-tenant propagation effects live in `settings.propagation_policy`; unknown
keys are ignored and effective values are echoed in decision evidence.

Ports (via `.env` or the environment): `BACKEND_PORT` (8000),
`FRONTEND_PORT` (8080), `POSTGRES_PORT` (5432).

---

## 6. Architecture notes

- **Modular monolith.** One FastAPI process; modules are separated by domain
  (`services/agents.py`, `services/decisions.py`, `policy.py`, `risk.py`, ...).
  Split services only when there is a measured reason.
- **SQLite by default, PostgreSQL for deployment.** Timestamps are stored as
  UTC ISO-8601 strings and IDs as UUID strings so the schema is portable.
- **Policy precedence** (blueprint §12.1): disabled agent → disabled/unregistered
  tool → missing permission → explicit deny → approval rule → allow rule →
  default deny. An explicit deny always wins; approval never overrides a deny.
- **Approval binding.** `payload_hash = sha256(canonical_json({tool, target,
  arguments}))`. A changed payload cannot reuse an approval.
- **Fail-closed SDK.** Every non-authorizing outcome raises. `call_guarded`
  executes the wrapped tool only after `ALLOW`, and reports the result back.
- **V2 decision ordering.** identity/schema -> operational gate -> workflow
  context -> policy -> propagation -> reliability friction -> risk/incidents ->
  audit. Propagation/reliability/risk can only restrict.
- **Provenance is relational.** `dependencies` edges plus
  `parent_artifact_ids`; bounded BFS traversal. No graph database is used
  because current workflows do not justify the operational cost.
- **Containment is persisted state.** `agent_states` and `circuit_breakers`
  use conditional SQL updates; quarantine and recovery are explicit and audited.
- **Transactions record intent, not execution.** The service never runs tools or
  compensation actions; it gates and records transitions. Compensation requires
  explicit approval and is not guaranteed rollback.
- **Audit chain is per tenant.** Canonical JSON + SHA-256, monotonic sequence,
  checkpoint endpoint. External anchoring is required for stronger tamper proof.
- **Migrations are additive and versioned.** `app/migrations.py` versions 1-6;
  never renumber an applied version.

---

## 7. Repository / push notes

- The repository is initialized. All V2 work is currently in the working tree
  and has not been committed since the initial repository commit.
- `.gitignore` excludes `node_modules/`, `.venv/`, `*.db`, `.env`, and `dist/`.
- `backend/agentguard.db` is a local SQLite file - **do not commit it.**
- Before committing, review `git status` and `git diff`. Do not commit generated
  databases, node_modules, `.env`, or build output.

---

## 8. Verification checklist (run before pushing)

```bash
# 1. Backend unit + integration + SDK tests
cd backend && pytest                     # 171 tests

# 2. V2 end-to-end behavior demo (isolated DB)
cd backend && python scripts/demo_v2.py  # 17 checks

# 3. Frontend smoke test + production build
cd frontend && npm run smoke && npm run build

# 4. Docker stack from a clean state
docker compose down -v --remove-orphans
docker compose up -d --build
#    then check: http://localhost:8000/api/v1/health and http://localhost:8080/

# 5. End-to-end enforcement (SDK demo against the container)
docker compose exec -T backend python -c "..."   # rotate agent-support key
AGENTGUARD_API_KEY=<key> AGENTGUARD_BASE_URL=http://127.0.0.1:8000/api \
  PYTHONPATH=backend/sdk/python python backend/scripts/demo_agent.py

# 6. V2 AFPB benchmark (real service, isolated temp DB)
curl -X POST http://localhost:8000/api/v1/benchmarks/afpb/run \
  -H "Content-Type: application/json" -d '{"suite":"AFPB","seed":7}'

# 7. Rate limiting (60 req/min; the 61st returns 429 + Retry-After)
```

**Before debugging any client/server discrepancy, check for duplicate
listeners:** `netstat -ano | grep ':8000'`. A stale local uvicorn will shadow
the Docker port mapping and produce symptoms that look like an auth bug in the
SDK. This cost the most time during this pass.
