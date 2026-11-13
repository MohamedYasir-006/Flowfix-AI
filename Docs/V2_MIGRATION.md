# AgentGuard V2 — Migration Guide

V2 evolves an existing V1 database in place. It does not drop tables, columns,
or rows, and it does not require a separate database or cache.

The migration runner exists because `Base.metadata.create_all()` creates missing
tables but does not alter existing ones. `create_all()` remains the first step;
the runner then applies only the additive changes an existing database needs.

---

## 1. Execution order

`app.db.init_db()`:

1. creates the engine and session factory;
2. imports the models;
3. runs `Base.metadata.create_all()` (non-destructive);
4. applies pending versioned migrations;
5. ensures the default organization and backfills legacy tenant IDs.

All steps are idempotent. Restarting the service is safe.

---

## 2. Migration versions

| Version | Description | Changes |
| --- | --- | --- |
| 1 | V2 tenant columns on existing tables | `org_id` on `users`, `agents`, `tools`, `policies`, `approvals` (default `org-default`). |
| 2 | V2 approval consumption column | `approvals.consumed_at`. |
| 3 | V2 audit hash-chain columns | `audit_events.org_id`, `prev_hash`, `event_hash`, `chain_sequence`. |
| 4 | V2 intelligence settings columns | `settings.propagation_policy`, `reliability_enforcement`, `containment_threshold`, `transaction_compensation_requires_approval`. |
| 5 | V2 indexes | Tenant and audit-chain indexes. |
| 6 | V2 approval workflow-context columns | `approvals.workflow_execution_id`, `agent_execution_id`, `input_artifact_ids`, `risk_assessment_id`. |

New V2 tables (`organizations`, `workflows`, `workflow_executions`,
`agent_executions`, `artifacts`, `validation_rules`, `artifact_validations`,
`dependencies`, `agent_states`, `circuit_breakers`, `quarantine_events`,
`reliability_snapshots`, `risk_assessments`, `incidents`, `notifications`,
`transactions`, `transaction_steps`, `compensation_actions`, `policy_versions`,
`audit_checkpoints`, `benchmark_runs`) are created by `create_all()`.

Rules for future changes:

- append a new version; never renumber or rewrite an applied version;
- make each step additive and idempotent;
- do not delete business records in a migration;
- update `Docs/V2_ARCHITECTURE.md` and this table when adding a version.

---

## 3. Legacy data behavior

- Existing rows receive `org_id = 'org-default'`.
- The default organization is inserted only if absent.
- Existing audit events created before V2 may have `chain_sequence = NULL`.
  `GET /audit/verify` reports them as `unchained_legacy_events` and does not
  claim they are chained.
- Existing approvals remain valid records. They simply lack V2 workflow context;
  an approval without stored context cannot be used to bypass propagation.
- Existing settings rows are backfilled with empty propagation policy and
  reliability enforcement enabled.

No existing agent key, policy, approval, or audit record is deleted or rewritten.

---

## 4. SQLite vs. PostgreSQL

The migration statements are portable:

- `ALTER TABLE ... ADD COLUMN ...` is used with a conservative type/default;
- indexes use `CREATE INDEX IF NOT EXISTS`;
- default organization insertion uses `INSERT ... SELECT ... WHERE NOT EXISTS`;
- learnings from `sqlite_master` are avoided in favor of SQLAlchemy inspection.

SQLite is the exercised default in this repository's verification. The
PostgreSQL compose profile and portable schema exist, but PostgreSQL migration
behavior should be validated in your deployment environment before production
use.

---

## 5. Running the migration

### Normal startup

No manual step is required. Start the API:

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`init_db()` applies pending migrations.

### Explicit check

```python
from app.db import init_db, engine
from app.migrations import apply_migrations

init_db()
print(apply_migrations(engine))  # [] when up to date
```

### Inspect applied versions

SQLite:

```sql
SELECT version, description, applied_at
FROM schema_migrations
ORDER BY version;
```

PostgreSQL:

```sql
SELECT version, description, applied_at
FROM schema_migrations
ORDER BY version;
```

---

## 6. Deployment checklist

1. **Back up the database.** Additive migrations are safe, but backups are
   mandatory for any production change.
2. Stop old writers or use a single migration instance. Do not run multiple
   application instances against the same SQLite file.
3. Start the new backend and confirm `/api/v1/health`.
4. Inspect `schema_migrations`; versions 1–6 should be present.
5. Verify the default organization and spot-check tenant IDs:
   ```sql
   SELECT COUNT(*) FROM organizations WHERE id = 'org-default';
   SELECT COUNT(*) FROM audit_events WHERE org_id IS NULL;
   ```
6. Call `GET /api/v1/audit/verify`. Legacy unchained events are expected and
   reported; new events must chain.
7. Run one decision with a workflow context and confirm audit/risk records.
8. Run the AFPB benchmark if you want a local behavioral check:
   `POST /api/v1/benchmarks/afpb/run`.

---

## 7. Rollback stance

There is no automatic down-migration. The runner is intentionally forward-only
because V2 changes are additive and destructive rollback risks data loss.

To return to V1 code with a V2 database:

- V1 ignores new tables and columns; additive columns with defaults are
  compatible with the old models;
- keep the database backup taken before the upgrade;
- do not manually drop columns to "clean up" unless you have verified the old
  application and your backup strategy.

If a future migration needs a non-additive change, document an explicit,
tested rollback procedure instead of assuming this one applies.

---

## 8. Failure handling

- Each version runs inside `engine.begin()`. A failure rolls back that
  transaction; the version is not recorded.
- Re-running after fixing the cause retries the pending version.
- Column/index additions check the inspector first, so a partially applied
  database can recover without duplicate-column errors.
- Migration failures are logged under `agentguard.migrations`.

If a migration fails repeatedly, capture the database engine, version table,
and exception before making manual changes.
