"""Asynchronous client for the Ollama HTTP API.

This provider talks to a local Ollama instance over its documented HTTP API. It
does not download or load models, and it deliberately avoids any orchestration
framework: the only dependency is ``httpx``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ..schemas_llm import resolve_chat_options

DEFAULT_HEALTH_TIMEOUT_SECONDS = 10.0


class OllamaError(Exception):
    """Base class for Ollama provider failures."""


class OllamaConnectionError(OllamaError):
    """Ollama could not be reached."""


class OllamaTimeoutError(OllamaError):
    """Ollama did not respond before the configured timeout."""


class OllamaModelNotFoundError(OllamaError):
    """The configured model is not available in the local Ollama instance."""


class OllamaResponseError(OllamaError):
    """Ollama returned an error status or an unexpected payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OllamaChatResult:
    """Structured result of a non-streaming chat completion."""

    model: str
    content: str
    role: str = "assistant"
    done: bool = True
    total_duration_ns: int | None = None
    eval_count: int | None = None
    prompt_eval_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class OllamaHealth:
    """Reachability and model-availability snapshot."""

    base_url: str
    model: str
    reachable: bool
    model_available: bool
    error: str | None = None


def _normalize_model_name(name: str) -> str:
    return name.strip().lower()


def model_names_match(configured: str, candidate: str) -> bool:
    """Compare model names, treating an implicit ``:latest`` tag as equal."""
    configured_name = _normalize_model_name(configured)
    candidate_name = _normalize_model_name(candidate)
    if not configured_name or not candidate_name:
        return False
    if configured_name == candidate_name:
        return True
    if ":" not in configured_name and candidate_name == f"{configured_name}:latest":
        return True
    if ":" not in candidate_name and configured_name == f"{candidate_name}:latest":
        return True
    return False


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class OllamaProvider:
    """Thin async wrapper around the Ollama HTTP API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # An injected client is owned by the caller (used by tests). When it is
        # absent, each request creates and closes a short-lived client.
        self._client = client

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        request_timeout = self.timeout if timeout is None else timeout
        headers = {"Accept": "application/json"}
        try:
            if self._client is not None:
                response = await self._client.request(
                    method,
                    self._url(path),
                    json=json,
                    headers=headers,
                    timeout=request_timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    response = await client.request(
                        method,
                        self._url(path),
                        json=json,
                        headers=headers,
                    )
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama did not respond within {request_timeout} seconds"
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaConnectionError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc

        if response.status_code >= 400:
            detail = self._error_detail(response)
            if response.status_code == 404 and "model" in detail.lower():
                raise OllamaModelNotFoundError(detail)
            raise OllamaResponseError(detail, status_code=response.status_code)
        return response

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
        text = response.text.strip()
        return text[:500] if text else f"Ollama returned HTTP {response.status_code}"

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaResponseError("Ollama returned a malformed JSON response") from exc
        if not isinstance(payload, dict):
            raise OllamaResponseError("Ollama returned an unexpected response shape")
        return payload

    async def _fetch_models(self, timeout: float | None = None) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/tags", timeout=timeout)
        payload = self._decode(response)
        models = payload.get("models", [])
        if not isinstance(models, list):
            raise OllamaResponseError("Ollama model list was not a list")
        return [model for model in models if isinstance(model, dict)]

    async def list_models(self) -> list[dict[str, Any]]:
        return await self._fetch_models()

    async def model_exists(self) -> bool:
        models = await self.list_models()
        for model in models:
            name = model.get("name") or model.get("model")
            if isinstance(name, str) and model_names_match(self.model, name):
                return True
        return False

    async def health(self) -> OllamaHealth:
        """Return reachability and model presence without raising on failure."""
        health_timeout = min(self.timeout, DEFAULT_HEALTH_TIMEOUT_SECONDS)
        try:
            models = await self._fetch_models(timeout=health_timeout)
        except (OllamaConnectionError, OllamaTimeoutError) as exc:
            return OllamaHealth(
                base_url=self.base_url,
                model=self.model,
                reachable=False,
                model_available=False,
                error=str(exc),
            )
        except OllamaError as exc:
            # The HTTP endpoint answered, but not with a usable model list.
            return OllamaHealth(
                base_url=self.base_url,
                model=self.model,
                reachable=True,
                model_available=False,
                error=str(exc),
            )

        available = any(
            isinstance(model.get("name") or model.get("model"), str)
            and model_names_match(self.model, model.get("name") or model.get("model"))
            for model in models
        )
        return OllamaHealth(
            base_url=self.base_url,
            model=self.model,
            reachable=True,
            model_available=available,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
    ) -> OllamaChatResult:
        """Send chat messages to Ollama and return a structured result."""
        if not messages:
            raise ValueError("At least one chat message is required")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": resolve_chat_options(options),
        }

        response = await self._request("POST", "/api/chat", json=body)
        payload = self._decode(response)
        message = payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaResponseError("Ollama chat response did not include a message")

        return OllamaChatResult(
            model=str(payload.get("model") or self.model),
            content=message["content"],
            role=str(message.get("role") or "assistant"),
            done=bool(payload.get("done", True)),
            total_duration_ns=_optional_int(payload.get("total_duration")),
            eval_count=_optional_int(payload.get("eval_count")),
            prompt_eval_count=_optional_int(payload.get("prompt_eval_count")),
            raw=payload,
        )
