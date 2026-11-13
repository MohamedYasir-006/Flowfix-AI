"""AFPB benchmark execution and run history."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_org_id
from ..models import User
from ..schemas_v2 import BenchmarkOut, BenchmarkRunRequest
from ..services import benchmarks as benchmark_service

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.post("/afpb/run", response_model=BenchmarkOut)
def run_afpb(
    input: BenchmarkRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run the Agent Failure Propagation Benchmark in an isolated database.

    The benchmark executes real service code. Baseline results come from an
    explicit policy-only ablation, not from historical traffic.
    """
    return benchmark_service.run_benchmark(db, user.org_id, input)


@router.get("/runs")
def list_runs(
    limit: int = 100, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    rows = benchmark_service.list_benchmark_runs(db, org_id, limit=limit)
    return [
        {
            "id": row.id,
            "suite": row.suite,
            "scenario": row.scenario,
            "config": row.config,
            "result": row.result,
            "created_at": row.created_at,
        }
        for row in rows
    ]
