"""Dependency graph queries: lineage, downstream impact, and cycle detection.

The graph is stored relationally (``dependencies``) rather than in a graph
database. Workflows are small enough that bounded breadth-first traversal over
indexed edges is appropriate; introducing a graph database here would add
operational cost without a demonstrated query need.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models import (
    Agent,
    AgentExecution,
    Artifact,
    Dependency,
    RiskAssessmentRecord,
    WorkflowExecution,
)
from ..schemas_v2 import GraphEdge, GraphNode, WorkflowGraph


def _edges(db: Session, org_id: str, workflow_execution_id: str) -> list[Dependency]:
    return list(
        db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.workflow_execution_id == workflow_execution_id,
            )
        ).scalars()
    )


def workflow_graph(db: Session, org_id: str, workflow_execution_id: str) -> WorkflowGraph:
    execution = db.get(WorkflowExecution, workflow_execution_id)
    if execution is None or execution.org_id != org_id:
        raise NotFoundError("Workflow execution not found")

    edges = _edges(db, org_id, workflow_execution_id)
    nodes: dict[str, GraphNode] = {
        workflow_execution_id: GraphNode(
            id=workflow_execution_id,
            type="workflow",
            label=f"Workflow execution {workflow_execution_id[:8]}",
            status=execution.status,
            metadata={"workflowId": execution.workflow_id},
        )
    }

    def add_node(node_id: str, node_type: str, label: str, status: str, metadata: dict | None = None):
        if node_id not in nodes:
            nodes[node_id] = GraphNode(
                id=node_id,
                type=node_type,
                label=label,
                status=status,
                metadata=metadata or {},
            )

    agent_ids = {
        edge.source_id for edge in edges if edge.source_type == "agent"
    } | {edge.target_id for edge in edges if edge.target_type == "agent"}
    for agent_id in agent_ids:
        agent = db.get(Agent, agent_id)
        if agent is None or agent.org_id != org_id:
            continue
        add_node(agent.id, "agent", agent.name, agent.status, {"environment": agent.environment})

    artifact_ids = {
        edge.source_id for edge in edges if edge.source_type == "artifact"
    } | {edge.target_id for edge in edges if edge.target_type == "artifact"}
    for artifact_id in artifact_ids:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.org_id != org_id:
            continue
        add_node(
            artifact.id,
            "artifact",
            artifact.name or artifact.artifact_type,
            artifact.validation_status,
            {
                "artifactType": artifact.artifact_type,
                "producerAgentId": artifact.producer_agent_id,
                "integrityHash": artifact.integrity_hash,
                "expiresAt": artifact.expires_at,
            },
        )

    tool_ids = {
        edge.source_id for edge in edges if edge.source_type == "tool"
    } | {edge.target_id for edge in edges if edge.target_type == "tool"}
    for tool_id in tool_ids:
        add_node(tool_id, "tool", tool_id.removeprefix("tool:"), "ACTIVE")

    graph_edges = [
        GraphEdge(
            id=edge.id,
            source=edge.source_id,
            target=edge.target_id,
            relationship=edge.relationship,
            validation_status=edge.validation_status,
            artifact_id=edge.artifact_id,
            created_at=edge.created_at,
        )
        for edge in edges
        if edge.source_id in nodes and edge.target_id in nodes
    ]
    return WorkflowGraph(
        workflow_execution_id=workflow_execution_id,
        nodes=list(nodes.values()),
        edges=graph_edges,
        cycles=detect_cycles(graph_edges),
    )


def detect_cycles(edges: list[GraphEdge]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.relationship in ("depends_on", "consumed", "produced", "validated"):
            adjacency[edge.source].append(edge.target)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        color[node] = GREY
        stack.append(node)
        for neighbour in adjacency.get(node, []):
            if color[neighbour] == GREY:
                try:
                    start = stack.index(neighbour)
                except ValueError:
                    start = 0
                cycle = stack[start:] + [neighbour]
                if cycle not in cycles:
                    cycles.append(cycle)
            elif color[neighbour] == WHITE:
                visit(neighbour)
        stack.pop()
        color[node] = BLACK

    for node in list(adjacency):
        if color[node] == WHITE:
            visit(node)
    return cycles


def artifact_lineage(db: Session, org_id: str, artifact_id: str, max_depth: int = 32) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.org_id != org_id:
        raise NotFoundError("Artifact not found")

    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque([(artifact_id, 0)])
    while queue:
        current_id, depth = queue.popleft()
        if current_id in seen or depth > max_depth:
            continue
        seen.add(current_id)
        current = db.get(Artifact, current_id)
        if current is None or current.org_id != org_id:
            continue
        ordered.append(
            {
                "id": current.id,
                "artifact_type": current.artifact_type,
                "name": current.name,
                "producer_agent_id": current.producer_agent_id,
                "producer_execution_id": current.producer_execution_id,
                "validation_status": current.validation_status,
                "integrity_hash": current.integrity_hash,
                "expires_at": current.expires_at,
                "parent_artifact_ids": list(current.parent_artifact_ids or []),
                "created_at": current.created_at,
                "depth": depth,
            }
        )
        for parent_id in current.parent_artifact_ids or []:
            queue.append((parent_id, depth + 1))
        # Also follow explicit depends_on edges (covers artifacts without parent ids).
        parents = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.target_type == "artifact",
                Dependency.target_id == current_id,
                Dependency.relationship == "depends_on",
            )
        ).scalars().all()
        for edge in parents:
            queue.append((edge.source_id, depth + 1))

    return {"artifact_id": artifact_id, "nodes": ordered, "depth": max_depth}


def downstream_impact(
    db: Session,
    org_id: str,
    *,
    agent_id: str | None = None,
    artifact_id: str | None = None,
    failure_type: str = "INVALID_OUTPUT",
    max_depth: int = 32,
) -> dict[str, Any]:
    if agent_id is None and artifact_id is None:
        raise ValueError("agent_id or artifact_id is required")

    start_artifacts: list[str] = []
    if artifact_id:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.org_id != org_id:
            raise NotFoundError("Artifact not found")
        start_artifacts.append(artifact.id)
    else:
        rows = db.execute(
            select(Artifact.id).where(
                Artifact.org_id == org_id, Artifact.producer_agent_id == agent_id
            )
        ).scalars().all()
        start_artifacts.extend(rows)

    seen_artifacts: set[str] = set(start_artifacts)
    affected_agents: set[str] = set()
    affected_workflows: set[str] = set()
    queue: deque[tuple[str, int]] = deque((a, 0) for a in start_artifacts)
    while queue:
        current_id, depth = queue.popleft()
        if depth > max_depth:
            continue
        current = db.get(Artifact, current_id)
        if current and current.workflow_execution_id:
            affected_workflows.add(current.workflow_execution_id)

        # Children artifacts that depend on this one.
        child_edges = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.source_type == "artifact",
                Dependency.source_id == current_id,
            )
        ).scalars().all()
        for edge in child_edges:
            if edge.target_type == "artifact" and edge.target_id not in seen_artifacts:
                seen_artifacts.add(edge.target_id)
                queue.append((edge.target_id, depth + 1))
            if edge.target_type == "agent":
                affected_agents.add(edge.target_id)
            if edge.relationship == "consumed" and current.workflow_execution_id:
                affected_workflows.add(current.workflow_execution_id)

        # Agents that consumed this artifact directly.
        consumers = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.artifact_id == current_id,
                Dependency.target_type == "agent",
            )
        ).scalars().all()
        for edge in consumers:
            affected_agents.add(edge.target_id)

    if agent_id:
        affected_agents.discard(agent_id)  # origin is reported separately

    blocked_actions: list[str] = []
    if affected_agents or affected_workflows:
        risk_rows = db.execute(
            select(RiskAssessmentRecord).where(
                RiskAssessmentRecord.org_id == org_id,
                RiskAssessmentRecord.decision != "ALLOW",
            )
        ).scalars().all()
        for row in risk_rows:
            if row.agent_id in affected_agents or (
                row.workflow_execution_id in affected_workflows
            ):
                blocked_actions.append(row.action_id)

    evidence = [
        f"Artifact {aid} is part of the downstream lineage" for aid in sorted(seen_artifacts)
    ]
    agent_names = []
    for aid in affected_agents:
        agent = db.get(Agent, aid)
        if agent and agent.org_id == org_id:
            agent_names.append(agent.name)
        else:
            agent_names.append(aid)

    severity = "HIGH" if affected_agents else "MEDIUM"
    if failure_type in ("INVALID_OUTPUT", "QUARANTINED_AGENT"):
        severity = "HIGH"
    return {
        "origin_agent": agent_id,
        "failure_type": failure_type,
        "affected_agents": sorted(agent_names),
        "affected_workflows": sorted(affected_workflows),
        "blocked_actions": sorted(set(blocked_actions)),
        "risk_level": severity,
        "evidence": evidence,
    }


def upstream_artifacts(
    db: Session,
    org_id: str,
    *,
    artifact_ids: list[str],
    agent_execution_id: str | None = None,
    agent_id: str | None = None,
    max_depth: int = 12,
) -> list[tuple[Artifact, int]]:
    """Return all upstream artifacts with their maximum distance from inputs."""
    roots = list(dict.fromkeys(artifact_ids))

    # Artifacts consumed by this agent execution are implicit inputs.
    if agent_execution_id and agent_id:
        consumed = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.target_type == "agent",
                Dependency.target_id == agent_id,
                Dependency.relationship == "consumed",
            )
        ).scalars().all()
        execution = db.get(AgentExecution, agent_execution_id)
        for edge in consumed:
            artifact = db.get(Artifact, edge.source_id)
            if artifact and (
                execution is None
                or artifact.workflow_execution_id == execution.workflow_execution_id
            ):
                roots.append(edge.source_id)

    seen: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((root, 0) for root in roots)
    while queue:
        current_id, depth = queue.popleft()
        if current_id in seen or depth > max_depth:
            continue
        artifact = db.get(Artifact, current_id)
        if artifact is None or artifact.org_id != org_id:
            continue
        seen[current_id] = depth
        for parent_id in artifact.parent_artifact_ids or []:
            queue.append((parent_id, depth + 1))
        edges = db.execute(
            select(Dependency).where(
                Dependency.org_id == org_id,
                Dependency.target_type == "artifact",
                Dependency.target_id == current_id,
                Dependency.relationship == "depends_on",
            )
        ).scalars().all()
        for edge in edges:
            queue.append((edge.source_id, depth + 1))

    result: list[tuple[Artifact, int]] = []
    for artifact_id, depth in seen.items():
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None:
            result.append((artifact, depth))
    return result
