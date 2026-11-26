"""FixFlow AI maintenance workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_org_id
from ..models import User
from ..schemas_fixflow import (
    EquipmentOut,
    FixFlowRunOut,
    FixFlowRunRequest,
    KnowledgeDocOut,
    VerificationRequest,
)
from ..services import fixflow as fixflow_service

router = APIRouter(prefix="/fixflow", tags=["fixflow"])


@router.get("/equipment", response_model=list[EquipmentOut])
def list_equipment(org_id: str = Depends(get_org_id)) -> list[dict]:
    return fixflow_service.list_equipment()


@router.get("/knowledge", response_model=list[KnowledgeDocOut])
def list_knowledge(org_id: str = Depends(get_org_id)) -> list[dict]:
    return fixflow_service.list_knowledge()


@router.post("/runs", response_model=FixFlowRunOut, status_code=201)
async def start_run(
    input: FixFlowRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await fixflow_service.start_run(
        db, org_id=user.org_id, user=user, request=input
    )


@router.get("/runs", response_model=list[FixFlowRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
) -> list[dict]:
    return fixflow_service.list_runs(db, org_id, limit=limit)


@router.get("/runs/{run_id}", response_model=FixFlowRunOut)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
) -> dict:
    return fixflow_service.get_run(db, org_id, run_id)


@router.post("/runs/{run_id}/verify", response_model=FixFlowRunOut)
def verify_run(
    run_id: str,
    input: VerificationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return fixflow_service.verify_run(
        db,
        org_id=user.org_id,
        user=user,
        run_id=run_id,
        readings=input.readings,
        notes=input.notes,
    )
