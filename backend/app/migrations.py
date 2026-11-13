"""Versioned, additive schema migrations.

AgentGuard historically relied on ``Base.metadata.create_all()``. That creates
missing tables but cannot evolve existing ones. This module adds a small,
dependency-free migration runner for the additive changes V2 needs.

Rules:
- Migrations are ordered, recorded in ``schema_migrations`` and idempotent.
- They are additive only. No migration drops a column or deletes rows.
- New tables are still created by ``create_all`` (SQLAlchemy metadata is the
  source of truth); this runner evolves tables that already exist.
"""

from __future__ import annotations

import logging

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

DEFAULT_ORG_ID = "org-default"

logger = logging.getLogger("agentguard.migrations")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description VARCHAR(255) NOT NULL,
    applied_at VARCHAR(32) NOT NULL
)
"""

# Explicit indexes added by the final migration.
_INDEXES: list[tuple[str, str, str]] = [
    ("ix_users_org_id", "users", "org_id"),
    ("ix_agents_org_id", "agents", "org_id"),
    ("ix_tools_org_id", "tools", "org_id"),
    ("ix_policies_org_id", "policies", "org_id"),
    ("ix_approvals_org_id", "approvals", "org_id"),
    ("ix_audit_events_org_id", "audit_events", "org_id"),
    ("ix_audit_events_event_hash", "audit_events", "event_hash"),
    ("ix_audit_events_chain_sequence", "audit_events", "chain_sequence"),
]

_MIGRATIONS: list[tuple[int, str, list[tuple[str, str, str]]]] = [
    (
        1,
        "V2 tenant columns on existing tables",
        [
            ("users", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
            ("agents", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
            ("tools", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
            ("policies", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
            ("approvals", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
        ],
    ),
    (
        2,
        "V2 approval consumption column",
        [("approvals", "consumed_at", "VARCHAR(32)")],
    ),
    (
        3,
        "V2 audit hash-chain columns",
        [
            ("audit_events", "org_id", "VARCHAR(36) NOT NULL DEFAULT 'org-default'"),
            ("audit_events", "prev_hash", "VARCHAR(80)"),
            ("audit_events", "event_hash", "VARCHAR(80)"),
            ("audit_events", "chain_sequence", "INTEGER"),
        ],
    ),
    (
        4,
        "V2 intelligence settings columns",
        [
            ("settings", "propagation_policy", "JSON"),
            ("settings", "reliability_enforcement", "INTEGER NOT NULL DEFAULT 1"),
            ("settings", "containment_threshold", "INTEGER NOT NULL DEFAULT 3"),
            (
                "settings",
                "transaction_compensation_requires_approval",
                "INTEGER NOT NULL DEFAULT 1",
            ),
        ],
    ),
    (5, "V2 indexes", []),
    (
        6,
        "V2 approval workflow-context columns",
        [
            ("approvals", "workflow_execution_id", "VARCHAR(36)"),
            ("approvals", "agent_execution_id", "VARCHAR(36)"),
            ("approvals", "input_artifact_ids", "JSON"),
            ("approvals", "risk_assessment_id", "VARCHAR(36)"),
        ],
    ),
]


def _applied_versions(conn) -> set[int]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {int(row[0]) for row in rows}


def _record(conn, version: int, description: str) -> None:
    conn.execute(
        text(
            "INSERT INTO schema_migrations (version, description, applied_at) "
            "VALUES (:version, :description, :applied_at)"
        ),
        {"version": version, "description": description, "applied_at": _utcnow()},
    )


def apply_migrations(engine: Engine) -> list[int]:
    """Apply pending additive migrations. Returns versions applied this run."""
    applied_now: list[int] = []

    with engine.begin() as conn:
        conn.execute(text(_VERSION_TABLE))
        done = _applied_versions(conn)

        for version, description, columns in _MIGRATIONS:
            if version in done:
                continue

            for table, column, ddl in columns:
                _add_column_if_missing(conn, table, column, ddl)
            if version == 5:
                for index_name, table, column in _INDEXES:
                    _create_index_if_missing(conn, index_name, table, column)

            _record(conn, version, description)
            applied_now.append(version)

        # SQLite/Postgres both accept this; fresh databases already have the
        # column because create_all ran against the current models.
        inspector = inspect(engine)
        if inspector.has_table("settings") and _has_column(
            inspector, "settings", "propagation_policy"
        ):
            conn.execute(
                text(
                    "UPDATE settings SET propagation_policy = '{}' "
                    "WHERE propagation_policy IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE settings SET reliability_enforcement = 1 "
                    "WHERE reliability_enforcement IS NULL"
                )
            )

    if applied_now:
        logger.info("Applied AgentGuard migrations: %s", applied_now)
    return applied_now


def _has_column(inspector, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspector.get_columns(table))


def _add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    inspector = inspect(conn.engine)
    if not inspector.has_table(table):
        return
    if _has_column(inspector, table, column):
        return
    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
    logger.info("Added column %s.%s", table, column)


def _create_index_if_missing(conn, name: str, table: str, column: str) -> None:
    inspector = inspect(conn.engine)
    if not inspector.has_table(table):
        return
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name in existing:
        return
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))


def ensure_default_organization(engine: Engine) -> None:
    """Create the default organization and backfill legacy rows.

    Uses raw SQL rather than ORM models because ``init_db`` runs while
    ``app.models`` is still being imported. This is data-preserving: it never
    deletes or rewrites business records, only fills a tenant id that predates
    multi-tenancy.
    """
    # SQLite and PostgreSQL both accept INSERT ... SELECT ... WHERE NOT EXISTS.
    with engine.begin() as conn:
        inspector = inspect(engine)
        if not inspector.has_table("organizations"):
            return
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at) "
                "SELECT :id, :name, :slug, 'ACTIVE', :created_at "
                "WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE id = :id)"
            ),
            {
                "id": DEFAULT_ORG_ID,
                "name": "Default Organization",
                "slug": "default",
                "created_at": _utcnow(),
            },
        )
        for table in ("users", "agents", "tools", "policies", "approvals", "audit_events"):
            if not inspector.has_table(table):
                continue
            columns = {col["name"] for col in inspector.get_columns(table)}
            if "org_id" in columns:
                conn.execute(
                    text(f"UPDATE {table} SET org_id = :org WHERE org_id IS NULL"),
                    {"org": DEFAULT_ORG_ID},
                )
