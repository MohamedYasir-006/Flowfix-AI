"""Incident inspection, replay reports, and isolated what-if simulation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_org_id
from ..models import User
from ..schemas_v2 import IncidentOut, IncidentReport, WhatIfRequest, WhatIfResult
from ..services import incidents as incident_service

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    return incident_service.list_incidents(db, org_id, status=status, limit=limit)


@router.post("/what-if", response_model=WhatIfResult)
def what_if(
    input: WhatIfRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Simulate a decision change from recorded evidence only.

    Read-only: no decision is written, no tool is invoked, and containment state
    is unchanged.
    """
    return incident_service.what_if(
        db, org_id, action_id=input.action_id, hypothetical=input.hypothetical_decision
    )


@router.get("/summary")
def incident_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    incidents = incident_service.list_incidents(db, org_id, limit=1000)
    by_status: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for incident in incidents:
        by_status[incident.status] = by_status.get(incident.status, 0) + 1
        by_risk[incident.risk_level] = by_risk.get(incident.risk_level, 0) + 1
    return {
        "total": len(incidents),
        "open": by_status.get("OPEN", 0),
        "by_status": by_status,
        "by_risk": by_risk,
    }


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return incident_service.get_incident(db, org_id, incident_id)


@router.get("/{incident_id}/report", response_model=IncidentReport)
def incident_report(
    incident_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    return incident_service.incident_report(db, org_id, incident_id)


@router.post("/{incident_id}/resolve", response_model=IncidentOut)
def resolve_incident(
    incident_id: str,
    resolution: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = incident_service.get_incident(db, user.org_id, incident_id)
    result = incident_service.resolve_incident(
        db, incident, actor_user_id=user.id, resolution=resolution
    )
    db.commit()
    db.refresh(result)
    return result
