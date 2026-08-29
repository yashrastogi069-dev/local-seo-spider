"""Local website knowledge extraction and citation-preserving chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class KnowledgeChunk:
    """A searchable passage with enough provenance to verify an answer."""

    page_id: int
    crawl_id: str
    url: str
    title: str
    heading_path: str
    content: str
    chunk_index: int

    def as_row(self) -> tuple[int, str, str, str, str, str, int]:
        return (self.page_id, self.crawl_id, self.url, self.title, self.heading_path, self.content, self.chunk_index)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _blocks_from_html(html: str) -> list[tuple[str, str]]:
    """Return readable blocks paired with the nearest heading context."""
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup(["script", "style", "noscript", "template", "svg"]):
        element.decompose()

    heading_stack: list[str] = []
    blocks: list[tuple[str, str]] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "blockquote", "td", "th"]):
        text = _clean_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if element.name and element.name.startswith("h"):
            level = int(element.name[1:])
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(text[:300])
            continue
        blocks.append((" > ".join(heading_stack), text))
    return blocks


def _split_text(text: str, max_chars: int = 1400) -> Iterable[str]:
    words = text.split()
    current: list[str] = []
    length = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > max_chars:
            yield " ".join(current)
            current = []
            length = 0
        current.append(word)
        length += extra
    if current:
        yield " ".join(current)


def extract_knowledge_chunks(page: dict[str, Any], crawl_id: str, max_chars: int = 1400) -> list[KnowledgeChunk]:
    """Extract meaningful page passages while retaining page and heading provenance."""
    html = str(page.get("rendered_html") or page.get("source_html") or "")
    blocks = _blocks_from_html(html)
    if not blocks and page.get("rendered_text"):
        blocks = [("", _clean_text(str(page["rendered_text"]))) ]
    if not blocks and page.get("extracted_text"):
        blocks = [("", _clean_text(str(page["extracted_text"]))) ]

    chunks: list[KnowledgeChunk] = []
    pending_heading = ""
    buffer: list[str] = []
    buffer_length = 0

    def flush() -> None:
        nonlocal buffer, buffer_length
        if not buffer:
            return
        for part in _split_text(" ".join(buffer), max_chars):
            chunks.append(
                KnowledgeChunk(
                    page_id=int(page["id"]),
                    crawl_id=crawl_id,
                    url=str(page["url"]),
                    title=str(page.get("title") or ""),
                    heading_path=pending_heading,
                    content=part,
                    chunk_index=len(chunks),
                )
            )
        buffer = []
        buffer_length = 0

    for heading, text in blocks:
        if heading != pending_heading and buffer:
            flush()
        pending_heading = heading
        if buffer and buffer_length + len(text) + 1 > max_chars:
            flush()
        buffer.append(text)
        buffer_length += len(text) + 1
    flush()
    return chunks


def compare_knowledge(current: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Compare citation-bearing chunks without pretending content changes have a cause."""
    def key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (str(item.get("url", "")), str(item.get("heading_path", "")), str(item.get("content", "")))

    current_by_key = {key(item): item for item in current}
    baseline_by_key = {key(item): item for item in baseline}
    return {
        "added": [current_by_key[item] for item in sorted(set(current_by_key) - set(baseline_by_key))],
        "removed": [baseline_by_key[item] for item in sorted(set(baseline_by_key) - set(current_by_key))],
    }


def extract_pages_knowledge(pages: list[dict[str, Any]], crawl_id: str) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for page in pages:
        content_type = page.get("content_type", "").lower().split(";", 1)[0]
        supported = {"", "text/html", "application/xhtml+xml", "application/pdf", "application/json", "application/ld+json", "application/xml", "text/xml", "text/plain", "text/csv"}
        if content_type not in supported and not content_type.startswith("text/"):
            continue
        if page.get("fetch_error") or not page.get("robots_allowed", True):
            continue
        chunks.extend(extract_knowledge_chunks(page, crawl_id))
    return chunks
