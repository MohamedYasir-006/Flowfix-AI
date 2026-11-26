"""Local LLM service: chat orchestration on top of the Ollama provider."""

from __future__ import annotations

from ..config import get_settings
from ..providers.ollama import OllamaProvider
from ..schemas_llm import ChatMessage, ChatRequest, ChatResponse, OllamaHealthResponse


def get_provider() -> OllamaProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout=settings.ollama_timeout,
    )


def _provider_messages(request: ChatRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.extend({"role": message.role, "content": message.content} for message in request.messages)
    return messages


async def chat(
    request: ChatRequest,
    *,
    provider: OllamaProvider | None = None,
) -> ChatResponse:
    """Send chat messages through Ollama and return a structured response."""
    active_provider = provider or get_provider()
    result = await active_provider.chat(
        _provider_messages(request),
        options=request.options,
    )
    return ChatResponse(
        model=result.model,
        message=ChatMessage(role=result.role, content=result.content),
        done=result.done,
        total_duration_ns=result.total_duration_ns,
        eval_count=result.eval_count,
        prompt_eval_count=result.prompt_eval_count,
    )


async def health(*, provider: OllamaProvider | None = None) -> OllamaHealthResponse:
    """Check whether Ollama is reachable and the configured model is present."""
    active_provider = provider or get_provider()
    result = await active_provider.health()
    healthy = result.reachable and result.model_available
    return OllamaHealthResponse(
        status="ok" if healthy else "unavailable",
        base_url=result.base_url,
        model=result.model,
        reachable=result.reachable,
        model_available=result.model_available,
        error=result.error,
    )
