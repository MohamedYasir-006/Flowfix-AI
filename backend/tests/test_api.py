"""API-level tests: HTTP contract, authentication, and fail-closed behavior."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Agent
from app.security import generate_agent_key, hash_key


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def key(db) -> str:
    agent = db.get(Agent, "agent-support")
    api_key = generate_agent_key()
    agent.credential_hash = hash_key(api_key)
    db.commit()
    return api_key


class TestHealth:
    def test_health_ok(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "up"

    def test_openapi_available(self, client):
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
        assert "paths" in response.json()


class TestAuthentication:
    def test_missing_key_rejected(self, client):
        response = client.post(
            "/api/v1/decisions/evaluate",
            json={"tool": "search_knowledge_base", "arguments": {}},
        )
        assert response.status_code == 401

    def test_invalid_key_rejected(self, client):
        response = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": "ag_invalid"},
            json={"tool": "search_knowledge_base", "arguments": {}},
        )
        assert response.status_code == 401

    def test_valid_key_accepted(self, client, key):
        response = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "ALLOW"

    def test_agent_id_mismatch_rejected(self, client, key):
        response = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={
                "tool": "search_knowledge_base",
                "arguments": {"query": "x"},
                "agent_id": "not-me",
            },
        )
        assert response.status_code == 200
        assert response.json()["reason_codes"] == ["AGENT_ID_MISMATCH"]


class TestRegistry:
    def test_list_agents(self, client):
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        names = {agent["name"] for agent in response.json()}
        assert "support-agent" in names

    def test_create_agent_returns_key_once(self, client, db):
        response = client.post(
            "/api/v1/agents",
            json={"name": "brand-new-agent", "owner_user_id": "u-admin", "environment": "dev"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["api_key"].startswith("ag_")
        assert body["name"] == "brand-new-agent"

    def test_duplicate_agent_conflict(self, client):
        response = client.post(
            "/api/v1/agents",
            json={"name": "support-agent", "owner_user_id": "u-admin", "environment": "dev"},
        )
        assert response.status_code == 409

    def test_list_tools(self, client):
        response = client.get("/api/v1/tools")
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()}
        assert "send_email" in names

    def test_create_tool(self, client):
        response = client.post(
            "/api/v1/tools",
            json={
                "name": "brand_new_tool",
                "description": "test",
                "input_schema": {"type": "object"},
                "category": "read",
                "default_risk": "LOW",
            },
        )
        assert response.status_code == 201

    def test_disable_agent_blocks_decisions(self, client, db, key):
        agent = db.get(Agent, "agent-support")
        response = client.post(f"/api/v1/agents/{agent.id}/disable")
        assert response.status_code == 200

        decision = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
        )
        assert decision.json()["decision"] == "DENY"
        assert "AGENT_DISABLED" in decision.json()["reason_codes"]

    def test_rotate_key_invalidates_old_key(self, client, db):
        agent = db.get(Agent, "agent-support")
        old_key = generate_agent_key()
        agent.credential_hash = hash_key(old_key)
        db.commit()

        response = client.post(f"/api/v1/agents/{agent.id}/rotate-key")
        assert response.status_code == 200
        new_key = response.json()["api_key"]

        old_attempt = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": old_key},
            json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
        )
        assert old_attempt.status_code == 401

        new_attempt = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": new_key},
            json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
        )
        assert new_attempt.status_code == 200


class TestApprovalsApi:
    def _create_pending(self, client, key, to="api@example.com"):
        response = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={
                "tool": "send_email",
                "target": to,
                "arguments": {"to": to, "subject": "Hi", "body": "Body text"},
            },
        )
        return response.json()

    def test_pending_approval_appears_in_queue(self, client, key):
        created = self._create_pending(client, key)
        listing = client.get("/api/v1/approvals?status=PENDING")
        assert listing.status_code == 200
        ids = {approval["id"] for approval in listing.json()}
        assert created["approval_id"] in ids

    def test_approve_and_consume(self, client, key):
        created = self._create_pending(client, key)
        approval_id = created["approval_id"]

        approved = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"approver_user_id": "u-approver", "decision": "APPROVED"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"

        retry = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={
                "tool": "send_email",
                "target": "api@example.com",
                "arguments": {
                    "to": "api@example.com",
                    "subject": "Hi",
                    "body": "Body text",
                },
                "approval_id": approval_id,
            },
        )
        assert retry.json()["decision"] == "ALLOW"

    def test_reject_returns_conflict_on_retry(self, client, key):
        created = self._create_pending(client, key)
        approval_id = created["approval_id"]
        rejected = client.post(
            f"/api/v1/approvals/{approval_id}/reject",
            json={"approver_user_id": "u-approver", "decision": "REJECTED"},
        )
        assert rejected.status_code == 200

        retry = client.post(
            "/api/v1/decisions/evaluate",
            headers={"X-Agent-Key": key},
            json={
                "tool": "send_email",
                "target": "api@example.com",
                "arguments": {
                    "to": "api@example.com",
                    "subject": "Hi",
                    "body": "Body text",
                },
                "approval_id": approval_id,
            },
        )
        assert retry.json()["decision"] == "DENY"

    def test_double_decision_conflict(self, client, key):
        created = self._create_pending(client, key)
        approval_id = created["approval_id"]
        first = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"approver_user_id": "u-approver", "decision": "APPROVED"},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"approver_user_id": "u-approver", "decision": "APPROVED"},
        )
        assert second.status_code == 409

    def test_non_approver_cannot_decide(self, client, key):
        created = self._create_pending(client, key)
        response = client.post(
            f"/api/v1/approvals/{created['approval_id']}/approve",
            json={"approver_user_id": "u-developer", "decision": "APPROVED"},
        )
        assert response.status_code == 403


class TestEventsApi:
    def test_events_listed(self, client):
        response = client.get("/api/v1/events?limit=5")
        assert response.status_code == 200
        assert len(response.json()) > 0

    def test_events_filter_by_decision(self, client):
        response = client.get("/api/v1/events?decision=DENY")
        assert response.status_code == 200
        assert all(event["decision"] == "DENY" for event in response.json())

    def test_events_search(self, client):
        response = client.get("/api/v1/events?q=delete_customer_record")
        assert response.status_code == 200
        assert any(
            event.get("tool_name") == "delete_customer_record" for event in response.json()
        )


class TestOverviewApi:
    def test_overview_shape(self, client):
        response = client.get("/api/v1/overview")
        assert response.status_code == 200
        body = response.json()
        for field in (
            "active_agents",
            "total_agents",
            "actions_today",
            "blocked_today",
            "pending_approvals",
            "decisions_today",
            "recent_events",
        ):
            assert field in body
