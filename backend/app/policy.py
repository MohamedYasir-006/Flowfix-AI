"""Deterministic policy evaluation.

Implements the blueprint's decision precedence:

1. Disabled agent                       -> DENY
2. Disabled or unregistered tool        -> DENY
3. Missing agent-tool permission        -> DENY
4. Explicit deny rule                   -> DENY
5. Protected action matching an approval rule -> REQUIRE_APPROVAL
6. Matching allow rule and valid scope  -> ALLOW
7. No matching allow rule               -> DENY (default deny)

All active policies are combined: an explicit deny in any active policy wins,
then an approval rule, then an allow rule. An explicit deny always overrides an
allow, and an approval never overrides a hard deny.
"""

from dataclasses import dataclass, field
from typing import Any

from .models import Agent, Policy, Tool, Settings
from .risk import assess_risk, exceeds_max, is_approval_risk
from .schemas import Decision, RiskAssessment


@dataclass
class EvaluationContext:
    agent: Agent | None
    tool: Tool | None
    environment: str
    target: str | None
    arguments: dict[str, Any]
    has_permission: bool
    policies: list[Policy] = field(default_factory=list)
    settings: Settings | None = None
    # Approval rules whose human decision has already been granted. Used only on
    # the post-approval re-evaluation path so the same rule does not re-trigger.
    satisfied_approval_rule_ids: list[str] = field(default_factory=list)


@dataclass
class PolicyDecision:
    decision: Decision
    reason_codes: list[str]
    risk: RiskAssessment
    policy_id: str | None = None
    policy_version: int | None = None
    rule_id: str | None = None
    explanation: str = ""

    def to_response_dict(self, action_id: str) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "decision": self.decision,
            "risk": {"level": self.risk.level, "reasons": self.risk.reasons},
            "reason_codes": self.reason_codes,
            "policy": (
                {"id": self.policy_id, "version": self.policy_version}
                if self.policy_id
                else None
            ),
        }


def rule_matches(
    rule: dict[str, Any],
    agent: Agent,
    tool: Tool,
    environment: str,
    target: str | None,
) -> bool:
    """A rule matches when every field it specifies matches the request."""

    def equals(field: str, actual: str | None) -> bool:
        expected = rule.get(field)
        return expected is None or expected == actual

    if not equals("agent", agent.name):
        return False
    if not equals("tool", tool.name):
        return False
    if not equals("environment", environment):
        return False
    if not equals("target", target):
        return False

    category = rule.get("category")
    if category is not None and category != tool.category:
        return False

    return True


