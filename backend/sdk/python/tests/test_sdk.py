"""Security tests for the AgentGuard SDK.

The SDK is the enforcement boundary an agent actually calls, so these tests
prove the fail-closed contract: transport errors, malformed responses, and
pending approvals must never look like authorization.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agentguard import (
    AgentGuardClient,
    ApprovalRequired,
    GuardDenied,
    GuardTransportError,
    call_guarded,
    poll_for_approval,
)

BASE = "http://127.0.0.1:9999/api"  # nothing listens here; used for failure paths


def make_client(handler, base_url="http://127.0.0.1:8000/api", api_key="ag_test"):
    """Build a client whose transport is replaced by a stub handler."""
    client = AgentGuardClient(base_url=base_url, api_key=api_key)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def json_response(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://x"))


class TestDecisionParsing:
    def test_allow_payload(self):
        client = make_client(
            lambda request: json_response(
                {
                    "action_id": "act-1",
                    "decision": "ALLOW",
                    "risk": {"level": "LOW", "reasons": ["DATA_ACCESS"]},
                    "reason_codes": ["TOOL_REGISTERED"],
                    "policy": {"id": "p1", "version": 2},
                }
            )
        )
        decision = client.evaluate(tool="search_knowledge_base", arguments={"query": "x"})
        assert decision.allowed is True
        assert decision.denied is False
        assert decision.requires_approval is False
        assert decision.action_id == "act-1"
        assert decision.policy_version == 2

    def test_deny_payload(self):
        client = make_client(
            lambda request: json_response(
                {
                    "action_id": "act-2",
                    "decision": "DENY",
                    "risk": {"level": "CRITICAL", "reasons": ["DESTRUCTIVE_OPERATION"]},
                    "reason_codes": ["EXPLICIT_DENY_RULE"],
                    "policy": None,
                }
            )
        )
        decision = client.evaluate(tool="delete_customer_record", arguments={})
        assert decision.denied is True

    def test_approval_payload(self):
        client = make_client(
            lambda request: json_response(
                {
                    "action_id": "act-3",
                    "decision": "REQUIRE_APPROVAL",
                    "risk": {"level": "HIGH", "reasons": []},
                    "reason_codes": ["POLICY_APPROVAL_REQUIRED"],
                    "policy": {"id": "p1", "version": 3},
                    "approval_id": "ap-9",
                    "expires_at": "2026-01-01T00:00:00+00:00",
                }
            )
        )
        decision = client.evaluate(tool="send_email", arguments={})
        assert decision.requires_approval is True
        assert decision.approval_id == "ap-9"


class TestFailClosed:
    def test_connection_error_raises_transport_error(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        client = make_client(handler)
        with pytest.raises(GuardTransportError):
            client.evaluate(tool="search_knowledge_base", arguments={})

    def test_timeout_raises_transport_error(self):
        def handler(request):
            raise httpx.TimeoutException("timed out", request=request)

        client = make_client(handler)
        with pytest.raises(GuardTransportError):
            client.evaluate(tool="search_knowledge_base", arguments={})

    def test_http_error_status_raises(self):
        client = make_client(lambda request: json_response({"detail": "boom"}, status=500))
        with pytest.raises(GuardTransportError):
            client.evaluate(tool="search_knowledge_base", arguments={})

    def test_malformed_json_raises(self):
        client = make_client(
            lambda request: httpx.Response(
                200, content=b"not json", request=httpx.Request("POST", "http://x")
            )
        )
        with pytest.raises(GuardTransportError):
            client.evaluate(tool="search_knowledge_base", arguments={})

    def test_missing_action_id_raises(self):
        client = make_client(lambda request: json_response({"decision": "ALLOW"}))
        with pytest.raises(KeyError):
            client.evaluate(tool="search_knowledge_base", arguments={})


class TestCallGuarded:
    def test_denied_never_executes(self):
        client = make_client(
            lambda request: json_response(
                {
                    "action_id": "act-1",
                    "decision": "DENY",
                    "risk": {"level": "CRITICAL", "reasons": []},
                    "reason_codes": ["EXPLICIT_DENY_RULE"],
                    "policy": None,
                }
            )
        )
        executed = []
        with pytest.raises(GuardDenied):
            call_guarded(
                client,
                "delete_customer_record",
                {"customer_id": "c1"},
                execute=lambda **kwargs: executed.append(kwargs),
            )
        assert executed == []

    def test_pending_approval_never_executes(self):
        client = make_client(
            lambda request: json_response(
                {
                    "action_id": "act-1",
                    "decision": "REQUIRE_APPROVAL",
                    "risk": {"level": "HIGH", "reasons": []},
                    "reason_codes": ["POLICY_APPROVAL_REQUIRED"],
                    "policy": None,
                    "approval_id": "ap-1",
                }
            )
        )
        executed = []
        with pytest.raises(ApprovalRequired):
            call_guarded(
                client,
                "send_email",
                {"to": "x@example.com"},
                execute=lambda **kwargs: executed.append(kwargs),
            )
        assert executed == []

    def test_allowed_executes_and_reports(self):
        calls = {"evaluate": 0, "report": 0}

        def handler(request):
            if request.url.path.endswith("/decisions/evaluate"):
                calls["evaluate"] += 1
                return json_response(
                    {
                        "action_id": "act-1",
                        "decision": "ALLOW",
                        "risk": {"level": "LOW", "reasons": []},
                        "reason_codes": ["TOOL_REGISTERED"],
                        "policy": None,
                    }
                )
            calls["report"] += 1
            return json_response({"id": "evt-1", "event_type": "execution"})

        client = make_client(handler)
        executed = []
        result = call_guarded(
            client,
            "search_knowledge_base",
            {"query": "x"},
            execute=lambda **kwargs: executed.append(kwargs) or "ok",
        )
        assert result == "ok"
        assert executed == [{"query": "x"}]
        assert calls["report"] == 1

    def test_execution_failure_is_reported(self):
        reported = []

        def handler(request):
            if request.url.path.endswith("/decisions/evaluate"):
                return json_response(
                    {
                        "action_id": "act-1",
                        "decision": "ALLOW",
                        "risk": {"level": "LOW", "reasons": []},
                        "reason_codes": [],
                        "policy": None,
                    }
                )
            reported.append(json.loads(request.content))
            return json_response({"id": "evt-1"})

        client = make_client(handler)

        def boom(**kwargs):
            raise RuntimeError("tool exploded")

        with pytest.raises(RuntimeError):
            call_guarded(client, "search_knowledge_base", {"query": "x"}, execute=boom)

        assert reported[0]["success"] is False
        assert "tool exploded" in reported[0]["error"]

    def test_transport_failure_does_not_execute(self):
        def handler(request):
            raise httpx.ConnectError("down", request=request)

        client = make_client(handler)
        executed = []
        with pytest.raises(GuardTransportError):
            call_guarded(
                client,
                "search_knowledge_base",
                {"query": "x"},
                execute=lambda **kwargs: executed.append(kwargs),
            )
        assert executed == []


class TestApprovalPolling:
    def test_poll_returns_true_when_approved(self):
        client = make_client(
            lambda request: json_response({"id": "ap-1", "status": "APPROVED"})
        )
        assert poll_for_approval(client, "ap-1", interval=0.01) is True

    def test_poll_returns_false_when_rejected(self):
        client = make_client(
            lambda request: json_response({"id": "ap-1", "status": "REJECTED"})
        )
        assert poll_for_approval(client, "ap-1", interval=0.01) is False

    def test_poll_returns_false_on_timeout(self):
        client = make_client(
            lambda request: json_response({"id": "ap-1", "status": "PENDING"})
        )
        assert poll_for_approval(client, "ap-1", interval=0.01, timeout=0.05) is False


class TestBaseUrlNormalization:
    def test_trailing_slash_and_version(self):
        client = AgentGuardClient(base_url="http://x/api/", api_key="ag_k")
        assert client.base_url == "http://x/api/v1"

    def test_existing_version_not_duplicated(self):
        client = AgentGuardClient(base_url="http://x/api/v1", api_key="ag_k")
        assert client.base_url == "http://x/api/v1"
