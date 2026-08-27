"""Field Manual interface for a local, permission-gated SEO crawler."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.analyzer import analyze_pages
from app.comparison import compare_crawls
from app.config import Settings
from app.crawler import CrawlEngine
from app.database import Database, now
from app.exports import write_csv_exports, write_html_report
from app.types import CrawlRequest
from app.urltools import UrlValidationError, is_same_host, normalize_url, visible_url

ROOT = Path(__file__).resolve().parent.parent
settings = Settings.from_environment(ROOT)
database = Database(settings.database_path)
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
templates.env.filters["visible_url"] = visible_url
active_crawls = threading.Semaphore(settings.max_concurrent_crawls)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="Local SEO Spider", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")


def _context(request: Request, **kwargs: object) -> dict[str, object]:
    return {"request": request, "app_name": "Local SEO Spider", **kwargs}


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


def _run_crawl(crawl_id: str, crawl_request: CrawlRequest) -> None:
    with active_crawls:
        database.update_crawl(crawl_id, status="running", started_at=now(), robots_status="checking")
        def progress(pages_crawled: int, _: int, robots_status: str) -> None:
            database.update_crawl(crawl_id, pages_crawled=pages_crawled, robots_status=robots_status)
        try:
            pages, links, robots_status = CrawlEngine(settings).run(crawl_request, progress)
            issues = analyze_pages(pages, links, crawl_request.start_url)
            database.replace_pages_and_links(crawl_id, pages, links)
            database.replace_issues(crawl_id, issues)
            database.update_crawl(crawl_id, status="completed", completed_at=now(), robots_status=robots_status, pages_crawled=len(pages), issues_found=len(issues))
        except Exception as exc:
            database.update_crawl(crawl_id, status="failed", completed_at=now(), error_message=f"{type(exc).__name__}: {exc}")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html", _context(request, crawls=database.list_crawls(), defaults={"url_cap": settings.default_url_cap, "delay": settings.default_delay_seconds, "max_url_cap": settings.max_url_cap}))


@app.post("/crawls", response_class=HTMLResponse)
def create_crawl(
    request: Request,
    background_tasks: BackgroundTasks,
    start_url: Annotated[str, Form()],
    mode: Annotated[str, Form()] = "site",
    url_list: Annotated[str, Form()] = "",
    max_urls: Annotated[str, Form()] = str(settings.default_url_cap),
    delay_seconds: Annotated[str, Form()] = str(settings.default_delay_seconds),
    respect_nofollow: Annotated[str | None, Form()] = None,
    authorization_acknowledgment: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    try:
        crawl_request = _parse_request(start_url, mode, url_list, max_urls, delay_seconds, respect_nofollow, authorization_acknowledgment)
    except (ValueError, UrlValidationError) as exc:
        return templates.TemplateResponse(request, "partials/crawl_form.html", _context(request, error=str(exc), defaults={"url_cap": settings.default_url_cap, "delay": settings.default_delay_seconds, "max_url_cap": settings.max_url_cap}), status_code=422)
    crawl_id = database.create_crawl(crawl_request)
    background_tasks.add_task(_run_crawl, crawl_id, crawl_request)
    return templates.TemplateResponse(request, "partials/crawl_status.html", _context(request, crawl=database.get_crawl(crawl_id)))


@app.get("/crawls/{crawl_id}/status", response_class=HTMLResponse)
def crawl_status(request: Request, crawl_id: str) -> HTMLResponse:
    crawl = database.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(404, "Crawl not found.")
    return templates.TemplateResponse(request, "partials/crawl_status.html", _context(request, crawl=crawl))


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
    return templates.TemplateResponse(request, "crawl_detail.html", _context(request, crawl=crawl, pages=pages, issues=issues, completed_crawls=completed_crawls))


@app.get("/crawls/{crawl_id}/compare/{baseline_id}", response_class=HTMLResponse)
def crawl_comparison(request: Request, crawl_id: str, baseline_id: str) -> HTMLResponse:
    current, current_pages, current_issues = _export_data(crawl_id)
    baseline, baseline_pages, baseline_issues = _export_data(baseline_id)
    if current["start_url"] != baseline["start_url"]:
        raise HTTPException(422, "Only crawls of the same normalized start URL can be compared.")
    comparison = compare_crawls(current_pages, current_issues, baseline_pages, baseline_issues)
    return templates.TemplateResponse(request, "crawl_comparison.html", _context(request, crawl=current, baseline=baseline, comparison=comparison))


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
