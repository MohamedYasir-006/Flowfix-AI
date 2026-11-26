"""LLM provider integrations.

Providers own transport concerns (HTTP, timeouts, error mapping). Application
orchestration lives in ``app.services`` so routers stay thin.
"""

from .ollama import OllamaProvider  # noqa: F401  (re-exported for convenience)
