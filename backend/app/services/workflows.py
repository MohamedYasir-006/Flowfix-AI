"""Workflow and execution lifecycle."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ConflictError, ForbiddenError, NotFoundError
from ..models import Agent, AgentExecution, Workflow, WorkflowExecution, utcnow
from ..schemas_v2 import AgentExecutionCreate, WorkflowCreate, WorkflowExecutionCreate
from . import audit as audit_service


def create_workflow(db: Session, org_id: str, input: WorkflowCreate, actor: str | None) -> Workflow:
    workflow = Workflow(
        org_id=org_id,
        name=input.name,
        description=input.description,
        status="ACTIVE",
        metadata_json=input.metadata,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(workflow)
    db.flush()
    audit_service.record_event(
        db,
        event_type="admin",
        reason_codes=["WORKFLOW_CREATED"],
        risk_level="LOW",
        metadata={"workflowId": workflow.id, "name": workflow.name, "actor": actor},
        org_id=org_id,
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def list_workflows(db: Session, org_id: str) -> list[Workflow]:
    return list(
        db.execute(
            select(Workflow)
            .where(Workflow.org_id == org_id)
            .order_by(Workflow.created_at.desc())
        ).scalars()
    )


def get_workflow(db: Session, org_id: str, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.org_id != org_id:
        raise NotFoundError("Workflow not found")
    return workflow


def start_execution(
    db: Session, org_id: str, workflow_id: str, input: WorkflowExecutionCreate, actor: str | None
) -> WorkflowExecution:
    workflow = get_workflow(db, org_id, workflow_id)
    if workflow.status != "ACTIVE":
        raise ConflictError("Workflow is not active", reason_codes=["WORKFLOW_NOT_ACTIVE"])
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=org_id,
        external_key=input.external_key,
        status="RUNNING",
        started_at=utcnow(),
        metadata_json=input.metadata,
    )
    db.add(execution)
    db.flush()
    audit_service.record_event(
        db,
        event_type="workflow",
        reason_codes=["WORKFLOW_EXECUTION_STARTED"],
        risk_level="LOW",
        metadata={
            "workflowId": workflow.id,
            "workflowExecutionId": execution.id,
            "externalKey": input.external_key,
            "actor": actor,
        },
        org_id=org_id,
    )
    db.commit()
    db.refresh(execution)
    return execution


def get_execution(db: Session, org_id: str, execution_id: str) -> WorkflowExecution:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("Workflow execution not found")
    return execution


def list_executions(db: Session, org_id: str, limit: int = 100) -> list[WorkflowExecution]:
    return list(
        db.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.org_id == org_id)
            .order_by(WorkflowExecution.started_at.desc())
            .limit(max(1, min(limit, 500)))
        ).scalars()
    )


def start_agent_execution(
    db: Session, org_id: str, agent: Agent, input: AgentExecutionCreate
) -> AgentExecution:
    execution = get_execution(db, org_id, input.workflow_execution_id)
    if execution.status != "RUNNING":
        raise ConflictError("Workflow execution is not running")
    row = AgentExecution(
        org_id=org_id,
        workflow_execution_id=execution.id,
        agent_id=agent.id,
        status="RUNNING",
        started_at=utcnow(),
        metadata_json=input.metadata,
    )
    db.add(row)
    db.flush()
    audit_service.record_event(
        db,
        event_type="workflow",
        agent_id=agent.id,
        reason_codes=["AGENT_EXECUTION_STARTED"],
        risk_level="LOW",
        metadata={
            "workflowExecutionId": execution.id,
            "agentExecutionId": row.id,
        },
        org_id=org_id,
    )
    db.commit()
    db.refresh(row)
    return row


def complete_agent_execution(
    db: Session,
    org_id: str,
    agent: Agent,
    agent_execution_id: str,
    status: str,
    error: str | None,
) -> AgentExecution:
    row = db.get(AgentExecution, agent_execution_id)
    if row is None or row.org_id != org_id:
        raise NotFoundError("Agent execution not found")
    if row.agent_id != agent.id:
        raise ForbiddenError("Agent execution belongs to a different agent")
    if row.status != "RUNNING":
        raise ConflictError("Agent execution is already finished")
    row.status = status
    row.error = error
    row.ended_at = utcnow()
    db.flush()
    audit_service.record_event(
        db,
        event_type="workflow",
        agent_id=agent.id,
        reason_codes=[f"AGENT_EXECUTION_{status}"],
        risk_level="LOW" if status == "COMPLETED" else "HIGH",
        metadata={
            "workflowExecutionId": row.workflow_execution_id,
            "agentExecutionId": row.id,
            "error": error,
        },
        org_id=org_id,
    )
    db.commit()
    db.refresh(row)
    return row


def complete_execution(
    db: Session, org_id: str, execution_id: str, status: str, actor: str | None
) -> WorkflowExecution:
    execution = get_execution(db, org_id, execution_id)
    if execution.status in ("COMPLETED", "FAILED"):
        raise ConflictError("Workflow execution is already finished")
    execution.status = status
    execution.ended_at = utcnow()
    db.flush()
    audit_service.record_event(
        db,
        event_type="workflow",
        reason_codes=[f"WORKFLOW_EXECUTION_{status}"],
        risk_level="LOW" if status == "COMPLETED" else "HIGH",
        metadata={
            "workflowExecutionId": execution.id,
            "actor": actor,
        },
        org_id=org_id,
    )
    db.commit()
    db.refresh(execution)
    return execution


def execution_summary(
    db: Session, org_id: str, execution_id: str
) -> dict[str, Any]:
    execution = get_execution(db, org_id, execution_id)
    agents = db.execute(
        select(AgentExecution).where(AgentExecution.workflow_execution_id == execution.id)
    ).scalars().all()
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "org_id": execution.org_id,
        "external_key": execution.external_key,
        "status": execution.status,
        "started_at": execution.started_at,
        "ended_at": execution.ended_at,
        "agent_executions": [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "status": row.status,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "error": row.error,
            }
            for row in agents
        ],
    }
