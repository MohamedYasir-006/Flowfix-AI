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

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
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
    ) -> Decision:
        body: dict[str, Any] = {"tool": tool, "arguments": arguments or {}}
        for key, value in {
            "target": target,
            "session_id": session_id,
            "environment": environment,
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
            "agent_id": agent_id,
        }.items():
            if value is not None:
                body[key] = value
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
