"""Request/response contracts for the local LLM integration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ChatRole = Literal["system", "user", "assistant"]

DEFAULT_CONTEXT_LENGTH = 2048
DEFAULT_TEMPERATURE = 0.2
MIN_CONTEXT_LENGTH = 128
# Keep the ceiling conservative for the 8 GB local target. Larger contexts
# increase KV-cache memory use substantially.
MAX_CONTEXT_LENGTH = 8192
MAX_TEMPERATURE = 2.0


def validate_context_length(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("num_ctx must be an integer")
    if not MIN_CONTEXT_LENGTH <= value <= MAX_CONTEXT_LENGTH:
        raise ValueError(
            f"num_ctx must be between {MIN_CONTEXT_LENGTH} and "
            f"{MAX_CONTEXT_LENGTH} tokens"
        )
    return value


def validate_temperature(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("temperature must be a number")
    numeric = float(value)
    if not 0.0 <= numeric <= MAX_TEMPERATURE:
        raise ValueError(f"temperature must be between 0.0 and {MAX_TEMPERATURE}")
    return numeric


def resolve_chat_options(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Merge explicit overrides over the safe local-model defaults."""
    options: dict[str, Any] = {
        "num_ctx": DEFAULT_CONTEXT_LENGTH,
        "temperature": DEFAULT_TEMPERATURE,
    }
    if not overrides:
        return options

    options.update(overrides)
    if "num_ctx" in overrides:
        options["num_ctx"] = validate_context_length(overrides["num_ctx"])
    if "temperature" in overrides:
        options["temperature"] = validate_temperature(overrides["temperature"])
    return options


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    system: str | None = None
    # Explicit Ollama option overrides, merged over the safe defaults
    # (``num_ctx=2048``, ``temperature=0.2``).
    options: dict[str, Any] | None = None

    @field_validator("options")
    @classmethod
    def _validate_options(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            resolve_chat_options(value)
        return value


class ChatResponse(BaseModel):
    model: str
    message: ChatMessage
    done: bool = True
    total_duration_ns: int | None = None
    eval_count: int | None = None
    prompt_eval_count: int | None = None


class OllamaHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    base_url: str
    model: str
    reachable: bool
    model_available: bool
    error: str | None = None
