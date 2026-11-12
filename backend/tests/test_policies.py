"""Tests for policy creation, editing, and publishing."""

from __future__ import annotations

import pytest

from app.models import Policy
from app.services import policies as policies_service
from app.schemas import PolicyCreate, PolicyRule, PolicyUpdate


def make_rule(rule_id: str = "r1", effect: str = "ALLOW", **kwargs) -> PolicyRule:
    return PolicyRule(id=rule_id, effect=effect, **kwargs)  # type: ignore[arg-type]


class TestCreatePolicy:
    def test_create_starts_as_draft(self, db):
        policy = policies_service.create_policy(
            db,
            PolicyCreate(
                name="Test policy",
                description="desc",
                rules=[make_rule()],
            ),
            "u-admin",
        )
        assert policy.status == "DRAFT"
        assert policy.version >= 1
        assert policy.created_by == "u-admin"
        assert policy.rules[0]["id"] == "r1"

    def test_versions_increment(self, db):
        first = policies_service.create_policy(db, PolicyCreate(name="p1"), "u-admin")
        second = policies_service.create_policy(db, PolicyCreate(name="p2"), "u-admin")
        assert second.version > first.version

    def test_create_is_audited(self, db):
        from app.models import AuditEvent

        before = db.query(AuditEvent).count()
        policies_service.create_policy(db, PolicyCreate(name="audited"), "u-admin")
        events = db.query(AuditEvent).all()[before:]
        assert any("POLICY_CREATED" in event.reason_codes for event in events)

    def test_rules_drop_none_fields(self, db):
        policy = policies_service.create_policy(
            db,
            PolicyCreate(
                name="p",
                rules=[PolicyRule(id="r", effect="ALLOW", tool="send_email")],
            ),
            "u-admin",
        )
        rule = policy.rules[0]
        assert rule["tool"] == "send_email"
        assert "agent" not in rule
        assert "environment" not in rule


class TestUpdatePolicy:
    def _draft(self, db, name="editable"):
        return policies_service.create_policy(db, PolicyCreate(name=name), "u-admin")

    def test_draft_can_be_edited(self, db):
        policy = self._draft(db)
        updated = policies_service.update_policy(
            db,
            policy,
            PolicyUpdate(description="new desc", rules=[make_rule("r2", "DENY")]),
            "u-admin",
        )
        assert updated.description == "new desc"
        assert updated.rules[0]["id"] == "r2"
        assert updated.status == "DRAFT"

    def test_published_policy_cannot_be_edited(self, db):
        policy = self._draft(db)
        policies_service.publish_policy(db, policy, "u-admin")
        with pytest.raises(ValueError, match="draft"):
            policies_service.update_policy(
                db, policy, PolicyUpdate(description="nope"), "u-admin"
            )

    def test_update_is_audited(self, db):
        from app.models import AuditEvent

        policy = self._draft(db)
        before = db.query(AuditEvent).count()
        policies_service.update_policy(db, policy, PolicyUpdate(description="x"), "u-admin")
        events = db.query(AuditEvent).all()[before:]
        assert any("POLICY_UPDATED" in event.reason_codes for event in events)


class TestPublishPolicy:
    def test_publish_activates_and_bumps_version(self, db):
        policy = policies_service.create_policy(db, PolicyCreate(name="to publish"), "u-admin")
        version = policy.version
        published = policies_service.publish_policy(db, policy, "u-admin")
        assert published.status == "ACTIVE"
        assert published.version == version + 1

    def test_publish_is_audited(self, db):
        from app.models import AuditEvent

        policy = policies_service.create_policy(db, PolicyCreate(name="p"), "u-admin")
        before = db.query(AuditEvent).count()
        policies_service.publish_policy(db, policy, "u-admin")
        events = db.query(AuditEvent).all()[before:]
        assert any("POLICY_PUBLISHED" in event.reason_codes for event in events)


class TestPolicyApi:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as test_client:
            yield test_client

    def test_create_policy_endpoint(self, client):
        response = client.post(
            "/api/v1/policies",
            json={
                "name": "API policy",
                "description": "created over HTTP",
                "default_effect": "DENY",
                "rules": [{"id": "r1", "effect": "ALLOW", "tool": "send_email"}],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "DRAFT"
        assert body["rules"][0]["tool"] == "send_email"

    def test_update_policy_endpoint(self, client):
        created = client.post("/api/v1/policies", json={"name": "edit me"}).json()
        response = client.put(
            f"/api/v1/policies/{created['id']}",
            json={"description": "updated", "rules": [{"id": "r9", "effect": "DENY"}]},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "updated"
        assert response.json()["rules"][0]["id"] == "r9"

    def test_update_published_policy_conflict(self, client):
        created = client.post("/api/v1/policies", json={"name": "immutable"}).json()
        published = client.post(f"/api/v1/policies/{created['id']}/publish")
        assert published.status_code == 200

        response = client.put(
            f"/api/v1/policies/{created['id']}", json={"description": "nope"}
        )
        assert response.status_code == 409

    def test_get_missing_policy_404(self, client):
        assert client.get("/api/v1/policies/nope").status_code == 404
