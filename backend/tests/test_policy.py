"""Unit tests for the deterministic policy engine.

These mirror the blueprint's acceptance checklist: unregistered/disabled
agents and tools, missing permissions, explicit deny precedence, default deny,
and approval rules.
"""

from __future__ import annotations

import pytest

from app.models import Agent, Policy, Tool
from app.policy import EvaluationContext, evaluate
from app.risk import RISK_RANK, assess_risk, exceeds_max


def make_tool(**overrides) -> Tool:
    values = dict(
        id="t1",
        name="send_email",
        description="",
        input_schema={},
        category="external",
        default_risk="HIGH",
        status="ACTIVE",
        created_at="2026-01-01T00:00:00+00:00",
    )
    values.update(overrides)
    return Tool(**values)


def make_agent(**overrides) -> Agent:
    values = dict(
        id="a1",
        name="support-agent",
        owner_user_id="u-admin",
        environment="prod",
        status="ACTIVE",
        credential_hash="x",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    values.update(overrides)
    return Agent(**values)


def make_policy(rules: list[dict], status: str = "ACTIVE", version: int = 1) -> Policy:
    return Policy(
        id="p1",
        name="test policy",
        description="",
        version=version,
        rules=rules,
        default_effect="DENY",
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def low_risk_tool(**overrides) -> Tool:
    """A tool whose category and declared risk are both LOW.

    Risk is ``max(category baseline, default_risk)``, so both must be LOW for
    the action to avoid the workspace approval threshold.
    """
    values = dict(
        id="t-low",
        name="search_knowledge_base",
        description="",
        input_schema={},
        category="read",
        default_risk="LOW",
        status="ACTIVE",
        created_at="2026-01-01T00:00:00+00:00",
    )
    values.update(overrides)
    return Tool(**values)


def ctx(tool=None, agent=None, policies=None, has_permission=True, **kwargs):
    """Build an evaluation context.

    ``agent``/``tool`` default to a valid seeded-shaped object; pass a sentinel
    of ``False`` to represent "not registered" (``None`` is a valid ORM value
    for "no row", so an explicit False keeps the distinction unambiguous).
    """
    from app.models import Settings

    if agent is None:
        agent = make_agent()
    elif agent is False:
        agent = None  # type: ignore[assignment]
    if tool is None:
        tool = make_tool()
    elif tool is False:
        tool = None  # type: ignore[assignment]

    settings = kwargs.pop("settings", None)
    if settings is None:
        # Mirror the workspace defaults so unit tests are deterministic and do
        # not silently depend on whether a Settings row exists.
        settings = Settings(
            id="1",
            workspace_name="test",
            default_environment="prod",
            approval_ttl_minutes=240,
            retention_days=90,
            redact_secrets=1,
            redact_fields=[],
            require_approval_for=["HIGH", "CRITICAL"],
            max_payload_bytes=65536,
        )
    return EvaluationContext(
        agent=agent,
        tool=tool,
        environment=kwargs.pop("environment", "prod"),
        target=kwargs.pop("target", None),
        arguments=kwargs.pop("arguments", {}),
        has_permission=has_permission,
        policies=policies if policies is not None else [],
        settings=settings,
        **kwargs,
    )


class TestPrecedence:
    def test_unregistered_agent_denied(self):
        decision = evaluate(ctx(agent=False, tool=low_risk_tool(), policies=[make_policy([])]))
        assert decision.decision == "DENY"
        assert "AGENT_NOT_REGISTERED" in decision.reason_codes

    def test_disabled_agent_denied(self):
        decision = evaluate(
            ctx(
                agent=make_agent(status="DISABLED"),
                tool=low_risk_tool(),
                policies=[make_policy([])],
            )
        )
        assert decision.decision == "DENY"
        assert "AGENT_DISABLED" in decision.reason_codes

    def test_unregistered_tool_denied(self):
        decision = evaluate(ctx(tool=False, policies=[make_policy([])]))
        assert decision.decision == "DENY"
        assert "TOOL_NOT_REGISTERED" in decision.reason_codes

    def test_disabled_tool_denied(self):
        decision = evaluate(
            ctx(tool=low_risk_tool(status="DISABLED"), policies=[make_policy([])])
        )
        assert decision.decision == "DENY"
        assert "TOOL_DISABLED" in decision.reason_codes

    def test_missing_permission_denied(self):
        decision = evaluate(ctx(has_permission=False))
        assert decision.decision == "DENY"
        assert "PERMISSION_MISSING" in decision.reason_codes

    def test_no_active_policy_denied(self):
        decision = evaluate(ctx(policies=[]))
        assert decision.decision == "DENY"
        assert "NO_ACTIVE_POLICY" in decision.reason_codes

    def test_explicit_deny_overrides_allow(self):
        policy = make_policy(
            [
                {"id": "allow", "effect": "ALLOW", "tool": "send_email"},
                {"id": "deny", "effect": "DENY", "tool": "send_email"},
            ]
        )
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "DENY"
        assert decision.rule_id == "deny"
        assert "EXPLICIT_DENY_RULE" in decision.reason_codes

    def test_no_matching_allow_rule_is_default_deny(self):
        policy = make_policy([{"id": "allow-other", "effect": "ALLOW", "tool": "other_tool"}])
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "DENY"
        assert "DEFAULT_DENY" in decision.reason_codes

    def test_matching_allow_rule_allows(self):
        policy = make_policy([{"id": "allow", "effect": "ALLOW", "tool": "search_knowledge_base"}])
        decision = evaluate(ctx(policies=[policy], tool=low_risk_tool()))
        assert decision.decision == "ALLOW"
        assert decision.rule_id == "allow"

    def test_high_risk_allow_rule_requires_approval(self):
        """Workspace settings elevate a HIGH-risk allow to REQUIRE_APPROVAL."""
        policy = make_policy([{"id": "allow", "effect": "ALLOW", "tool": "send_email"}])
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "REQUIRE_APPROVAL"
        assert "POLICY_APPROVAL_REQUIRED" in decision.reason_codes

    def test_approval_rule_requires_approval(self):
        policy = make_policy([{"id": "approve", "effect": "REQUIRE_APPROVAL", "tool": "send_email"}])
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "REQUIRE_APPROVAL"
        assert "POLICY_APPROVAL_REQUIRED" in decision.reason_codes

    def test_deny_beats_approval_rule(self):
        policy = make_policy(
            [
                {"id": "approve", "effect": "REQUIRE_APPROVAL", "tool": "send_email"},
                {"id": "deny", "effect": "DENY", "tool": "send_email"},
            ]
        )
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "DENY"

    def test_satisfied_approval_rule_allows_after_revalidation(self):
        policy = make_policy([{"id": "approve", "effect": "REQUIRE_APPROVAL", "tool": "send_email"}])
        decision = evaluate(
            ctx(policies=[policy], satisfied_approval_rule_ids=["approve"])
        )
        assert decision.decision == "ALLOW"
        assert "APPROVAL_SATISFIES_RULE" in decision.reason_codes

    def test_draft_policy_is_ignored(self):
        policy = make_policy([{"id": "allow", "effect": "ALLOW", "tool": "send_email"}], status="DRAFT")
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "DENY"
        assert "NO_ACTIVE_POLICY" in decision.reason_codes


class TestRuleMatching:
    def test_rule_fields_all_must_match(self):
        policy = make_policy(
            [{"id": "r", "effect": "ALLOW", "agent": "support-agent", "environment": "prod"}]
        )
        assert (
            evaluate(ctx(policies=[policy], tool=low_risk_tool())).decision == "ALLOW"
        )
        assert (
            evaluate(
                ctx(policies=[policy], environment="dev", tool=low_risk_tool())
            ).decision
            == "DENY"
        )

    def test_category_matching(self):
        policy = make_policy([{"id": "r", "effect": "ALLOW", "category": "read"}])
        assert (
            evaluate(ctx(policies=[policy], tool=low_risk_tool())).decision == "ALLOW"
        )
        assert (
            evaluate(
                ctx(policies=[policy], tool=low_risk_tool(category="write"))
            ).decision
            == "DENY"
        )

    def test_risk_max_ceiling_blocks_allow(self):
        policy = make_policy(
            [{"id": "r", "effect": "ALLOW", "tool": "send_email", "riskMax": "LOW"}]
        )
        # Tool risk HIGH exceeds the LOW ceiling, so the rule cannot allow it.
        assert evaluate(ctx(policies=[policy])).decision == "DENY"

    def test_risk_max_allows_when_within_limit(self):
        policy = make_policy(
            [{"id": "r", "effect": "ALLOW", "tool": "send_email", "riskMax": "CRITICAL"}]
        )
        # riskMax CRITICAL permits HIGH, but workspace settings still require
        # approval for HIGH-risk actions.
        decision = evaluate(ctx(policies=[policy]))
        assert decision.decision == "REQUIRE_APPROVAL"


class TestRisk:
    def test_destructive_is_critical(self):
        risk = assess_risk(make_tool(category="destructive"), make_agent(), "prod", {})
        assert risk.level == "CRITICAL"
        assert "DESTRUCTIVE_OPERATION" in risk.reasons

    def test_external_is_high(self):
        risk = assess_risk(make_tool(category="external"), make_agent(), "prod", {})
        assert risk.level == "HIGH"

    def test_prod_floor_is_medium(self):
        risk = assess_risk(make_tool(category="read", default_risk="LOW"), make_agent(), "prod", {})
        assert risk.level == "MEDIUM"
        assert "PRODUCTION_ENVIRONMENT" in risk.reasons

    def test_dev_low_stays_low(self):
        risk = assess_risk(
            make_tool(category="read", default_risk="LOW"),
            make_agent(environment="dev"),
            "dev",
            {},
        )
        assert risk.level == "LOW"

    def test_external_destination_detected(self):
        risk = assess_risk(
            make_tool(category="external"),
            make_agent(),
            "prod",
            {"to": "someone@example.com"},
        )
        assert "EXTERNAL_DESTINATION" in risk.reasons

    def test_risk_ordering(self):
        assert RISK_RANK["LOW"] < RISK_RANK["MEDIUM"] < RISK_RANK["HIGH"] < RISK_RANK["CRITICAL"]

    def test_exceeds_max(self):
        assert exceeds_max("HIGH", "MEDIUM") is True
        assert exceeds_max("MEDIUM", "MEDIUM") is False
        assert exceeds_max("LOW", "MEDIUM") is False
        assert exceeds_max("HIGH", None) is False
