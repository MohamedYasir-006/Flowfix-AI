"""Workflow identity, execution, graph, and timeline endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_agent, get_current_user, get_org_id
from ..models import Agent, User
from ..schemas_v2 import (
    AgentExecutionComplete,
    AgentExecutionCreate,
    AgentExecutionOut,
    WorkflowCreate,
    WorkflowExecutionCreate,
    WorkflowExecutionOut,
    WorkflowGraph,
    WorkflowOut,
)
from ..services import containment as containment_service
from ..services import dependencies as dependency_service
from ..services import incidents as incident_service
from ..services import workflows as workflow_service

router = APIRouter(tags=["workflows"])


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def create_workflow(
    input: WorkflowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return workflow_service.create_workflow(db, user.org_id, input, user.id)


@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return workflow_service.list_workflows(db, org_id)


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return workflow_service.get_workflow(db, org_id, workflow_id)


@router.post(
    "/workflows/{workflow_id}/executions",
    response_model=WorkflowExecutionOut,
    status_code=201,
)
def start_execution(
    workflow_id: str,
    input: WorkflowExecutionCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    return workflow_service.start_execution(db, agent.org_id, workflow_id, input, agent.id)


@router.get("/workflow-executions", response_model=list[WorkflowExecutionOut])
def list_executions(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return workflow_service.list_executions(db, org_id)


@router.get("/workflow-executions/{execution_id}")
def get_execution(execution_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return workflow_service.execution_summary(db, org_id, execution_id)


@router.post("/workflow-executions/{execution_id}/agent-executions", response_model=AgentExecutionOut, status_code=201)
def start_agent_execution(
    execution_id: str,
    input: AgentExecutionCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    # The path id is authoritative; reject a mismatched body rather than
    # silently creating an execution under a different workflow.
    if input.workflow_execution_id != execution_id:
        from ..errors import ConflictError

        raise ConflictError("Path and body workflow execution ids differ")
    return workflow_service.start_agent_execution(db, agent.org_id, agent, input)


@router.post("/agent-executions/{agent_execution_id}/complete", response_model=AgentExecutionOut)
def complete_agent_execution(
    agent_execution_id: str,
    input: AgentExecutionComplete,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    return workflow_service.complete_agent_execution(
        db, agent.org_id, agent, agent_execution_id, input.status, input.error
    )


@router.post("/workflow-executions/{execution_id}/complete", response_model=WorkflowExecutionOut)
def complete_execution(
    execution_id: str,
    status: str = "COMPLETED",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return workflow_service.complete_execution(db, user.org_id, execution_id, status, user.id)


@router.get("/workflow-executions/{execution_id}/graph", response_model=WorkflowGraph)
def execution_graph(
    execution_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return dependency_service.workflow_graph(db, org_id, execution_id)


@router.get("/workflow-executions/{execution_id}/timeline")
def execution_timeline(
    execution_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return incident_service.workflow_timeline(db, org_id, execution_id)


@router.post("/workflow-executions/{execution_id}/pause", response_model=WorkflowExecutionOut)
def pause_execution(
    execution_id: str,
    reason: str = "Administrator containment",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    execution = workflow_service.get_execution(db, user.org_id, execution_id)
    result = containment_service.pause_workflow(
        db, workflow_execution=execution, actor_user_id=user.id, reason=reason
    )
    db.commit()
    db.refresh(result)
    return result


@router.post("/workflow-executions/{execution_id}/resume", response_model=WorkflowExecutionOut)
def resume_execution(
    execution_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    execution = workflow_service.get_execution(db, user.org_id, execution_id)
    result = containment_service.resume_workflow(
        db, workflow_execution=execution, actor_user_id=user.id
    )
    db.commit()
    db.refresh(result)
    return result
