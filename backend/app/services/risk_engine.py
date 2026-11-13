"""Deterministic, explainable risk aggregation.

This module never decides authorization. It translates policy risk, propagation
violations, operational state, and reliability evidence into a stable score,
rule list, and recommended action. The enforcement decision comes from the
policy and propagation engines.
"""

from __future__ import annotations

from typing import Any

_LEVEL_SCORE = {"LOW": 15, "MEDIUM": 40, "HIGH": 70, "CRITICAL": 95}
_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _max_level(*levels: str) -> str:
    return max(levels, key=lambda level: _RANK.get(level, 0))


def compute_risk(
    *,
    action_risk: str,
    decision: str,
    propagation: dict[str, Any] | None,
    reliability: dict[str, Any] | None = None,
    operational_status: str = "ACTIVE",
    policy_explanation: str = "",
) -> dict[str, Any]:
    level = action_risk if action_risk in _LEVEL_SCORE else "MEDIUM"
    score = _LEVEL_SCORE[level]
    rules: list[dict[str, Any]] = [
        {
            "rule": "ACTION_RISK",
            "level": level,
            "evidence": f"Policy risk for this tool/context is {level}.",
        }
    ]
    evidence: list[str] = []
    if policy_explanation:
        evidence.append(policy_explanation)

    propagation = propagation or {}
    if propagation.get("applicable"):
        level = _max_level(level, propagation.get("risk_level", "LOW"))
        score = max(score, _LEVEL_SCORE.get(level, score))
        for violation in propagation.get("violated_rules", []):
            rules.append(
                {
                    "rule": violation.get("rule"),
                    "effect": violation.get("effect"),
                    "reasonCode": violation.get("reason_code"),
                    "evidence": violation.get("evidence"),
                }
            )
        evidence.extend(propagation.get("evidence", []))

    if reliability:
        rel_level = reliability.get("level", "INSUFFICIENT")
        if rel_level in ("LOW", "CRITICAL"):
            bump = "HIGH" if rel_level == "LOW" else "CRITICAL"
            level = _max_level(level, bump)
            score = max(score, _LEVEL_SCORE[bump])
        rules.append(
            {
                "rule": "AGENT_RELIABILITY",
                "level": rel_level,
                "score": reliability.get("score"),
                "confidence": reliability.get("confidence"),
                "evidence": "; ".join(reliability.get("contributing_factors", [])),
            }
        )
        evidence.append(
            f"Reliability level {rel_level} "
            f"(score {reliability.get('score')}, confidence {reliability.get('confidence')})."
        )

    if operational_status != "ACTIVE":
        rules.append(
            {
                "rule": "OPERATIONAL_STATE",
                "level": operational_status,
                "evidence": f"Agent operational status is {operational_status}.",
            }
        )
        if operational_status == "QUARANTINED":
            level = "CRITICAL"
            score = max(score, 100)

    if decision == "DENY":
        score = max(score, 80)
    elif decision == "REQUIRE_APPROVAL":
        score = max(score, 55)

    if decision == "DENY":
        recommended = (
            "Do not execute. Review the triggered evidence, repair the upstream "
            "artifact or agent state, and retry through normal policy evaluation."
        )
    elif decision == "REQUIRE_APPROVAL":
        recommended = (
            "Pause this action for human review. The approver must see the upstream "
            "evidence before approving; the approval is payload-bound and single-use."
        )
    else:
        recommended = "Allowed by policy and propagation checks. Execute and report the result."

    return {
        "level": level,
        "score": min(100, int(score)),
        "rules": rules,
        "evidence": list(dict.fromkeys(evidence)),
        "recommended_action": recommended,
    }
