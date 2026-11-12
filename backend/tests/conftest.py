"""Shared pytest fixtures for the AgentGuard test suite."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the backend package is importable when pytest runs from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Agent,
    AgentToolPermission,
    Approval,
    AuditEvent,
    Policy,
    Settings,
    Tool,
    User,
)
from app.seed import seed_demo_data  # noqa: E402
from app.security import generate_agent_key, hash_key  # noqa: E402


@pytest.fixture()
def db():
    """A clean database session with the demo dataset seeded."""
    init_db()
    session = SessionLocal()
    try:
        # Reset to a known state for every test, children before parents.
        for model in (AuditEvent, Approval, AgentToolPermission, Policy, Agent, Tool, Settings, User):
            session.query(model).delete()
        session.commit()
        seed_demo_data(session)
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def support_agent(db) -> Agent:
    return db.get(Agent, "agent-support")


@pytest.fixture()
def agent_key(db, support_agent) -> str:
    """A valid API key for the seeded support agent."""
    key = generate_agent_key()
    support_agent.credential_hash = hash_key(key)
    db.commit()
    return key
