"""Tool registry."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Tool, utcnow
from ..schemas import ToolCreate


def get_tool(db: Session, tool_id: str) -> Tool | None:
    return db.get(Tool, tool_id)


def get_tool_by_name(db: Session, name: str) -> Tool | None:
    return db.execute(select(Tool).where(Tool.name == name)).scalar_one_or_none()


def list_tools(db: Session) -> list[Tool]:
    return list(db.execute(select(Tool).order_by(Tool.name)).scalars())


def create_tool(db: Session, input: ToolCreate) -> Tool:
    if get_tool_by_name(db, input.name):
        raise ValueError(f"Tool '{input.name}' is already registered")
    tool = Tool(
        name=input.name,
        description=input.description,
        input_schema=input.input_schema,
        category=input.category,
        default_risk=input.default_risk,
        status=input.status,
        created_at=utcnow(),
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool
