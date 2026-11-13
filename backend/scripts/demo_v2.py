"""AgentGuard V2 end-to-end demonstration.

Runs real service code against an isolated temporary SQLite database. It does
not touch the caller's database and does not execute external tools.

Covered:
1. invalid upstream artifact -> DENY
2. unverified high-impact input -> REQUIRE_APPROVAL, then post-approval
   propagation denial when the artifact becomes INVALID
3. quarantine -> decision denied, recovery after a validated replacement
4. saga partial failure -> compensation approval -> compensation completion
5. audit hash-chain verification

Usage:
    cd backend
    python scripts/demo_v2.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.migrations import ensure_default_organization
from app.models import Agent, Approval, TransactionStep
from app.schemas import ApprovalDecision, EvaluateRequest
from app.schemas_v2 import (
    TransactionCreate,
    TransactionStepCreate,
    WorkflowCreate,
    WorkflowExecutionCreate,
)
from app.seed import seed_demo_data
from app.services import approvals as approvals_service
from app.services import audit as audit_service
from app.services import containment as containment_service
from app.services import decisions as decision_service
from app.services import provenance as provenance_service
from app.services import transactions as transaction_service
from app.services import workflows as workflow_service


PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def record_artifact(db, agent, execution, *, name, content, status, parents=None):
    artifact = provenance_service.record_artifact(
        db,
        org_id=agent.org_id,
        producer=agent,
        artifact_type="customer_record",
        name=name,
        content=content,
        workflow_execution_id=execution.id,
        parent_artifact_ids=parents or [],
    )
    if status != "UNVERIFIED":
        artifact.validation_status = status
    db.flush()
    return artifact


def evaluate(db, agent, execution, *, artifact_ids, arguments, approval_id=None):
    return decision_service.evaluate_decision(
        db,
        agent,
        EvaluateRequest(
            tool="send_email",
            arguments=arguments,
            target="customer@example.com",
            workflow_execution_id=execution.id,
            input_artifact_ids=artifact_ids,
            approval_id=approval_id,
        ),
    )


def main() -> int:
    temp_dir = Path(tempfile.mkdtemp(prefix="agentguard-demo-v2-"))
    database_path = temp_dir / "demo.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    ensure_default_organization(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False, future=True)()

    try:
        seed_demo_data(db)
        db.flush()
        agent = db.get(Agent, "agent-support")
        print("=" * 72)
        print("AgentGuard V2 demo - isolated database")
        print("=" * 72)
        print(f"agent: {agent.name} ({agent.id}), environment={agent.environment}")

        workflow = workflow_service.create_workflow(
            db, agent.org_id, WorkflowCreate(name="v2-demo-flow"), "u-admin"
        )
        execution = workflow_service.start_execution(
            db,
            agent.org_id,
            workflow.id,
            WorkflowExecutionCreate(workflow_id=workflow.id, external_key="demo-1"),
            agent.id,
        )
        print(f"workflow execution: {execution.id}")

        arguments = {
            "to": "customer@example.com",
            "subject": "Refund confirmation",
            "body": "Your refund was approved.",
        }

        # ------------------------------------------------------------------
        print("\n1) Invalid upstream artifact")
        invalid = record_artifact(
            db,
            agent,
            execution,
            name="beneficiary",
            content={"account": "acct-1", "verified": False},
            status="INVALID",
        )
        first = evaluate(db, agent, execution, artifact_ids=[invalid.id], arguments=arguments)
        print(f"  decision={first.decision}")
        print(f"  reason_codes={first.reason_codes}")
        print(f"  propagation_effect={(first.propagation or {}).get('effect')}")
        check("invalid upstream denied", first.decision == "DENY")
        check(
            "invalid-upstream reason present",
            "INVALID_UPSTREAM_ARTIFACT" in first.reason_codes,
        )

        # ------------------------------------------------------------------
        print("\n2) Unverified high-impact input, approval, then post-approval denial")
        unverified = record_artifact(
            db,
            agent,
            execution,
            name="unverified-beneficiary",
            content={"account": "acct-2", "source": "scraped"},
            status="UNVERIFIED",
        )
        pending = evaluate(
            db, agent, execution, artifact_ids=[unverified.id], arguments=arguments
        )
        print(f"  first decision={pending.decision}, approval_id={pending.approval_id}")
        print(f"  reason_codes={pending.reason_codes}")
        check("unverified input requires approval", pending.decision == "REQUIRE_APPROVAL")
        check(
            "approval created",
            bool(pending.approval_id),
            f"got {pending.approval_id!r}",
        )

        approval = db.get(Approval, pending.approval_id) if pending.approval_id else None
        if approval is not None:
            approvals_service.decide(
                db,
                approval,
                "u-approver",
                ApprovalDecision(decision="APPROVED"),
            )
            db.flush()
            print(f"  human approval status={approval.status}")

        # The evidence changes after the human decision. Approval must not wave
        # an invalid upstream through.
        unverified.validation_status = "INVALID"
        db.flush()
        retry = evaluate(
            db,
            agent,
            execution,
            artifact_ids=[unverified.id],
            arguments=arguments,
            approval_id=pending.approval_id,
        )
        print(f"  post-approval decision={retry.decision}")
        print(f"  reason_codes={retry.reason_codes}")
        check(
            "approval does not bypass invalid upstream",
            retry.decision == "DENY",
        )
        check(
            "post-approval propagation reason present",
            "PROPAGATION_BLOCKED_AFTER_APPROVAL" in retry.reason_codes,
        )
        if approval is not None:
            db.refresh(approval)
            check("approval was not consumed", approval.consumed_at is None)

        # ------------------------------------------------------------------
        print("\n3) Quarantine and recovery")
        # Provide newer validated replacements so recovery is allowed. The
        # replacement rule is same artifact_type/name and a later timestamp.
        replacement = record_artifact(
            db,
            agent,
            execution,
            name="unverified-beneficiary",
            content={"account": "acct-2", "source": "verified"},
            status="VALIDATED",
        )
        invalid_replacement = record_artifact(
            db,
            agent,
            execution,
            name="beneficiary",
            content={"account": "acct-1", "verified": True},
            status="VALIDATED",
        )
        db.flush()
        print(f"  validated replacement artifacts: {replacement.id}, {invalid_replacement.id}")

        containment_service.quarantine_agent(
            db,
            agent=agent,
            reason="demo quarantine",
            actor_user_id="u-admin",
        )
        db.flush()
        blocked = decision_service.evaluate_decision(
            db,
            agent,
            EvaluateRequest(
                tool="search_knowledge_base",
                arguments={"query": "refund policy"},
                workflow_execution_id=execution.id,
            ),
        )
        print(f"  quarantined decision={blocked.decision}")
        print(f"  reason_codes={blocked.reason_codes}")
        check("quarantined agent denied", blocked.decision == "DENY")
        check("quarantine reason present", "AGENT_QUARANTINED" in blocked.reason_codes)

        containment_service.start_recovery(db, agent=agent, actor_user_id="u-admin")
        containment_service.complete_recovery(db, agent=agent, actor_user_id="u-admin")
        db.flush()
        state = containment_service.get_or_create_state(db, agent)
        print(f"  operational status after recovery={state.operational_status}")
        check("recovery returns agent to ACTIVE", state.operational_status == "ACTIVE")

        # ------------------------------------------------------------------
        print("\n4) Saga transaction and compensation approval")
        transaction, created = transaction_service.create_transaction(
            db,
            org_id=agent.org_id,
            input=TransactionCreate(
                workflow_execution_id=execution.id,
                idempotency_key="demo-checkout-1",
                steps=[
                    TransactionStepCreate(
                        step_key="reserve",
                        tool_name="reserve_funds",
                        compensation_tool="release_funds",
                    ),
                    TransactionStepCreate(step_key="settle", tool_name="settle_transfer"),
                ],
            ),
        )
        db.flush()
        print(f"  transaction={transaction.id}, created={created}")

        transaction_service.start_step(db, transaction=transaction, step_ref="reserve")
        transaction_service.complete_step(
            db, transaction=transaction, step_ref="reserve", success=True
        )
        transaction_service.start_step(db, transaction=transaction, step_ref="settle")
        transaction_service.complete_step(
            db,
            transaction=transaction,
            step_ref="settle",
            success=False,
            error="settlement failed",
        )
        db.flush()
        print(f"  status after partial failure={transaction.status}")
        check("partial failure requires recovery", transaction.status == "RECOVERY_REQUIRED")

        transaction_service.request_compensation(
            db, transaction=transaction, reason="rollback", approved=False
        )
        db.flush()
        print(f"  status awaiting compensation approval={transaction.status}")
        check("compensation waits for approval", transaction.status == "WAITING_APPROVAL")

        transaction_service.request_compensation(
            db, transaction=transaction, reason="approved rollback", approved=True
        )
        db.flush()
        print(f"  status during compensation={transaction.status}")
        check("compensation approved", transaction.status == "COMPENSATING")

        transaction_service.complete_compensation(
            db, transaction=transaction, step_ref="reserve", success=True
        )
        db.flush()
        step = (
            db.query(TransactionStep)
            .filter_by(transaction_id=transaction.id, step_key="reserve")
            .one()
        )
        print(f"  transaction status={transaction.status}")
        print(f"  reserve compensation status={step.compensation_status}")
        check("compensation completed", transaction.status == "COMPLETED")
        check("compensated step recorded", step.compensation_status == "COMPLETED")

        # ------------------------------------------------------------------
        print("\n5) Audit hash chain")
        verification = audit_service.verify_chain(db, agent.org_id)
        print(f"  valid={verification.get('valid')}, checked={verification.get('checked')}")
        print(f"  last_hash={verification.get('last_hash')}")
        check("audit chain verifies", verification.get("valid") is True)
        check("audit chain has events", int(verification.get("checked") or 0) > 0)

        # ------------------------------------------------------------------
        print("\n" + "=" * 72)
        print(f"Result: {PASS} passed, {FAIL} failed")
        print("=" * 72)
        if FAIL:
            print("Some checks failed. Review the output above.")
            return 1

        print("Verified: invalid upstream data was denied, approval did not bypass")
        print("a post-approval propagation denial, containment denied execution,")
        print("compensation required approval, and the audit chain verified.")
        return 0

    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
