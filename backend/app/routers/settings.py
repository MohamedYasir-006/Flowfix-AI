"""Workspace settings endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import SettingsOut, SettingsUpdate
from ..services import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    return settings_service.to_out(settings_service.get_or_create(db))


@router.patch("", response_model=SettingsOut)
def update_settings(
    patch: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SettingsOut:
    row = settings_service.update(db, patch)
    return settings_service.to_out(row)
