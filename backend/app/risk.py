"""Deterministic risk scoring.

Risk is derived from registered tool metadata and request context only — no
model calls in the critical path. Every assessment carries the reason codes
that produced it so decisions stay explainable.
"""

from .models import Agent, Tool
from .schemas import RiskAssessment

RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RISK_RANK = {level: index for index, level in enumerate(RISK_ORDER)}

CATEGORY_BASELINE = {
    "read": "LOW",
    "write": "MEDIUM",
    "external": "HIGH",
    "destructive": "CRITICAL",
}


def _rank(level: str) -> int:
    return RISK_RANK.get(level, 0)


def _max_level(*levels: str) -> str:
    return max(levels, key=_rank)


def assess_risk(
    tool: Tool | None,
    agent: Agent | None,
    environment: str,
    arguments: dict | None = None,
) -> RiskAssessment:
    """Return an explainable risk assessment for a proposed action."""
    reasons: list[str] = []

    if agent is None:
        return RiskAssessment(level="HIGH", reasons=["AGENT_NOT_REGISTERED"])

    if tool is None:
        return RiskAssessment(level="HIGH", reasons=["TOOL_NOT_REGISTERED"])

    baseline = CATEGORY_BASELINE.get(tool.category, tool.default_risk)
    level = _max_level(tool.default_risk, baseline)

    # Category-specific explainability.
    if tool.category == "destructive":
        reasons.append("DESTRUCTIVE_OPERATION")
    elif tool.category == "external":
        reasons.append("EXTERNAL_COMMUNICATION")
    elif tool.category == "write":
        reasons.append("WRITE_OPERATION")
    elif tool.category == "read":
        reasons.append("DATA_ACCESS")

    if environment == "prod":
        reasons.append("PRODUCTION_ENVIRONMENT")
        level = _max_level(level, "MEDIUM")

    if _rank(level) >= _rank("HIGH"):
        reasons.append("PRIVILEGED_TOOL")

    if arguments:
        target = arguments.get("to") or arguments.get("recipient")
        if isinstance(target, str) and "@" in target:
            reasons.append("EXTERNAL_DESTINATION")

    if not reasons:
        reasons.append("TOOL_DEFAULT_RISK")

    return RiskAssessment(level=level, reasons=list(dict.fromkeys(reasons)))


def exceeds_max(tool_risk: str, risk_max: str | None) -> bool:
    """True when the tool risk is above an allow rule's ``riskMax`` ceiling."""
    if not risk_max:
        return False
    return _rank(tool_risk) > _rank(risk_max)


def is_approval_risk(level: str, require_approval_for: list[str]) -> bool:
    return level in require_approval_for
