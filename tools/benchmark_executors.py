"""Benchmark bounded crawler executors against a supplied authorized URL list."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from app.config import Settings
from app.crawler import CrawlEngine
from app.types import CrawlRequest
from app.urltools import is_same_host, normalize_url


def run(urls: list[str], modes: list[str], output: Path) -> None:
    urls = [normalize_url(url) for url in urls]
    if not urls or any(not is_same_host(url, urls[0]) for url in urls):
        raise ValueError("All benchmark URLs must use the same normalized scheme and host.")
    settings = Settings.from_environment(Path(__file__).resolve().parents[1])
    rows = []
    for mode in modes:
        request = CrawlRequest(start_url=urls[0], mode="list", url_list=urls, max_urls=len(urls), delay_seconds=0.1, acknowledgment=True, executor_mode=mode)
        started = time.perf_counter()
        pages, links, robots = CrawlEngine(settings).run(request, lambda *_: None)
        rows.append({"executor_mode": mode, "elapsed_seconds": round(time.perf_counter() - started, 4), "requested_urls": len(urls), "pages": len(pages), "links": len(links), "robots_status": robots})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"benchmark": rows, "note": "Compare relative results only; network, server, and delay conditions affect timing."}, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark local crawler executor modes.")
    parser.add_argument("urls", nargs="+", help="Authorized URLs to inspect")
    parser.add_argument("--modes", nargs="+", default=["serial", "thread", "async", "process"], choices=["serial", "thread", "async", "process"])
    parser.add_argument("--output", type=Path, default=Path("benchmark-report.json"))
    args = parser.parse_args()
    run(args.urls, args.modes, args.output)
