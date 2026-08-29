"""Local, bounded workflow primitives inspired by node-based automation tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4


ALLOWED_NODE_TYPES = {"core.input", "crawl.status", "knowledge.search", "knowledge.ask", "local_db.query"}
ALLOWED_TRIGGER_TYPES = {"manual", "crawl.completed"}
MAX_NODES = 16


class WorkflowValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    type: str
    config: dict[str, Any]


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    nodes: list[WorkflowNode]
    edges: list[tuple[str, str]]
    trigger: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any], workflow_id: str | None = None) -> "WorkflowDefinition":
        nodes = [WorkflowNode(str(item["id"]), str(item["type"]), dict(item.get("config", {}))) for item in payload.get("nodes", [])]
        edges = [(str(edge[0]), str(edge[1])) for edge in payload.get("edges", [])]
        trigger = dict(payload.get("trigger", {"type": "manual"}))
        definition = cls(workflow_id or str(payload.get("id") or uuid4()), str(payload.get("name") or "Untitled local workflow"), nodes, edges, trigger)
        validate_workflow(definition)
        return definition

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "trigger": self.trigger, "nodes": [{"id": node.id, "type": node.type, "config": node.config} for node in self.nodes], "edges": [list(edge) for edge in self.edges]}


def validate_workflow(workflow: WorkflowDefinition) -> None:
    if not workflow.name.strip():
        raise WorkflowValidationError("Workflow name is required.")
    trigger_type = str(workflow.trigger.get("type", "manual"))
    if trigger_type not in ALLOWED_TRIGGER_TYPES:
        raise WorkflowValidationError(f"Unsupported workflow trigger: {trigger_type}")
    if not workflow.nodes or len(workflow.nodes) > MAX_NODES:
        raise WorkflowValidationError(f"A workflow must contain between 1 and {MAX_NODES} nodes.")
    ids = [node.id for node in workflow.nodes]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", node_id) for node_id in ids):
        raise WorkflowValidationError("Node IDs must be unique and contain only letters, numbers, underscores, or hyphens.")
    node_ids = set(ids)
    for node in workflow.nodes:
        if node.type not in ALLOWED_NODE_TYPES:
            raise WorkflowValidationError(f"Unsupported or unsafe node type: {node.type}")
    for source, target in workflow.edges:
        if source not in node_ids or target not in node_ids or source == target:
            raise WorkflowValidationError("Workflow edges must connect two distinct existing nodes.")
    adjacency = {node_id: [] for node_id in node_ids}
    for source, target in workflow.edges:
        adjacency[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise WorkflowValidationError("Workflow cycles are not allowed.")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency[node_id]:
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in node_ids:
        visit(node_id)


def trigger_matches(workflow: WorkflowDefinition, event_type: str, event_data: dict[str, Any]) -> bool:
    trigger = workflow.trigger
    if str(trigger.get("type", "manual")) != event_type:
        return False
    expected_start_url = str(trigger.get("start_url", "")).strip()
    return not expected_start_url or expected_start_url == str(event_data.get("start_url", ""))


def execution_order(workflow: WorkflowDefinition) -> list[WorkflowNode]:
    by_id = {node.id: node for node in workflow.nodes}
    adjacency = {node.id: [] for node in workflow.nodes}
    incoming = {node.id: 0 for node in workflow.nodes}
    for source, target in workflow.edges:
        adjacency[source].append(target)
        incoming[target] += 1
    ready = [node.id for node in workflow.nodes if incoming[node.id] == 0]
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in adjacency[current]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if len(ordered) != len(workflow.nodes):
        raise WorkflowValidationError("Workflow cycles are not allowed.")
    return [by_id[node_id] for node_id in ordered]


def _resolve(value: Any, input_data: dict[str, Any], outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve(item, input_data, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, input_data, outputs) for item in value]
    if not isinstance(value, str):
        return value
    exact = re.fullmatch(r"\{\{\s*(input|node\.([A-Za-z0-9_-]{1,48}))(?:\.([A-Za-z0-9_-]{1,48}))?\s*\}\}", value)
    if exact:
        if exact.group(1) == "input":
            return input_data.get(exact.group(3 or ""))
        return outputs.get(exact.group(2), {}).get(exact.group(3) or "")
    return value


class WorkflowEngine:
    def __init__(self, database: Any, answer: Callable[[str, str], dict[str, Any]]) -> None:
        self.database = database
        self.answer = answer

    def run(self, workflow: WorkflowDefinition, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        validate_workflow(workflow)
        payload = input_data or {}
        if not self.database.get_workflow(workflow.id):
            self.database.save_workflow(workflow.id, workflow.name, workflow_json(workflow), False)
        run_id = self.database.create_workflow_run(workflow.id, payload)
        outputs: dict[str, Any] = {}
        try:
            for node in execution_order(workflow):
                config = _resolve(node.config, payload, outputs)
                outputs[node.id] = self._execute_node(node.type, config, payload)
            result = {"run_id": run_id, "workflow_id": workflow.id, "status": "completed", "outputs": outputs}
            self.database.finish_workflow_run(run_id, "completed", result)
            return result
        except Exception as exc:
            result = {"run_id": run_id, "workflow_id": workflow.id, "status": "failed", "outputs": outputs, "error": f"{type(exc).__name__}: {exc}"}
            self.database.finish_workflow_run(run_id, "failed", result)
            return result

    def _execute_node(self, node_type: str, config: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        if node_type == "core.input":
            return dict(input_data)
        if node_type == "crawl.status":
            crawl = self.database.get_crawl(str(config.get("crawl_id", "")))
            if not crawl:
                raise ValueError("Crawl was not found.")
            return {"crawl_id": crawl["id"], "status": crawl["status"], "pages_crawled": crawl["pages_crawled"], "issues_found": crawl["issues_found"]}
        if node_type == "knowledge.search":
            crawl_id, query = str(config.get("crawl_id", "")), str(config.get("query", ""))
            return {"crawl_id": crawl_id, "query": query, "results": self.database.search_hybrid_knowledge(crawl_id, query, int(config.get("limit", 6)))}
        if node_type == "knowledge.ask":
            return self.answer(str(config.get("crawl_id", "")), str(config.get("question", "")))
        if node_type == "local_db.query":
            return {"rows": self.database.readonly_query(str(config.get("sql", "")), config.get("params", []), int(config.get("limit", 100)))}
        raise WorkflowValidationError(f"Unsupported workflow node type: {node_type}")


def workflow_json(workflow: WorkflowDefinition) -> str:
    return json.dumps(workflow.to_dict(), sort_keys=True)
