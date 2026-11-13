# AgentGuard V2 — Final Engineering Report

Date: 2026-11-13
Repository: `D:\AgentGuard`
Status: implementation complete in the working tree; verified by execution.
No git commit has been made since the initial repository commit.

---

## 1. Objective

Transform AgentGuard from a policy-only tool-action guard into a
production-oriented multi-agent runtime security and workflow-reliability
platform, without breaking existing FastAPI, React, or Python SDK behavior.

The central addition is deterministic failure-propagation intelligence over
recorded dependencies, provenance, and validation. Policy remains the
authorization source; propagation and reliability may only restrict.

---

## 2. Delivered capabilities

| Capability | Implementation | Verified by |
| --- | --- | --- |
| DENY always wins | `services/decisions.py`, `policy.py`, `propagation.py`, `risk_engine.py` | Policy + V2 tests, demo, AFPB |
| Provenance and validation | `services/provenance.py`, artifact and validation-rule routes | `tests/test_v2_intelligence.py`, demo |
| Dependency graph, lineage, impact | Relational `dependencies`, bounded BFS in `services/dependencies.py` | Lineage/impact tests |
| Deterministic failure propagation | `services/propagation.py` with `NONE < REQUIRE_APPROVAL < DENY` | Invalid/quarantined/unverified tests, AFPB |
| Confidence-aware reliability | `services/reliability.py`, smoothed components, `INSUFFICIENT` level | Operations/API tests |
| Containment and circuit breakers | `services/containment.py`, conditional SQL transitions | Quarantine/recovery tests, demo |
| Saga transactions and idempotency | `services/transactions.py`, transaction routes | State-machine and compensation tests, demo |
| Explainable risk | `services/risk_engine.py`, persisted `risk_assessments` | Decision tests, API |
| Incidents, timeline, what-if | `services/incidents.py`, incident routes | Incident summary/report tests |
| Tenancy | `org_id` on V2 records, credential-derived `get_org_id` | Cross-tenant and ignored-header tests |
| Audit hash chain | `services/audit.py`, `/audit/verify`, checkpoints, export | Chain verification and tamper tests |
| SDK v2 | `client.py`, `guard.py`, version `0.2.0` | Compile/import check |
| Operational dashboard | Agent health, Provenance, Incidents, Transactions, Benchmarks pages | Frontend production build |
| AFPB benchmark | `services/benchmarks.py`, benchmark routes | Real run: 8/8 |
| Additive migrations | `app/migrations.py`, versions 1–6, `init_db()` integration | Backend suite |
| Documentation | `Docs/V2_ARCHITECTURE.md`, `V2_SECURITY_MODEL.md`, `FAILURE_PROPAGATION.md`, `AFPB_BENCHMARK.md`, `API_V2.md`, `V2_MIGRATION.md`; README and memory updated | Link/path check |

---

## 3. Decision ordering

The enforcement path is ordered and fail-closed:

1. credential binding (`agent_id`, environment);
2. idempotent replay;
3. payload bound and tool schema validation;
4. operational gate (quarantine / circuit breaker);
5. workflow-context validation and consumption recording;
6. deterministic policy;
7. failure propagation;
8. reliability friction;
9. explainable risk record;
10. incident/approval creation;
11. audit hash-chain write.

Approvals are revalidated against operational state, current policy, and current
propagation before atomic single-use consumption. A post-approval upstream
failure denies with `PROPAGATION_BLOCKED_AFTER_APPROVAL` and does not consume
the approval.

---

## 4. Verification evidence

All commands were executed locally on Windows, Python 3.10.11, Node 22.21.0.

### 4.1 Backend suite

```text
cd backend
python -m pytest
...
171 passed in 78.60s (0:01:18)
```

Coverage includes policy precedence, decisions, approvals, API contracts, rate
limiting, SDK fail-closed behavior, import integrity, and V2 invariance:
provenance validation/lineage, propagation denial and approval re-denial,
quarantine/recovery, transaction compensation, tenancy, audit tamper detection,
and a real AFPB run through the API test client.

### 4.2 Frontend production build

```text
cd frontend
npm run build
...
✓ 49 modules transformed.
dist/index.html                   1.06 kB
dist/assets/index-CfZLBo1I.css   20.96 kB
dist/assets/index-BF5t9Mnn.js   363.25 kB
✓ built in 264ms
```

TypeScript compilation and Vite bundling both succeeded.

### 4.3 SDK

```text
cd backend
python -m compileall -q sdk/python/agentguard
python -c "import agentguard; print(agentguard.__version__)"
0.2.0
```

V2 methods are present on `AgentGuardClient`, including
`run_afpb_benchmark`, `verify_audit_chain`, provenance, workflow, incident, and
transaction helpers.

### 4.4 V2 end-to-end demo

```text
cd backend
python scripts/demo_v2.py
...
Result: 17 passed, 0 failed
```

Verified behavior:

- invalid upstream artifact → `DENY` with `INVALID_UPSTREAM_ARTIFACT`;
- unverified high-impact input → `REQUIRE_APPROVAL`;
- after the artifact becomes `INVALID`, post-approval retry → `DENY` with
  `PROPAGATION_BLOCKED_AFTER_APPROVAL`, approval not consumed;
