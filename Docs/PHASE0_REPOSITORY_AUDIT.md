# Phase 0 — Repository Audit (AgentGuard V2)

Date: 2026-11-13
Scope: full repository inspection, executed test suite, schema review, security review.

## 1. Verified baseline

| Check | Result |
| --- | --- |
| Backend test suite (`cd backend && pytest`) | **133 passed** |
| Frontend production build (`npm run build`) | **passes** |
| Frontend smoke render (`npm run smoke`) | available; build verified |
| Git history | single initial commit, clean working tree |
| Persistence | SQLAlchemy 2.x, `create_all()` only, no migration system |
| API version | `/api/v1`, OpenAPI enabled |

### What actually exists and works

- FastAPI modular monolith (`app/main.py`, routers, services).
- Agent registry with per-agent API keys (SHA-256 hashed, plaintext shown once),
  enable/disable, credential rotation, per-agent tool permissions.
- Tool registry with lightweight JSON-schema validation.
- Deterministic policy engine with precedence: disabled agent → disabled tool →
  missing permission → explicit deny → approval rule → allow rule → default deny.
- `ALLOW` / `DENY` / `REQUIRE_APPROVAL` decisions; approval payload-hash binding,
  expiry, single consumption, fresh policy revalidation before execution.
- Append-only audit events with redaction; idempotency key replay for decisions.
- Fixed-window per-agent rate limiting on the decision endpoint.
- Python SDK with fail-closed transport, `call_guarded`, approval polling.
- React/TypeScript dashboard: Overview, Activity, Approvals, Agents, Tools,
  Policies, Settings. Mock data layer is the default unless
  `VITE_USE_MOCK=false`.
- Docker Compose (SQLite default, optional PostgreSQL profile).
- 96+ backend tests plus SDK tests; frontend smoke script.

## 2. Architectural gaps (verified, not assumed)

1. **No workflow/execution identity.** Decisions are stateless per action. There
   is no workflow ID, agent-execution ID, or artifact ID in the decision path.
2. **No information provenance.** Tool arguments are hashed and redacted but not
   modelled as artifacts with producers, parents, validation, or lineage.
3. **No dependency graph.** Agents, tools, and data have no modelled edges.
4. **No propagation enforcement.** A tool call is authorized solely from the
   caller's permission and policy, regardless of unreliable upstream data.
5. **No reliability model.** Agent health is only `ACTIVE`/`DISABLED`.
6. **No containment.** Circuit breakers, quarantine, and workflow pause do not
   exist.
7. **No transaction integrity.** Multi-step external operations have no saga,
   idempotency, compensation, or recovery state.
8. **No incident/replay surface.** Audit events are searchable, but there is no
   timeline reconstruction, impact analysis, or what-if simulation.
9. **No migrations.** `Base.metadata.create_all()` creates missing tables but
   cannot evolve existing ones. Startup is non-destructive, which is good, but
   schema evolution is unsafe.
10. **Single tenancy.** No organization boundary anywhere in the schema, API, or
    queries.
11. **Audit is append-only by convention, not tamper-evident.** No hash chain.
12. **No benchmark or scientific evaluation harness.**
13. **Dashboard default is mock data**, so "live" operational claims require an
    explicit env flag; new operational views must read the backend.

## 3. Security findings

| Severity | Finding | Handling in V2 |
| --- | --- | --- |
| High (design) | Action authorization ignores data trust | Failure propagation engine integrated into the decision point |
| High | No tenant boundary | Organizations, org-scoped agents/keys, backend filtering, cross-tenant tests |
| Medium | Audit records rewritable without evidence | Hash-linked audit chain + checkpoints + verification endpoint (limitations documented) |
| Medium | `auth_required=false` falls back to seeded admin | Preserved for local dev; production deployment docs require `AUTH_REQUIRED=true`; no new endpoint relies on frontend filtering |
| Medium | Dashboard has no login UI | Out of scope for this pass; documented; API token flow exists |
| Low | Rate limiter is process-local | Documented; Redis remains optional, not introduced without measured need |
| Low | `CORS allow_credentials=true` with explicit origins | Acceptable; origins are explicit, not `*` |
| Low | Existing decision idempotency lookup not tenant-scoped | Tenant is bound to the authenticated agent, so keys cannot cross tenants in practice; documented |

## 4. Duplicate / risky functionality

- `frontend/src/api/mock.ts` + `mockData.ts` duplicate the live API shapes. They
  stay for offline demos but are never used by the new operational pages.
- Seed data intentionally fabricates *demo* history. It is isolated behind
  `SEED_DEMO_DATA`; benchmark and operational endpoints never read it.
- `Settings.retention_days` existed but no retention job ran. V2 adds an
  explicit cleanup service/endpoint rather than an unbounded background loop.

## 5. Recommended implementation order (executed)

1. Versioned additive migrations + extend schema without data loss.
2. Workflow/execution identity, artifacts, provenance, dependencies.
3. Deterministic validation + failure propagation at the decision point.
4. Explainable risk records, reliability scoring, containment.
5. Transaction manager with idempotency and compensation.
6. Tenant scoping, audit hash chain, approvals replay hardening.
7. APIs, SDK v2, dashboard operational views.
8. AFPB benchmark harness, tests, docs, demo.

## 6. Non-negotiable invariants retained

- DENY always wins; reliability and propagation can only restrict, never allow.
- Approvals remain payload-bound, expiring, single-use; revalidated.
- Security-service failure is fail-closed for protected actions.
- No fabricated production metrics; benchmark output is generated by execution.
