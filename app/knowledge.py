"""Local website knowledge extraction, source provenance preservation, and citation-preserving chunking."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from app.documents import format_json_semantics
from app.urltools import redact_secrets_in_text


@dataclass(frozen=True)
class KnowledgeChunk:
    """A searchable passage with rich provenance and structural metadata to verify answers."""

    page_id: int
    crawl_id: str
    url: str
    title: str
    heading_path: str
    content: str
    chunk_index: int
    canonical_url: str = ""
    section: str = ""
    heading_path_list: list[str] = field(default_factory=list)
    content_type: str = "text/html"
    source_type: str = "html_page"
    crawl_timestamp: str = ""
    parent_url: str = ""
    depth: int = 0
    content_hash: str = ""

    def as_row(self) -> tuple[int, str, str, str, str, str, str, str, str, str, str, str, int, str, str, int]:
        return (
            self.page_id,
            self.crawl_id,
            self.url,
            self.canonical_url,
            self.title,
            self.section,
            self.heading_path,
            json.dumps(self.heading_path_list),
            self.content_type,
            self.source_type,
            self.crawl_timestamp,
            self.parent_url,
            self.depth,
            self.content_hash,
            self.content,
            self.chunk_index,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def infer_source_type(url: str, content_type: str) -> str:
    """Infer provenance source quality category."""
    norm_ct = (content_type or "").lower()
    if "json" in norm_ct or re.search(r"/(?:api|v\d+|rest|graphql)(?:/|$|\?)", url, re.IGNORECASE):
        return "official_api"
    if "pdf" in norm_ct:
        return "document"
    if re.search(r"/(?:docs|documentation|guide|manual|reference|api-docs)(?:/|$|\?)", url, re.IGNORECASE):
        return "documentation"
    parsed = urlsplit(url)
    if parsed.path in {"", "/"}:
        return "landing_page"
    return "html_page"


def _blocks_from_html(html: str) -> list[tuple[str, list[str], str]]:
    """Return readable blocks paired with the nearest heading context and heading stack."""
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup(["script", "style", "noscript", "template", "svg"]):
        element.decompose()

    heading_stack: list[str] = []
    blocks: list[tuple[str, list[str], str]] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "blockquote", "td", "th"]):
        text = _clean_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if element.name and element.name.startswith("h"):
            try:
                level = int(element.name[1:])
            except ValueError:
                level = 1
            heading_stack = heading_stack[: max(0, level - 1)]
            heading_stack.append(text[:300])
            continue
        blocks.append((" > ".join(heading_stack), list(heading_stack), text))
    return blocks


def _split_text(text: str, max_chars: int = 1400, overlap_chars: int = 180) -> Iterable[str]:
    words = text.split()
    current: list[str] = []
    length = 0
    previous = ""
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > max_chars:
            chunk = " ".join(current).strip()
            if chunk and chunk != previous:
                yield chunk
            overlap: list[str] = []
            overlap_len = 0
            for prior in reversed(current):
                if overlap_len + len(prior) + 1 > overlap_chars:
                    break
                overlap.insert(0, prior)
                overlap_len += len(prior) + 1
            current = overlap
            length = len(" ".join(current))
            previous = chunk
        current.append(word)
        length += extra
    if current:
        chunk = " ".join(current).strip()
        if chunk and chunk != previous:
            yield chunk


def deduplicate_chunks(chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    """Eliminate identical content chunks across pages to prevent duplicate indexing and embeddings."""
    seen_hashes: set[str] = set()
    unique_chunks: list[KnowledgeChunk] = []
    for chunk in chunks:
        chash = chunk.content_hash or sha256(re.sub(r"\s+", " ", chunk.content.lower().strip()).encode("utf-8")).hexdigest()
        if chash in seen_hashes:
            continue
        seen_hashes.add(chash)
        if not chunk.content_hash:
            chunk = KnowledgeChunk(
                page_id=chunk.page_id,
                crawl_id=chunk.crawl_id,
                url=chunk.url,
                title=chunk.title,
                heading_path=chunk.heading_path,
                content=chunk.content,
                chunk_index=len(unique_chunks),
                canonical_url=chunk.canonical_url,
                section=chunk.section,
                heading_path_list=chunk.heading_path_list,
                content_type=chunk.content_type,
                source_type=chunk.source_type,
                crawl_timestamp=chunk.crawl_timestamp,
                parent_url=chunk.parent_url,
                depth=chunk.depth,
                content_hash=chash,
            )
        unique_chunks.append(chunk)
    return unique_chunks


def _chunks_from_json(page: Any, crawl_id: str, max_chars: int = 1400) -> list[KnowledgeChunk]:
    """Extract structured, semantically tagged knowledge chunks from API/JSON responses."""
    if hasattr(page, "to_dict"):
        page_dict = page.to_dict()
        page_id = getattr(page, "id", 1)
    elif isinstance(page, dict):
        page_dict = page
        page_id = page.get("id", 1)
    else:
        page_dict = vars(page)
        page_id = getattr(page, "id", 1)

    url = str(page_dict.get("url", ""))
    canonical_url = str(page_dict.get("canonical") or url)
    title = str(page_dict.get("title") or f"API {urlsplit(url).path}")
    source_type = "official_api"
    content_type = page_dict.get("content_type", "application/json")
    crawl_timestamp = str(page_dict.get("discovered_at", ""))
    parent_url = str(page_dict.get("parent_url", ""))
    depth = int(page_dict.get("depth", 0))

    # Locate and parse JSON payload
    data = None
    raw_payload = ""
    for candidate in [page_dict.get("source_html"), page_dict.get("extracted_text"), page_dict.get("rendered_text")]:
        if candidate and isinstance(candidate, str) and candidate.strip():
            try:
                parsed = json.loads(candidate.strip())
                if isinstance(parsed, (dict, list)):
                    data = parsed
                    raw_payload = candidate
                    break
            except Exception:
                pass

    if not raw_payload:
        raw_payload = str(page_dict.get("extracted_text") or page_dict.get("rendered_text") or page_dict.get("source_html") or "")
    if not raw_payload.strip():
        return []

    chunks: list[KnowledgeChunk] = []

    if isinstance(data, dict):
        # Extract top-level scalars/metadata as first chunk
        scalars = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        if scalars:
            scalar_content = format_json_semantics(scalars)
            scalar_content = redact_secrets_in_text(scalar_content)
            chash = sha256(scalar_content.encode("utf-8")).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    page_id=int(page_id),
                    crawl_id=crawl_id,
                    url=url,
                    title=title,
                    heading_path="API > Metadata",
                    content=scalar_content,
                    chunk_index=len(chunks),
                    canonical_url=canonical_url,
                    section="Metadata",
                    heading_path_list=["API", "Metadata"],
                    content_type=content_type,
                    source_type=source_type,
                    crawl_timestamp=crawl_timestamp,
                    parent_url=parent_url,
                    depth=depth,
                    content_hash=chash,
                )
            )

        # Extract collections / arrays
        for k, v in data.items():
            if isinstance(v, list) and v:
                # Group items into chunks
                batch: list[str] = []
                batch_len = 0
                item_group_start = 0
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        item_str = f"{k}[{i}]: " + " | ".join(f"{ik} = {iv}" for ik, iv in item.items() if not isinstance(iv, (dict, list)))
                    else:
                        item_str = f"{k}[{i}] = {item}"
                    if batch and batch_len + len(item_str) + 1 > max_chars:
                        content_str = redact_secrets_in_text("\n".join(batch))
                        chash = sha256(content_str.encode("utf-8")).hexdigest()
                        section_name = f"{k} items {item_group_start}-{i - 1}"
                        chunks.append(
                            KnowledgeChunk(
                                page_id=int(page_id),
                                crawl_id=crawl_id,
                                url=url,
                                title=title,
                                heading_path=f"API > {k} > items",
                                content=content_str,
                                chunk_index=len(chunks),
                                canonical_url=canonical_url,
                                section=section_name,
                                heading_path_list=["API", k, "items"],
                                content_type=content_type,
                                source_type=source_type,
                                crawl_timestamp=crawl_timestamp,
                                parent_url=parent_url,
                                depth=depth,
                                content_hash=chash,
                            )
                        )
                        batch = []
                        batch_len = 0
                        item_group_start = i
                    batch.append(item_str)
                    batch_len += len(item_str) + 1
                if batch:
                    content_str = redact_secrets_in_text("\n".join(batch))
                    chash = sha256(content_str.encode("utf-8")).hexdigest()
                    section_name = f"{k} items {item_group_start}-{len(v) - 1}"
                    chunks.append(
                        KnowledgeChunk(
                            page_id=int(page_id),
                            crawl_id=crawl_id,
                            url=url,
                            title=title,
                            heading_path=f"API > {k} > items",
                            content=content_str,
                            chunk_index=len(chunks),
                            canonical_url=canonical_url,
                            section=section_name,
                            heading_path_list=["API", k, "items"],
                            content_type=content_type,
                            source_type=source_type,
                            crawl_timestamp=crawl_timestamp,
                            parent_url=parent_url,
                            depth=depth,
                            content_hash=chash,
                        )
                    )
    elif isinstance(data, list):
        batch = []
        batch_len = 0
        item_group_start = 0
        for i, item in enumerate(data):
            if isinstance(item, dict):
                item_str = f"item[{i}]: " + " | ".join(f"{ik} = {iv}" for ik, iv in item.items() if not isinstance(iv, (dict, list)))
            else:
                item_str = f"item[{i}] = {item}"
            if batch and batch_len + len(item_str) + 1 > max_chars:
                content_str = redact_secrets_in_text("\n".join(batch))
                chash = sha256(content_str.encode("utf-8")).hexdigest()
                chunks.append(
                    KnowledgeChunk(
                        page_id=int(page_id),
                        crawl_id=crawl_id,
                        url=url,
                        title=title,
                        heading_path="API > items",
                        content=content_str,
                        chunk_index=len(chunks),
                        canonical_url=canonical_url,
                        section=f"items {item_group_start}-{i - 1}",
                        heading_path_list=["API", "items"],
                        content_type=content_type,
                        source_type=source_type,
                        crawl_timestamp=crawl_timestamp,
                        parent_url=parent_url,
                        depth=depth,
                        content_hash=chash,
                    )
                )
                batch = []
                batch_len = 0
                item_group_start = i
            batch.append(item_str)
            batch_len += len(item_str) + 1
        if batch:
            content_str = redact_secrets_in_text("\n".join(batch))
            chash = sha256(content_str.encode("utf-8")).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    page_id=int(page_id),
                    crawl_id=crawl_id,
                    url=url,
                    title=title,
                    heading_path="API > items",
                    content=content_str,
                    chunk_index=len(chunks),
                    canonical_url=canonical_url,
                    section=f"items {item_group_start}-{len(data) - 1}",
                    heading_path_list=["API", "items"],
                    content_type=content_type,
                    source_type=source_type,
                    crawl_timestamp=crawl_timestamp,
                    parent_url=parent_url,
                    depth=depth,
                    content_hash=chash,
                )
            )

    # Fallback to splitting formatted text if data couldn't be parsed as dict/list
    if not chunks and raw_payload:
        for part in _split_text(raw_payload, max_chars):
            clean_part = redact_secrets_in_text(part)
            chash = sha256(clean_part.encode("utf-8")).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    page_id=int(page_id),
                    crawl_id=crawl_id,
                    url=url,
                    title=title,
                    heading_path="API > Content",
                    content=clean_part,
                    chunk_index=len(chunks),
                    canonical_url=canonical_url,
                    section="Content",
                    heading_path_list=["API", "Content"],
                    content_type=content_type,
                    source_type=source_type,
                    crawl_timestamp=crawl_timestamp,
                    parent_url=parent_url,
                    depth=depth,
                    content_hash=chash,
                )
            )
    return chunks


def extract_knowledge_chunks(page: dict[str, Any] | Any, crawl_id: str, max_chars: int = 1400) -> list[KnowledgeChunk]:
    """Extract meaningful page passages while retaining rich metadata, heading provenance, and source quality."""
    if hasattr(page, "to_dict"):
        page_dict = page.to_dict()
        page_id = getattr(page, "id", 1)
    elif isinstance(page, dict):
        page_dict = page
        page_id = page.get("id", 1)
    else:
        page_dict = vars(page)
        page_id = getattr(page, "id", 1)

    content_type = page_dict.get("content_type", "").lower().split(";", 1)[0].strip()
    url = str(page_dict.get("url", ""))
    canonical_url = str(page_dict.get("canonical") or url)
    title = str(page_dict.get("title") or "")
    source_type = infer_source_type(url, content_type)
    crawl_timestamp = str(page_dict.get("discovered_at", ""))
    parent_url = str(page_dict.get("parent_url", ""))
    depth = int(page_dict.get("depth", 0))

    if "json" in content_type:
        return _chunks_from_json(page, crawl_id, max_chars)

    html = str(page_dict.get("rendered_html") or page_dict.get("source_html") or "")
    blocks = _blocks_from_html(html)
    if not blocks and page_dict.get("rendered_text"):
        blocks = [("", [], _clean_text(str(page_dict["rendered_text"])))]
    if not blocks and page_dict.get("extracted_text"):
        blocks = [("", [], _clean_text(str(page_dict["extracted_text"])))]

    chunks: list[KnowledgeChunk] = []
    pending_heading = ""
    pending_stack: list[str] = []
    buffer: list[str] = []
    buffer_length = 0

    def flush() -> None:
        nonlocal buffer, buffer_length
        if not buffer:
            return
        section = pending_stack[-1] if pending_stack else (pending_heading or "Overview")
        full_text = redact_secrets_in_text(" ".join(buffer))
        for part in _split_text(full_text, max_chars):
            chash = sha256(re.sub(r"\s+", " ", part.lower().strip()).encode("utf-8")).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    page_id=int(page_id),
                    crawl_id=crawl_id,
                    url=url,
                    title=title,
                    heading_path=pending_heading or section,
                    content=part,
                    chunk_index=len(chunks),
                    canonical_url=canonical_url,
                    section=section,
                    heading_path_list=list(pending_stack) if pending_stack else [section],
                    content_type=content_type or "text/html",
                    source_type=source_type,
                    crawl_timestamp=crawl_timestamp,
                    parent_url=parent_url,
                    depth=depth,
                    content_hash=chash,
                )
            )
        buffer = []
        buffer_length = 0

    for heading, stack, text in blocks:
        if heading != pending_heading and buffer:
            flush()
        pending_heading = heading
        pending_stack = stack
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
    """Extract and deduplicate knowledge chunks across all eligible pages in a crawl."""
    chunks: list[KnowledgeChunk] = []
    for page in pages:
        content_type = page.get("content_type", "").lower().split(";", 1)[0].strip()
        supported = {"", "text/html", "application/xhtml+xml", "application/pdf", "application/json", "application/ld+json", "application/xml", "text/xml", "text/plain", "text/csv"}
        if content_type not in supported and not content_type.startswith("text/"):
            continue
        if page.get("fetch_error") or not page.get("robots_allowed", True):
            continue
        if page.get("is_duplicate", False):
            continue
        chunks.extend(extract_knowledge_chunks(page, crawl_id))
    return deduplicate_chunks(chunks)

