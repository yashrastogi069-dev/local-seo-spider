"""Smart escalation detector for crawler fetch strategy (Phase 2E).

Explicit criteria determining when a static HTTP acquisition requires automatic
escalation to Playwright browser rendering.
"""

from __future__ import annotations

import re

# Explicit signatures indicating bot protection or JavaScript verification challenges
CHALLENGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"checking your browser before accessing", re.IGNORECASE),
    re.compile(r"just a moment\.\.\.", re.IGNORECASE),
    re.compile(r"enable javascript (?:and cookies )?to (?:continue|view)", re.IGNORECASE),
    re.compile(r"cf-browser-verification", re.IGNORECASE),
    re.compile(r"challenge-running", re.IGNORECASE),
    re.compile(r"<noscript>.*?enable javascript.*?</noscript>", re.IGNORECASE | re.DOTALL),
]

# Root mount elements used by client-side Single Page Applications (React, Vue, Angular, Next.js)
SPA_CONTAINER_PATTERNS: list[re.Pattern] = [
    re.compile(r'<div\b[^>]*\bid=["\'](?:root|app|__next)["\'][^>]*>\s*</div>', re.IGNORECASE),
    re.compile(r'<main\b[^>]*\bid=["\'](?:root|app|__next)["\'][^>]*>\s*</main>', re.IGNORECASE),
    re.compile(r'<app-root\b[^>]*>\s*</app-root>', re.IGNORECASE),
]


def should_escalate_to_browser(
    status_code: int | None,
    headers: dict[str, str],
    source_html: str,
    extracted_text: str,
    configured_fetch_mode: str = "smart",
) -> tuple[bool, str]:
    """Determine whether static HTTP acquisition should escalate to browser rendering.

    Criteria:
    1. Configured Browser Requirement: If the crawl specifically requested browser rendering.
    2. JavaScript Challenge: Bot verification or protection gate requiring browser JS execution.
    3. Empty Application Shell: SPA mount point present with script bundles and minimal body text (< 100 chars).
    4. Required Rendered DOM Absent: Page contains script tags but body has minimal readable text (< 30 chars).

    Anti-Criteria (Never Escalate):
    - Normal static HTML with script tags (analytics, trackers, widgets) where readable body text is present.
    - Non-HTML responses (PDF, plain text, JSON, CSV).
    - Definite HTTP errors (404, 500) that do not contain a JS challenge.

    Returns:
        tuple[bool, str]: (should_escalate, escalation_reason)
    """
    if configured_fetch_mode == "browser":
        return True, "configured_browser_requirement"

    if configured_fetch_mode != "smart":
        return False, ""

    # Content-type check: non-HTML resources cannot be rendered in a browser
    headers_lower = {k.lower(): v for k, v in headers.items()} if headers else {}
    content_type = headers_lower.get("content-type", "").lower()
    if content_type and "html" not in content_type:
        return False, ""

    if not source_html:
        return False, ""

    # Rule 1: JavaScript Challenge / Protection gate
    # Can occur on 200, 403, or 503
    for pattern in CHALLENGE_PATTERNS:
        if pattern.search(source_html):
            return True, "js_challenge"

    # Don't escalate on standard error codes that aren't challenges
    if status_code is not None and status_code not in (200, 201, 202, 203, 204, 206):
        return False, ""

    # Clean text length (whitespace-normalized)
    text_len = len(" ".join(extracted_text.split()))

    has_scripts = "<script" in source_html.lower()

    # Rule 2: Empty Client-Side Application Shell
    # SPA root mount point exists, script bundle present, and visible text is negligible (< 100 chars)
    if has_scripts and text_len < 100:
        for pattern in SPA_CONTAINER_PATTERNS:
            if pattern.search(source_html):
                return True, "empty_application_shell"

    # Rule 3: Required Rendered DOM Absent
    # Body exists, has scripts, but visible text is virtually empty (< 30 chars)
    if has_scripts and text_len < 30 and ("<body" in source_html.lower()):
        return True, "required_dom_absent"

    # Conservative Policy: Normal static HTML with script tags must NOT escalate.
    return False, ""
