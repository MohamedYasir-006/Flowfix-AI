"""Integration tests for the decision and approval flows.

These exercise the real service layer against a seeded database and assert the
blueprint's critical invariants: blocked actions never execute, approvals are
bound to the exact payload, and every decision is audited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.errors import ApiError, ConflictError
from app.models import Agent, Approval, AuditEvent, Tool
from app.schemas import ActionResultRequest, ApprovalDecision, EvaluateRequest
from app.services import agents as agents_service
from app.services import approvals as approvals_service
from app.services import audit as audit_service
from app.services import decisions as decisions_service
from app.services import settings as settings_service
from app.utils import payload_hash


def evaluate(db, agent, tool, arguments=None, target=None, **kwargs):
    request = EvaluateRequest(
        tool=tool,
        target=target,
        arguments=arguments or {},
        session_id=kwargs.pop("session_id", "test-session"),
        **kwargs,
    )
    return decisions_service.evaluate_decision(db, agent, request)


class TestAllowDeny:
    def test_allowed_action(self, db, support_agent):
        result = evaluate(db, support_agent, "search_knowledge_base", {"query": "refund"})
        assert result.decision == "ALLOW"
        assert result.policy is not None

    def test_denied_destructive_action(self, db, support_agent):
        result = evaluate(
            db, support_agent, "delete_customer_record", {"customer_id": "c1", "reason": "dup"}
        )
        assert result.decision == "DENY"
        assert "EXPLICIT_DENY_RULE" in result.reason_codes

    def test_unregistered_tool_denied(self, db, support_agent):
        result = evaluate(db, support_agent, "not_a_real_tool", {})
        assert result.decision == "DENY"
        assert "TOOL_NOT_REGISTERED" in result.reason_codes

    def test_disabled_agent_denied(self, db, support_agent):
        agents_service.set_status(db, support_agent, "DISABLED", "u-admin")
        result = evaluate(db, support_agent, "search_knowledge_base", {"query": "x"})
        assert result.decision == "DENY"
        assert "AGENT_DISABLED" in result.reason_codes

    def test_missing_permission_denied(self, db, support_agent):
        # support-agent does not hold query_sales_db.
        result = evaluate(db, support_agent, "query_sales_db", {"sql": "SELECT 1"})
        assert result.decision == "DENY"
        assert "PERMISSION_MISSING" in result.reason_codes

    def test_agent_id_mismatch_denied(self, db, support_agent):
        result = evaluate(
            db, support_agent, "search_knowledge_base", {"query": "x"}, agent_id="someone-else"
        )
        assert result.decision == "DENY"
        assert "AGENT_ID_MISMATCH" in result.reason_codes

    def test_environment_mismatch_denied(self, db, support_agent):
        result = evaluate(
            db,
            support_agent,
            "search_knowledge_base",
            {"query": "x"},
            environment="dev",
        )
        assert result.decision == "DENY"
        assert "ENVIRONMENT_MISMATCH" in result.reason_codes

    def test_schema_validation_failure_denied(self, db, support_agent):
        result = evaluate(db, support_agent, "send_email", {"to": "not-an-email"})
        assert result.decision == "DENY"
        assert "SCHEMA_VALIDATION_FAILED" in result.reason_codes

    def test_every_decision_is_audited(self, db, support_agent):
        before = db.query(AuditEvent).count()
        evaluate(db, support_agent, "search_knowledge_base", {"query": "x"})
        evaluate(db, support_agent, "delete_customer_record", {"customer_id": "c", "reason": "r"})
        after = db.query(AuditEvent).count()
        assert after - before == 2

    def test_idempotent_replay_returns_original_decision(self, db, support_agent):
        key = "idem-12345"
        first = evaluate(db, support_agent, "search_knowledge_base", {"query": "x"}, idempotency_key=key)
        second = evaluate(db, support_agent, "search_knowledge_base", {"query": "x"}, idempotency_key=key)
        assert first.action_id == second.action_id
        assert first.decision == second.decision


class TestApprovalFlow:
    def _request_email(self, db, agent, to="customer@example.com", subject="Hi", body="Hello there"):
        return evaluate(
            db, agent, "send_email", {"to": to, "subject": subject, "body": body}, target=to
        )

    def test_approval_created_and_pending(self, db, support_agent):
        result = self._request_email(db, support_agent)
        assert result.decision == "REQUIRE_APPROVAL"
        assert result.approval_id is not None

        approval = db.get(Approval, result.approval_id)
        assert approval.status == "PENDING"
        assert approval.payload_hash == payload_hash(
            "send_email",
            "customer@example.com",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
        )

    def test_reject_prevents_execution(self, db, support_agent):
        result = self._request_email(db, support_agent)
        approvals_service.decide(
            db,
            db.get(Approval, result.approval_id),
            "u-approver",
            ApprovalDecision(decision="REJECTED", reason="no"),
        )
        retry = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "DENY"
        assert "APPROVAL_NOT_APPROVED" in retry.reason_codes

    def test_approve_then_revalidate_allows(self, db, support_agent):
        result = self._request_email(db, support_agent)
        approvals_service.decide(
            db,
            db.get(Approval, result.approval_id),
            "u-approver",
            ApprovalDecision(decision="APPROVED"),
        )
        retry = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "ALLOW"
        assert "APPROVAL_SATISFIES_RULE" in retry.reason_codes

        approval = db.get(Approval, result.approval_id)
        assert approval.status == "CONSUMED"

    def test_approval_is_single_use(self, db, support_agent):
        result = self._request_email(db, support_agent)
        approvals_service.decide(
            db,
            db.get(Approval, result.approval_id),
            "u-approver",
            ApprovalDecision(decision="APPROVED"),
        )
        args = {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"}
        first = evaluate(
            db, support_agent, "send_email", args, target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert first.decision == "ALLOW"

        # Replaying the same approval must not execute again.
        second = evaluate(
            db, support_agent, "send_email", args, target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert second.decision == "DENY"

    def test_changed_payload_cannot_reuse_approval(self, db, support_agent):
        result = self._request_email(db, support_agent)
        approvals_service.decide(
            db,
            db.get(Approval, result.approval_id),
            "u-approver",
            ApprovalDecision(decision="APPROVED"),
        )
        retry = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "CHANGED", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "DENY"
        assert "PAYLOAD_HASH_MISMATCH" in retry.reason_codes

    def test_expired_approval_denied(self, db, support_agent):
        result = self._request_email(db, support_agent)
        approval = db.get(Approval, result.approval_id)
        approvals_service.decide(
            db, approval, "u-approver", ApprovalDecision(decision="APPROVED")
        )
        approval.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.commit()

        retry = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "DENY"
        assert "APPROVAL_EXPIRED" in retry.reason_codes

    def test_another_agents_approval_denied(self, db, support_agent):
        result = self._request_email(db, support_agent)
        other = db.get(Agent, "agent-analyst")
        retry = evaluate(
            db,
            other,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "DENY"
        assert "APPROVAL_NOT_YOURS" in retry.reason_codes

    def test_unknown_approval_denied(self, db, support_agent):
        result = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id="does-not-exist",
        )
        assert result.decision == "DENY"
        assert "APPROVAL_NOT_FOUND" in result.reason_codes

    def test_deny_rule_still_wins_after_approval(self, db, support_agent):
        """A policy change that adds a deny rule must block even an approved action."""
        result = self._request_email(db, support_agent)
        approvals_service.decide(
            db,
            db.get(Approval, result.approval_id),
            "u-approver",
            ApprovalDecision(decision="APPROVED"),
        )
        from app.models import Policy

        policy = db.get(Policy, "policy-prod")
        policy.rules = [
            *policy.rules,
            {"id": "deny-all-email", "effect": "DENY", "tool": "send_email"},
        ]
        db.commit()

        retry = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "Hello there"},
            target="customer@example.com",
            approval_id=result.approval_id,
        )
        assert retry.decision == "DENY"
        assert "POLICY_REVALIDATION_DENIED" in retry.reason_codes


class TestExecutionReporting:
    def test_report_result_creates_execution_event(self, db, support_agent):
        decision = evaluate(db, support_agent, "search_knowledge_base", {"query": "x"})
        event = decisions_service.report_result(
            db,
            support_agent,
            decision.action_id,
            ActionResultRequest(success=True, duration_ms=42),
        )
        assert event.event_type == "execution"
        assert event.decision == "ALLOW"
        assert event.metadata["success"] is True

    def test_report_result_is_idempotent(self, db, support_agent):
        decision = evaluate(db, support_agent, "search_knowledge_base", {"query": "x"})
        first = decisions_service.report_result(
            db, support_agent, decision.action_id, ActionResultRequest(success=True)
        )
        second = decisions_service.report_result(
            db, support_agent, decision.action_id, ActionResultRequest(success=True)
        )
        assert first.id == second.id

    def test_cannot_report_for_denied_action(self, db, support_agent):
        decision = evaluate(
            db, support_agent, "delete_customer_record", {"customer_id": "c", "reason": "r"}
        )
        with pytest.raises(ConflictError):
            decisions_service.report_result(
                db, support_agent, decision.action_id, ActionResultRequest(success=True)
            )

    def test_cannot_report_for_unknown_action(self, db, support_agent):
        with pytest.raises(ApiError):
            decisions_service.report_result(
                db, support_agent, "no-such-action", ActionResultRequest(success=True)
            )


class TestRedaction:
    def test_secrets_redacted_in_audit_metadata(self, db, support_agent):
        evaluate(
            db,
            support_agent,
            "send_email",
            {
                "to": "customer@example.com",
                "subject": "Hello",
                "body": "my password=hunter2 and token abcdef",
            },
            target="customer@example.com",
        )
        event = (
            db.query(AuditEvent)
            .filter(AuditEvent.tool_name == "send_email", AuditEvent.event_type == "decision")
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        stored = str(event.redacted_metadata)
        assert "hunter2" not in stored
        assert "[redacted]" in stored

    def test_approval_summary_redacts_sensitive_fields(self, db, support_agent):
        result = evaluate(
            db,
            support_agent,
            "send_email",
            {"to": "customer@example.com", "subject": "Hi", "body": "sensitive body text"},
            target="customer@example.com",
        )
        approval = db.get(Approval, result.approval_id)
        assert approval.arguments_summary["body"] == "[redacted]"
        assert approval.arguments_summary["to"] == "customer@example.com"


class TestAgentAuthentication:
    def test_valid_key_authenticates(self, db, support_agent):
        from app.security import generate_agent_key, hash_key

        key = generate_agent_key()
        support_agent.credential_hash = hash_key(key)
        db.commit()
        assert agents_service.authenticate(db, key).id == support_agent.id

    def test_invalid_key_fails_closed(self, db):
        assert agents_service.authenticate(db, "ag_not_a_real_key") is None
        assert agents_service.authenticate(db, None) is None
        assert agents_service.authenticate(db, "") is None

    def test_timing_safe_comparison(self, db, support_agent):
        from app.security import hash_key, verify_key

        support_agent.credential_hash = hash_key("ag_correct")
        db.commit()
        assert verify_key("ag_correct", support_agent.credential_hash) is True
        assert verify_key("ag_wrong", support_agent.credential_hash) is False
