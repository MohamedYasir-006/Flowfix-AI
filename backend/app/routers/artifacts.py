"""Artifact provenance, validation, lineage, and validation-rule endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_agent, get_current_user, get_org_id, require_admin_or_approver
from ..errors import NotFoundError
from ..models import Agent, Artifact, User, ValidationRule, utcnow
from ..schemas_v2 import (
    ArtifactCreate,
    ArtifactOut,
    ConsumptionRecord,
    HumanVerificationRequest,
    ValidateRequest,
    ValidationConfig,
)
from ..services import dependencies as dependency_service
from ..services import provenance as provenance_service

router = APIRouter(tags=["artifacts"])


@router.post("/artifacts", response_model=ArtifactOut, status_code=201)
def record_artifact(
    input: ArtifactCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    artifact = provenance_service.record_artifact(
        db,
        org_id=agent.org_id,
        producer=agent,
        artifact_type=input.artifact_type,
        name=input.name,
        content=input.content,
        workflow_execution_id=input.workflow_execution_id,
        agent_execution_id=input.agent_execution_id,
        parent_artifact_ids=input.parent_artifact_ids,
        expires_at=input.expires_at,
        trust_metadata=input.trust_metadata,
    )
    db.commit()
    db.refresh(artifact)
    return artifact


@router.get("/artifacts", response_model=list[ArtifactOut])
def list_artifacts(
    workflow_execution_id: str | None = None,
    validation_status: str | None = None,
    producer_agent_id: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    query = select(Artifact).where(Artifact.org_id == org_id)
    if workflow_execution_id:
        query = query.where(Artifact.workflow_execution_id == workflow_execution_id)
    if validation_status:
        query = query.where(Artifact.validation_status == validation_status)
    if producer_agent_id:
        query = query.where(Artifact.producer_agent_id == producer_agent_id)
    query = query.order_by(Artifact.created_at.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(query).scalars())


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.org_id != org_id:
        raise NotFoundError("Artifact not found")
    return artifact


@router.post("/artifacts/{artifact_id}/validate")
def validate_artifact(
    artifact_id: str,
    input: ValidateRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.org_id != org_id:
        raise NotFoundError("Artifact not found")
    updated, results = provenance_service.validate_artifact(
        db,
        org_id=org_id,
        artifact=artifact,
        configs=input.configs if input.mode == "configured" else None,
    )
    db.commit()
    db.refresh(updated)
    return {
        "artifact": ArtifactOut.model_validate(updated),
        "validation_status": updated.validation_status,
        "results": [
            {
                "id": row.id,
                "validator": row.validator,
                "rule_version": row.rule_version,
                "status": row.status,
                "errors": row.errors,
                "evidence": row.evidence,
                "created_at": row.created_at,
            }
            for row in results
        ],
    }


@router.post("/artifacts/{artifact_id}/verify", response_model=ArtifactOut)
def human_verify_artifact(
    artifact_id: str,
    input: HumanVerificationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_approver),
):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.org_id != user.org_id:
        raise NotFoundError("Artifact not found")
    updated = provenance_service.human_verify(
        db,
        org_id=user.org_id,
        artifact=artifact,
        verified=input.verified,
        actor_user_id=user.id,
        note=input.note,
    )
    db.commit()
    db.refresh(updated)
    return updated


@router.get("/artifacts/{artifact_id}/lineage")
def artifact_lineage(
    artifact_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return dependency_service.artifact_lineage(db, org_id, artifact_id)


@router.post("/artifacts/consumption")
def record_consumption(
    input: ConsumptionRecord,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    edges = provenance_service.record_consumption(
        db,
        org_id=agent.org_id,
        consumer=agent,
        workflow_execution_id=input.workflow_execution_id,
        artifact_ids=input.artifact_ids,
        agent_execution_id=input.agent_execution_id,
    )
    db.commit()
    return {
        "recorded": len(edges),
        "artifact_ids": [edge.artifact_id for edge in edges],
    }


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


@router.post("/validation-rules", status_code=201)
def create_validation_rule(
    input: ValidationConfig,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = ValidationRule(
        org_id=user.org_id,
        workflow_id=input.workflow_id,
        artifact_type=input.artifact_type,
        validator=input.validator,
        rule_version=input.rule_version,
        config=input.config,
        enabled=input.enabled,
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "artifact_type": row.artifact_type,
        "validator": row.validator,
        "rule_version": row.rule_version,
        "config": row.config,
        "enabled": row.enabled,
        "created_at": row.created_at,
    }


@router.get("/validation-rules")
def list_validation_rules(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = db.execute(
        select(ValidationRule)
        .where(ValidationRule.org_id == user.org_id)
        .order_by(ValidationRule.created_at.desc())
    ).scalars().all()
    return [
        {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "artifact_type": row.artifact_type,
            "validator": row.validator,
            "rule_version": row.rule_version,
            "config": row.config,
            "enabled": row.enabled,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.delete("/validation-rules/{rule_id}", status_code=204)
def disable_validation_rule(
    rule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    row = db.get(ValidationRule, rule_id)
    if row is None or row.org_id != user.org_id:
        raise NotFoundError("Validation rule not found")
    row.enabled = False
    db.commit()
