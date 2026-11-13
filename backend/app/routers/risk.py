"""Explainable, read-only risk preview.

This endpoint never authorizes an action. ``/decisions/evaluate`` remains the
single policy decision point. The preview exists so operators can inspect how
risk is aggregated from policy risk, upstream provenance, reliability, and
operational state before attempting an action.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_agent
from ..errors import NotFoundError
from ..models import Agent, AgentExecution, Tool, WorkflowExecution
from ..policy import EvaluationContext, PolicyDecision
from ..policy import evaluate as evaluate_policy
from ..schemas import RiskAssessment
from ..schemas_v2 import RiskEvaluateRequest, RiskEvaluationOut
from ..services import agents as agents_service
from ..services import containment as containment_service
from ..services import policies as policies_service
from ..services import propagation as propagation_service
from ..services import reliability as reliability_service
from ..services import risk_engine
from ..services import settings as settings_service

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/evaluate", response_model=RiskEvaluationOut)
def evaluate_risk(
    input: RiskEvaluateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    org_id = agent.org_id
    if input.workflow_execution_id:
        execution = db.get(WorkflowExecution, input.workflow_execution_id)
        if execution is None or execution.org_id != org_id:
            raise NotFoundError("Workflow execution not found")
    if input.agent_execution_id:
        row = db.get(AgentExecution, input.agent_execution_id)
        if row is None or row.org_id != org_id or row.agent_id != agent.id:
            raise NotFoundError("Agent execution not found")

    settings_row = settings_service.get_or_create(db)
    tool = None
    if input.tool:
        tool = db.query(Tool).filter(Tool.name == input.tool).one_or_none()

    has_permission = (
        tool is not None and agents_service.has_permission(db, agent.id, tool.id)
    )
    policy_decision = evaluate_policy(
        EvaluationContext(
            agent=agent,
            tool=tool,
            environment=settings_row.default_environment,
            target=None,
            arguments={},
            has_permission=has_permission,
            policies=policies_service.list_policies(db),
            settings=settings_row,
        )
    )
    action_risk = policy_decision.risk.level
    if input.action_risk != "LOW":
        from ..risk import exceeds_max

        if exceeds_max(input.action_risk, action_risk):
            action_risk = input.action_risk

    propagation = propagation_service.evaluate_propagation(
        db,
        org_id=org_id,
        agent=agent,
        workflow_execution_id=input.workflow_execution_id,
        agent_execution_id=input.agent_execution_id,
        input_artifact_ids=list(input.input_artifact_ids),
        action_risk=action_risk,
        settings_row=settings_row,
        tool_name=input.tool,
    )

    decision = policy_decision
    reason_codes = list(policy_decision.reason_codes)
    reliability_payload: dict | None = None

    if propagation.get("effect") == "DENY" and decision.decision != "DENY":
        reason_codes = list(dict.fromkeys([*propagation.get("reason_codes", []), *reason_codes]))
        decision = PolicyDecision(
            decision="DENY",
            reason_codes=reason_codes,
            risk=RiskAssessment(level=propagation.get("risk_level", "HIGH"), reasons=reason_codes),
            policy_id=policy_decision.policy_id,
            policy_version=policy_decision.policy_version,
            rule_id=policy_decision.rule_id,
            explanation=propagation.get("recommended_action", ""),
        )
    elif propagation.get("effect") == "REQUIRE_APPROVAL" and decision.decision == "ALLOW":
        reason_codes = list(dict.fromkeys([*propagation.get("reason_codes", []), *reason_codes]))
        decision = PolicyDecision(
            decision="REQUIRE_APPROVAL",
            reason_codes=reason_codes,
            risk=RiskAssessment(level="HIGH", reasons=reason_codes),
            policy_id=policy_decision.policy_id,
            policy_version=policy_decision.policy_version,
            rule_id=policy_decision.rule_id,
            explanation="Propagation requires human review of upstream evidence.",
        )

    if (
        settings_row.reliability_enforcement
        and input.workflow_execution_id is not None
        and decision.decision == "ALLOW"
    ):
        reliability_payload = reliability_service.compute_reliability(
            db, agent=agent, persist=False
        )
        if (
            reliability_payload["level"] in ("LOW", "CRITICAL")
            and action_risk in ("HIGH", "CRITICAL")
        ):
            code = (
                "AGENT_RELIABILITY_CRITICAL"
                if reliability_payload["level"] == "CRITICAL"
                else "AGENT_RELIABILITY_LOW"
            )
            reason_codes = list(dict.fromkeys([code, *reason_codes]))
            decision = PolicyDecision(
                decision="REQUIRE_APPROVAL",
                reason_codes=reason_codes,
                risk=RiskAssessment(level="HIGH", reasons=reason_codes),
                policy_id=policy_decision.policy_id,
                policy_version=policy_decision.policy_version,
                rule_id=policy_decision.rule_id,
                explanation=(
                    f"Reliability is {reliability_payload['level']}; elevated review "
                    "is required for a high-impact action."
                ),
            )

    state = containment_service.get_or_create_state(db, agent)
    risk = risk_engine.compute_risk(
        action_risk=action_risk,
        decision=decision.decision,
        propagation=propagation,
        reliability=reliability_payload,
        operational_status=state.operational_status,
        policy_explanation=decision.explanation,
    )
    evidence = list(dict.fromkeys([*risk["evidence"], "PREVIEW_ONLY: no decision was recorded."]))
    return RiskEvaluationOut(
        decision=decision.decision,
        risk_level=risk["level"],
        risk_score=risk["score"],
        triggered_rules=[rule.get("rule", "") for rule in risk["rules"] if rule.get("rule")],
        evidence=evidence,
        recommended_action=risk["recommended_action"],
        propagation=propagation,
    )
