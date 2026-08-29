"""Field Manual interface for a local, permission-gated SEO crawler."""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.analyzer import analyze_pages
from app.comparison import compare_crawls
from app.knowledge import compare_knowledge, extract_pages_knowledge
from app.qa import answer_question
from app.config import Settings
from app.crawler import CrawlEngine
from app.agentic import agentic_retrieve
from app.answering import LocalAnswerer
from app.database import Database, now
from app.embeddings import build_embedding_provider
from app.exports import write_csv_exports, write_html_report
from app.types import CrawlRequest
from app.urltools import UrlValidationError, is_same_host, normalize_url, visible_url

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = Path(os.environ.get("SPIDER_ASSET_DIR", str(ROOT / "assets")))
ASSET_DIR.mkdir(parents=True, exist_ok=True)
settings = Settings.from_environment(ROOT)
database = Database(settings.database_path)
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
templates.env.filters["visible_url"] = visible_url
worker_wake = threading.Event()
worker_stop = threading.Event()
worker_thread: threading.Thread | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    database.recover_interrupted_jobs()
    _start_worker()
    try:
        yield
    finally:
        worker_stop.set()
        worker_wake.set()
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=2)


app = FastAPI(title="Local SEO Spider", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
app.mount("/manus-storage", StaticFiles(directory=str(ASSET_DIR)), name="generated_assets")


@app.middleware("http")
async def local_security_headers(request: Request, call_next: object) -> Response:
    response = await call_next(request)  # type: ignore[misc]
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline' https://unpkg.com; connect-src 'self'; form-action 'self'; base-uri 'self'; frame-ancestors 'none'")
    return response


def _context(request: Request, **kwargs: object) -> dict[str, object]:
    return {"request": request, "app_name": "Local SEO Spider", **kwargs}


def _home_response(request: Request, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "home.html",
        _context(
            request,
            crawls=database.list_crawls(),
            error=error,
            defaults={"url_cap": settings.default_url_cap, "delay": settings.default_delay_seconds, "max_url_cap": settings.max_url_cap},
        ),
        status_code=status_code,
    )


def _parse_request(start_url: str, mode: str, url_list: str, max_urls: str, delay_seconds: str, respect_nofollow: str | None, authorization_acknowledgment: str | None) -> CrawlRequest:
    if authorization_acknowledgment != "yes":
        raise ValueError("Confirm that you own this site or have explicit permission to assess it before starting a crawl.")
    normalized_start = normalize_url(start_url)
    if mode not in {"site", "list"}:
        raise ValueError("Choose a valid crawl mode.")
    try:
        parsed_max = int(max_urls)
    except ValueError as exc:
        raise ValueError("URL cap must be a whole number.") from exc
    if not 1 <= parsed_max <= settings.max_url_cap:
        raise ValueError(f"URL cap must be between 1 and {settings.max_url_cap:,}.")
    try:
        parsed_delay = float(delay_seconds)
    except ValueError as exc:
        raise ValueError("Delay must be a number of seconds.") from exc
    if not 0.1 <= parsed_delay <= 60:
        raise ValueError("Delay must be between 0.1 and 60 seconds.")
    parsed_urls: list[str] = []
    if mode == "list":
        for line in url_list.splitlines():
            if not line.strip():
                continue
            item = normalize_url(line)
            if not is_same_host(item, normalized_start):
                raise ValueError("Every exact-list URL must use the same scheme and host as the start URL.")
            if item not in parsed_urls:
                parsed_urls.append(item)
        if not parsed_urls:
            raise ValueError("Paste at least one URL for exact URL list mode.")
        parsed_max = min(parsed_max, len(parsed_urls))
    return CrawlRequest(normalized_start, mode, parsed_urls, parsed_max, parsed_delay, respect_nofollow == "yes", True)


def _run_claimed_crawl(crawl_id: str, crawl_request: CrawlRequest) -> None:
    """Run a job already claimed by the sole local worker and persist its outcome."""
    database.update_crawl(crawl_id, robots_status="checking")
    def progress(pages_crawled: int, _: int, robots_status: str) -> None:
        database.update_crawl(crawl_id, pages_crawled=pages_crawled, robots_status=robots_status)
    try:
        pages, links, robots_status = CrawlEngine(settings).run(crawl_request, progress)
        issues = analyze_pages(pages, links, crawl_request.start_url)
        database.replace_pages_and_links(crawl_id, pages, links)
        stored_pages = database.get_pages(crawl_id)
        database.replace_knowledge_chunks(crawl_id, extract_pages_knowledge(stored_pages, crawl_id), _embedding_provider())
        database.replace_issues(crawl_id, issues)
        database.update_crawl(crawl_id, status="completed", completed_at=now(), robots_status=robots_status, pages_crawled=len(pages), issues_found=len(issues), pause_reason="")
    except Exception as exc:
        database.defer_or_pause_job(crawl_id, f"{type(exc).__name__}: {exc}")


def _worker_loop() -> None:
    """Claim and execute one approved local job at a time until this process stops."""
    while not worker_stop.is_set():
        job = database.claim_next_job()
        if not job:
            worker_wake.wait(timeout=1)
            worker_wake.clear()
            continue
        crawl_request = database.get_crawl_request(job["id"])
        if crawl_request is None:
            database.update_crawl(job["id"], status="failed", completed_at=now(), error_message="The durable local request payload is unavailable. Resume is blocked until this record is reviewed.")
            continue
        _run_claimed_crawl(job["id"], crawl_request)


def _start_worker() -> None:
    """Start exactly one local dispatcher for this FastAPI process."""
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        return
    worker_stop.clear()
    worker_thread = threading.Thread(target=_worker_loop, name="local-seo-spider-worker", daemon=True)
    worker_thread.start()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _home_response(request)


@app.post("/crawls", response_class=HTMLResponse)
def create_crawl(
    request: Request,
    start_url: Annotated[str, Form()],
    mode: Annotated[str, Form()] = "site",
    url_list: Annotated[str, Form()] = "",
    max_urls: Annotated[str, Form()] = str(settings.default_url_cap),
    delay_seconds: Annotated[str, Form()] = str(settings.default_delay_seconds),
    respect_nofollow: Annotated[str | None, Form()] = None,
    authorization_acknowledgment: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        crawl_request = _parse_request(start_url, mode, url_list, max_urls, delay_seconds, respect_nofollow, authorization_acknowledgment)
    except (ValueError, UrlValidationError) as exc:
        if request.headers.get("HX-Request") != "true":
            return _home_response(request, error=str(exc), status_code=422)
        return templates.TemplateResponse(request, "partials/crawl_form.html", _context(request, error=str(exc), defaults={"url_cap": settings.default_url_cap, "delay": settings.default_delay_seconds, "max_url_cap": settings.max_url_cap}), status_code=422)
    crawl_id = database.create_crawl(crawl_request)
    worker_wake.set()
    if request.headers.get("HX-Request") != "true":
        return RedirectResponse(url=f"/crawls/{crawl_id}", status_code=303)
    return templates.TemplateResponse(request, "partials/crawl_status.html", _context(request, crawl=database.get_crawl(crawl_id)))


@app.get("/crawls/{crawl_id}/status", response_class=HTMLResponse)
def crawl_status(request: Request, crawl_id: str) -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(404, "Crawl not found.")
    return templates.TemplateResponse(request, "partials/crawl_status.html", _context(request, crawl=crawl))


def _job_control_response(request: Request, crawl: dict[str, object]) -> Response:
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "partials/crawl_status.html", _context(request, crawl=crawl))
    return RedirectResponse(url=f"/crawls/{crawl['id']}", status_code=303)


@app.post("/crawls/{crawl_id}/pause")
def pause_crawl(request: Request, crawl_id: str) -> Response:
    crawl = database.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(404, "Crawl not found.")
    if crawl["status"] not in {"queued", "retryable"}:
        raise HTTPException(409, "Only a queued or retryable crawl can be paused safely.")
    updated = database.pause_job(crawl_id)
    return _job_control_response(request, updated or crawl)


@app.post("/crawls/{crawl_id}/resume")
def resume_crawl(request: Request, crawl_id: str) -> Response:
    crawl = database.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(404, "Crawl not found.")
    if crawl["status"] not in {"paused", "retryable", "failed"}:
        raise HTTPException(409, "Only a paused, retryable, or failed crawl can be resumed.")
    updated = database.resume_job(crawl_id)
    if updated:
        worker_wake.set()
    return _job_control_response(request, updated or crawl)


@app.get("/crawls/{crawl_id}", response_class=HTMLResponse)
def crawl_detail(request: Request, crawl_id: str) -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(404, "Crawl not found.")
    pages = database.get_pages(crawl_id) if crawl["status"] == "completed" else []
    issues = database.get_issues(crawl_id) if crawl["status"] == "completed" else []
    completed_crawls = [
        entry for entry in database.list_crawls()
        if entry["status"] == "completed" and entry["id"] != crawl_id and entry["start_url"] == crawl["start_url"]
    ]
    return templates.TemplateResponse(request, "crawl_detail.html", _context(request, crawl=crawl, pages=pages, issues=issues, completed_crawls=completed_crawls, knowledge_count=database.knowledge_count(crawl_id)))


@app.get("/crawls/{crawl_id}/compare/{baseline_id}", response_class=HTMLResponse)
def crawl_comparison(request: Request, crawl_id: str, baseline_id: str) -> HTMLResponse:
    current, current_pages, current_issues = _export_data(crawl_id)
    baseline, baseline_pages, baseline_issues = _export_data(baseline_id)
    if current["start_url"] != baseline["start_url"]:
        raise HTTPException(422, "Only crawls of the same normalized start URL can be compared.")
    comparison = compare_crawls(current_pages, current_issues, baseline_pages, baseline_issues)
    return templates.TemplateResponse(request, "crawl_comparison.html", _context(request, crawl=current, baseline=baseline, comparison=comparison))


def _embedding_provider():
    try:
        return build_embedding_provider(settings.embedding_provider, settings.embedding_model, settings.embedding_dimension)
    except Exception:
        # A missing optional semantic model never blocks local crawling; hash retrieval remains available.
        return build_embedding_provider("hash", dimension=settings.embedding_dimension)


def _search_knowledge(crawl_id: str, query: str, limit: int = 6) -> list[dict[str, object]]:
    return agentic_retrieve(crawl_id, query, lambda cid, subquery, sublimit: database.search_hybrid_knowledge(cid, subquery, sublimit, _embedding_provider()), limit)


def _answer_generator():
    if settings.answer_provider.strip().lower() not in {"ollama", "local-model", "local_model"}:
        return None
    try:
        return LocalAnswerer(settings.ollama_url, settings.ollama_model, settings.answer_timeout_seconds)
    except Exception:
        return None


def _answer_question(crawl_id: str, question: str) -> dict[str, object]:
    return answer_question(crawl_id, question, _search_knowledge, generator=_answer_generator())


def _reindex_knowledge(crawl_id: str) -> int:
    stored_pages = database.get_pages(crawl_id)
    chunks = extract_pages_knowledge(stored_pages, crawl_id)
    database.replace_knowledge_chunks(crawl_id, chunks, _embedding_provider())
    return len(chunks)


@app.post("/crawls/{crawl_id}/knowledge/reindex", response_class=HTMLResponse)
def reindex_knowledge(request: Request, crawl_id: str) -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "completed":
        raise HTTPException(404, "A completed crawl is required to rebuild knowledge.")
    try:
        count = _reindex_knowledge(crawl_id)
        return templates.TemplateResponse(request, "partials/knowledge_status.html", _context(request, count=count, error=""))
    except Exception as exc:
        return templates.TemplateResponse(request, "partials/knowledge_status.html", _context(request, count=database.knowledge_count(crawl_id), error=f"Knowledge rebuild failed: {type(exc).__name__}: {exc}"), status_code=500)


@app.get("/crawls/{crawl_id}/knowledge/compare/{baseline_id}", response_class=HTMLResponse)
def knowledge_comparison(request: Request, crawl_id: str, baseline_id: str) -> HTMLResponse:
    current = database.get_crawl(crawl_id)
    baseline = database.get_crawl(baseline_id)
    if not current or current["status"] != "completed" or not baseline or baseline["status"] != "completed":
        raise HTTPException(404, "Two completed crawls are required for knowledge comparison.")
    if current["start_url"] != baseline["start_url"]:
        raise HTTPException(422, "Only crawls of the same normalized start URL can be compared.")
    comparison = compare_knowledge(database.get_knowledge_chunks(crawl_id), database.get_knowledge_chunks(baseline_id))
    return templates.TemplateResponse(request, "knowledge_comparison.html", _context(request, crawl=current, baseline=baseline, comparison=comparison))


@app.get("/api/crawls/{crawl_id}/ask")
def ask_crawl_api(crawl_id: str, q: str = "") -> dict[str, object]:
    crawl = database.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "completed":
        raise HTTPException(404, "A completed crawl is required for questions.")
    return _answer_question(crawl_id, q)


@app.post("/crawls/{crawl_id}/ask", response_class=HTMLResponse)
def ask_crawl(request: Request, crawl_id: str, question: Annotated[str, Form()] = "") -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "completed":
        raise HTTPException(404, "A completed crawl is required for questions.")
    result = _answer_question(crawl_id, question)
    return templates.TemplateResponse(request, "partials/knowledge_answer.html", _context(request, result=result, crawl=crawl))


@app.get("/crawls/{crawl_id}/content", response_class=HTMLResponse)
def content_inventory(request: Request, crawl_id: str) -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "completed":
        raise HTTPException(404, "Completed crawl not found.")
    pages = database.get_pages(crawl_id)
    return templates.TemplateResponse(request, "content_inventory.html", _context(request, crawl=crawl, pages=pages, issues=database.get_issues(crawl_id)))


def _export_data(crawl_id: str) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    crawl = database.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "completed":
        raise HTTPException(404, "A completed crawl is required for export.")
    return crawl, database.get_pages(crawl_id), database.get_issues(crawl_id)


@app.get("/crawls/{crawl_id}/export/{kind}")
def export(crawl_id: str, kind: str) -> FileResponse:
    crawl, pages, issues = _export_data(crawl_id)
    if kind == "pages-csv":
        page_path, _ = write_csv_exports(settings.data_dir, crawl, pages, issues)
        path = page_path
    elif kind == "issues-csv":
        _, issue_path = write_csv_exports(settings.data_dir, crawl, pages, issues)
        path = issue_path
    elif kind == "report-html":
        path = write_html_report(settings.data_dir, crawl, pages, issues)
    else:
        raise HTTPException(404, "Unknown export type.")
    return FileResponse(path, filename=path.name, media_type="text/csv" if path.suffix == ".csv" else "text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": str(settings.data_dir)}


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