def evaluate(context: EvaluationContext) -> PolicyDecision:
    agent = context.agent
    tool = context.tool

    # 1. Agent must be registered and enabled.
    if agent is None:
        return PolicyDecision(
            decision="DENY",
            reason_codes=["AGENT_NOT_REGISTERED"],
            risk=RiskAssessment(level="HIGH", reasons=["AGENT_NOT_REGISTERED"]),
            explanation="The calling credential does not belong to a registered agent.",
        )
    if agent.status == "DISABLED":
        return PolicyDecision(
            decision="DENY",
            reason_codes=["AGENT_DISABLED"],
            risk=RiskAssessment(level="HIGH", reasons=["AGENT_DISABLED"]),
            explanation=f"Agent '{agent.name}' is disabled.",
        )

    # 2. Tool must be registered and enabled.
    if tool is None:
        return PolicyDecision(
            decision="DENY",
            reason_codes=["TOOL_NOT_REGISTERED"],
            risk=RiskAssessment(level="HIGH", reasons=["TOOL_NOT_REGISTERED"]),
            explanation="The requested tool is not registered. Unregistered tools are denied by default.",
        )
    if tool.status == "DISABLED":
        return PolicyDecision(
            decision="DENY",
            reason_codes=["TOOL_DISABLED"],
            risk=assess_risk(tool, agent, context.environment, context.arguments),
            explanation=f"Tool '{tool.name}' is disabled.",
        )

    risk = assess_risk(tool, agent, context.environment, context.arguments)

    # 3. Least privilege: the agent must hold the tool permission.
    if not context.has_permission:
        return PolicyDecision(
            decision="DENY",
            reason_codes=["PERMISSION_MISSING"],
            risk=risk,
            explanation=f"Agent '{agent.name}' is not permitted to use tool '{tool.name}'.",
        )

    # 4. No active policy means no allow rule can exist. Agent and tool checks
    #    above already ran, so their more specific reason codes win.
    active_policies = [policy for policy in context.policies if policy.status == "ACTIVE"]
    if not active_policies:
        return PolicyDecision(
            decision="DENY",
            reason_codes=["NO_ACTIVE_POLICY"],
            risk=risk,
            explanation="No active policy is published; default deny applies.",
        )

    matching: list[tuple[Policy, dict[str, Any]]] = []
    for policy in active_policies:
        for rule in policy.rules:
            if rule_matches(rule, agent, tool, context.environment, context.target):
                matching.append((policy, rule))

    # 5. Explicit deny overrides everything.
    deny_hits = [(policy, rule) for policy, rule in matching if rule.get("effect") == "DENY"]
    if deny_hits:
        policy, rule = deny_hits[0]
        codes = ["EXPLICIT_DENY_RULE"] + risk.reasons
        return PolicyDecision(
            decision="DENY",
            reason_codes=list(dict.fromkeys(codes)),
            risk=risk,
            policy_id=policy.id,
            policy_version=policy.version,
            rule_id=rule.get("id"),
            explanation=f"Matched deny rule '{rule.get('id')}' in policy '{policy.name}' v{policy.version}.",
        )

    # 6. Approval rules come before allow rules, unless the human decision that
    #    satisfies them has already been granted for this action.
    approval_hits = [
        (policy, rule)
        for policy, rule in matching
        if rule.get("effect") == "REQUIRE_APPROVAL"
    ]
    if approval_hits:
        policy, rule = approval_hits[0]
        if rule.get("id") in context.satisfied_approval_rule_ids:
            # The approval is the human decision for this rule. Policy has been
            # re-evaluated; allow execution (an explicit deny already won above).
            codes = ["POLICY_REVALIDATED", "APPROVAL_SATISFIES_RULE", *risk.reasons]
            return PolicyDecision(
                decision="ALLOW",
                reason_codes=list(dict.fromkeys(codes)),
                risk=risk,
                policy_id=policy.id,
                policy_version=policy.version,
                rule_id=rule.get("id"),
                explanation=(
                    f"Rule '{rule.get('id')}' required approval and was granted; "
                    f"policy re-validated against '{policy.name}' v{policy.version}."
                ),
            )
        codes = ["POLICY_APPROVAL_REQUIRED"] + risk.reasons
        return PolicyDecision(
            decision="REQUIRE_APPROVAL",
            reason_codes=list(dict.fromkeys(codes)),
            risk=risk,
            policy_id=policy.id,
            policy_version=policy.version,
            rule_id=rule.get("id"),
            explanation=(
                f"Matched approval rule '{rule.get('id')}' in policy "
                f"'{policy.name}' v{policy.version}. A human must approve before execution."
            ),
        )

    # 7. Matching allow rule.
    allow_hits: list[tuple[Policy, dict[str, Any]]] = []
    for policy, rule in matching:
        if rule.get("effect") != "ALLOW":
            continue
        if exceeds_max(tool.default_risk, rule.get("risk_max") or rule.get("riskMax")):
            continue
        allow_hits.append((policy, rule))

    if allow_hits:
        policy, rule = allow_hits[0]
        codes = ["TOOL_REGISTERED", "PERMISSION_GRANTED"]
        if rule.get("risk_max") or rule.get("riskMax"):
            codes.append("RISK_WITHIN_LIMIT")

        require_approval_for = (
            context.settings.require_approval_for if context.settings else ["HIGH", "CRITICAL"]
        )
        if is_approval_risk(risk.level, require_approval_for):
            codes.append("POLICY_APPROVAL_REQUIRED")
            return PolicyDecision(
                decision="REQUIRE_APPROVAL",
                reason_codes=list(dict.fromkeys(codes)),
                risk=risk,
                policy_id=policy.id,
                policy_version=policy.version,
                rule_id=rule.get("id"),
                explanation=(
                    f"Action is allowed by rule '{rule.get('id')}' but the risk level "
                    f"{risk.level} requires human approval under workspace settings."
                ),
            )

        return PolicyDecision(
            decision="ALLOW",
            reason_codes=list(dict.fromkeys(codes)),
            risk=risk,
            policy_id=policy.id,
            policy_version=policy.version,
            rule_id=rule.get("id"),
            explanation=f"Matched allow rule '{rule.get('id')}' in policy '{policy.name}' v{policy.version}.",
        )

    # 8. Default deny.
    fallback = max(active_policies, key=lambda p: p.version)
    return PolicyDecision(
        decision="DENY",
        reason_codes=["NO_MATCHING_ALLOW_RULE", "DEFAULT_DENY"],
        risk=risk,
        policy_id=fallback.id,
        policy_version=fallback.version,
        explanation=(
            f"No allow rule matched in policy '{fallback.name}' v{fallback.version}; "
            "default deny applies."
        ),
    )
