"""SDK exception hierarchy.

Every non-authorizing outcome — denied policy, pending approval, network
failure, malformed response — raises. Calling code must treat these as "do not
execute".
"""


class AgentGuardError(Exception):
    """Base class for all AgentGuard SDK errors."""


class GuardDenied(AgentGuardError):
    """The control plane returned ``DENY``. The tool must not execute."""

    def __init__(self, reason_codes: list[str], detail: str | None = None):
        self.reason_codes = list(reason_codes or [])
        self.detail = detail or "Action denied by AgentGuard policy"
        super().__init__(f"{self.detail} (reason_codes={','.join(self.reason_codes)})")


class ApprovalRequired(AgentGuardError):
    """The action requires human approval and has not been approved yet."""

    def __init__(self, approval_id: str, expires_at: str | None = None, detail: str | None = None):
        self.approval_id = approval_id
        self.expires_at = expires_at
        self.detail = detail or "Action requires human approval"
        super().__init__(f"{self.detail} (approval_id={approval_id})")


class GuardTransportError(AgentGuardError):
    """The control plane could not be reached or returned an invalid response.

    Transport failures are non-authorizing: the tool must not execute.
    """
