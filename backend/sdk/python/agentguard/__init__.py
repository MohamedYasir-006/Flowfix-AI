"""AgentGuard Python SDK.

Safe interception of agent tool calls: the SDK never executes a tool unless
the AgentGuard control plane returns an explicit ``ALLOW`` decision (or a
valid, unconsumed approval followed by a fresh policy check).

Basic usage::

    from agentguard import AgentGuardClient, GuardDenied, ApprovalRequired

    guard = AgentGuardClient(base_url="http://127.0.0.1:8000/api", api_key="ag_...")

    try:
        result = guard.call(
            tool="search_knowledge_base",
            arguments={"query": "refund policy"},
            execute=search_knowledge_base,
        )
    except GuardDenied as exc:
        ...
    except ApprovalRequired as exc:
        ...
"""

from .client import AgentGuardClient, Decision
from .exceptions import (
    AgentGuardError,
    ApprovalRequired,
    GuardDenied,
    GuardTransportError,
)
from .guard import call_guarded, poll_for_approval

__all__ = [
    "AgentGuardClient",
    "AgentGuardError",
    "ApprovalRequired",
    "Decision",
    "GuardDenied",
    "GuardTransportError",
    "call_guarded",
    "poll_for_approval",
]

__version__ = "0.2.0"
