"""High-level guarded execution helpers.

``call_guarded`` is the recommended integration point. It executes the wrapped
tool only after an explicit ``ALLOW`` decision, and — when ``approval_timeout``
is set — polls for approval and re-evaluates before executing exactly once.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .client import AgentGuardClient, Decision
from .exceptions import ApprovalRequired, GuardDenied


def poll_for_approval(
    client: AgentGuardClient,
    approval_id: str,
    interval: float = 2.0,
    timeout: float = 0.0,
) -> bool:
    """Poll an approval until it is decided or the timeout elapses.

    Returns ``True`` only when the approval reaches ``APPROVED``. Rejected,
    expired, consumed, or timed-out approvals return ``False``.
    """
    deadline = time.monotonic() + timeout if timeout > 0 else None
    while True:
        approval = client.get_approval(approval_id)
        status = str(approval.get("status", "")).upper()
        if status == "APPROVED":
            return True
        if status in {"REJECTED", "EXPIRED", "CONSUMED"}:
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def call_guarded(
    client: AgentGuardClient,
    tool: str,
    arguments: dict[str, Any] | None = None,
    target: str | None = None,
    session_id: str | None = None,
    execute: Callable[..., Any] | None = None,
    environment: str | None = None,
    idempotency_key: str | None = None,
    on_approval_required: Callable[[Decision], None] | None = None,
    approval_timeout: float = 0.0,
    poll_interval: float = 2.0,
) -> Any:
    """Evaluate a tool call, then execute it only when authorized.

    - ``DENY`` raises :class:`GuardDenied`.
    - ``REQUIRE_APPROVAL`` raises :class:`ApprovalRequired` unless an
      ``approval_timeout`` is given, in which case the approval is polled and,
      once granted, the action is re-evaluated and executed once.
    - ``ALLOW`` executes ``execute(**arguments)`` when supplied and reports the
      result back to the control plane.
    """
    arguments = arguments or {}
    decision = client.evaluate(
        tool=tool,
        arguments=arguments,
        target=target,
        session_id=session_id,
        environment=environment,
        idempotency_key=idempotency_key,
    )

    if decision.denied:
        raise GuardDenied(decision.reason_codes)

    if decision.requires_approval:
        if on_approval_required is not None:
            on_approval_required(decision)
        if execute is None:
            raise ApprovalRequired(decision.approval_id or "", decision.expires_at)
        if approval_timeout <= 0:
            raise ApprovalRequired(decision.approval_id or "", decision.expires_at)

        if not poll_for_approval(
            client, decision.approval_id or "", interval=poll_interval, timeout=approval_timeout
        ):
            raise ApprovalRequired(decision.approval_id or "", decision.expires_at)

        # Fresh policy check after approval; the server consumes the approval.
        decision = client.evaluate(
            tool=tool,
            arguments=arguments,
            target=target,
            session_id=session_id,
            environment=environment,
            approval_id=decision.approval_id,
            idempotency_key=idempotency_key,
        )
        if decision.denied:
            raise GuardDenied(decision.reason_codes)
        if decision.requires_approval:
            raise ApprovalRequired(decision.approval_id or "", decision.expires_at)

    if execute is None:
        return decision

    started = time.monotonic()
    try:
        result = execute(**arguments)
    except Exception as exc:
        client.report_result(
            decision.action_id,
            success=False,
            error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise

    client.report_result(
        decision.action_id,
        success=True,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return result
