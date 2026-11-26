"""Tests for the local Ollama integration.

All HTTP traffic is mocked with ``httpx.MockTransport``; no model is loaded and
no network connection is made.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.providers.ollama import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaProvider,
    OllamaResponseError,
    OllamaTimeoutError,
)
from app.schemas_llm import (
    DEFAULT_CONTEXT_LENGTH,
    DEFAULT_TEMPERATURE,
    MAX_CONTEXT_LENGTH,
    MIN_CONTEXT_LENGTH,
    ChatMessage,
    ChatRequest,
)
from app.services import llm as llm_service

BASE = "http://ollama.test:11434"
MODEL = "fixflow-llm"


def run_with_provider(handler, action, *, timeout: float = 5.0):
    async def runner():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaProvider(BASE, MODEL, timeout, client=client)
            return await action(provider)

    return asyncio.run(runner())


def json_response(payload, request, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def provider_factory(handler):
    """Build a provider inside the caller's event loop for API tests."""

    def factory() -> OllamaProvider:
        return OllamaProvider(
            BASE,
            MODEL,
            5.0,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    return factory


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


class TestConfiguration:
    def test_ollama_environment_variables_are_read(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.test:1234")
        monkeypatch.setenv("OLLAMA_MODEL", "custom-model")
        monkeypatch.setenv("OLLAMA_TIMEOUT", "30")
        get_settings.cache_clear()
        try:
            settings = get_settings()
            assert settings.ollama_base_url == "http://example.test:1234"
            assert settings.ollama_model == "custom-model"
            assert settings.ollama_timeout == 30
        finally:
            get_settings.cache_clear()


class TestProviderChat:
    def test_chat_returns_structured_result(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return json_response(
                {
                    "model": MODEL,
                    "message": {"role": "assistant", "content": "Hello from FixFlow"},
                    "done": True,
                    "total_duration": 1234,
                    "eval_count": 12,
                    "prompt_eval_count": 8,
                },
                request,
            )

        result = run_with_provider(
            handler,
            lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
        )

        assert captured["path"] == "/api/chat"
        assert captured["body"] == {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "options": {
                "num_ctx": DEFAULT_CONTEXT_LENGTH,
                "temperature": DEFAULT_TEMPERATURE,
            },
        }
        assert result.model == MODEL
        assert result.content == "Hello from FixFlow"
        assert result.role == "assistant"
        assert result.total_duration_ns == 1234
        assert result.eval_count == 12
        assert result.prompt_eval_count == 8

    def test_chat_merges_partial_context_override(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "ok"}},
                request,
            )

        run_with_provider(
            handler,
            lambda provider: provider.chat(
                [{"role": "user", "content": "Hi"}],
                options={"num_ctx": 4096},
            ),
        )

        assert captured["body"]["options"] == {
            "num_ctx": 4096,
            "temperature": DEFAULT_TEMPERATURE,
        }

    def test_chat_merges_partial_temperature_override(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "ok"}},
                request,
            )

        run_with_provider(
            handler,
            lambda provider: provider.chat(
                [{"role": "user", "content": "Hi"}],
                options={"temperature": 0.7},
            ),
        )

        assert captured["body"]["options"] == {
            "num_ctx": DEFAULT_CONTEXT_LENGTH,
            "temperature": 0.7,
        }

    @pytest.mark.parametrize("value", [MIN_CONTEXT_LENGTH - 1, MAX_CONTEXT_LENGTH + 1])
    def test_chat_rejects_out_of_range_context_length(self, value):
        with pytest.raises(ValueError):
            run_with_provider(
                lambda request: json_response(
                    {"model": MODEL, "message": {"role": "assistant", "content": "ok"}},
                    request,
                ),
                lambda provider: provider.chat(
                    [{"role": "user", "content": "Hi"}],
                    options={"num_ctx": value},
                ),
            )

    def test_chat_rejects_non_integer_context_length(self):
        with pytest.raises(ValueError):
            run_with_provider(
                lambda request: json_response(
                    {"model": MODEL, "message": {"role": "assistant", "content": "ok"}},
                    request,
                ),
                lambda provider: provider.chat(
                    [{"role": "user", "content": "Hi"}],
                    options={"num_ctx": "8192"},
                ),
            )

    def test_chat_connection_error_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with pytest.raises(OllamaConnectionError):
            run_with_provider(
                handler,
                lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
            )

    def test_chat_timeout_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        with pytest.raises(OllamaTimeoutError):
            run_with_provider(
                handler,
                lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
            )

    def test_chat_model_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                {"error": f'model "{MODEL}" not found, try pulling it first'},
                request,
                status=404,
            )

        with pytest.raises(OllamaModelNotFoundError):
            run_with_provider(
                handler,
                lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
            )

    def test_chat_http_error_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"error": "boom"}, request, status=500)

        with pytest.raises(OllamaResponseError):
            run_with_provider(
                handler,
                lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
            )

    def test_chat_malformed_json_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json", request=request)

        with pytest.raises(OllamaResponseError):
            run_with_provider(
                handler,
                lambda provider: provider.chat([{"role": "user", "content": "Hi"}]),
            )


