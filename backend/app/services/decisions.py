"""Decision service: the single policy decision point for agent tool actions.

V2 ordering is deliberate and fail-closed:

1. Identity/environment/schema/payload checks (unchanged).
2. Operational gate (quarantine / circuit breaker) — can only deny.
3. Workflow context validation and consumption recording.
4. Deterministic policy evaluation (explicit DENY always wins).
5. Failure propagation evaluation over the upstream artifact graph.
6. Reliability friction (approval only, never overrides DENY).
7. Explainable risk record, approval creation, audit event.
8. Post-approval: policy and propagation are both re-evaluated before the
   approval is atomically consumed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError, ConflictError, NotFoundError
from ..models import Agent, AgentExecution, Approval, AuditEvent, RiskAssessmentRecord, Tool, WorkflowExecution, utcnow
from ..policy import EvaluationContext, PolicyDecision
from ..policy import evaluate as evaluate_policy
from ..redaction import payload_size, redact_dict, summarize_arguments
from ..schemas import ActionResultRequest, DecisionResponse, EvaluateRequest, EventOut, RiskAssessment
from ..utils import payload_hash
from ..validation import validate_arguments
from . import agents as agents_service
from . import approvals as approvals_service
from . import audit as audit_service
from . import containment as containment_service
from . import incidents as incidents_service
from . import policies as policies_service
from . import propagation as propagation_service
from . import provenance as provenance_service
from . import reliability as reliability_service
from . import risk_engine
from . import settings as settings_service
from . import tools as tools_service

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _redact_fields(settings_row) -> list[str]:
    return list(settings_row.redact_fields or [])


def _redaction_enabled(settings_row) -> bool:
    return bool(settings_row.redact_secrets)


def _safe_summary(arguments: dict[str, Any], settings_row) -> dict[str, Any]:
    return summarize_arguments(
        arguments, _redact_fields(settings_row), _redaction_enabled(settings_row)
    )


def _safe_metadata(arguments: dict[str, Any], settings_row) -> dict[str, Any]:
    return redact_dict(arguments, _redact_fields(settings_row), _redaction_enabled(settings_row))


def _decision_from_event(event) -> DecisionResponse:
    metadata = event.redacted_metadata or {}
    return DecisionResponse(
        action_id=event.action_id or "",
        decision=event.decision or "DENY",
        risk={"level": event.risk_level or "MEDIUM", "reasons": list(event.reason_codes or [])},
        reason_codes=list(event.reason_codes or []),
        policy=(
            {"id": event.policy_id, "version": event.policy_version}
            if event.policy_id
            else None
        ),
        approval_id=metadata.get("approvalId"),
        expires_at=metadata.get("expiresAt"),
        explanation=metadata.get("explanation", ""),
        risk_score=metadata.get("riskScore"),
        risk_assessment_id=metadata.get("riskAssessmentId"),
        propagation=metadata.get("propagation"),
        operational_status=metadata.get("operationalStatus"),
    )


def _record_risk(
    db: Session,
    *,
    agent: Agent,
    request: EvaluateRequest,
    action_id: str,
    decision: str,
    risk: dict[str, Any],
    propagation: dict[str, Any] | None,
    explanation: str,
) -> RiskAssessmentRecord:
    record = RiskAssessmentRecord(
        org_id=agent.org_id,
        action_id=action_id,
        workflow_execution_id=request.workflow_execution_id,
        agent_execution_id=request.agent_execution_id,
        agent_id=agent.id,
        decision=decision,
        risk_level=risk["level"],
        score=int(risk["score"]),
        rules=risk.get("rules", []),
        evidence={
            "explanation": explanation,
            "evidence": risk.get("evidence", []),
            "recommendedAction": risk.get("recommended_action", ""),
        },
        propagation=propagation or {},
        created_at=utcnow(),
    )
    db.add(record)
    db.flush()
    return record


def _record_decision(
    db: Session,
    *,
    agent: Agent,
    request: EvaluateRequest,
    tool: Tool | None,
    decision: PolicyDecision,
    action_id: str,
    settings_row,
    reason_codes: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    approval_id: str | None = None,
    expires_at: str | None = None,
    risk: dict[str, Any] | None = None,
    propagation: dict[str, Any] | None = None,
    risk_assessment_id: str | None = None,
    operational_status: str = "ACTIVE",
) -> DecisionResponse:
    codes = reason_codes if reason_codes is not None else decision.reason_codes
    merged = dict(metadata if metadata is not None else _safe_metadata(request.arguments, settings_row))
    merged.update(
        {
            "explanation": decision.explanation,
            "propagation": propagation,
            "propagationEffect": (propagation or {}).get("effect"),
            "operationalStatus": operational_status,
        }
    )
    if risk is not None:
        merged["riskScore"] = risk.get("score")
        merged["riskRules"] = risk.get("rules", [])
    if risk_assessment_id:
        merged["riskAssessmentId"] = risk_assessment_id
    if approval_id:
        merged["approvalId"] = approval_id
    if expires_at:
        merged["expiresAt"] = expires_at

    event = audit_service.record_event(
        db,
        event_type="decision",
        action_id=action_id,
        agent_id=agent.id,
        session_id=request.session_id,
        tool_name=request.tool,
        decision=decision.decision,
        risk_level=decision.risk.level,
        reason_codes=codes,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        payload_hash=payload_hash(request.tool, request.target, request.arguments),
        idempotency_key=request.idempotency_key,
        metadata=merged,
        org_id=agent.org_id,
    )
    agents_service.touch_last_action(db, agent)
    db.commit()
    db.refresh(event)

    return DecisionResponse(
        action_id=action_id,
        decision=decision.decision,
        risk=decision.risk,
        reason_codes=codes,
        policy=(
            {"id": decision.policy_id, "version": decision.policy_version}
            if decision.policy_id
            else None
        ),
        approval_id=approval_id,
        expires_at=expires_at,
        explanation=decision.explanation,
        risk_score=(risk or {}).get("score"),
        risk_assessment_id=risk_assessment_id,
        propagation=propagation,
        operational_status=operational_status,
    )


def _deny(
    db: Session,
    *,
    agent: Agent,
    request: EvaluateRequest,
    tool: Tool | None,
    reason_codes: list[str],
    explanation: str,
    risk_level: str = "HIGH",
    metadata: dict[str, Any] | None = None,
    policy_id: str | None = None,
    policy_version: int | None = None,
    propagation: dict[str, Any] | None = None,
) -> DecisionResponse:
    decision = PolicyDecision(
        decision="DENY",
        reason_codes=reason_codes,
        risk=RiskAssessment(level=risk_level, reasons=reason_codes),
        policy_id=policy_id,
        policy_version=policy_version,
        explanation=explanation,
    )
    action_id = str(uuid.uuid4())
    settings_row = settings_service.get_or_create(db)
    state = containment_service.get_or_create_state(db, agent)
    risk = risk_engine.compute_risk(
        action_risk=risk_level,
        decision="DENY",
        propagation=propagation,
        operational_status=state.operational_status,
        policy_explanation=explanation,
    )
    risk_record = _record_risk(
        db,
        agent=agent,
        request=request,
        action_id=action_id,
        decision="DENY",
        risk=risk,
        propagation=propagation,
        explanation=explanation,
    )
    return _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=decision,
        action_id=action_id,
        settings_row=settings_row,
        metadata=metadata if metadata is not None else _safe_metadata(request.arguments, settings_row),
        risk=risk,
        propagation=propagation,
        risk_assessment_id=risk_record.id,
        operational_status=state.operational_status,
    )


def _validate_workflow_context(
    db: Session, agent: Agent, request: EvaluateRequest
) -> tuple[WorkflowExecution | None, AgentExecution | None]:
    if request.agent_execution_id and not request.workflow_execution_id:
        raise ConflictError(
            "agent_execution_id requires workflow_execution_id",
            reason_codes=["INVALID_WORKFLOW_CONTEXT"],
        )
    if not request.workflow_execution_id:
        return None, None

    execution = db.get(WorkflowExecution, request.workflow_execution_id)
    if execution is None or execution.org_id != agent.org_id:
        raise NotFoundError("Workflow execution not found")
    if execution.status in ("COMPLETED", "FAILED"):
        raise ConflictError(
            "Workflow execution is not running", reason_codes=["WORKFLOW_NOT_RUNNING"]
        )

    agent_execution = None
    if request.agent_execution_id:
        agent_execution = db.get(AgentExecution, request.agent_execution_id)
        if agent_execution is None or agent_execution.org_id != agent.org_id:
            raise NotFoundError("Agent execution not found")
        if agent_execution.agent_id != agent.id:
            raise ApiError(
                "Agent execution belongs to a different agent",
                status_code=403,
                reason_codes=["AGENT_EXECUTION_MISMATCH"],
            )
        if agent_execution.workflow_execution_id != execution.id:
            raise ConflictError(
                "Agent execution is not part of this workflow execution",
                reason_codes=["AGENT_EXECUTION_MISMATCH"],
            )
    return execution, agent_execution


def _reliability_for(agent: Agent, db: Session) -> dict[str, Any]:
    return reliability_service.compute_reliability(db, agent=agent, persist=False)


def evaluate_decision(db: Session, agent: Agent, request: EvaluateRequest) -> DecisionResponse:
    """Evaluate a proposed tool action and persist the decision."""
    settings_row = settings_service.get_or_create(db)

    # Never trust a client-supplied agent id: it must match the credential.
    if request.agent_id and request.agent_id != agent.id:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=None,
            reason_codes=["AGENT_ID_MISMATCH"],
            explanation="The supplied agent_id does not match the authenticated credential.",
        )

    # Bind the environment to the authenticated credential.
    if request.environment and request.environment != agent.environment:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=None,
            reason_codes=["ENVIRONMENT_MISMATCH"],
            explanation=(
                f"Requested environment '{request.environment}' does not match the "
                f"agent's registered environment '{agent.environment}'."
            ),
        )

    environment = agent.environment
    tool = tools_service.get_tool_by_name(db, request.tool)

    # Idempotent replay: return the original decision for a repeated key.
    if request.idempotency_key:
        existing = audit_service.find_event_by_idempotency_key(db, request.idempotency_key)
        if existing:
            return _decision_from_event(existing)

    # Bounded request size.
    if payload_size(request.arguments) > settings_row.max_payload_bytes:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["PAYLOAD_TOO_LARGE"],
            explanation="The action payload exceeds the configured maximum size.",
            metadata={"maxPayloadBytes": settings_row.max_payload_bytes},
        )

    # Schema validation before policy evaluation.
    if tool is not None:
        errors = validate_arguments(tool.input_schema, request.arguments)
        if errors:
            return _deny(
                db,
                agent=agent,
                request=request,
                tool=tool,
                reason_codes=["SCHEMA_VALIDATION_FAILED", "INVALID_ARGUMENTS"],
                explanation="Tool arguments failed schema validation.",
                risk_level=tool.default_risk,
                metadata={"errors": errors},
            )

    # Containment gate: quarantine and open circuit breakers fail closed. This
    # runs before policy so a quarantined agent cannot probe for allowances.
    gate = containment_service.check_operational_gate(
        db, agent=agent, tool_name=request.tool
    )
    if not gate.get("allowed", False):
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=[str(gate.get("reason_code", "CONTAINMENT_BLOCKED"))],
            explanation=str(gate.get("detail", "Agent is contained")),
            risk_level="CRITICAL" if gate.get("operational_status") == "QUARANTINED" else "HIGH",
            metadata={"containment": gate},
        )

    # Validate and record the workflow context before any approval shortcut.
    try:
        workflow_execution, agent_execution = _validate_workflow_context(db, agent, request)
        if request.input_artifact_ids:
            if workflow_execution is None:
                raise ConflictError(
                    "input_artifact_ids requires workflow_execution_id",
                    reason_codes=["INVALID_WORKFLOW_CONTEXT"],
                )
            provenance_service.record_consumption(
                db,
                org_id=agent.org_id,
                consumer=agent,
                workflow_execution_id=workflow_execution.id,
                artifact_ids=request.input_artifact_ids,
                agent_execution_id=agent_execution.id if agent_execution else None,
            )
    except ApiError as exc:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=exc.reason_codes or ["INVALID_WORKFLOW_CONTEXT"],
            explanation=exc.message,
        )

    # Approved execution path: revalidate and consume the approval.
    if request.approval_id:
        return _execute_approved(
            db, agent, request, tool, environment, settings_row, workflow_execution, agent_execution
        )

    # Standard evaluation.
    has_permission = tool is not None and agents_service.has_permission(db, agent.id, tool.id)
    active_policies = policies_service.list_policies(db)
    policy_decision = evaluate_policy(
        EvaluationContext(
            agent=agent,
            tool=tool,
            environment=environment,
            target=request.target,
            arguments=request.arguments,
            has_permission=has_permission,
            policies=active_policies,
            settings=settings_row,
        )
    )

    action_risk = policy_decision.risk.level
    propagation = propagation_service.evaluate_propagation(
        db,
        org_id=agent.org_id,
        agent=agent,
        workflow_execution_id=workflow_execution.id if workflow_execution else None,
        agent_execution_id=agent_execution.id if agent_execution else None,
        input_artifact_ids=list(request.input_artifact_ids),
        action_risk=action_risk,
        settings_row=settings_row,
        tool_name=request.tool,
    )

    decision = policy_decision
    reason_codes = list(policy_decision.reason_codes)
    reliability_payload: dict[str, Any] | None = None

    if propagation.get("effect") == "DENY" and policy_decision.decision != "DENY":
        reason_codes = list(dict.fromkeys([*propagation.get("reason_codes", []), *reason_codes]))
        decision = PolicyDecision(
            decision="DENY",
            reason_codes=reason_codes,
            risk=RiskAssessment(level=propagation.get("risk_level", "HIGH"), reasons=reason_codes),
            policy_id=policy_decision.policy_id,
            policy_version=policy_decision.policy_version,
            rule_id=policy_decision.rule_id,
            explanation=(
                "Blocked by the failure propagation engine: the action depends on "
                "upstream information or agents that are not trustworthy. "
                + propagation.get("recommended_action", "")
            ).strip(),
        )
    elif propagation.get("effect") == "REQUIRE_APPROVAL" and policy_decision.decision == "ALLOW":
        reason_codes = list(dict.fromkeys([*propagation.get("reason_codes", []), *reason_codes]))
        decision = PolicyDecision(
            decision="REQUIRE_APPROVAL",
            reason_codes=reason_codes,
            risk=RiskAssessment(level="HIGH", reasons=reason_codes),
            policy_id=policy_decision.policy_id,
            policy_version=policy_decision.policy_version,
            rule_id=policy_decision.rule_id,
            explanation=(
                "Policy allows the action, but failure propagation requires human "
                "review of unverified or conflicting upstream evidence."
            ),
        )

    # Reliability adds friction only for workflow-scoped, high-impact actions.
    # It can never turn a DENY into an ALLOW or override an explicit policy deny.
    if (
        settings_row.reliability_enforcement
        and workflow_execution is not None
        and decision.decision == "ALLOW"
    ):
        reliability_payload = _reliability_for(agent, db)
        if (
            reliability_payload["level"] in ("LOW", "CRITICAL")
            and action_risk in ("HIGH", "CRITICAL")
        ):
            reliability_code = (
                "AGENT_RELIABILITY_CRITICAL"
                if reliability_payload["level"] == "CRITICAL"
                else "AGENT_RELIABILITY_LOW"
            )
            reason_codes = list(dict.fromkeys([reliability_code, *reason_codes]))
            decision = PolicyDecision(
                decision="REQUIRE_APPROVAL",
                reason_codes=reason_codes,
                risk=RiskAssessment(level="HIGH", reasons=reason_codes),
                policy_id=policy_decision.policy_id,
                policy_version=policy_decision.policy_version,
                rule_id=policy_decision.rule_id,
                explanation=(
                    f"Agent reliability is {reliability_payload['level']} "
                    f"(score {reliability_payload['score']}, confidence "
                    f"{reliability_payload['confidence']}); elevated review is required "
                    "for a high-impact action. Explicit policy results are unchanged."
                ),
            )

    action_id = str(uuid.uuid4())
    state = containment_service.get_or_create_state(db, agent)
    risk = risk_engine.compute_risk(
        action_risk=action_risk,
        decision=decision.decision,
        propagation=propagation,
        reliability=reliability_payload,
        operational_status=state.operational_status,
        policy_explanation=decision.explanation,
    )
    # Keep the response's risk level aligned with the aggregated score while the
    # policy decision itself remains authoritative.
    decision.risk = RiskAssessment(level=risk["level"], reasons=reason_codes)

    risk_record = _record_risk(
        db,
        agent=agent,
        request=request,
        action_id=action_id,
        decision=decision.decision,
        risk=risk,
        propagation=propagation,
        explanation=decision.explanation,
    )

    # Create an incident only for a deterministic propagation denial, once per
    # action, with the origin and blast radius preserved as evidence.
    if propagation.get("effect") == "DENY" and workflow_execution is not None:
        origin = (propagation.get("origin_agents") or [None])[0]
        incident = incidents_service.create_incident(
            db,
            org_id=agent.org_id,
            workflow_execution_id=workflow_execution.id,
            origin_agent_id=origin,
            failure_type="FAILURE_PROPAGATION",
            risk_level=propagation.get("risk_level", "HIGH"),
            summary=(
                f"Blocked {request.tool} for agent {agent.name}: "
                f"{', '.join(propagation.get('reason_codes', []))}"
            ),
            evidence={
                "actionId": action_id,
                "agentId": agent.id,
                "upstreamArtifactIds": propagation.get("upstream_artifact_ids", []),
                "affectedAgents": propagation.get("affected_agents", []),
                "violatedRules": propagation.get("violated_rules", []),
            },
        )
        from ..models import Notification

        db.add(
            Notification(
                org_id=agent.org_id,
                kind="propagation",
                severity=propagation.get("risk_level", "HIGH"),
                title=f"Unsafe downstream action blocked: {agent.name}",
                body=incident.summary,
                incident_id=incident.id,
                created_at=utcnow(),
            )
        )

    approval_id: str | None = None
    expires_at: str | None = None
    if decision.decision == "REQUIRE_APPROVAL":
        approval = approvals_service.create_approval(
            db,
            agent_id=agent.id,
            action_id=action_id,
            tool_name=request.tool,
            target=request.target or "",
            payload_hash=payload_hash(request.tool, request.target, request.arguments),
            arguments_summary=_safe_summary(request.arguments, settings_row),
            risk_level=decision.risk.level,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version or 1,
            rule_id=decision.rule_id,
            reason=decision.reason_codes[0] if decision.reason_codes else "POLICY_APPROVAL_REQUIRED",
            settings=settings_row,
            workflow_execution_id=workflow_execution.id if workflow_execution else None,
            agent_execution_id=agent_execution.id if agent_execution else None,
            input_artifact_ids=list(request.input_artifact_ids),
            risk_assessment_id=risk_record.id,
            org_id=agent.org_id,
        )
        approval_id = approval.id
        expires_at = approval.expires_at

    if decision.decision == "ALLOW" and workflow_execution is not None:
        provenance_service.add_dependency(
            db,
            org_id=agent.org_id,
            workflow_execution_id=workflow_execution.id,
            source_type="agent",
            source_id=agent.id,
            target_type="tool",
            target_id=f"tool:{request.tool}",
            relationship="invoked",
            validation_status="VALIDATED",
        )

    return _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=decision,
        action_id=action_id,
        settings_row=settings_row,
        reason_codes=reason_codes,
        approval_id=approval_id,
        expires_at=expires_at,
        risk=risk,
        propagation=propagation,
        risk_assessment_id=risk_record.id,
        operational_status=state.operational_status,
    )


def _execute_approved(
    db: Session,
    agent: Agent,
    request: EvaluateRequest,
    tool: Tool | None,
    environment: str,
    settings_row,
    workflow_execution: WorkflowExecution | None,
    agent_execution: AgentExecution | None,
) -> DecisionResponse:
    approval = db.get(Approval, request.approval_id)
    if approval is None:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_NOT_FOUND"],
            explanation="The supplied approval does not exist.",
        )
    if approval.requested_by_agent_id != agent.id or approval.org_id != agent.org_id:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_NOT_YOURS"],
            explanation="The approval belongs to a different agent or organization.",
        )
    if approval.status == "EXPIRED" or datetime.fromisoformat(approval.expires_at) < datetime.now(timezone.utc):
        if approval.status == "PENDING":
            approval.status = "EXPIRED"
            db.commit()
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_EXPIRED"],
            explanation="The approval has expired.",
        )
    if approval.status == "CONSUMED":
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_ALREADY_CONSUMED"],
            explanation="The approval has already been consumed; replay is not permitted.",
        )
    if approval.status != "APPROVED":
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_NOT_APPROVED"],
            explanation=f"The approval is {approval.status.lower()}, not approved.",
        )
    if approval.payload_hash != payload_hash(request.tool, request.target, request.arguments):
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["PAYLOAD_HASH_MISMATCH"],
            explanation="The payload changed after approval; the approval cannot be reused.",
        )

    # Never trust context supplied at retry time: bind to the context recorded at
    # approval creation. Missing context here would otherwise bypass propagation.
    if approval.workflow_execution_id:
        request = request.model_copy(
            update={
                "workflow_execution_id": approval.workflow_execution_id,
                "agent_execution_id": approval.agent_execution_id,
                "input_artifact_ids": list(approval.input_artifact_ids or []),
            }
        )
        workflow_execution = db.get(WorkflowExecution, approval.workflow_execution_id)
        if workflow_execution is None or workflow_execution.org_id != agent.org_id:
            return _deny(
                db,
                agent=agent,
                request=request,
                tool=tool,
                reason_codes=["INVALID_WORKFLOW_CONTEXT"],
                explanation="The approval's workflow context is no longer valid.",
            )
        if approval.agent_execution_id:
            agent_execution = db.get(AgentExecution, approval.agent_execution_id)
            if agent_execution is None or agent_execution.agent_id != agent.id:
                return _deny(
                    db,
                    agent=agent,
                    request=request,
                    tool=tool,
                    reason_codes=["INVALID_WORKFLOW_CONTEXT"],
                    explanation="The approval's agent execution is no longer valid.",
                )

    gate = containment_service.check_operational_gate(
        db, agent=agent, tool_name=request.tool
    )
    if not gate.get("allowed", False):
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=[str(gate.get("reason_code", "CONTAINMENT_BLOCKED"))],
            explanation="Containment state changed after approval; the approval was not consumed.",
            metadata={"containment": gate},
        )

    # Re-evaluate policy immediately before execution. An explicit deny still
    # wins, but the approval rule that paused this action must not re-trigger.
    has_permission = tool is not None and agents_service.has_permission(db, agent.id, tool.id)
    active_policies = policies_service.list_policies(db)
    decision = evaluate_policy(
        EvaluationContext(
            agent=agent,
            tool=tool,
            environment=environment,
            target=request.target,
            arguments=request.arguments,
            has_permission=has_permission,
            policies=active_policies,
            settings=settings_row,
            satisfied_approval_rule_ids=[approval.rule_id] if approval.rule_id else [],
        )
    )
    if decision.decision != "ALLOW":
        return _record_decision(
            db,
            agent=agent,
            request=request,
            tool=tool,
            decision=PolicyDecision(
                decision="DENY",
                reason_codes=["POLICY_REVALIDATION_DENIED", *decision.reason_codes],
                risk=decision.risk,
                policy_id=decision.policy_id,
                policy_version=decision.policy_version,
                explanation="Policy no longer allows this action; approval was not consumed.",
            ),
            action_id=approval.action_id,
            settings_row=settings_row,
            reason_codes=["POLICY_REVALIDATION_DENIED", *decision.reason_codes],
        )

    # Propagation must also be rechecked. A human approval of a previously
    # unverified input does not authorize an input that later became INVALID.
    propagation = propagation_service.evaluate_propagation(
        db,
        org_id=agent.org_id,
        agent=agent,
        workflow_execution_id=workflow_execution.id if workflow_execution else None,
        agent_execution_id=agent_execution.id if agent_execution else None,
        input_artifact_ids=list(request.input_artifact_ids),
        action_risk=decision.risk.level,
        settings_row=settings_row,
        tool_name=request.tool,
    )
    if propagation.get("effect") == "DENY":
        codes = list(dict.fromkeys([*propagation.get("reason_codes", []), "PROPAGATION_BLOCKED_AFTER_APPROVAL"]))
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=codes,
            explanation=(
                "The upstream dependency state changed after approval; the action is "
                "blocked and the approval was not consumed."
            ),
            risk_level=propagation.get("risk_level", "HIGH"),
            propagation=propagation,
        )

    final_reason_codes = ["POLICY_REVALIDATED", "APPROVAL_CONSUMED", *decision.reason_codes]
    if propagation.get("effect") == "REQUIRE_APPROVAL":
        final_reason_codes = [
            "PROPAGATION_APPROVAL_SATISFIED",
            *propagation.get("reason_codes", []),
            *final_reason_codes,
        ]

    action_id = approval.action_id
    state = containment_service.get_or_create_state(db, agent)
    risk = risk_engine.compute_risk(
        action_risk=decision.risk.level,
        decision="ALLOW",
        propagation=propagation,
        operational_status=state.operational_status,
        policy_explanation="Approval consumed after fresh policy and propagation evaluation.",
    )
    risk_record = _record_risk(
        db,
        agent=agent,
        request=request,
        action_id=action_id,
        decision="ALLOW",
        risk=risk,
        propagation=propagation,
        explanation="Approval consumed after fresh policy and propagation evaluation.",
    )
    # Record first, then atomically consume; if consumption loses a race the
    # transaction rolls back and no audit is lost.
    response = _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=PolicyDecision(
            decision="ALLOW",
            reason_codes=final_reason_codes,
            risk=RiskAssessment(level=risk["level"], reasons=final_reason_codes),
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            explanation="Approval consumed after fresh policy and propagation evaluation.",
        ),
        action_id=action_id,
        settings_row=settings_row,
        reason_codes=final_reason_codes,
        risk=risk,
        propagation=propagation,
        risk_assessment_id=risk_record.id,
        operational_status=state.operational_status,
    )

    if not approvals_service.consume(db, approval):
        db.rollback()
        raise ConflictError(
            "Approval was already consumed",
            reason_codes=["APPROVAL_ALREADY_CONSUMED"],
        )

    db.commit()
    return response


def report_result(
    db: Session,
    agent: Agent,
    action_id: str,
    request: ActionResultRequest,
) -> EventOut:
    """Record the outcome of an executed action. Idempotent by action id."""
    existing = audit_service.find_execution_event(db, action_id)
    if existing:
        return EventOut.model_validate(existing)

    decision_event = db.execute(
        select(AuditEvent).where(
            AuditEvent.action_id == action_id,
            AuditEvent.event_type == "decision",
        )
    ).scalars().first()

    if decision_event is None:
        raise NotFoundError("Unknown action id")
    if decision_event.agent_id != agent.id:
        raise ApiError("Action does not belong to this agent", status_code=403, reason_codes=["FORBIDDEN"])
    if decision_event.decision != "ALLOW":
        raise ConflictError(
            "Cannot report execution for a non-allowed action",
            reason_codes=["ACTION_NOT_ALLOWED"],
        )

    metadata = {
        "success": request.success,
        "durationMs": request.duration_ms,
    }
    if request.error:
        metadata["error"] = request.error

    event = audit_service.record_event(
        db,
        event_type="execution",
        action_id=action_id,
        agent_id=agent.id,
        tool_name=decision_event.tool_name,
        decision="ALLOW",
        risk_level=decision_event.risk_level,
        reason_codes=["TOOL_EXECUTED" if request.success else "TOOL_EXECUTION_FAILED"],
        policy_id=decision_event.policy_id,
        policy_version=decision_event.policy_version,
        payload_hash=decision_event.payload_hash,
        metadata=metadata,
        org_id=agent.org_id,
    )
    agents_service.touch_last_action(db, agent)
    if not request.success:
        containment_service.record_execution_failure(
            db,
            agent=agent,
            action_id=action_id,
            error=request.error,
            tool_name=decision_event.tool_name or "*",
        )
    else:
        containment_service.record_trial_success(
            db, agent=agent, tool_name=decision_event.tool_name or "*"
        )
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)
