"""Seed the demo workspace described in the blueprint's demo scenario.

Timestamps are generated relative to "now" so dashboard counters are meaningful
on first load. Idempotent: seeding is skipped when users already exist.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import (
    Agent,
    AgentToolPermission,
    Approval,
    AuditEvent,
    Policy,
    Settings,
    Tool,
    User,
    utcnow,
)
from .security import generate_agent_key, hash_key
from .services.settings import DEFAULT_SETTINGS

ISO_NOW = datetime.now(timezone.utc)


def _iso(offset_ms: int) -> str:
    return (ISO_NOW + timedelta(milliseconds=offset_ms)).isoformat()


def _hours_ago(hours: float) -> str:
    return _iso(int(-hours * 3_600_000))


def _hours_from_now(hours: float) -> str:
    return _iso(int(hours * 3_600_000))


def _days_ago(days: float) -> str:
    return _iso(int(-days * 86_400_000))


def seed_demo_data(db: Session, show_keys: bool = False) -> dict[str, str]:
    """Populate the demo dataset. Returns agent name -> API key (dev only)."""
    if db.query(User).first() is not None:
        return {}

    users = [
        User(id="u-admin", email="admin@agentguard.local", display_name="Asha Verma", role="ADMIN", status="ACTIVE", created_at=_days_ago(90)),
        User(id="u-approver", email="approver@agentguard.local", display_name="Daniel Osei", role="APPROVER", status="ACTIVE", created_at=_days_ago(80)),
        User(id="u-auditor", email="auditor@agentguard.local", display_name="Mei Lin", role="AUDITOR", status="ACTIVE", created_at=_days_ago(75)),
        User(id="u-developer", email="dev@agentguard.local", display_name="Ravi Patel", role="DEVELOPER", status="ACTIVE", created_at=_days_ago(60)),
    ]
    db.add_all(users)

    tools = [
        Tool(id="tool-kb-search", name="search_knowledge_base", description="Semantic search over the support knowledge base. Read-only; returns article excerpts.", input_schema={"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}, "max_results": {"type": "integer", "default": 5}}, "required": ["query"]}, category="read", default_risk="LOW", status="ACTIVE", created_at=_days_ago(30)),
        Tool(id="tool-email", name="send_email", description="Send an email to an external recipient through the corporate mail relay.", input_schema={"type": "object", "properties": {"to": {"type": "string", "format": "email"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}, category="external", default_risk="HIGH", status="ACTIVE", created_at=_days_ago(30)),
        Tool(id="tool-delete-record", name="delete_customer_record", description="Permanently delete a customer record and all associated history. Irreversible.", input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["customer_id", "reason"]}, category="destructive", default_risk="CRITICAL", status="ACTIVE", created_at=_days_ago(30)),
        Tool(id="tool-sales-db", name="query_sales_db", description="Run a read-only SQL query against the sales analytics warehouse.", input_schema={"type": "object", "properties": {"sql": {"type": "string"}, "limit": {"type": "integer", "default": 100}}, "required": ["sql"]}, category="read", default_risk="MEDIUM", status="ACTIVE", created_at=_days_ago(28)),
        Tool(id="tool-jira", name="create_jira_ticket", description="Create a ticket in the support Jira project.", input_schema={"type": "object", "properties": {"project": {"type": "string"}, "summary": {"type": "string"}, "description": {"type": "string"}, "priority": {"type": "string", "enum": ["Low", "Medium", "High"]}}, "required": ["project", "summary"]}, category="write", default_risk="MEDIUM", status="ACTIVE", created_at=_days_ago(25)),
        Tool(id="tool-deploy", name="deploy_service", description="Trigger a production deployment of a service through the CI pipeline.", input_schema={"type": "object", "properties": {"service": {"type": "string"}, "tag": {"type": "string"}}, "required": ["service", "tag"]}, category="write", default_risk="HIGH", status="DISABLED", created_at=_days_ago(20)),
    ]
    db.add_all(tools)

    agent_specs = [
        ("agent-support", "support-agent", "u-admin", "prod", "ACTIVE", ["tool-kb-search", "tool-email", "tool-delete-record", "tool-jira"], _days_ago(21), _hours_ago(2)),
        ("agent-analyst", "data-analyst-agent", "u-developer", "prod", "ACTIVE", ["tool-sales-db", "tool-jira"], _days_ago(18), _hours_ago(6)),
        ("agent-devscout", "dev-scout-agent", "u-developer", "dev", "ACTIVE", ["tool-kb-search", "tool-sales-db", "tool-jira", "tool-deploy"], _days_ago(12), _hours_ago(26)),
        ("agent-legacy", "legacy-reporter-agent", "u-admin", "staging", "DISABLED", ["tool-sales-db"], _days_ago(45), _days_ago(3)),
    ]
    agent_keys: dict[str, str] = {}
    for agent_id, name, owner, environment, status, tool_ids, created, updated in agent_specs:
        api_key = generate_agent_key()
        agent_keys[name] = api_key
        agent = Agent(
            id=agent_id,
            name=name,
            owner_user_id=owner,
            environment=environment,
            status=status,
            credential_hash=hash_key(api_key),
            created_at=created,
            updated_at=updated,
            last_action_at=_hours_ago(0.4) if agent_id == "agent-support" else _hours_ago(1.2),
        )
        db.add(agent)
        for tool_id in tool_ids:
            db.add(
                AgentToolPermission(
                    agent_id=agent_id, tool_id=tool_id, scopes={}, created_at=created
                )
            )

    policies = [
        Policy(
            id="policy-prod", name="Default production policy",
            description="Baseline production governance: read-only research is allowed, outbound communication requires a human, destructive operations are denied.",
            version=3, default_effect="DENY", status="ACTIVE", created_by="u-admin",
            created_at=_days_ago(14), updated_at=_hours_ago(30),
            rules=[
                {"id": "allow-read-docs", "effect": "ALLOW", "agent": "support-agent", "tool": "search_knowledge_base", "riskMax": "MEDIUM"},
                {"id": "allow-read-sales", "effect": "ALLOW", "agent": "data-analyst-agent", "tool": "query_sales_db", "riskMax": "MEDIUM"},
                {"id": "allow-jira", "effect": "ALLOW", "tool": "create_jira_ticket", "environment": "prod", "riskMax": "MEDIUM"},
                {"id": "approve-outbound-email", "effect": "REQUIRE_APPROVAL", "tool": "send_email", "environment": "prod"},
                {"id": "allow-email-after-approval", "effect": "ALLOW", "tool": "send_email", "environment": "prod"},
                {"id": "deny-delete", "effect": "DENY", "tool": "delete_customer_record"},
            ],
        ),
        Policy(
            id="policy-dev", name="Development sandbox policy",
            description="Permissive policy for the dev environment. Deployments still require approval because they share the production pipeline credentials.",
            version=1, default_effect="DENY", status="ACTIVE", created_by="u-developer",
            created_at=_days_ago(10), updated_at=_days_ago(2),
            rules=[
                {"id": "dev-allow-read", "effect": "ALLOW", "environment": "dev", "category": "read"},
                {"id": "dev-allow-write", "effect": "ALLOW", "environment": "dev", "category": "write", "riskMax": "MEDIUM"},
                {"id": "dev-approve-deploy", "effect": "REQUIRE_APPROVAL", "tool": "deploy_service", "environment": "dev"},
            ],
        ),
        Policy(
            id="policy-draft", name="Stricter outbound policy",
            description="Draft: extends approval requirements to staging and caps knowledge-base result counts. Not yet published.",
            version=4, default_effect="DENY", status="DRAFT", created_by="u-admin",
            created_at=_days_ago(2), updated_at=_hours_ago(4),
            rules=[
                {"id": "draft-allow-read", "effect": "ALLOW", "tool": "search_knowledge_base", "riskMax": "LOW"},
                {"id": "draft-approve-email", "effect": "REQUIRE_APPROVAL", "tool": "send_email"},
                {"id": "draft-deny-delete", "effect": "DENY", "tool": "delete_customer_record"},
            ],
        ),
    ]
    db.add_all(policies)

    approvals = [
        Approval(id="ap-1001", action_id="act-1001", payload_hash="sha256:9f2c1ab74e0d4c8f9a1b2c3d4e5f60718293a4b5c6d7e8f9012345678abcdef01", requested_by_agent_id="agent-support", status="PENDING", expires_at=_hours_from_now(6), reason="POLICY_APPROVAL_REQUIRED", tool_name="send_email", target="customer@example.com", arguments_summary={"to": "customer@example.com", "subject": "Account update", "body": "[redacted — 412 chars]"}, risk_level="HIGH", policy_version=3, created_at=_hours_ago(1.5)),
        Approval(id="ap-1002", action_id="act-1002", payload_hash="sha256:1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809", requested_by_agent_id="agent-devscout", status="PENDING", expires_at=_hours_from_now(2), reason="POLICY_APPROVAL_REQUIRED", tool_name="deploy_service", target="checkout-service", arguments_summary={"service": "checkout-service", "tag": "v1.14.2"}, risk_level="HIGH", policy_version=1, created_at=_hours_ago(0.6)),
        Approval(id="ap-1003", action_id="act-1003", payload_hash="sha256:77aa10b2c3d4e5f60718293a4b5c6d7e8f9012345678abcdef0123456789abcde", requested_by_agent_id="agent-support", status="APPROVED", approver_user_id="u-approver", expires_at=_hours_from_now(10), decided_at=_hours_ago(2.5), reason="POLICY_APPROVAL_REQUIRED", tool_name="send_email", target="billing@example.com", arguments_summary={"to": "billing@example.com", "subject": "Invoice question", "body": "[redacted — 268 chars]"}, risk_level="HIGH", policy_version=3, created_at=_hours_ago(4)),
        Approval(id="ap-1004", action_id="act-1004", payload_hash="sha256:3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a", requested_by_agent_id="agent-support", status="REJECTED", approver_user_id="u-approver", expires_at=_hours_ago(1), decided_at=_hours_ago(3), reason="POLICY_APPROVAL_REQUIRED", tool_name="send_email", target="external-vendor@example.net", arguments_summary={"to": "external-vendor@example.net", "subject": "Contract terms", "body": "[redacted — 904 chars]"}, risk_level="HIGH", policy_version=3, created_at=_hours_ago(8)),
        Approval(id="ap-1005", action_id="act-1005", payload_hash="sha256:ccddeeff00112233445566778899aabbccddeeff00112233445566778899aabb", requested_by_agent_id="agent-analyst", status="EXPIRED", expires_at=_hours_ago(0.2), reason="POLICY_APPROVAL_REQUIRED", tool_name="send_email", target="partner@example.org", arguments_summary={"to": "partner@example.org", "subject": "Data sharing request", "body": "[redacted — 188 chars]"}, risk_level="HIGH", policy_version=3, created_at=_hours_ago(12)),
    ]
    db.add_all(approvals)

    events = [
        AuditEvent(id="evt-2001", event_type="decision", action_id="act-2001", agent_id="agent-support", session_id="sess-7f3a", tool_name="search_knowledge_base", decision="ALLOW", risk_level="LOW", reason_codes=["TOOL_REGISTERED", "PERMISSION_GRANTED", "RISK_WITHIN_LIMIT"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:aaa1", redacted_metadata={"query": "refund policy", "results": 5}, created_at=_hours_ago(0.2)),
        AuditEvent(id="evt-2002", event_type="decision", action_id="act-1001", agent_id="agent-support", session_id="sess-7f3a", tool_name="send_email", decision="REQUIRE_APPROVAL", risk_level="HIGH", reason_codes=["POLICY_APPROVAL_REQUIRED", "EXTERNAL_COMMUNICATION", "PRODUCTION_ENVIRONMENT"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:9f2c1ab74e0d4c8f9a1b2c3d4e5f60718293a4b5c6d7e8f9012345678abcdef01", redacted_metadata={"to": "customer@example.com", "subject": "Account update"}, created_at=_hours_ago(1.5)),
        AuditEvent(id="evt-2003", event_type="approval", action_id="act-1001", agent_id="agent-support", tool_name="send_email", decision="REQUIRE_APPROVAL", risk_level="HIGH", reason_codes=["APPROVAL_CREATED"], policy_id="policy-prod", policy_version=3, redacted_metadata={"approvalId": "ap-1001", "expiresAt": _hours_from_now(6)}, created_at=_hours_ago(1.5)),
        AuditEvent(id="evt-2004", event_type="decision", action_id="act-2004", agent_id="agent-support", session_id="sess-7f3a", tool_name="delete_customer_record", decision="DENY", risk_level="CRITICAL", reason_codes=["EXPLICIT_DENY_RULE", "DESTRUCTIVE_OPERATION"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:bbb2", redacted_metadata={"customer_id": "cust-8812", "reason": "duplicate record"}, created_at=_hours_ago(0.8)),
        AuditEvent(id="evt-2005", event_type="decision", action_id="act-2005", agent_id="agent-analyst", session_id="sess-2c91", tool_name="query_sales_db", decision="ALLOW", risk_level="MEDIUM", reason_codes=["TOOL_REGISTERED", "PERMISSION_GRANTED"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:ccc3", redacted_metadata={"sql": "SELECT region, sum(revenue) FROM orders GROUP BY region", "rows": 12}, created_at=_hours_ago(1.2)),
        AuditEvent(id="evt-2006", event_type="execution", action_id="act-2005", agent_id="agent-analyst", tool_name="query_sales_db", decision="ALLOW", risk_level="MEDIUM", reason_codes=["TOOL_EXECUTED"], policy_id="policy-prod", policy_version=3, redacted_metadata={"success": True, "durationMs": 412}, created_at=_hours_ago(1.2)),
        AuditEvent(id="evt-2007", event_type="decision", action_id="act-1002", agent_id="agent-devscout", session_id="sess-51dd", tool_name="deploy_service", decision="REQUIRE_APPROVAL", risk_level="HIGH", reason_codes=["POLICY_APPROVAL_REQUIRED", "DEPLOYMENT_INFRASTRUCTURE"], policy_id="policy-dev", policy_version=1, payload_hash="sha256:1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809", redacted_metadata={"service": "checkout-service", "tag": "v1.14.2"}, created_at=_hours_ago(0.6)),
        AuditEvent(id="evt-2008", event_type="approval", action_id="act-1003", agent_id="agent-support", tool_name="send_email", decision="REQUIRE_APPROVAL", risk_level="HIGH", reason_codes=["APPROVAL_GRANTED"], policy_id="policy-prod", policy_version=3, redacted_metadata={"approvalId": "ap-1003", "approverUserId": "u-approver"}, created_at=_hours_ago(2.5)),
        AuditEvent(id="evt-2009", event_type="execution", action_id="act-1003", agent_id="agent-support", tool_name="send_email", decision="ALLOW", risk_level="HIGH", reason_codes=["APPROVAL_CONSUMED", "POLICY_REVALIDATED"], policy_id="policy-prod", policy_version=3, redacted_metadata={"success": True, "durationMs": 890}, created_at=_hours_ago(2.5)),
        AuditEvent(id="evt-2010", event_type="approval", action_id="act-1004", agent_id="agent-support", tool_name="send_email", decision="REQUIRE_APPROVAL", risk_level="HIGH", reason_codes=["APPROVAL_REJECTED"], policy_id="policy-prod", policy_version=3, redacted_metadata={"approvalId": "ap-1004", "approverUserId": "u-approver", "reason": "Outside approved recipient list"}, created_at=_hours_ago(3)),
        AuditEvent(id="evt-2011", event_type="decision", action_id="act-2011", agent_id="agent-support", session_id="sess-7f3a", tool_name="create_jira_ticket", decision="ALLOW", risk_level="MEDIUM", reason_codes=["TOOL_REGISTERED", "PERMISSION_GRANTED"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:ddd4", redacted_metadata={"project": "SUP", "summary": "Refund not reflected"}, created_at=_hours_ago(3.4)),
        AuditEvent(id="evt-2012", event_type="decision", action_id="act-2012", agent_id="agent-legacy", session_id="sess-00ab", tool_name="query_sales_db", decision="DENY", risk_level="MEDIUM", reason_codes=["AGENT_DISABLED"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:eee5", redacted_metadata={}, created_at=_hours_ago(5)),
        AuditEvent(id="evt-2013", event_type="admin", action_id="act-2013", agent_id="agent-legacy", reason_codes=["AGENT_DISABLED_BY_ADMIN"], redacted_metadata={"actorUserId": "u-admin", "previousStatus": "ACTIVE"}, created_at=_days_ago(3)),
        AuditEvent(id="evt-2014", event_type="decision", action_id="act-2014", agent_id="agent-devscout", session_id="sess-51dd", tool_name="deploy_service", decision="DENY", risk_level="HIGH", reason_codes=["TOOL_DISABLED"], policy_id="policy-dev", policy_version=1, payload_hash="sha256:fff6", redacted_metadata={"service": "checkout-service"}, created_at=_hours_ago(9)),
        AuditEvent(id="evt-2015", event_type="decision", action_id="act-2015", agent_id="agent-support", session_id="sess-7f3a", tool_name="search_knowledge_base", decision="ALLOW", risk_level="LOW", reason_codes=["TOOL_REGISTERED", "PERMISSION_GRANTED"], policy_id="policy-prod", policy_version=3, payload_hash="sha256:1117", redacted_metadata={"query": "password reset steps", "results": 3}, created_at=_hours_ago(0.4)),
    ]
    db.add_all(events)

    db.add(
        Settings(
            id="1",
            workspace_name="AgentGuard Workspace",
            default_environment="prod",
            approval_ttl_minutes=DEFAULT_SETTINGS["approval_ttl_minutes"],
            retention_days=DEFAULT_SETTINGS["retention_days"],
            redact_secrets=1,
            redact_fields=DEFAULT_SETTINGS["redact_fields"],
            require_approval_for=DEFAULT_SETTINGS["require_approval_for"],
            max_payload_bytes=DEFAULT_SETTINGS["max_payload_bytes"],
        )
    )
    db.commit()

    if show_keys:
        print("\n[agentguard] Seeded demo agent API keys (development only):")
        for name, key in agent_keys.items():
            print(f"  {name}: {key}")
        print()

    return agent_keys
