"""AgentGuard API application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .db import init_db
from .errors import ApiError
from .ratelimit import RateLimiter
from .routers import agents, approvals, auth, decisions, events, health, overview, policies, settings, tools, users
from .seed import seed_demo_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app_state = app.state
    app_state.seeded_keys = {}
    # Per-agent fixed-window limiter for the decision endpoint. A noisy or
    # compromised agent must not be able to flood the policy engine.
    app_state.agent_decision_limiter = RateLimiter(
        limit=get_settings().decision_rate_limit,
        window_seconds=get_settings().decision_rate_window_seconds,
    )
    if get_settings().seed_demo_data:
        from .db import SessionLocal

        db = SessionLocal()
        try:
            app_state.seeded_keys = seed_demo_data(db)
        finally:
            db.close()
    yield


app = FastAPI(
    title="AgentGuard",
    description="AI-agent governance, security, and observability control plane",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    headers = dict(getattr(exc, "headers", {}) or {})
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        headers.setdefault("Retry-After", str(int(retry_after) + 1))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "reason_codes": exc.reason_codes},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals to clients; log server-side.
    import logging

    logging.getLogger("agentguard").exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


API_V1 = "/api/v1"

app.include_router(health.router, prefix=API_V1)
app.include_router(auth.router, prefix=API_V1)
app.include_router(agents.router, prefix=API_V1)
app.include_router(tools.router, prefix=API_V1)
app.include_router(policies.router, prefix=API_V1)
app.include_router(decisions.router, prefix=API_V1)
app.include_router(approvals.router, prefix=API_V1)
app.include_router(events.router, prefix=API_V1)
app.include_router(overview.router, prefix=API_V1)
app.include_router(users.router, prefix=API_V1)
app.include_router(settings.router, prefix=API_V1)


@app.get("/api/v1/openapi.json", include_in_schema=False)
def _openapi_alias():  # pragma: no cover - convenience redirect target
    return app.openapi()