- quarantined agent → `DENY` with `AGENT_QUARANTINED`;
- recovery returns the agent to `ACTIVE` after validated replacements;
- partial transaction → `RECOVERY_REQUIRED`;
- compensation → `WAITING_APPROVAL` → `COMPENSATING` → `COMPLETED`;
- audit chain valid with 26 checked events.

### 4.5 AFPB benchmark

Real service execution in an isolated temporary SQLite database, seed 7:

```text
scenarios:                    8
passed:                       8
failed:                       0
unsafe_scenarios:             7
baseline_unsafe_executions:   7
v2_prevented:                 7
v2_allow:                     1
v2_require_approval:          5
v2_deny:                      2
prevention_rate:              1.0
false_positives:              0
false_positive_rate:          0.0
```

Per-scenario:

| Scenario | Expected | Baseline | V2 |
| --- | --- | --- | --- |
| invalid_upstream | DENY | ALLOW | DENY |
| quarantined_upstream | DENY | ALLOW | DENY |
| unverified_high_impact | REQUIRE_APPROVAL | ALLOW | REQUIRE_APPROVAL |
| stale_upstream | REQUIRE_APPROVAL | ALLOW | REQUIRE_APPROVAL |
| expired_upstream | REQUIRE_APPROVAL | ALLOW | REQUIRE_APPROVAL |
| missing_provenance | REQUIRE_APPROVAL | ALLOW | REQUIRE_APPROVAL |
| conflicting_sources | REQUIRE_APPROVAL | ALLOW | REQUIRE_APPROVAL |
| clean_control | ALLOW | ALLOW | ALLOW |

This is a measurement of eight synthetic scenarios, not a production detection
rate or third-party certification.

---

## 5. Requirements traceability

| Requirement | Where |
| --- | --- |
| DENY wins; reliability/propagation only restrict | `services/decisions.py` lines 450–511; `policy.py`; `risk_engine.py` docstring |
| Approval payload-bound, expiring, single-use, fail closed | `services/approvals.py`, `services/decisions.py` `_execute_approved`; V2 approval columns |
| Provenance and validation | `services/provenance.py`, `routers/artifacts.py` |
| Dependency graph and impact | `services/dependencies.py`, `routers/dependencies.py` |
| Confidence-aware reliability | `services/reliability.py` |
| Containment and circuit breakers | `services/containment.py`, `routers/operations.py` |
| Saga transactions and idempotency | `services/transactions.py`, `routers/transactions.py` |
| Explainable risk | `services/risk_engine.py`, persisted risk records |
| Incidents/replay | `services/incidents.py`, `routers/incidents.py` |
| Tenancy | `models.py` `org_id`, `deps.get_org_id`, tenant-scoped services |
| Audit hash chain | `services/audit.py`, `routers/audit.py` |
| SDK v2 | `sdk/python/agentguard/client.py`, `guard.py`, version `0.2.0` |
| Operational dashboard | `frontend/src/pages/*`, nav and routes |
| AFPB benchmark | `services/benchmarks.py`, `routers/benchmarks.py` |
| Tests | `tests/test_v2_intelligence.py` plus existing suite |
| Migrations | `app/migrations.py` versions 1–6, `db.init_db()` |
| Docs | `Docs/*.md`, `README.md`, `memory.md` |

---

## 6. Design decisions

- **Modular monolith retained.** No graph database or Redis was introduced.
  Relational bounded BFS is adequate for current workflow sizes.
- **Additive migrations.** `create_all()` remains the source of truth for new
  tables; the versioned runner evolves existing tables without data loss.
- **Benchmark baseline is an explicit ablation.** Baseline means policy-only
  with provenance disabled, not fabricated historical traffic.
- **Compensation is an external operation.** It is gated and recorded, never
  described as guaranteed rollback.
- **Risk preview is read-only.** `/risk/evaluate` is labelled `PREVIEW_ONLY`;
  only `/decisions/evaluate` enforces.
- **Audit checkpoints are not automatic external anchoring.** The limitation is
  stated in the API and security docs.

---

## 7. Limitations and residual risks

1. Propagation reasons only over provenance the runtime records. Unrecorded
   dependencies cannot be enforced.
2. Validation verifies configured rules, not semantic truth.
3. Human approval acknowledges reviewed evidence; post-approval rechecks exist
   because evidence can change.
4. Compensation may fail or be incomplete; it is not true rollback.
5. The audit hash chain detects tampering only when a checkpoint is trusted
   externally; full-database rewrite is not prevented.
6. The rate limiter is process-local; multi-instance deployments need a shared
   limiter.
7. PostgreSQL schema and compose profile exist, but this verification used
   SQLite.
8. AFPB covers eight synthetic scenarios and is not a certification.
9. AgentGuard does not protect tool paths that bypass the SDK/API; tool-side and
   network controls remain necessary.
10. The dashboard has no login screen when auth is enabled; it relies on tokens
    or the development fallback.

---

## 8. Repository state

The V2 implementation is uncommitted in the working tree. The initial commit is
`7c9e968 AgentGuard: AI-agent governance, security, and observability control
plane`. Generated databases, node_modules, virtual environments, `.env`, and
build output are excluded by `.gitignore` and should not be committed.

Recommended next actions:

1. review the working-tree diff;
2. run the verification commands in section 4 once more in CI;
3. commit the V2 implementation and docs;
4. add a CI workflow;
5. validate the PostgreSQL path and external audit anchoring in deployment.
