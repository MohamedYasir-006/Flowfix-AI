"""Artifact provenance, validation, and integrity.

Important distinction: an integrity hash proves recorded content has not changed
relative to the stored hash. It does **not** prove the content is factually
correct. Validation status is therefore a separate, evidence-bearing field and
only ``VALIDATED`` may be treated as trusted by propagation policy.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ConflictError, ForbiddenError, NotFoundError
from ..models import (
    Agent,
    AgentExecution,
    Artifact,
    ArtifactValidation,
    Dependency,
    ValidationRule,
    WorkflowExecution,
    utcnow,
)
from ..schemas_v2 import ValidationConfig
from ..utils import canonical_json
from ..validation import validate_arguments
from . import audit as audit_service

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TRUSTED = "VALIDATED"
_TERMINAL_FAILURES = {"INVALID", "REJECTED", "QUARANTINED", "EXPIRED", "STALE"}


def integrity_hash(content: Any) -> str:
    body = canonical_json(content)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    value = datetime.fromisoformat(ts)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def record_artifact(
    db: Session,
    *,
    org_id: str,
    producer: Agent,
    artifact_type: str,
    name: str,
    content: Any,
    workflow_execution_id: str | None = None,
    agent_execution_id: str | None = None,
    parent_artifact_ids: list[str] | None = None,
    expires_at: str | None = None,
    trust_metadata: dict[str, Any] | None = None,
) -> Artifact:
    """Persist an agent output as a provenance-bearing artifact."""
    if producer.org_id != org_id:
        raise ForbiddenError("Producer agent belongs to a different organization")

    if workflow_execution_id:
        execution = db.get(WorkflowExecution, workflow_execution_id)
        if execution is None or execution.org_id != org_id:
            raise NotFoundError("Workflow execution not found")
        if execution.status in ("COMPLETED", "FAILED"):
            raise ConflictError("Cannot add artifacts to a finished workflow execution")

    if agent_execution_id:
        agent_execution = db.get(AgentExecution, agent_execution_id)
        if agent_execution is None or agent_execution.org_id != org_id:
            raise NotFoundError("Agent execution not found")
        if agent_execution.agent_id != producer.id:
            raise ForbiddenError("Agent execution belongs to a different agent")
        if workflow_execution_id and agent_execution.workflow_execution_id != workflow_execution_id:
            raise ConflictError("Agent execution is not part of this workflow execution")

    parents = list(dict.fromkeys(parent_artifact_ids or []))
    parent_rows: list[Artifact] = []
    for parent_id in parents:
        parent = db.get(Artifact, parent_id)
        if parent is None or parent.org_id != org_id:
            raise NotFoundError(f"Parent artifact '{parent_id}' not found")
        parent_rows.append(parent)

    artifact = Artifact(
        org_id=org_id,
        workflow_execution_id=workflow_execution_id,
        producer_agent_id=producer.id,
        producer_execution_id=agent_execution_id,
        artifact_type=artifact_type,
        name=name or artifact_type,
        content=content,
        integrity_hash=integrity_hash(content),
        validation_status="UNVERIFIED",
        version=1,
        parent_artifact_ids=parents,
        expires_at=expires_at,
        trust_metadata=trust_metadata or {},
        validation_results=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(artifact)
    db.flush()

    add_dependency(
        db,
        org_id=org_id,
        workflow_execution_id=workflow_execution_id,
        source_type="agent",
        source_id=producer.id,
        target_type="artifact",
        target_id=artifact.id,
        relationship="produced",
        artifact_id=artifact.id,
        validation_status=artifact.validation_status,
    )
    if workflow_execution_id:
        add_dependency(
            db,
            org_id=org_id,
            workflow_execution_id=workflow_execution_id,
            source_type="workflow",
            source_id=workflow_execution_id,
            target_type="artifact",
            target_id=artifact.id,
            relationship="produced",
            artifact_id=artifact.id,
            validation_status=artifact.validation_status,
        )
    for parent in parent_rows:
        add_dependency(
            db,
            org_id=org_id,
            workflow_execution_id=workflow_execution_id or parent.workflow_execution_id,
            source_type="artifact",
            source_id=parent.id,
            target_type="artifact",
            target_id=artifact.id,
            relationship="depends_on",
            artifact_id=artifact.id,
            validation_status=artifact.validation_status,
        )

    audit_service.record_event(
        db,
        event_type="artifact",
        action_id=None,
        agent_id=producer.id,
        reason_codes=["ARTIFACT_RECORDED"],
        risk_level="LOW",
        metadata={
            "artifactId": artifact.id,
            "artifactType": artifact_type,
            "validationStatus": artifact.validation_status,
            "integrityHash": artifact.integrity_hash,
            "parentArtifactIds": parents,
        },
        org_id=org_id,
    )
    return artifact


def add_dependency(
    db: Session,
    *,
    org_id: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relationship: str,
    workflow_execution_id: str | None = None,
    artifact_id: str | None = None,
    validation_status: str = "UNVERIFIED",
) -> Dependency:
    dependency = Dependency(
        org_id=org_id,
        workflow_execution_id=workflow_execution_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relationship=relationship,
        artifact_id=artifact_id,
        validation_status=validation_status,
        created_at=utcnow(),
    )
    db.add(dependency)
    db.flush()
    return dependency


def record_consumption(
    db: Session,
    *,
    org_id: str,
    consumer: Agent,
    workflow_execution_id: str,
    artifact_ids: list[str],
    agent_execution_id: str | None = None,
) -> list[Dependency]:
    if consumer.org_id != org_id:
        raise ForbiddenError("Consumer agent belongs to a different organization")
    execution = db.get(WorkflowExecution, workflow_execution_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("Workflow execution not found")

    if agent_execution_id:
        agent_execution = db.get(AgentExecution, agent_execution_id)
        if agent_execution is None or agent_execution.org_id != org_id:
            raise NotFoundError("Agent execution not found")
        if agent_execution.agent_id != consumer.id:
            raise ForbiddenError("Agent execution belongs to a different agent")

    edges: list[Dependency] = []
    for artifact_id in dict.fromkeys(artifact_ids):
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.org_id != org_id:
            raise NotFoundError(f"Artifact '{artifact_id}' not found")
        if artifact.workflow_execution_id and artifact.workflow_execution_id != workflow_execution_id:
            raise ConflictError("Artifact belongs to a different workflow execution")
        edge = add_dependency(
            db,
            org_id=org_id,
            workflow_execution_id=workflow_execution_id,
            source_type="artifact",
            source_id=artifact.id,
            target_type="agent",
            target_id=consumer.id,
            relationship="consumed",
            artifact_id=artifact.id,
            validation_status=artifact.validation_status,
        )
        edges.append(edge)

    if edges:
        audit_service.record_event(
            db,
            event_type="provenance",
            agent_id=consumer.id,
            reason_codes=["ARTIFACTS_CONSUMED"],
            risk_level="LOW",
            metadata={
                "workflowExecutionId": workflow_execution_id,
                "agentExecutionId": agent_execution_id,
                "artifactIds": [edge.artifact_id for edge in edges],
            },
            org_id=org_id,
        )
    return edges


def _resolve_configs(
    db: Session,
    *,
    org_id: str,
    artifact: Artifact,
    workflow_id: str | None,
    configs: list[ValidationConfig] | None,
) -> list[ValidationConfig]:
    if configs is not None:
        return configs

    rows = db.execute(
        select(ValidationRule).where(
            ValidationRule.org_id == org_id,
            ValidationRule.enabled.is_(True),
        )
    ).scalars().all()
    applicable: list[ValidationConfig] = []
    for row in rows:
        if row.artifact_type and row.artifact_type != artifact.artifact_type:
            continue
        if row.workflow_id and row.workflow_id != workflow_id:
            continue
        applicable.append(
            ValidationConfig(
                validator=row.validator,  # type: ignore[arg-type]
                rule_version=row.rule_version,
                artifact_type=row.artifact_type,
                workflow_id=row.workflow_id,
                config=row.config or {},
            )
        )
    if applicable:
        return applicable

    # Defaults: integrity + provenance + expiration are always meaningful.
    defaults = [
        ValidationConfig(validator="integrity", config={}),
        ValidationConfig(validator="provenance", config={}),
        ValidationConfig(validator="expiration", config={}),
    ]
    trust = artifact.trust_metadata or {}
    if isinstance(artifact.content, dict) and isinstance(trust.get("schema"), dict):
        defaults.append(ValidationConfig(validator="schema", config=trust["schema"]))
        defaults.append(
            ValidationConfig(
                validator="required",
                config={"fields": list(trust.get("required") or [])},
            )
        )
    if isinstance(trust.get("business_rules"), list):
        defaults.append(
            ValidationConfig(
                validator="business_rules", config={"rules": trust["business_rules"]}
            )
        )
    return defaults


def validate_artifact(
    db: Session,
    *,
    org_id: str,
    artifact: Artifact,
    configs: list[ValidationConfig] | None = None,
    actor: str = "system",
) -> tuple[Artifact, list[ArtifactValidation]]:
    if artifact.org_id != org_id:
        raise NotFoundError("Artifact not found")

    workflow_id: str | None = None
    if artifact.workflow_execution_id:
        execution = db.get(WorkflowExecution, artifact.workflow_execution_id)
        workflow_id = execution.workflow_id if execution else None

    resolved = _resolve_configs(
        db, org_id=org_id, artifact=artifact, workflow_id=workflow_id, configs=configs
    )
    results: list[ArtifactValidation] = []
    failures: list[str] = []

    for config in resolved:
        status, errors, evidence = _run_validator(db, org_id, artifact, config)
        row = ArtifactValidation(
            org_id=org_id,
            artifact_id=artifact.id,
            validator=config.validator,
            rule_version=config.rule_version,
            status=status,
            errors=errors,
            evidence=evidence,
            created_at=utcnow(),
        )
        db.add(row)
        db.flush()
        results.append(row)
        if status != "PASS":
            failures.append(config.validator)

    now = _now()
    expires = _parse(artifact.expires_at)
    if expires and expires < now:
        final_status = "EXPIRED"
    elif failures:
        final_status = "INVALID"
    elif results:
        final_status = "VALIDATED"
    else:
        final_status = "UNVERIFIED"

    artifact.validation_status = final_status
    artifact.updated_at = utcnow()
    artifact.validation_results = [
        *list(artifact.validation_results or []),
        {
            "at": artifact.updated_at,
            "actor": actor,
            "status": final_status,
            "validators": [
                {
                    "id": row.id,
                    "validator": row.validator,
                    "ruleVersion": row.rule_version,
                    "status": row.status,
                    "errors": row.errors,
                }
                for row in results
            ],
        },
    ]
    db.flush()

    # Update provenance edges that reference this artifact.
    db.query(Dependency).filter(
        Dependency.artifact_id == artifact.id, Dependency.org_id == org_id
    ).update({"validation_status": final_status}, synchronize_session=False)

    audit_service.record_event(
        db,
        event_type="validation",
        agent_id=artifact.producer_agent_id,
        reason_codes=[
            "ARTIFACT_VALIDATED" if final_status == "VALIDATED" else "ARTIFACT_VALIDATION_FAILED",
            *[f"VALIDATOR_FAILED:{name}" for name in failures],
        ],
        risk_level="LOW" if final_status == "VALIDATED" else "HIGH",
        metadata={
            "artifactId": artifact.id,
            "artifactType": artifact.artifact_type,
            "status": final_status,
            "failedValidators": failures,
            "actor": actor,
        },
        org_id=org_id,
    )

    if final_status in ("INVALID", "EXPIRED", "REJECTED", "QUARANTINED"):
        from . import containment as containment_service

        producer = db.get(Agent, artifact.producer_agent_id)
        if producer is not None:
            containment_service.record_validation_failure(
                db,
                agent=producer,
                artifact_id=artifact.id,
                reason=f"VALIDATION_{final_status}",
                evidence={"failedValidators": failures, "artifactType": artifact.artifact_type},
            )
    return artifact, results


def human_verify(
    db: Session,
    *,
    org_id: str,
    artifact: Artifact,
    verified: bool,
    actor_user_id: str,
    note: str = "",
) -> Artifact:
    if artifact.org_id != org_id:
        raise NotFoundError("Artifact not found")
    status = "VALIDATED" if verified else "REJECTED"
    row = ArtifactValidation(
        org_id=org_id,
        artifact_id=artifact.id,
        validator="human",
        rule_version="1",
        status="PASS" if verified else "FAIL",
        errors=[] if verified else [note or "Rejected by human reviewer"],
        evidence={"actorUserId": actor_user_id, "note": note},
        created_at=utcnow(),
    )
    db.add(row)
    artifact.validation_status = status
    artifact.updated_at = utcnow()
    artifact.validation_results = [
        *list(artifact.validation_results or []),
        {"at": artifact.updated_at, "actor": actor_user_id, "status": status, "note": note},
    ]
    db.query(Dependency).filter(
        Dependency.artifact_id == artifact.id, Dependency.org_id == org_id
    ).update({"validation_status": status}, synchronize_session=False)
    audit_service.record_event(
        db,
        event_type="validation",
        agent_id=artifact.producer_agent_id,
        reason_codes=["HUMAN_VERIFICATION_ACCEPTED" if verified else "HUMAN_VERIFICATION_REJECTED"],
        risk_level="LOW" if verified else "HIGH",
        metadata={"artifactId": artifact.id, "actorUserId": actor_user_id, "note": note},
        org_id=org_id,
    )
    db.flush()
    return artifact


# ---------------------------------------------------------------------------
# Validators (deterministic; no network, no model calls)
# ---------------------------------------------------------------------------


def _get_path(content: Any, path: str) -> Any:
    value = content
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _run_validator(
    db: Session, org_id: str, artifact: Artifact, config: ValidationConfig
) -> tuple[str, list[str], dict[str, Any]]:
    content = artifact.content
    rules = config.config or {}
    errors: list[str] = []
    evidence: dict[str, Any] = {"validator": config.validator, "ruleVersion": config.rule_version}

    if config.validator == "integrity":
        expected = integrity_hash(content)
        evidence["expectedHash"] = expected
        evidence["storedHash"] = artifact.integrity_hash
        if expected != artifact.integrity_hash:
            errors.append("INTEGRITY_HASH_MISMATCH")
        else:
            evidence["note"] = (
                "Integrity proves recorded bytes are unchanged; it does not prove factual truth."
            )

    elif config.validator == "schema":
        schema = rules.get("schema", rules)
        if not isinstance(content, dict):
            errors.append("CONTENT_NOT_OBJECT")
        else:
            errors.extend(validate_arguments(schema, content))
        evidence["schema"] = schema

    elif config.validator == "required":
        fields = rules.get("fields") or rules.get("required") or []
        if not isinstance(content, dict):
            errors.append("CONTENT_NOT_OBJECT")
        else:
            for field in fields:
                if _get_path(content, field) in (None, "", []):
                    errors.append(f"missing required field: {field}")
        evidence["fields"] = fields

    elif config.validator == "types":
        expected_types = rules.get("fields") or {}
        if not isinstance(content, dict):
            errors.append("CONTENT_NOT_OBJECT")
        else:
            checks = {
                "string": lambda v: isinstance(v, str),
                "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                "boolean": lambda v: isinstance(v, bool),
                "object": lambda v: isinstance(v, dict),
                "array": lambda v: isinstance(v, list),
            }
            for field, type_name in expected_types.items():
                value = _get_path(content, field)
                check = checks.get(type_name)
                if check is None:
                    errors.append(f"unknown type validator for {field}: {type_name}")
                elif value is not None and not check(value):
                    errors.append(f"{field} must be of type {type_name}")
        evidence["expectedTypes"] = expected_types

    elif config.validator == "business_rules":
        business_rules = rules.get("rules") or []
        if not isinstance(content, dict):
            errors.append("CONTENT_NOT_OBJECT")
        else:
            for rule in business_rules:
                field = str(rule.get("field", ""))
                op = rule.get("op", "eq")
                expected = rule.get("value")
                actual = _get_path(content, field)
                if not _business_rule_passes(actual, op, expected):
                    errors.append(str(rule.get("message") or f"business rule failed: {field} {op}"))
        evidence["businessRules"] = business_rules

    elif config.validator == "expiration":
        expires = _parse(artifact.expires_at)
        evidence["expiresAt"] = artifact.expires_at
        if expires is None and rules.get("required"):
            errors.append("EXPIRATION_MISSING")
        elif expires is not None and expires < _now():
            errors.append("ARTIFACT_EXPIRED")
        ttl = rules.get("max_age_seconds")
        if ttl is not None:
            created = _parse(artifact.created_at)
            if created and (_now() - created).total_seconds() > int(ttl):
                errors.append("ARTIFACT_STALE")

    elif config.validator == "provenance":
        producer = db.get(Agent, artifact.producer_agent_id)
        if producer is None or producer.org_id != org_id:
            errors.append("PRODUCER_NOT_FOUND")
        evidence["producerAgentId"] = artifact.producer_agent_id
        if artifact.producer_execution_id:
            execution = db.get(AgentExecution, artifact.producer_execution_id)
            if execution is None or execution.org_id != org_id:
                errors.append("PRODUCER_EXECUTION_NOT_FOUND")
            elif execution.agent_id != artifact.producer_agent_id:
                errors.append("PRODUCER_EXECUTION_MISMATCH")
        for parent_id in artifact.parent_artifact_ids or []:
            parent = db.get(Artifact, parent_id)
            if parent is None or parent.org_id != org_id:
                errors.append(f"parent artifact missing: {parent_id}")
                continue
            if parent.validation_status in _TERMINAL_FAILURES:
                errors.append(
                    f"parent artifact not trusted: {parent_id} ({parent.validation_status})"
                )
        evidence["parentArtifactIds"] = list(artifact.parent_artifact_ids or [])
        if rules.get("require_workflow") and not artifact.workflow_execution_id:
            errors.append("WORKFLOW_PROVENANCE_MISSING")

    elif config.validator == "source_consistency":
        fields = rules.get("fields") or []
        if fields and artifact.workflow_execution_id:
            peers = db.execute(
                select(Artifact).where(
                    Artifact.org_id == org_id,
                    Artifact.workflow_execution_id == artifact.workflow_execution_id,
                    Artifact.artifact_type == artifact.artifact_type,
                    Artifact.id != artifact.id,
                )
            ).scalars().all()
            conflicts: list[str] = []
            for peer in peers:
                if peer.integrity_hash == artifact.integrity_hash:
                    continue
                for field in fields:
                    left = _get_path(content, field)
                    right = _get_path(peer.content, field)
                    if left is not None and right is not None and left != right:
                        conflicts.append(f"{field}: '{left}' vs '{right}' ({peer.id})")
            if conflicts:
                errors.append("CONFLICTING_SOURCES")
                evidence["conflicts"] = conflicts
        else:
            evidence["note"] = "No comparison fields configured; consistency check skipped."

    return ("PASS" if not errors else "FAIL", errors, evidence)


def _business_rule_passes(actual: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return actual is not None
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return isinstance(expected, list) and actual in expected
    if op == "not_in":
        return isinstance(expected, list) and actual not in expected
    if op == "gt":
        return isinstance(actual, (int, float)) and actual > expected
    if op == "gte":
        return isinstance(actual, (int, float)) and actual >= expected
    if op == "lt":
        return isinstance(actual, (int, float)) and actual < expected
    if op == "lte":
        return isinstance(actual, (int, float)) and actual <= expected
    if op == "matches":
        return isinstance(actual, str) and bool(re.match(str(expected), actual))
    if op == "email":
        return isinstance(actual, str) and bool(_EMAIL_RE.match(actual))
    return False
