"""Sample agent and mock tools for the AgentGuard demo scenario.

This is the blueprint's worked example: a support agent that can search a
knowledge base, must get a human to approve outbound email, and is prohibited
from deleting customer records.

Run against a live backend::

    AGENTGUARD_API_KEY=ag_... python scripts/demo_agent.py

The script reports, for each action, whether the tool actually executed. The
critical assertion is that the denied tool is never called.
"""

from __future__ import annotations

import os
import sys

from agentguard import AgentGuardClient, ApprovalRequired, GuardDenied, call_guarded

BASE_URL = os.environ.get("AGENTGUARD_BASE_URL", "http://127.0.0.1:8000/api")

# ---------------------------------------------------------------------------
# Mock tools. Each records whether it ran so the demo can prove enforcement.
# ---------------------------------------------------------------------------

EXECUTION_LOG: list[str] = []


def search_knowledge_base(query: str, max_results: int = 5) -> dict:
    """Read-only knowledge-base search."""
    EXECUTION_LOG.append(f"search_knowledge_base(query={query!r})")
    return {"results": [{"title": "Refund policy", "excerpt": "Refunds within 30 days."}], "count": 1}


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an external email. High risk: requires approval."""
    EXECUTION_LOG.append(f"send_email(to={to!r}, subject={subject!r})")
    return {"message_id": "msg-0001", "to": to}


def delete_customer_record(customer_id: str, reason: str) -> dict:
    """Irreversibly delete a customer record. Prohibited."""
    EXECUTION_LOG.append(f"delete_customer_record(customer_id={customer_id!r})")
    return {"deleted": customer_id}


TOOLS = {
    "search_knowledge_base": search_knowledge_base,
    "send_email": send_email,
    "delete_customer_record": delete_customer_record,
}


def run_action(client: AgentGuardClient, tool: str, arguments: dict, target: str | None = None) -> None:
    print(f"\n▶ agent proposes: {tool}({arguments})")
    try:
        result = call_guarded(
            client,
            tool=tool,
            arguments=arguments,
            target=target,
            session_id="demo-session-1",
            execute=TOOLS[tool],
        )
        print(f"  ✅ ALLOW — tool executed, result: {result}")
    except GuardDenied as exc:
        print(f"  ⛔ DENY — tool did NOT execute. reason_codes={exc.reason_codes}")
    except ApprovalRequired as exc:
        print(
            f"  ⏸ REQUIRE_APPROVAL — tool did NOT execute. "
            f"approval_id={exc.approval_id} expires_at={exc.expires_at}"
        )


def main() -> int:
    api_key = os.environ.get("AGENTGUARD_API_KEY")
    if not api_key:
        print(
            "Set AGENTGUARD_API_KEY to an agent credential from the dashboard "
            "(Agents → register/rotate key).",
            file=sys.stderr,
        )
        return 2

    client = AgentGuardClient(base_url=BASE_URL, api_key=api_key)
    try:
        print("=" * 70)
        print("AgentGuard demo scenario")
        print("=" * 70)

        run_action(
            client,
            "search_knowledge_base",
            {"query": "refund policy"},
        )
        run_action(
            client,
            "send_email",
            {
                "to": "customer@example.com",
                "subject": "Your refund",
                "body": "Your refund has been approved and will arrive in 3 days.",
            },
            target="customer@example.com",
        )
        run_action(
            client,
            "delete_customer_record",
            {"customer_id": "cust-8812", "reason": "duplicate record"},
        )

        print("\n" + "=" * 70)
        print("Execution log (proof of what actually ran):")
        for entry in EXECUTION_LOG:
            print(f"  • {entry}")

        deleted_ran = any(entry.startswith("delete_customer_record") for entry in EXECUTION_LOG)
        print()
        if deleted_ran:
            print("❌ SECURITY FAILURE: the prohibited delete tool executed.")
            return 1
        print("✅ Enforcement verified: the destructive tool never executed.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
