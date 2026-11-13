"""HTTP client for the AgentGuard control plane.

The client is fail-closed: any transport error, timeout, or malformed response
raises :class:`GuardTransportError`, which callers must treat as
"do not execute".
"""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx

from .exceptions import GuardTransportError


@dataclasses.dataclass
class Decision:
    action_id: str
    status: str
    reason_codes: list[str] = dataclasses.field(default_factory=list)
    risk_level: str = "MEDIUM"
    risk_reasons: list[str] = dataclasses.field(default_factory=list)
    policy_id: str | None = None
    policy_version: int | None = None
    approval_id: str | None = None
    expires_at: str | None = None
    # V2 explainability (optional for backward compatibility).
    explanation: str = ""
    risk_score: int | None = None
    risk_assessment_id: str | None = None
    propagation: dict[str, Any] | None = None
    operational_status: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "ALLOW"

    @property
    def denied(self) -> bool:
        return self.status == "DENY"

    @property
    def requires_approval(self) -> bool:
        return self.status == "REQUIRE_APPROVAL"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Decision":
        risk = payload.get("risk") or {}
        policy = payload.get("policy")
        return cls(
            action_id=str(payload["action_id"]),
            status=str(payload["decision"]),
            reason_codes=list(payload.get("reason_codes") or []),
            risk_level=str(risk.get("level", "MEDIUM")),
            risk_reasons=list(risk.get("reasons") or []),
            policy_id=policy.get("id") if policy else None,
            policy_version=policy.get("version") if policy else None,
            approval_id=payload.get("approval_id"),
            expires_at=payload.get("expires_at"),
            explanation=str(payload.get("explanation") or ""),
            risk_score=payload.get("risk_score"),
            risk_assessment_id=payload.get("risk_assessment_id"),
            propagation=payload.get("propagation"),
            operational_status=payload.get("operational_status"),
        )


def _normalize_base_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


class AgentGuardClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={"X-Agent-Key": api_key, "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AgentGuardClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GuardTransportError(
                f"Cannot reach AgentGuard at {self.base_url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise GuardTransportError(
                f"AgentGuard returned {response.status_code}: {response.text[:500]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GuardTransportError("AgentGuard returned a malformed response") from exc

    def evaluate(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        target: str | None = None,
        session_id: str | None = None,
        environment: str | None = None,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
        agent_id: str | None = None,
        workflow_execution_id: str | None = None,
        agent_execution_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
    ) -> Decision:
        body: dict[str, Any] = {"tool": tool, "arguments": arguments or {}}
        for key, value in {
            "target": target,
            "session_id": session_id,
            "environment": environment,
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
            "agent_id": agent_id,
            "workflow_execution_id": workflow_execution_id,
            "agent_execution_id": agent_execution_id,
        }.items():
            if value is not None:
                body[key] = value
        if input_artifact_ids:
            body["input_artifact_ids"] = list(input_artifact_ids)
        return Decision.from_payload(self._request("POST", "/decisions/evaluate", json=body))

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        return self._request("GET", f"/approvals/{approval_id}")

    def report_result(
        self,
        action_id: str,
        success: bool,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"success": success}
        if error is not None:
            body["error"] = error
        if duration_ms is not None:
            body["duration_ms"] = duration_ms
        return self._request("POST", f"/actions/{action_id}/result", json=body)

    # ------------------------------------------------------------------
    # V2 workflow, provenance, and operational intelligence
    # ------------------------------------------------------------------

    def create_workflow(
        self, name: str, description: str = "", metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/workflows",
            json={"name": name, "description": description, "metadata": metadata or {}},
        )

    def list_workflows(self) -> list[dict[str, Any]]:
        return self._request("GET", "/workflows")

    def start_workflow_execution(
        self,
        workflow_id: str,
        external_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"workflow_id": workflow_id, "metadata": metadata or {}}
        if external_key is not None:
            body["external_key"] = external_key
        return self._request("POST", f"/workflows/{workflow_id}/executions", json=body)

    def start_agent_execution(
        self, workflow_execution_id: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/workflow-executions/{workflow_execution_id}/agent-executions",
            json={
                "workflow_execution_id": workflow_execution_id,
                "metadata": metadata or {},
            },
        )

    def complete_agent_execution(
        self,
        agent_execution_id: str,
        status: str = "COMPLETED",
        error: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/agent-executions/{agent_execution_id}/complete",
            json={"status": status, "error": error},
        )

    def workflow_graph(self, workflow_execution_id: str) -> dict[str, Any]:
        return self._request("GET", f"/workflow-executions/{workflow_execution_id}/graph")

