"""Local Ollama integration endpoints: health check and chat test."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..errors import ApiError
from ..models import User
from ..providers.ollama import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from ..schemas_llm import ChatRequest, ChatResponse, OllamaHealthResponse
from ..services import llm as llm_service

router = APIRouter(prefix="/ollama", tags=["ollama"])


@router.get("/health", response_model=OllamaHealthResponse)
async def ollama_health() -> OllamaHealthResponse:
    """Report whether Ollama is reachable and the configured model exists."""
    return await llm_service.health()


@router.post("/chat", response_model=ChatResponse)
async def ollama_chat(
    input: ChatRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """Send chat messages to the configured local model and return its reply."""
    try:
        return await llm_service.chat(input)
    except OllamaTimeoutError as exc:
        raise ApiError(
            "Ollama request timed out",
            status_code=504,
            reason_codes=["OLLAMA_TIMEOUT"],
        ) from exc
    except OllamaConnectionError as exc:
        raise ApiError(
            "Ollama is not reachable",
            status_code=503,
            reason_codes=["OLLAMA_UNAVAILABLE"],
        ) from exc
    except OllamaModelNotFoundError as exc:
        raise ApiError(
            str(exc),
            status_code=404,
            reason_codes=["OLLAMA_MODEL_NOT_FOUND"],
        ) from exc
    except OllamaResponseError as exc:
        raise ApiError(
            str(exc),
            status_code=502,
            reason_codes=["OLLAMA_BAD_RESPONSE"],
        ) from exc
