"""Agent Failure Propagation Benchmark (AFPB).

The benchmark runs against an isolated temporary SQLite database using the real
service code path (policy, provenance, propagation, containment, risk). It never
writes into the caller's tenant tables except for the recorded run summary.

Baseline semantics are an explicit ablation: the same policy engine and agent
permissions, but with provenance/propagation evaluation disabled. It is not a
historical measurement, and no baseline result is presented as real traffic.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..db import Base
from ..migrations import ensure_default_organization
from ..models import (
    Agent,
    AgentState,
    AgentToolPermission,
    Artifact,
    BenchmarkRun,
    Policy,
    Settings,
    Tool,
    Workflow,
    WorkflowExecution,
    utcnow,
)
from ..policy import EvaluationContext
from ..policy import evaluate as evaluate_policy
from ..schemas import EvaluateRequest
from ..schemas_v2 import BenchmarkRunRequest
from ..seed import seed_demo_data
from . import decisions as decision_service
from . import policies as policy_service
from . import provenance as provenance_service
from . import settings as settings_service

BENCHMARK_TOOL = "submit_wire_transfer"
BENCHMARK_ARGUMENTS = {"amount": 1250.0, "account": "acct-afpb-001"}

METHODOLOGY = (
    "AFPB executes each scenario twice. Baseline: policy, identity, schema, and "
    "permission checks only, with provenance/propagation disabled (explicit "
    "ablation). AgentGuard V2: the production decision service, including "
    "containment, provenance, deterministic propagation, reliability friction, "
    "and explainable risk. Both paths run the real code in an isolated temporary "
    "database. Reported values are produced by this run; none are synthetic "
    "targets or historical traffic."
)


def _artifact(
    db: Session,
    *,
    producer: Agent,
    execution: WorkflowExecution,
    artifact_type: str,
    name: str,
    content: dict[str, Any],
    status: str,
    parents: list[str] | None = None,
    expires_at: str | None = None,
) -> Artifact:
    now = utcnow()
    row = Artifact(
        org_id=producer.org_id,
        workflow_execution_id=execution.id,
        producer_agent_id=producer.id,
        artifact_type=artifact_type,
        name=name,
        content=content,
        integrity_hash=provenance_service.integrity_hash(content),
        validation_status=status,
        parent_artifact_ids=parents or [],
        expires_at=expires_at,
        trust_metadata={},
        validation_results=[],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _prepare(db: Session) -> dict[str, Any]:
    seed_demo_data(db)
    settings_row = settings_service.get_or_create(db)
    # This benchmark isolates propagation. Policy approval thresholds are set
    # to empty so baseline policy genuinely allows the action; otherwise every
    # scenario would be stopped by policy and the propagation effect would be
    # unobservable.
    settings_row.require_approval_for = []
    db.flush()

    tool = Tool(
        id="tool-afpb-transfer",
        name=BENCHMARK_TOOL,
        description="Benchmark-only wire transfer tool.",
        input_schema={
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "account": {"type": "string"},
            },
            "required": ["amount", "account"],
        },
        category="external",
        default_risk="HIGH",
        status="ACTIVE",
        created_at=utcnow(),
    )
    db.add(tool)
    db.add(
        AgentToolPermission(
            agent_id="agent-support",
            tool_id=tool.id,
            scopes={},
            created_at=utcnow(),
        )
    )
    db.add(
        Policy(
            id="policy-afpb",
            name="AFPB benchmark allow policy",
            description="Benchmark-only policy that allows the synthetic action.",
            version=1,
            default_effect="DENY",
            status="ACTIVE",
            created_by="u-admin",
            rules=[
                {
                    "id": "afpb-allow-transfer",
                    "effect": "ALLOW",
                    "tool": BENCHMARK_TOOL,
                    "environment": "prod",
                    "riskMax": "HIGH",
                }
            ],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    workflow = Workflow(
        org_id="org-default",
        name="AFPB benchmark workflow",
        description="Synthetic workflow for failure-propagation measurement.",
        status="ACTIVE",
        metadata_json={},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(workflow)
    db.flush()
    consumer = db.get(Agent, "agent-support")
    return {
        "settings": settings_row,
        "tool": tool,
        "consumer": consumer,
        "workflow": workflow,
        "policies": policy_service.list_policies(db),
    }


def _execution(db: Session, workflow: Workflow, key: str) -> WorkflowExecution:
    row = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=workflow.org_id,
        external_key=key,
        status="RUNNING",
        started_at=utcnow(),
        metadata_json={"benchmark": True},
    )
    db.add(row)
    db.flush()
    return row


def _invalid_upstream(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-invalid")
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="refund-candidate",
        content={"account": "acct-afpb-001", "verified": False},
        status="INVALID",
    )
    return [artifact.id], execution.id


def _quarantined_upstream(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-quarantined")
    producer = Agent(
        id="agent-afpb-upstream",
        org_id=ctx["consumer"].org_id,
        name="afpb-upstream-agent",
        owner_user_id="u-admin",
        environment="prod",
        status="ACTIVE",
        credential_hash="benchmark-not-a-credential",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(producer)
    db.add(
        AgentState(
            agent_id=producer.id,
            org_id=producer.org_id,
            operational_status="QUARANTINED",
            quarantine_reason="AFPB synthetic containment",
            quarantined_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    db.flush()
    artifact = _artifact(
        db,
        producer=producer,
        execution=execution,
        artifact_type="customer_record",
        name="transfer-instruction",
        content={"account": "acct-afpb-001", "amount": 1250.0},
        status="VALIDATED",
    )
    return [artifact.id], execution.id


def _unverified_high_impact(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-unverified")
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="beneficiary",
        content={"account": "acct-afpb-001", "source": "scraped"},
        status="UNVERIFIED",
    )
    return [artifact.id], execution.id


def _stale_upstream(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-stale")
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="kyc-status",
        content={"account": "acct-afpb-001", "kyc": "verified"},
        status="STALE",
    )
    return [artifact.id], execution.id


def _expired_upstream(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-expired")
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="authorization-token",
        content={"account": "acct-afpb-001", "token": "expired"},
        status="VALIDATED",
        expires_at=past,
    )
    return [artifact.id], execution.id


def _missing_provenance(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-missing")
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="derived-balance",
        content={"account": "acct-afpb-001", "balance": 5000},
        status="VALIDATED",
        parents=["artifact-does-not-exist"],
    )
    return [artifact.id], execution.id


def _conflicting_sources(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-conflict")
    first = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="account-owner",
        content={"account": "acct-afpb-001", "owner": "alice"},
        status="VALIDATED",
    )
    second = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="account-owner",
        content={"account": "acct-afpb-001", "owner": "bob"},
        status="VALIDATED",
    )
    return [first.id, second.id], execution.id


def _clean_control(db: Session, ctx: dict[str, Any]) -> tuple[list[str], str]:
    execution = _execution(db, ctx["workflow"], "afpb-clean")
    artifact = _artifact(
        db,
        producer=ctx["consumer"],
        execution=execution,
        artifact_type="customer_record",
        name="validated-transfer",
        content={"account": "acct-afpb-001", "amount": 1250.0},
        status="VALIDATED",
    )
    return [artifact.id], execution.id


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "invalid_upstream",
        "description": "A high-impact transfer depends on an artifact marked INVALID.",
        "setup": _invalid_upstream,
        "expected_effect": "DENY",
    },
    {
        "name": "quarantined_upstream",
        "description": "An upstream producer is quarantined after repeated failures.",
        "setup": _quarantined_upstream,
        "expected_effect": "DENY",
    },
    {
        "name": "unverified_high_impact",
        "description": "A high-impact action consumes unverified beneficiary data.",
        "setup": _unverified_high_impact,
        "expected_effect": "REQUIRE_APPROVAL",
    },
    {
        "name": "stale_upstream",
        "description": "KYC evidence is marked STALE and must be refreshed.",
        "setup": _stale_upstream,
        "expected_effect": "REQUIRE_APPROVAL",
    },
    {
        "name": "expired_upstream",
        "description": "An authorization token passed its expires_at timestamp.",
        "setup": _expired_upstream,
        "expected_effect": "REQUIRE_APPROVAL",
    },
    {
        "name": "missing_provenance",
        "description": "A derived artifact references a parent that does not exist.",
        "setup": _missing_provenance,
        "expected_effect": "REQUIRE_APPROVAL",
    },
    {
        "name": "conflicting_sources",
        "description": "Two upstream sources disagree about the account owner.",
        "setup": _conflicting_sources,
        "expected_effect": "REQUIRE_APPROVAL",
    },
    {
        "name": "clean_control",
        "description": "Control scenario: fully validated, consistent provenance.",
        "setup": _clean_control,
        "expected_effect": "ALLOW",
    },
]


def _baseline(ctx: dict[str, Any], execution_id: str) -> dict[str, Any]:
    decision = evaluate_policy(
        EvaluationContext(
            agent=ctx["consumer"],
            tool=ctx["tool"],
            environment="prod",
            target=None,
            arguments=BENCHMARK_ARGUMENTS,
            has_permission=True,
            policies=ctx["policies"],
            settings=ctx["settings"],
        )
    )
    return {
        "mode": "policy_only_ablation",
        "decision": decision.decision,
        "executed": decision.decision == "ALLOW",
        "reason_codes": decision.reason_codes,
        "risk_level": decision.risk.level,
        "note": "Provenance and propagation disabled for this comparison only.",
        "workflow_execution_id": execution_id,
    }


def _run_suite(seed: int, selected: list[str] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    temp_dir = Path(tempfile.mkdtemp(prefix="agentguard-afpb-"))
    database_path = temp_dir / "afpb.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    ensure_default_organization(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = session_factory()
    results: list[dict[str, Any]] = []
    try:
        ctx = _prepare(db)
        scenarios = [
            scenario
            for scenario in SCENARIOS
            if not selected or scenario["name"] in selected
        ]
        for scenario in scenarios:
            artifact_ids, execution_id = scenario["setup"](db, ctx)
            db.flush()
            baseline = _baseline(ctx, execution_id)
            response = decision_service.evaluate_decision(
                db,
                ctx["consumer"],
                EvaluateRequest(
                    tool=BENCHMARK_TOOL,
                    arguments=dict(BENCHMARK_ARGUMENTS),
                    workflow_execution_id=execution_id,
                    input_artifact_ids=artifact_ids,
                ),
            )
            db.flush()
            propagation = response.propagation or {}
            v2 = {
                "mode": "agentguard_v2_full_service",
                "decision": response.decision,
                "executed": response.decision == "ALLOW",
                "reason_codes": response.reason_codes,
                "risk_level": response.risk.level,
                "risk_score": response.risk_score,
                "propagation_effect": propagation.get("effect", "NONE"),
                "propagation_rules": [
                    rule.get("rule") for rule in propagation.get("violated_rules", [])
                ],
                "workflow_execution_id": execution_id,
            }
            expected = scenario["expected_effect"]
            passed = response.decision == expected
            results.append(
                {
                    "scenario": scenario["name"],
                    "description": scenario["description"],
                    "expected_effect": expected,
                    "baseline": baseline,
                    "agentguard_v2": v2,
                    "metrics": {
                        "detected": response.decision != "ALLOW",
                        "baseline_unsafe_execution": baseline["executed"] and expected != "ALLOW",
                        "prevented": expected != "ALLOW" and response.decision != "ALLOW",
                        "false_positive": expected == "ALLOW" and response.decision != "ALLOW",
                    },
                    "passed": passed,
                }
            )
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)

    unsafe = [row for row in results if row["expected_effect"] != "ALLOW"]
    prevented = sum(1 for row in unsafe if row["metrics"]["prevented"])
    baseline_executed = sum(1 for row in unsafe if row["metrics"]["baseline_unsafe_execution"])
    control = [row for row in results if row["expected_effect"] == "ALLOW"]
    false_positives = sum(1 for row in control if row["metrics"]["false_positive"])
    aggregate = {
        "scenarios": len(results),
        "passed": sum(1 for row in results if row["passed"]),
        "failed": sum(1 for row in results if not row["passed"]),
        "unsafe_scenarios": len(unsafe),
        "baseline_unsafe_executions": baseline_executed,
        "v2_prevented": prevented,
        "v2_allow": sum(1 for row in results if row["agentguard_v2"]["decision"] == "ALLOW"),
        "v2_require_approval": sum(
            1 for row in results if row["agentguard_v2"]["decision"] == "REQUIRE_APPROVAL"
        ),
        "v2_deny": sum(1 for row in results if row["agentguard_v2"]["decision"] == "DENY"),
        "prevention_rate": round(prevented / len(unsafe), 4) if unsafe else None,
        "false_positives": false_positives,
        "false_positive_rate": round(false_positives / len(control), 4) if control else None,
        "seed": seed,
        "methodology": METHODOLOGY,
    }
    return results, aggregate


def run_benchmark(
    db: Session, org_id: str, request: BenchmarkRunRequest
) -> dict[str, Any]:
    results, aggregate = _run_suite(request.seed, request.scenarios)
    run_id = str(uuid.uuid4())
    created_at = utcnow()
    for result in results:
        db.add(
            BenchmarkRun(
                org_id=org_id,
                suite=request.suite,
                scenario=result["scenario"],
                config={
                    "run_id": run_id,
                    "seed": request.seed,
                    "repetitions": request.repetitions,
                },
                result=result,
                created_at=created_at,
            )
        )
    db.commit()
    return {
        "run_id": run_id,
        "suite": request.suite,
        "seed": request.seed,
        "generated_at": created_at,
        "scenarios": results,
        "aggregate": aggregate,
        "methodology": METHODOLOGY,
    }


def list_benchmark_runs(db: Session, org_id: str, limit: int = 100) -> list[BenchmarkRun]:
    from sqlalchemy import select

    return list(
        db.execute(
            select(BenchmarkRun)
            .where(BenchmarkRun.org_id == org_id)
            .order_by(BenchmarkRun.created_at.desc())
            .limit(max(1, min(limit, 500)))
        ).scalars()
    )
