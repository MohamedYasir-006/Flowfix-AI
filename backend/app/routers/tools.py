"""Tool registry endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ConflictError, NotFoundError
from ..schemas import ToolCreate, ToolOut
from ..services import tools as tools_service

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolOut])
def list_tools(db: Session = Depends(get_db)) -> list[ToolOut]:
    return [ToolOut.model_validate(tool) for tool in tools_service.list_tools(db)]


@router.post("", response_model=ToolOut, status_code=201)
def create_tool(input: ToolCreate, db: Session = Depends(get_db)) -> ToolOut:
    try:
        tool = tools_service.create_tool(db, input)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return ToolOut.model_validate(tool)


@router.get("/{tool_id}", response_model=ToolOut)
def get_tool(tool_id: str, db: Session = Depends(get_db)) -> ToolOut:
    tool = tools_service.get_tool(db, tool_id)
    if tool is None:
        raise NotFoundError("Tool not found")
    return ToolOut.model_validate(tool)
