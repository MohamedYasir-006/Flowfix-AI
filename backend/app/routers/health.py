"""Health and readiness endpoint."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from .. import __version__
from ..db import get_db
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database = "up"
    except Exception:  # pragma: no cover - only hit when the DB is down
        database = "down"
    return HealthResponse(status="ok", version=__version__, database=database)
