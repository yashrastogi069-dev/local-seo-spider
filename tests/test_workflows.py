from pathlib import Path

import pytest

from app.database import Database
from app.knowledge import extract_knowledge_chunks
from app.types import CrawlRequest, PageRecord
from app.workflows import WorkflowDefinition, WorkflowEngine, WorkflowValidationError, trigger_matches, workflow_json


def page() -> PageRecord:
    return PageRecord(
        url="https://owned.example/", final_url="https://owned.example/", status_code=200, content_type="text/html",
        title="Home", description="", headings={"h1": ["Home"]}, canonical="", meta_robots="", x_robots="",
        source_html="<html><body><h1>Home</h1><p>Workshops are available.</p></body></html>", rendered_html="", rendered_text="",
        images=[], structured_data=[], redirect_chain=[], fetch_error="", render_error="", discovered_at="2026-08-29T00:00:00+00:00",
        content_hash="hash",
    )


def test_workflow_runs_safe_nodes_in_graph_order(tmp_path: Path) -> None:
    database = Database(tmp_path / "workflow.sqlite")
    database.initialize()
    crawl_id = database.create_crawl(CrawlRequest("https://owned.example/", "site", acknowledgment=True))
    database.replace_pages_and_links(crawl_id, [page()], [])
    database.replace_knowledge_chunks(crawl_id, extract_knowledge_chunks(database.get_pages(crawl_id)[0], crawl_id))
    database.update_crawl(crawl_id, status="completed", pages_crawled=1)
    workflow = WorkflowDefinition.from_dict({
        "id": "audit-read",
        "name": "Read local audit",
        "nodes": [
            {"id": "question", "type": "knowledge.search", "config": {"crawl_id": crawl_id, "query": "workshops"}},
            {"id": "status", "type": "crawl.status", "config": {"crawl_id": crawl_id}},
            {"id": "rows", "type": "local_db.query", "config": {"sql": "SELECT status FROM crawls WHERE id = ?", "params": [crawl_id]}},
        ],
        "edges": [["status", "question"], ["question", "rows"]],
    })
    database.save_workflow(workflow.id, workflow.name, workflow_json(workflow))
    result = WorkflowEngine(database, lambda cid, question: {"grounded": True, "answer": question}).run(workflow)
    assert result["status"] == "completed"
    assert result["outputs"]["status"]["status"] == "completed"
    assert result["outputs"]["question"]["results"]
    assert result["outputs"]["rows"]["rows"][0]["status"] == "completed"


def test_workflow_rejects_cycles_and_unsafe_nodes() -> None:
    with pytest.raises(WorkflowValidationError, match="Unsupported or unsafe"):
        WorkflowDefinition.from_dict({"name": "unsafe", "nodes": [{"id": "x", "type": "crawl.start"}]})
    with pytest.raises(WorkflowValidationError, match="cycles"):
        WorkflowDefinition.from_dict({
            "name": "cycle",
            "nodes": [{"id": "a", "type": "core.input"}, {"id": "b", "type": "core.input"}],
            "edges": [["a", "b"], ["b", "a"]],
        })


def test_trigger_matching_is_explicit_and_host_filtered() -> None:
    workflow = WorkflowDefinition.from_dict({
        "name": "on complete",
        "trigger": {"type": "crawl.completed", "start_url": "https://owned.example/"},
        "nodes": [{"id": "input", "type": "core.input"}],
    })
    assert trigger_matches(workflow, "crawl.completed", {"start_url": "https://owned.example/"})
    assert not trigger_matches(workflow, "manual", {"start_url": "https://owned.example/"})
    assert not trigger_matches(workflow, "crawl.completed", {"start_url": "https://other.example/"})


def test_local_db_node_rejects_writes(tmp_path: Path) -> None:
    database = Database(tmp_path / "readonly.sqlite")
    database.initialize()
    workflow = WorkflowDefinition.from_dict({
        "name": "readonly",
        "nodes": [{"id": "read", "type": "local_db.query", "config": {"sql": "DELETE FROM crawls"}}],
    })
    result = WorkflowEngine(database, lambda cid, question: {}).run(workflow)
    assert result["status"] == "failed"
    assert "read-only" in result["error"]
