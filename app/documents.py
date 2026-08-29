"""Bounded extraction for non-HTML resources discovered during an authorized crawl."""

from __future__ import annotations

from io import BytesIO
from typing import Any


TEXT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/javascript",
    "text/csv",
    "text/css",
    "text/plain",
    "text/xml",
}


def extract_document_text(content_type: str, payload: bytes, max_chars: int = 250_000) -> tuple[str, str]:
    """Return local text plus an explicit extraction note; never pretend binary is readable."""
    normalized = content_type.lower().split(";", 1)[0]
    bounded = payload[: max_chars * 4]
    if normalized == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(bounded), strict=False)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            text = text[:max_chars].strip()
            if text:
                return text, ""
            return "", "PDF contains no extractable text layer; OCR is not enabled."
        except Exception as exc:  # A bad document is page-level evidence, not a worker failure.
            return "", f"PDF text extraction failed: {type(exc).__name__}: {exc}"
    if normalized in TEXT_TYPES or normalized.startswith("text/"):
        try:
            return bounded.decode("utf-8", errors="replace")[:max_chars].strip(), ""
        except Exception as exc:
            return "", f"Text extraction failed: {type(exc).__name__}: {exc}"
    return "", f"No text extractor configured for content type {normalized or 'unknown'}."
