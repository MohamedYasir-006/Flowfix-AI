"""Dashboard authentication (development-friendly bearer tokens)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import get_current_user
from ..errors import ApiError
from ..models import User
from ..schemas import LoginRequest, LoginResponse, UserOut
from ..security import create_access_token
from ..db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(input: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == input.email).first()
    if user is None:
        raise ApiError("Unknown user", status_code=401, reason_codes=["UNKNOWN_USER"])
    if user.status != "ACTIVE":
        raise ApiError("User is disabled", status_code=403, reason_codes=["USER_DISABLED"])
    return LoginResponse(token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
