"""Bounded extraction for non-HTML resources discovered during an authorized crawl."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from app.ocr import ocr_image, ocr_pdf
from app.urltools import redact_secrets_in_text


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


def format_json_semantics(data: Any, max_chars: int = 250_000) -> str:
    """Format structured JSON into semantic, field-preserving text for search and numerical retrieval."""
    lines: list[str] = []

    if isinstance(data, dict):
        scalars = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        complex_fields = {k: v for k, v in data.items() if isinstance(v, (dict, list))}

        if scalars:
            scalar_summary = ", ".join(f"{k}: {v}" for k, v in scalars.items())
            lines.append(f"Structured API object metadata: {scalar_summary}")
            for k, v in scalars.items():
                lines.append(f"field = {k}, value = {v}")

        for k, v in complex_fields.items():
            if isinstance(v, list):
                lines.append(f"Field '{k}' contains a collection of {len(v)} item(s):")
                for i, item in enumerate(v[:100]):
                    if isinstance(item, dict):
                        item_fields = " | ".join(f"{ik} = {iv}" for ik, iv in item.items() if not isinstance(iv, (dict, list)))
                        lines.append(f"{k}[{i}]: {item_fields}")
                    else:
                        lines.append(f"{k}[{i}] = {item}")
            elif isinstance(v, dict):
                lines.append(f"Field '{k}' (nested object):")
                for sub_k, sub_v in v.items():
                    if not isinstance(sub_v, (dict, list)):
                        lines.append(f"{k}.{sub_k} = {sub_v} (field = {sub_k}, value = {sub_v})")
                    else:
                        lines.append(f"{k}.{sub_k} = {json.dumps(sub_v)[:200]}")
    elif isinstance(data, list):
        lines.append(f"Structured API array of {len(data)} items:")
        for i, item in enumerate(data[:100]):
            if isinstance(item, dict):
                item_fields = " | ".join(f"{ik} = {iv}" for ik, iv in item.items() if not isinstance(iv, (dict, list)))
                lines.append(f"item[{i}]: {item_fields}")
            else:
                lines.append(f"item[{i}] = {item}")
    else:
        lines.append(f"value = {data}")

    full_text = "\n".join(lines)
    return full_text[:max_chars].strip()


def extract_document_text(content_type: str, payload: bytes, max_chars: int = 250_000) -> tuple[str, str]:
    """Return local text plus an explicit extraction note; never pretend binary is readable."""
    normalized = content_type.lower().split(";", 1)[0].strip()
    bounded = payload[: max_chars * 4]
    if normalized == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(bounded), strict=False)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            text = text[:max_chars].strip()
            if text:
                return redact_secrets_in_text(text), ""
            ocr_text, ocr_note = ocr_pdf(bounded)
            return redact_secrets_in_text(ocr_text), ocr_note or "PDF contains no extractable text layer."
        except Exception as exc:  # A bad document is page-level evidence, not a worker failure.
            return "", f"PDF text extraction failed: {type(exc).__name__}: {exc}"
    if normalized.startswith("image/"):
        ocr_text, note = ocr_image(bounded, suffix="." + normalized.split("/", 1)[1])
        return redact_secrets_in_text(ocr_text), note
    if normalized in {"application/json", "application/ld+json"} or normalized.endswith("+json"):
        try:
            raw_str = bounded.decode("utf-8", errors="replace")
            parsed = json.loads(raw_str)
            semantic_text = format_json_semantics(parsed, max_chars)
            return redact_secrets_in_text(semantic_text), ""
        except Exception:
            try:
                raw_text = bounded.decode("utf-8", errors="replace")[:max_chars].strip()
                return redact_secrets_in_text(raw_text), ""
            except Exception as exc:
                return "", f"JSON text extraction failed: {type(exc).__name__}: {exc}"
    if normalized in TEXT_TYPES or normalized.startswith("text/"):
        try:
            raw_text = bounded.decode("utf-8", errors="replace")[:max_chars].strip()
            return redact_secrets_in_text(raw_text), ""
        except Exception as exc:
            return "", f"Text extraction failed: {type(exc).__name__}: {exc}"
    return "", f"No text extractor configured for content type {normalized or 'unknown'}."