    def workflow_timeline(self, workflow_execution_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/workflow-executions/{workflow_execution_id}/timeline")

    def record_artifact(
        self,
        artifact_type: str,
        name: str = "",
        content: Any = None,
        workflow_execution_id: str | None = None,
        agent_execution_id: str | None = None,
        parent_artifact_ids: list[str] | None = None,
        expires_at: str | None = None,
        trust_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/artifacts",
            json={
                "artifact_type": artifact_type,
                "name": name,
                "content": content,
                "workflow_execution_id": workflow_execution_id,
                "agent_execution_id": agent_execution_id,
                "parent_artifact_ids": parent_artifact_ids or [],
                "expires_at": expires_at,
                "trust_metadata": trust_metadata or {},
            },
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/artifacts/{artifact_id}")

    def validate_artifact(
        self,
        artifact_id: str,
        configs: list[dict[str, Any]] | None = None,
        mode: str = "configured",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"mode": mode}
        if configs is not None:
            body["configs"] = configs
        return self._request("POST", f"/artifacts/{artifact_id}/validate", json=body)

    def verify_artifact(self, artifact_id: str, verified: bool, note: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/artifacts/{artifact_id}/verify",
            json={"verified": verified, "note": note},
        )

    def record_consumption(
        self,
        workflow_execution_id: str,
        artifact_ids: list[str],
        agent_execution_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/artifacts/consumption",
            json={
                "workflow_execution_id": workflow_execution_id,
                "artifact_ids": artifact_ids,
                "agent_execution_id": agent_execution_id,
            },
        )

    def add_dependency(self, **fields: Any) -> dict[str, Any]:
        return self._request("POST", "/dependencies", json=fields)

    def artifact_lineage(self, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/artifacts/{artifact_id}/lineage")

    def downstream_impact(
        self,
        agent_id: str | None = None,
        artifact_id: str | None = None,
        failure_type: str = "INVALID_OUTPUT",
    ) -> dict[str, Any]:
        params = []
        if agent_id:
            params.append(f"agent_id={agent_id}")
        if artifact_id:
            params.append(f"artifact_id={artifact_id}")
        params.append(f"failure_type={failure_type}")
        return self._request("GET", f"/dependencies/impact?{'&'.join(params)}")

    def preview_risk(self, **fields: Any) -> dict[str, Any]:
        """Read-only risk preview; never authorizes an action."""
        return self._request("POST", "/risk/evaluate", json=fields)

    def agent_health(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/agents/{agent_id}/health")

    def agent_reliability(self, agent_id: str, window_days: int | None = None) -> dict[str, Any]:
        suffix = f"?window_days={window_days}" if window_days else ""
        return self._request("GET", f"/agents/{agent_id}/reliability{suffix}")

    def list_incidents(self, status: str | None = None) -> list[dict[str, Any]]:
        suffix = f"?status={status}" if status else ""
        return self._request("GET", f"/incidents{suffix}")

    def incident_report(self, incident_id: str) -> dict[str, Any]:
        return self._request("GET", f"/incidents/{incident_id}/report")

    def what_if(self, action_id: str, hypothetical_decision: str = "ALLOW") -> dict[str, Any]:
        return self._request(
            "POST",
            "/incidents/what-if",
            json={"action_id": action_id, "hypothetical_decision": hypothetical_decision},
        )

    def create_transaction(
        self,
        steps: list[dict[str, Any]],
        workflow_execution_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/transactions",
            json={
                "steps": steps,
                "workflow_execution_id": workflow_execution_id,
                "idempotency_key": idempotency_key,
                "metadata": metadata or {},
            },
        )

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        return self._request("GET", f"/transactions/{transaction_id}")

    def start_transaction_step(
        self, transaction_id: str, step_ref: str, action_id: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/transactions/{transaction_id}/steps/{step_ref}/start",
            json={"action_id": action_id},
        )

    def complete_transaction_step(
        self,
        transaction_id: str,
        step_ref: str,
        success: bool,
        action_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/transactions/{transaction_id}/steps/{step_ref}/complete",
            json={"success": success, "action_id": action_id, "error": error},
        )

    def compensation_plan(self, transaction_id: str) -> dict[str, Any]:
        return self._request("GET", f"/transactions/{transaction_id}/recovery-plan")

    def verify_audit_chain(self) -> dict[str, Any]:
        return self._request("GET", "/audit/verify")

    def run_afpb_benchmark(
        self,
        scenarios: list[str] | None = None,
        seed: int = 7,
        repetitions: int = 1,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/benchmarks/afpb/run",
            json={
                "suite": "AFPB",
                "scenarios": scenarios,
                "seed": seed,
                "repetitions": repetitions,
            },
        )
