"""FixFlow AI workflow tests.

The local model call is always mocked; deterministic safety and verification
are tested directly and through the HTTP API.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Artifact, AuditEvent, WorkflowExecution
from app.services import fixflow as fixflow_service

NORMAL = {
    "temperature_c": 66.8,
    "vibration_mm_s": 2.1,
    "pressure_bar": 6.4,
    "flow_m3h": 118.0,
}
WARNING = {
    "temperature_c": 84.2,
    "vibration_mm_s": 5.8,
    "pressure_bar": 5.4,
    "flow_m3h": 96.0,
}
CRITICAL = {
    "temperature_c": 97.6,
    "vibration_mm_s": 12.1,
    "pressure_bar": 5.8,
    "flow_m3h": 78.0,
}


@pytest.fixture()
def client(db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    async def no_model(equipment, readings, inspection):
        return None

    monkeypatch.setattr(fixflow_service, "_try_llm_diagnosis", no_model)


def create_run(client, equipment_id: str, readings: dict, **extra):
    response = client.post(
        "/api/v1/fixflow/runs",
        json={"equipment_id": equipment_id, "readings": readings, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestCatalog:
    def test_equipment_and_knowledge_are_listed(self, client):
        equipment = client.get("/api/v1/fixflow/equipment")
        assert equipment.status_code == 200
        ids = {item["id"] for item in equipment.json()}
        assert {"pump-p101", "pump-p202", "pump-p303"} <= ids

        knowledge = client.get("/api/v1/fixflow/knowledge")
        assert knowledge.status_code == 200
        assert any(doc["id"] == "kb-bearing-vibration" for doc in knowledge.json())


class TestDeterministicSafety:
    def test_warning_readings_require_approval(self, client):
        run = create_run(client, "pump-p101", WARNING)
        assert run["safety"]["decision"] == "REQUIRE_APPROVAL"
        assert "TEMPERATURE_ELEVATED" in run["safety"]["reason_codes"]
        assert "VIBRATION_ELEVATED" in run["safety"]["reason_codes"]
        assert run["status"] == "AWAITING_APPROVAL"
        assert len(run["agents"]) == 7

    def test_critical_readings_are_blocked(self, client):
        run = create_run(client, "pump-p202", CRITICAL)
        assert run["safety"]["decision"] == "BLOCK"
        assert "HIGH_TEMPERATURE" in run["safety"]["reason_codes"]
        assert "HIGH_VIBRATION" in run["safety"]["reason_codes"]
        assert run["status"] == "BLOCKED"
        assert run["plan"]["safety_gate"] == "BLOCK"

    def test_normal_readings_are_allowed(self, client):
        run = create_run(client, "pump-p303", NORMAL)
        assert run["safety"]["decision"] == "ALLOW"
        assert run["status"] == "AWAITING_VERIFICATION"

    def test_llm_severity_cannot_override_safety(self, client, monkeypatch):
        async def critical_model(equipment, readings, inspection):
            return {
                "summary": "Model claims catastrophic failure",
                "severity": "CRITICAL",
                "hypotheses": [
                    {
                        "fault": "Catastrophic bearing failure",
                        "likelihood": 1.0,
                        "evidence": ["model claim"],
                        "recommended_checks": ["stop"],
                        "source": "ollama",
                    }
                ],
                "model": "fixflow-llm",
            }

        monkeypatch.setattr(fixflow_service, "_try_llm_diagnosis", critical_model)
        run = create_run(client, "pump-p303", NORMAL)
        assert run["diagnosis"]["severity"] == "CRITICAL"
        assert run["diagnosis"]["source"] == "ollama+deterministic"
        assert run["safety"]["decision"] == "ALLOW"
        assert run["safety"]["llm_can_override"] is False

    def test_simulated_inspection_is_labelled_and_ignored_by_safety(self, client):
        run = create_run(
            client,
            "pump-p303",
            NORMAL,
            image_name="pump.jpg",
            image_size=2048,
        )
        assert run["inspection"]["simulated"] is True
        assert run["inspection"]["model_invoked"] is False
        assert "SIMULATED" in run["inspection"]["message"]
        assert run["safety"]["inspection_used"] is False
        assert "SIMULATED_INSPECTION_IGNORED" in run["safety"]["reason_codes"]
        assert any(
            rule["result"] == "IGNORED" for rule in run["safety"]["rules"]
        )


class TestPersistence:
    def test_run_creates_provenance_artifacts(self, client, db):
        run = create_run(client, "pump-p303", NORMAL)
        artifacts = db.execute(
            select(Artifact).where(Artifact.workflow_execution_id == run["id"])
        ).scalars().all()
        assert len(artifacts) >= 7
        assert all(item.integrity_hash.startswith("sha256:") for item in artifacts)
        assert any(item.artifact_type == "fault_diagnosis" for item in artifacts)
        assert any(item.artifact_type == "safety_validation" for item in artifacts)

        events = db.execute(
            select(AuditEvent).where(
                AuditEvent.event_type == "decision",
                AuditEvent.action_id == run["id"],
            )
        ).scalars().all()
        assert events
        assert events[0].decision == "ALLOW"


class TestVerification:
    def test_passing_verification_closes_run(self, client, db):
        run = create_run(client, "pump-p303", NORMAL)
        response = client.post(
            f"/api/v1/fixflow/runs/{run['id']}/verify",
            json={"readings": NORMAL, "notes": "post-maintenance check"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verification"]["result"] == "PASS"
        assert body["status"] == "VERIFIED"
        assert body["diagnosis_reopened"] is False
        verification_agent = next(
            item for item in body["agents"] if item["role"] == "verification"
        )
        assert verification_agent["status"] == "COMPLETED"
        assert verification_agent["artifact_id"] == body["verification"]["artifact_id"]

        execution = db.get(WorkflowExecution, run["id"])
        assert execution is not None
        assert execution.status == "COMPLETED"

    def test_failing_verification_reopens_diagnosis(self, client, db):
        run = create_run(client, "pump-p303", NORMAL)
        response = client.post(
            f"/api/v1/fixflow/runs/{run['id']}/verify",
            json={"readings": CRITICAL, "notes": "vibration persists"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verification"]["result"] == "FAIL"
        assert body["status"] == "VERIFICATION_FAILED"
        assert body["diagnosis_reopened"] is True
        assert body["reopened_diagnosis"] is not None
        assert body["reopened_diagnosis"]["severity"] == "CRITICAL"
        verification_agent = next(
            item for item in body["agents"] if item["role"] == "verification"
        )
        assert verification_agent["status"] == "FAILED"
        assert verification_agent["artifact_id"] == body["verification"]["artifact_id"]

        execution = db.get(WorkflowExecution, run["id"])
        assert execution is not None
        assert execution.status == "FAILED"