class TestProviderHealth:
    def test_health_reports_reachable_and_model_present(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                {"models": [{"name": f"{MODEL}:latest", "model": f"{MODEL}:latest"}]},
                request,
            )

        result = run_with_provider(handler, lambda provider: provider.health())

        assert result.reachable is True
        assert result.model_available is True
        assert result.error is None

    def test_health_reports_missing_model(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"models": [{"name": "other-model:latest"}]}, request)

        result = run_with_provider(handler, lambda provider: provider.health())

        assert result.reachable is True
        assert result.model_available is False

    def test_health_reports_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        result = run_with_provider(handler, lambda provider: provider.health())

        assert result.reachable is False
        assert result.model_available is False
        assert result.error


class TestLlmService:
    def test_service_chat_builds_system_message_and_returns_structured_response(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "done"}},
                request,
            )

        async def runner():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                provider = OllamaProvider(BASE, MODEL, 5.0, client=http)
                return await llm_service.chat(
                    ChatRequest(
                        system="Be concise.",
                        messages=[ChatMessage(role="user", content="Hello")],
                    ),
                    provider=provider,
                )

        response = asyncio.run(runner())

        assert captured["body"]["messages"] == [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ]
        assert captured["body"]["options"] == {
            "num_ctx": DEFAULT_CONTEXT_LENGTH,
            "temperature": DEFAULT_TEMPERATURE,
        }
        assert response.message.role == "assistant"
        assert response.message.content == "done"

    def test_service_chat_forwards_valid_options(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "done"}},
                request,
            )

        async def runner():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                provider = OllamaProvider(BASE, MODEL, 5.0, client=http)
                return await llm_service.chat(
                    ChatRequest(
                        messages=[ChatMessage(role="user", content="Hello")],
                        options={"num_ctx": 4096, "temperature": 0.5},
                    ),
                    provider=provider,
                )

        response = asyncio.run(runner())

        assert captured["body"]["options"] == {
            "num_ctx": 4096,
            "temperature": 0.5,
        }
        assert response.message.content == "done"

    def test_service_health_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"models": [{"name": MODEL}]}, request)

        async def runner():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                provider = OllamaProvider(BASE, MODEL, 5.0, client=http)
                return await llm_service.health(provider=provider)

        response = asyncio.run(runner())

        assert response.status == "ok"
        assert response.reachable is True
        assert response.model_available is True


class TestOllamaApi:
    def test_health_endpoint(self, client, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response({"models": [{"name": MODEL}]}, request)

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.get("/api/v1/ollama/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["model"] == MODEL
        assert body["model_available"] is True

    def test_health_endpoint_reports_unreachable(self, client, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.get("/api/v1/ollama/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["reachable"] is False
        assert body["error"]

    def test_chat_endpoint(self, client, monkeypatch):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "Hi!"}},
                request,
            )

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.post(
            "/api/v1/ollama/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["model"] == MODEL
        assert body["message"] == {"role": "assistant", "content": "Hi!"}
        assert captured["body"]["options"] == {
            "num_ctx": DEFAULT_CONTEXT_LENGTH,
            "temperature": DEFAULT_TEMPERATURE,
        }

    def test_chat_endpoint_accepts_valid_override(self, client, monkeypatch):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return json_response(
                {"model": MODEL, "message": {"role": "assistant", "content": "Hi!"}},
                request,
            )

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.post(
            "/api/v1/ollama/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "options": {"num_ctx": 4096, "temperature": 0.4},
            },
        )

        assert response.status_code == 200
        assert captured["body"]["options"] == {
            "num_ctx": 4096,
            "temperature": 0.4,
        }

    @pytest.mark.parametrize(
        "num_ctx",
        [MIN_CONTEXT_LENGTH - 1, MAX_CONTEXT_LENGTH + 1, "8192"],
    )
    def test_chat_endpoint_rejects_invalid_context_override(
        self, client, monkeypatch, num_ctx
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("invalid options must not reach Ollama")

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.post(
            "/api/v1/ollama/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "options": {"num_ctx": num_ctx},
            },
        )

        assert response.status_code == 422

    def test_chat_endpoint_maps_connection_error(self, client, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.post(
            "/api/v1/ollama/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert response.status_code == 503
        assert response.json()["reason_codes"] == ["OLLAMA_UNAVAILABLE"]

    def test_chat_endpoint_maps_timeout(self, client, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        monkeypatch.setattr(llm_service, "get_provider", provider_factory(handler))

        response = client.post(
            "/api/v1/ollama/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert response.status_code == 504
        assert response.json()["reason_codes"] == ["OLLAMA_TIMEOUT"]
