"""Failure propagation intelligence.

This is the core V2 differentiator: an action is not authorized solely because
the calling agent is allowed to perform it. The engine walks the action's
upstream artifact/dependency graph and determines whether the action depends on
information or agents that are not trustworthy.

The engine is deterministic. It has no model calls and returns no ALLOW: it can
only leave a policy decision unchanged, require approval, or deny. An explicit
policy DENY evaluated elsewhere always wins.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Agent, AgentState, Artifact, Dependency, WorkflowExecution
from .dependencies import upstream_artifacts

DEFAULT_PROPAGATION_POLICY: dict[str, Any] = {
    "invalid_upstream": "DENY",
    "quarantined_upstream": "DENY",
    "repeated_upstream_failures": "DENY",
    "excessive_dependency_depth": "DENY",
    "missing_provenance": "REQUIRE_APPROVAL",
    "conflicting_sources": "REQUIRE_APPROVAL",
    "expired_upstream": "REQUIRE_APPROVAL",
    "stale_upstream": "REQUIRE_APPROVAL",
    "unverified_high_impact": "REQUIRE_APPROVAL",
    "high_impact_risk_levels": ["HIGH", "CRITICAL"],
    "max_depth": 12,
    "repeated_failure_threshold": 3,
}

_EFFECT_RANK = {"NONE": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}


def effective_policy(settings_row) -> dict[str, Any]:
    policy = dict(DEFAULT_PROPAGATION_POLICY)
    configured = (settings_row.propagation_policy if settings_row else None) or {}
    for key, value in configured.items():
        if key in policy:
            policy[key] = value
    policy["max_depth"] = int(policy["max_depth"])
    policy["repeated_failure_threshold"] = int(policy["repeated_failure_threshold"])
    return policy


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        value = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _stronger(left: str, right: str) -> str:
    return left if _EFFECT_RANK[left] >= _EFFECT_RANK[right] else right


def evaluate_propagation(
    db: Session,
    *,
    org_id: str,
    agent: Agent,
    workflow_execution_id: str | None,
    agent_execution_id: str | None,
    input_artifact_ids: list[str],
    action_risk: str,
    settings_row,
    tool_name: str | None = None,
) -> dict[str, Any]:
    policy = effective_policy(settings_row)
    settings = get_settings()

    base: dict[str, Any] = {
        "applicable": bool(workflow_execution_id or input_artifact_ids),
        "effect": "NONE",
        "violated_rules": [],
        "reason_codes": [],
        "origin_agents": [],
        "affected_agents": [],
        "affected_workflows": [],
        "upstream_artifact_ids": [],
        "risk_level": "LOW",
        "recommended_action": "Proceed with normal policy evaluation.",
        "evidence": [],
        "effective_policy": {
            key: policy[key]
            for key in (
                "invalid_upstream",
                "quarantined_upstream",
                "repeated_upstream_failures",
                "excessive_dependency_depth",
                "missing_provenance",
                "conflicting_sources",
                "expired_upstream",
                "stale_upstream",
                "unverified_high_impact",
                "high_impact_risk_levels",
                "max_depth",
                "repeated_failure_threshold",
            )
        },
    }
    if not base["applicable"]:
        return base

    if workflow_execution_id:
        execution = db.get(WorkflowExecution, workflow_execution_id)
        if execution is None or execution.org_id != org_id:
            return _deny_invalid_context(base, "Workflow execution not found for this tenant")
        if execution.status in ("PAUSED", "FAILED"):
            return _deny_invalid_context(
                base, f"Workflow execution is {execution.status.lower()}", "WORKFLOW_NOT_RUNNING"
            )

    high_impact = action_risk in policy["high_impact_risk_levels"]

    artifacts = upstream_artifacts(
        db,
        org_id,
        artifact_ids=input_artifact_ids,
        agent_execution_id=agent_execution_id,
        agent_id=agent.id,
        max_depth=policy["max_depth"],
    )
    base["upstream_artifact_ids"] = [artifact.id for artifact, _ in artifacts]

    violations: list[dict[str, Any]] = []
    evidence: list[str] = []
    origin_agents: set[str] = set()
    affected_agents: dict[str, str] = {}
    affected_workflows: set[str] = set()

    def add(rule: str, effect_key: str, reason: str, detail: str, **extra: Any) -> None:
        effect = str(policy.get(effect_key, "NONE"))
        if effect == "NONE":
            return
        violations.append(
            {
                "rule": rule,
                "effect": effect,
                "reason_code": reason,
                "evidence": detail,
                **extra,
            }
        )

    now = datetime.now(timezone.utc)
    for artifact, depth in artifacts:
        if artifact.workflow_execution_id:
            affected_workflows.add(artifact.workflow_execution_id)
        origin_agents.add(artifact.producer_agent_id)
        affected_agents[artifact.producer_agent_id] = "upstream producer"
        if depth > policy["max_depth"]:
            add(
                "excessive_dependency_depth",
                "excessive_dependency_depth",
                "EXCESSIVE_DEPENDENCY_DEPTH",
                f"Upstream chain exceeds {policy['max_depth']} hops (artifact {artifact.id})",
            )
            continue

        status = artifact.validation_status
        if status in ("INVALID", "REJECTED"):
            add(
                "invalid_upstream",
                "invalid_upstream",
                "INVALID_UPSTREAM_ARTIFACT",
                f"Artifact {artifact.name or artifact.id} is {status}",
                artifact_id=artifact.id,
            )
        elif status == "QUARANTINED":
            add(
                "invalid_upstream",
                "quarantined_upstream",
                "QUARANTINED_UPSTREAM_ARTIFACT",
                f"Artifact {artifact.name or artifact.id} is quarantined",
                artifact_id=artifact.id,
            )
        elif status == "EXPIRED":
            add(
                "expired_upstream",
                "expired_upstream",
                "EXPIRED_UPSTREAM_ARTIFACT",
                f"Artifact {artifact.name or artifact.id} is expired",
                artifact_id=artifact.id,
            )
        elif status == "STALE":
            add(
                "stale_upstream",
                "stale_upstream",
                "STALE_UPSTREAM_ARTIFACT",
                f"Artifact {artifact.name or artifact.id} is stale",
                artifact_id=artifact.id,
            )
        elif status == "UNVERIFIED" and high_impact:
            add(
                "unverified_high_impact",
                "unverified_high_impact",
                "UNVERIFIED_HIGH_IMPACT_INPUT",
                f"High-impact action depends on unverified artifact {artifact.name or artifact.id}",
                artifact_id=artifact.id,
            )

        expires = _parse(artifact.expires_at)
        if expires and expires < now and status != "EXPIRED":
            add(
                "expired_upstream",
                "expired_upstream",
                "EXPIRED_UPSTREAM_ARTIFACT",
                f"Artifact {artifact.name or artifact.id} passed expires_at {artifact.expires_at}",
                artifact_id=artifact.id,
            )

        for parent_id in artifact.parent_artifact_ids or []:
            parent = db.get(Artifact, parent_id)
            if parent is None or parent.org_id != org_id:
                add(
                    "missing_provenance",
                    "missing_provenance",
                    "MISSING_PROVENANCE",
                    f"Artifact {artifact.id} references missing parent {parent_id}",
                    artifact_id=artifact.id,
                )

        producer_state = db.get(AgentState, artifact.producer_agent_id)
        if producer_state and producer_state.operational_status == "QUARANTINED":
            add(
                "quarantined_upstream",
                "quarantined_upstream",
                "QUARANTINED_UPSTREAM_AGENT",
                f"Upstream producer {artifact.producer_agent_id} is quarantined",
                agent_id=artifact.producer_agent_id,
            )
        if (
            producer_state
            and producer_state.validation_failure_count
            >= policy["repeated_failure_threshold"]
        ):
            add(
                "repeated_upstream_failures",
                "repeated_upstream_failures",
                "REPEATED_UPSTREAM_FAILURES",
                (
                    f"Upstream producer {artifact.producer_agent_id} has "
                    f"{producer_state.validation_failure_count} validation failures"
                ),
                agent_id=artifact.producer_agent_id,
            )

    # Conflicting sources: same logical artifact type/name, different payloads.
    groups: dict[tuple[str, str], set[str]] = {}
    for artifact, _ in artifacts:
        key = (artifact.artifact_type, artifact.name)
        groups.setdefault(key, set()).add(artifact.integrity_hash)
    for (artifact_type, name), hashes in groups.items():
        if len(hashes) > 1:
            add(
                "conflicting_sources",
                "conflicting_sources",
                "CONFLICTING_UPSTREAM_INFORMATION",
                f"{len(hashes)} different payloads share artifact type '{artifact_type}' / name '{name}'",
            )

    # Direct consumers of the action's workflow are also part of the blast radius.
    if workflow_execution_id:
        edges = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.workflow_execution_id == workflow_execution_id,
                Dependency.target_type == "agent",
            )
        ).scalars().all()
        for edge in edges:
            affected_agents.setdefault(edge.target_id, "consumer")

    effect = "NONE"
    for violation in violations:
        effect = _stronger(effect, str(violation["effect"]))
        evidence.append(str(violation["evidence"]))

    reason_codes = list(dict.fromkeys(v["reason_code"] for v in violations))
    risk_level = "LOW"
    if effect == "REQUIRE_APPROVAL":
        risk_level = "MEDIUM"
    if effect == "DENY" or any(v["reason_code"] in ("INVALID_UPSTREAM_ARTIFACT", "QUARANTINED_UPSTREAM_AGENT", "REPEATED_UPSTREAM_FAILURES") for v in violations):
        risk_level = "HIGH"

    recommended = "Proceed with normal policy evaluation."
    if effect == "DENY":
        recommended = (
            "Block the action, contain downstream agents, and revalidate or replace "
            "the failing upstream artifacts before retrying."
        )
    elif effect == "REQUIRE_APPROVAL":
        recommended = (
            "Require a human to review the upstream evidence and either revalidate "
            "the artifacts or explicitly approve this specific action."
        )

    base.update(
        {
            "effect": effect,
            "violated_rules": violations,
            "reason_codes": reason_codes,
            "origin_agents": sorted(origin_agents),
            "affected_agents": sorted(affected_agents),
            "affected_workflows": sorted(affected_workflows),
            "risk_level": risk_level,
            "recommended_action": recommended,
            "evidence": list(dict.fromkeys(evidence)),
            "action_risk": action_risk,
            "tool": tool_name,
        }
    )
    return base


def _deny_invalid_context(base: dict[str, Any], detail: str, reason: str = "INVALID_WORKFLOW_CONTEXT") -> dict[str, Any]:
    base.update(
        {
            "effect": "DENY",
            "violated_rules": [
                {
                    "rule": "workflow_context",
                    "effect": "DENY",
                    "reason_code": reason,
                    "evidence": detail,
                }
            ],
            "reason_codes": [reason],
            "risk_level": "HIGH",
            "evidence": [detail],
            "recommended_action": "Fail closed: establish a valid workflow context before retrying.",
        }
    )
    return base
