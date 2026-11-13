"""Dependency registration and cross-agent impact queries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_agent, get_org_id
from ..errors import NotFoundError
from ..models import Agent, Artifact, Dependency
from ..schemas_v2 import DependencyCreate, DependencyOut, DownstreamImpact
from ..services import dependencies as dependency_service
from ..services import provenance as provenance_service
from ..services import workflows as workflow_service

router = APIRouter(tags=["dependencies"])


@router.post("/dependencies", response_model=DependencyOut, status_code=201)
def register_dependency(
    input: DependencyCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Record one provenance edge for the authenticated tenant.

    Registration is additive. Edges never grant authorization; they are
    evidence used by the propagation engine to determine what an action
    depends on.
    """
    org_id = agent.org_id
    if input.workflow_execution_id:
        workflow_service.get_execution(db, org_id, input.workflow_execution_id)
    if input.artifact_id:
        artifact = db.get(Artifact, input.artifact_id)
        if artifact is None or artifact.org_id != org_id:
            raise NotFoundError("Artifact not found")

    edge = provenance_service.add_dependency(
        db,
        org_id=org_id,
        source_type=input.source_type,
        source_id=input.source_id,
        target_type=input.target_type,
        target_id=input.target_id,
        relationship=input.relationship,
        workflow_execution_id=input.workflow_execution_id,
        artifact_id=input.artifact_id,
        validation_status=input.validation_status,
    )
    db.commit()
    db.refresh(edge)
    return edge


@router.get("/dependencies", response_model=list[DependencyOut])
def list_dependencies(
    workflow_execution_id: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    artifact_id: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    query = select(Dependency).where(Dependency.org_id == org_id)
    if workflow_execution_id:
        query = query.where(Dependency.workflow_execution_id == workflow_execution_id)
    if source_id:
        query = query.where(Dependency.source_id == source_id)
    if target_id:
        query = query.where(Dependency.target_id == target_id)
    if artifact_id:
        query = query.where(Dependency.artifact_id == artifact_id)
    query = query.order_by(Dependency.created_at.desc()).limit(max(1, min(limit, 2000)))
    return list(db.execute(query).scalars())


@router.get("/dependencies/impact", response_model=DownstreamImpact)
def dependency_impact(
    agent_id: str | None = None,
    artifact_id: str | None = None,
    failure_type: str = "INVALID_OUTPUT",
    max_depth: int = Query(default=32, ge=1, le=128),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Compute the downstream blast radius of a failure.

    At least one of ``agent_id`` or ``artifact_id`` is required. The traversal
    is bounded and tenant-scoped; it returns recorded effects, not predictions.
    """
    if agent_id is None and artifact_id is None:
        from ..errors import ApiError

        raise ApiError("agent_id or artifact_id is required", status_code=422)
    if agent_id is not None:
        agent = db.get(Agent, agent_id)
        if agent is None or agent.org_id != org_id:
            raise NotFoundError("Agent not found")
    return dependency_service.downstream_impact(
        db,
        org_id,
        agent_id=agent_id,
        artifact_id=artifact_id,
        failure_type=failure_type,
        max_depth=max_depth,
    )


@router.get("/agents/{agent_id}/impact", response_model=DownstreamImpact)
def agent_impact(
    agent_id: str,
    failure_type: str = "INVALID_OUTPUT",
    max_depth: int = Query(default=32, ge=1, le=128),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = db.get(Agent, agent_id)
    if agent is None or agent.org_id != org_id:
        raise NotFoundError("Agent not found")
    return dependency_service.downstream_impact(
        db, org_id, agent_id=agent_id, failure_type=failure_type, max_depth=max_depth
    )
