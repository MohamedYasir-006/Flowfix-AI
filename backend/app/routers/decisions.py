"""Policy decision and execution-result endpoints (agent-authenticated)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_agent
from ..models import Agent
from ..schemas import ActionResultRequest, DecisionResponse, EvaluateRequest, EventOut
from ..services import decisions as decisions_service

router = APIRouter(tags=["decisions"])


@router.post("/decisions/evaluate", response_model=DecisionResponse)
def evaluate(
    input: EvaluateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> DecisionResponse:
    return decisions_service.evaluate_decision(db, agent, input)


@router.post("/actions/{action_id}/result", response_model=EventOut)
def report_result(
    action_id: str,
    input: ActionResultRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> EventOut:
    return decisions_service.report_result(db, agent, action_id, input)
