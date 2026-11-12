"""Decision service: the single policy decision point for agent tool actions."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError, ConflictError, NotFoundError
from ..models import Agent, Approval, AuditEvent, Tool, utcnow
from ..policy import EvaluationContext, PolicyDecision
from ..policy import evaluate as evaluate_policy
from ..redaction import payload_size, redact_dict, summarize_arguments
from ..schemas import ActionResultRequest, DecisionResponse, EvaluateRequest, EventOut, RiskAssessment
from ..utils import payload_hash
from ..validation import validate_arguments
from . import agents as agents_service
from . import approvals as approvals_service
from . import audit as audit_service
from . import policies as policies_service
from . import settings as settings_service
from . import tools as tools_service


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
    )


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
) -> DecisionResponse:
    codes = reason_codes if reason_codes is not None else decision.reason_codes
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
        metadata=metadata if metadata is not None else _safe_metadata(request.arguments, settings_row),
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
    return _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=decision,
        action_id=action_id,
        settings_row=settings_row,
        metadata=metadata if metadata is not None else _safe_metadata(request.arguments, settings_row),
    )


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

    # Approved execution path: revalidate and consume the approval.
    if request.approval_id:
        return _execute_approved(db, agent, request, tool, environment, settings_row)

    # Standard evaluation.
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
        )
    )

    action_id = str(uuid.uuid4())
    approval_id: str | None = None
    expires_at: str | None = None

    if decision.decision == "REQUIRE_APPROVAL":
        approval = approvals_service.create_approval(
            db,
            agent_id=agent.id,
            action_id=action_id,
            tool_name=request.tool,
            target=request.target,
            payload_hash=payload_hash(request.tool, request.target, request.arguments),
            arguments_summary=_safe_summary(request.arguments, settings_row),
            risk_level=decision.risk.level,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version or 1,
            rule_id=decision.rule_id,
            reason=decision.reason_codes[0] if decision.reason_codes else "POLICY_APPROVAL_REQUIRED",
            settings=settings_row,
        )
        approval_id = approval.id
        expires_at = approval.expires_at

    return _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=decision,
        action_id=action_id,
        settings_row=settings_row,
        approval_id=approval_id,
        expires_at=expires_at,
    )


def _execute_approved(
    db: Session,
    agent: Agent,
    request: EvaluateRequest,
    tool: Tool | None,
    environment: str,
    settings_row,
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
    if approval.requested_by_agent_id != agent.id:
        return _deny(
            db,
            agent=agent,
            request=request,
            tool=tool,
            reason_codes=["APPROVAL_NOT_YOURS"],
            explanation="The approval belongs to a different agent.",
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

    # Re-evaluate policy immediately before execution. An explicit deny still
    # wins, but the approval rule that paused this action must not re-trigger:
    # otherwise an approved action could never execute. The approval is the
    # human decision for that rule, so it is excluded from re-evaluation.
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

    # Consume the approval exactly once. Record first, then atomically consume;
    # if consumption loses a race the transaction rolls back and no audit is lost.
    action_id = approval.action_id
    response = _record_decision(
        db,
        agent=agent,
        request=request,
        tool=tool,
        decision=PolicyDecision(
            decision="ALLOW",
            reason_codes=["POLICY_REVALIDATED", "APPROVAL_CONSUMED", *decision.reason_codes],
            risk=decision.risk,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            explanation="Approval consumed after fresh policy evaluation.",
        ),
        action_id=action_id,
        settings_row=settings_row,
        reason_codes=["POLICY_REVALIDATED", "APPROVAL_CONSUMED", *decision.reason_codes],
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
    )
    agents_service.touch_last_action(db, agent)
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)
