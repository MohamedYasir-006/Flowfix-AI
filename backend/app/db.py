"""Database engine, session factory, and declarative base."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


Engine = None  # type: ignore[assignment]
SessionLocal = None  # type: ignore[assignment]


class Base(DeclarativeBase):
    """Shared declarative base for all AgentGuard models."""


def _build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )


def init_db() -> None:
    """Create the engine/session factory and create all tables.

    Idempotent: safe to call repeatedly (the application lifespan and the
    ``get_db`` dependency both call it). The first call wins.
    """
    global Engine, SessionLocal

    if Engine is not None and SessionLocal is not None:
        return

    settings = get_settings()
    Engine = _build_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=Engine, autoflush=False, expire_on_commit=False, future=True)

    # Import models so their tables register on the shared metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(Engine)


# Bind the factory at import time so ``from app.db import SessionLocal`` is
# usable without a manual init_db() call. Tests and scripts import this module
# directly and must not depend on lifespan having run.
init_db()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
