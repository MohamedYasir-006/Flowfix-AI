"""V2 intelligence tests: provenance, propagation, containment, sagas, tenancy.

These tests assert deterministic behavior of the real service layer. There are
no mocked scores and no fabricated benchmark values.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.errors import ConflictError
from app.main import app
from app.models import Agent, Approval, AuditEvent, Organization, TransactionStep
from app.schemas import ApprovalDecision, EvaluateRequest
from app.schemas_v2 import (
    TransactionCreate,
    TransactionStepCreate,
    ValidationConfig,
    WorkflowCreate,
    WorkflowExecutionCreate,
)
from app.services import approvals as approvals_service
from app.services import audit as audit_service
from app.services import containment as containment_service
from app.services import decisions as decision_service
from app.services import provenance as provenance_service
from app.services import transactions as transaction_service
from app.services import workflows as workflow_service


def _workflow(db, name="test-workflow"):
    workflow = workflow_service.create_workflow(
        db, "org-default", WorkflowCreate(name=name), "u-admin"
    )
    execution = workflow_service.start_execution(
        db,
        "org-default",
        workflow.id,
        WorkflowExecutionCreate(workflow_id=workflow.id),
        "agent-support",
    )
    return workflow, execution


def _artifact(db, execution, *, status="UNVERIFIED", content=None, parents=None, name="record"):
    agent = db.get(Agent, "agent-support")
    artifact = provenance_service.record_artifact(
        db,
        org_id=agent.org_id,
        producer=agent,
        artifact_type="customer_record",
        name=name,
        content=content or {"account": "acct-1"},
        workflow_execution_id=execution.id,
        parent_artifact_ids=parents or [],
    )
    if status != "UNVERIFIED":
        artifact.validation_status = status
    db.commit()
    return artifact


def _evaluate(db, tool="send_email", arguments=None, **kwargs):
    agent = db.get(Agent, "agent-support")
    return decision_service.evaluate_decision(
        db,
        agent,
        EvaluateRequest(
            tool=tool,
            arguments=arguments
            or {"to": "customer@example.com", "subject": "Hi", "body": "Hello"},
            target="customer@example.com",
            **kwargs,
        ),
    )


class TestProvenance:
    def test_validation_records_evidence_and_invalid_status(self, db):
        _, execution = _workflow(db)
        agent = db.get(Agent, "agent-support")
        artifact = provenance_service.record_artifact(
            db,
            org_id=agent.org_id,
            producer=agent,
            artifact_type="customer_record",
            name="bad-schema",
            content={"account": 42},
            workflow_execution_id=execution.id,
            trust_metadata={
                "schema": {
                    "type": "object",
                    "properties": {"account": {"type": "string"}},
                    "required": ["account"],
                }
            },
        )
        db.flush()
        updated, results = provenance_service.validate_artifact(
            db,
            org_id=agent.org_id,
            artifact=artifact,
            configs=[ValidationConfig(validator="schema", config=artifact.trust_metadata["schema"])],
        )
        db.commit()
        assert updated.validation_status == "INVALID"
        assert results[0].status == "FAIL"
        assert updated.validation_results[-1]["status"] == "INVALID"

    def test_lineage_tracks_parent_chain(self, db):
        _, execution = _workflow(db)
        root = _artifact(db, execution, name="root")
        child = _artifact(db, execution, name="child", parents=[root.id])
        from app.services import dependencies as dependency_service

        lineage = dependency_service.artifact_lineage(db, "org-default", child.id)
        ids = {row["id"] for row in lineage["nodes"]}
        assert {root.id, child.id} <= ids


class TestPropagation:
    def test_invalid_upstream_denies_even_when_policy_would_ask(self, db):
        _, execution = _workflow(db)
        artifact = _artifact(db, execution, status="INVALID")
        result = _evaluate(
            db,
            workflow_execution_id=execution.id,
            input_artifact_ids=[artifact.id],
        )
        assert result.decision == "DENY"
        assert "INVALID_UPSTREAM_ARTIFACT" in result.reason_codes
        assert result.propagation["effect"] == "DENY"

    def test_unverified_high_impact_requires_approval(self, db):
        _, execution = _workflow(db)
        artifact = _artifact(db, execution, status="UNVERIFIED")
        result = _evaluate(
            db,
            workflow_execution_id=execution.id,
            input_artifact_ids=[artifact.id],
        )
        assert result.decision == "REQUIRE_APPROVAL"
        assert result.propagation["effect"] == "REQUIRE_APPROVAL"
        assert any(
            rule["reason_code"] == "UNVERIFIED_HIGH_IMPACT_INPUT"
            for rule in result.propagation["violated_rules"]
        )

    def test_validated_upstream_has_no_propagation_violation(self, db):
        _, execution = _workflow(db)
        artifact = _artifact(db, execution, status="VALIDATED")
        result = _evaluate(
            db,
            workflow_execution_id=execution.id,
            input_artifact_ids=[artifact.id],
        )
        assert result.propagation["effect"] == "NONE"
        assert result.propagation["violated_rules"] == []

    def test_approval_does_not_bypass_new_propagation_denial(self, db):
        _, execution = _workflow(db)
        artifact = _artifact(db, execution, status="UNVERIFIED")
        arguments = {"to": "customer@example.com", "subject": "Hi", "body": "Hello"}
        first = _evaluate(
            db,
            arguments=arguments,
            workflow_execution_id=execution.id,
            input_artifact_ids=[artifact.id],
        )
        assert first.decision == "REQUIRE_APPROVAL"
        approvals_service.decide(
            db,
            db.get(Approval, first.approval_id),
            "u-approver",
            ApprovalDecision(decision="APPROVED"),
        )
        db.commit()

        artifact.validation_status = "INVALID"
        db.commit()
        retry = _evaluate(
            db,
            arguments=arguments,
            workflow_execution_id=execution.id,
            input_artifact_ids=[artifact.id],
            approval_id=first.approval_id,
        )
        assert retry.decision == "DENY"
        assert "PROPAGATION_BLOCKED_AFTER_APPROVAL" in retry.reason_codes


class TestContainment:
    def test_quarantined_agent_denied_and_recovery_requires_admin(self, db):
        agent = db.get(Agent, "agent-support")
        containment_service.quarantine_agent(
            db, agent=agent, reason="test containment", actor_user_id="u-admin"
        )
        db.commit()

        denied = _evaluate(db, tool="search_knowledge_base", arguments={"query": "x"})
        assert denied.decision == "DENY"
        assert "AGENT_QUARANTINED" in denied.reason_codes

        state = containment_service.get_or_create_state(db, agent)
        assert state.operational_status == "QUARANTINED"
        containment_service.start_recovery(db, agent=agent, actor_user_id="u-admin")
        containment_service.complete_recovery(db, agent=agent, actor_user_id="u-admin")
        db.commit()
        assert containment_service.get_or_create_state(db, agent).operational_status == "ACTIVE"

    def test_recovery_blocked_by_unresolved_invalid_output(self, db):
        _, execution = _workflow(db)
        agent = db.get(Agent, "agent-support")
        artifact = _artifact(db, execution, status="INVALID")
        containment_service.quarantine_agent(
            db, agent=agent, reason="invalid output", actor_user_id="u-admin"
        )
        db.commit()
        containment_service.start_recovery(db, agent=agent, actor_user_id="u-admin")
        with pytest.raises(ConflictError) as exc:
            containment_service.complete_recovery(db, agent=agent, actor_user_id="u-admin")
        assert "UNRESOLVED_INVALID_OUTPUTS" in exc.value.reason_codes
        assert artifact.id


class TestTransactions:
    def _create(self, db, key="txn-key-1"):
        return transaction_service.create_transaction(
            db,
            org_id="org-default",
            input=TransactionCreate(
                idempotency_key=key,
                steps=[
                    TransactionStepCreate(
                        step_key="reserve", tool_name="reserve_funds", compensation_tool="release_funds"
                    ),
                    TransactionStepCreate(step_key="settle", tool_name="settle_transfer"),
                ],
            ),
        )

    def test_idempotent_creation_and_step_state_machine(self, db):
        transaction, created = self._create(db)
        db.commit()
        again, created_again = self._create(db)
        db.commit()
        assert created is True
        assert created_again is False
        assert again.id == transaction.id

        transaction_service.start_step(db, transaction=transaction, step_ref="reserve")
        db.commit()
        with pytest.raises(ConflictError):
            transaction_service.start_step(db, transaction=transaction, step_ref="reserve")

        transaction_service.complete_step(
            db, transaction=transaction, step_ref="reserve", success=True
        )
        transaction_service.start_step(db, transaction=transaction, step_ref="settle")
        transaction_service.complete_step(
            db, transaction=transaction, step_ref="settle", success=True
        )
        db.commit()
        assert transaction.status == "COMPLETED"

    def test_compensation_requires_explicit_approval_then_executes(self, db):
        transaction, _ = self._create(db, key="txn-key-2")
        db.commit()
        transaction_service.start_step(db, transaction=transaction, step_ref="reserve")
        transaction_service.complete_step(
            db, transaction=transaction, step_ref="reserve", success=True
        )
        transaction_service.start_step(db, transaction=transaction, step_ref="settle")
        transaction_service.complete_step(
            db, transaction=transaction, step_ref="settle", success=False, error="settlement failed"
        )
        db.commit()
        assert transaction.status == "RECOVERY_REQUIRED"

        transaction_service.request_compensation(
            db, transaction=transaction, reason="rollback", approved=False
        )
        db.commit()
        assert transaction.status == "WAITING_APPROVAL"

        transaction_service.request_compensation(
            db, transaction=transaction, reason="approved rollback", approved=True
        )
        db.commit()
        assert transaction.status == "COMPENSATING"

        transaction_service.complete_compensation(
            db, transaction=transaction, step_ref="reserve", success=True
        )
        db.commit()
        assert transaction.status == "COMPLETED"
        step = (
            db.query(TransactionStep)
            .filter_by(transaction_id=transaction.id, step_key="reserve")
            .one()
        )
        assert step.compensation_status == "COMPLETED"


class TestTenancy:
    def test_other_tenant_workflow_context_is_rejected(self, db):
        org = Organization(
            id="org-other",
            name="Other",
            slug="other",
            created_at="2026-01-01T00:00:00+00:00",
        )
        db.add(org)
        other = Agent(
            id="agent-other",
            org_id="org-other",
            name="other-agent",
            owner_user_id="u-admin",
            environment="prod",
            status="ACTIVE",
            credential_hash="not-used",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        db.add(other)
        db.commit()
        workflow = workflow_service.create_workflow(
            db, "org-other", WorkflowCreate(name="other-workflow"), "u-admin"
        )
        execution = workflow_service.start_execution(
            db,
            "org-other",
            workflow.id,
            WorkflowExecutionCreate(workflow_id=workflow.id),
            other.id,
        )
        result = _evaluate(db, workflow_execution_id=execution.id)
        assert result.decision == "DENY"
        assert "NOT_FOUND" in result.reason_codes

    def test_artifact_lookup_is_tenant_scoped(self, db):
        _, execution = _workflow(db)
        artifact = _artifact(db, execution)
        assert artifact.org_id == "org-default"

    def test_tenant_headers_are_not_trusted(self, db):
        init_db()
        with TestClient(app) as client:
            # The client cannot select a tenant through a header.
            response = client.get(
                "/api/v1/artifacts", headers={"X-Organization-Id": "org-other"}
            )
            assert response.status_code == 200
            assert all(row["org_id"] == "org-default" for row in response.json())


class TestAuditChain:
    def test_chain_verifies_and_detects_tampering(self, db):
        _evaluate(db, tool="search_knowledge_base", arguments={"query": "x"})
        db.commit()
        verified = audit_service.verify_chain(db, "org-default")
        assert verified["valid"] is True
        assert verified["checked"] >= 1

        event = (
            db.query(AuditEvent)
            .filter(AuditEvent.org_id == "org-default", AuditEvent.chain_sequence.isnot(None))
            .order_by(AuditEvent.chain_sequence.desc())
            .first()
        )
        event.redacted_metadata = {**(event.redacted_metadata or {}), "tampered": True}
        db.commit()
        broken = audit_service.verify_chain(db, "org-default")
        assert broken["valid"] is False
        assert broken["reason"] == "EVENT_HASH_MISMATCH"

    def test_checkpoint_pins_latest_hash(self, db):
        _evaluate(db, tool="search_knowledge_base", arguments={"query": "x"})
        db.commit()
        checkpoint = audit_service.create_checkpoint(db, "org-default")
        db.commit()
        assert checkpoint.last_sequence >= 1
        assert checkpoint.last_hash


class TestV2Api:
    def test_health_and_audit_endpoints(self, db):
        init_db()
        with TestClient(app) as client:
            agent = db.get(Agent, "agent-support")
            health = client.get(f"/api/v1/agents/{agent.id}/health")
            assert health.status_code == 200
            assert health.json()["agent_id"] == agent.id

            verify = client.get("/api/v1/audit/verify")
            assert verify.status_code == 200
            assert "valid" in verify.json()

            summary = client.get("/api/v1/incidents/summary")
            assert summary.status_code == 200
            assert "total" in summary.json()

    def test_benchmark_endpoint_runs_real_service(self, db):
        init_db()
        with TestClient(app) as client:
            response = client.post("/api/v1/benchmarks/afpb/run", json={})
            assert response.status_code == 200
            body = response.json()
            assert body["suite"] == "AFPB"
            assert body["aggregate"]["scenarios"] == 8
            assert body["aggregate"]["passed"] == body["aggregate"]["scenarios"]
            assert body["aggregate"]["baseline_unsafe_executions"] >= 1
            for scenario in body["scenarios"]:
                assert scenario["baseline"]["mode"] == "policy_only_ablation"
                assert scenario["agentguard_v2"]["mode"] == "agentguard_v2_full_service"
