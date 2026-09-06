"""URL validation, canonicalization, secret redaction, and pagination tools for a bounded crawler."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


class UrlValidationError(ValueError):
    """Raised for malformed or unsafe crawl input."""


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_eid", "ref", "session_id",
    "sid", "spm", "_ga", "_gl", "trk", "yclid", "jsessionid", "phpsessid",
    "aspsessionid", "csrf_token", "__hsfp", "__hssc", "__hstc",
}

_SENSITIVE_PARAM_NAMES = {
    "api_key", "apikey", "token", "auth", "secret", "password", "passwd",
    "access_token", "bearer", "signature", "client_secret", "private_key",
    "jwt", "id_token", "refresh_token", "oauth_token", "session", "sessionid",
    "credentials", "auth_token",
}

_BLOCKED_HOSTNAMES = {
    "169.254.169.254", "metadata.google.internal", "metadata.internal",
    "instance-data", "169.254.169.253", "100.100.100.200",
}

_SECRET_TEXT_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.\~]{15,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    re.compile(r"\b(?:sk|pk)[_-][a-zA-Z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{30,45}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|bearer|auth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?"),
    re.compile(r"(?i)\b(?:postgres|mysql|mongodb|redis)://[^:]+:([^@\s]+)@"),
]


def parse_ip_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse various IP literal formats including standard decimal, octal, hex, dword, and IPv6."""
    raw = hostname.strip().strip("[]")
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        pass

    try:
        ip_bytes = socket.inet_aton(raw)
        return ipaddress.IPv4Address(ip_bytes)
    except (OSError, ValueError):
        pass

    if raw.isdigit():
        try:
            val = int(raw)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    return None


def is_ssrf_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool = False) -> bool:
    """Check if an IP address violates SSRF policy."""
    if isinstance(ip_obj, ipaddress.IPv4Address):
        if str(ip_obj) in {"169.254.169.254", "169.254.169.253", "100.100.100.200"}:
            return True

    if isinstance(ip_obj, ipaddress.IPv6Address):
        if ip_obj.ipv4_mapped:
            mapped = ip_obj.ipv4_mapped
            if str(mapped) in {"169.254.169.254", "169.254.169.253", "100.100.100.200"}:
                return True
            if not allow_private and (mapped.is_private or mapped.is_loopback or mapped.is_link_local):
                return True

    if not allow_private:
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return True

    return False


def validate_hostname_ssrf(hostname: str, allow_private: bool = False) -> None:
    """Validate that a hostname does not target protected endpoints or internal infrastructure."""
    h_lower = hostname.lower().rstrip(".").strip("[]")
    if not h_lower:
        raise UrlValidationError("Host cannot be empty.")

    if h_lower in _BLOCKED_HOSTNAMES or h_lower.endswith(".metadata.google.internal") or h_lower == "metadata.google.internal":
        raise UrlValidationError(f"Forbidden destination: {h_lower} is a protected internal/metadata endpoint.")

    ip_obj = parse_ip_literal(h_lower)
    if ip_obj is not None:
        if is_ssrf_forbidden_ip(ip_obj, allow_private=allow_private):
            raise UrlValidationError(f"Forbidden destination: IP {ip_obj} is a private, loopback, or metadata address.")
        return

    if not allow_private:
        if h_lower == "localhost" or h_lower.endswith(".localhost") or h_lower.endswith(".local") or h_lower.endswith(".internal"):
            raise UrlValidationError(f"Forbidden destination: {h_lower} resolves to local or internal infrastructure.")


def redact_secrets_in_text(text: str) -> str:
    """Redact API keys, tokens, JWTs, and credentials in extracted text and chunks."""
    if not text:
        return ""
    result = text
    for pattern in _SECRET_TEXT_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def redact_sensitive_url(url: str) -> str:
    """Safely redact credentials in userinfo and sensitive query parameters."""
    if not url:
        return ""
    try:
        parsed = urlsplit(url.strip())
        netloc = parsed.hostname or ""
        if parsed.port and not ((parsed.scheme == "http" and parsed.port == 80) or (parsed.scheme == "https" and parsed.port == 443)):
            netloc = f"{netloc}:{parsed.port}"
        
        # Redact query params
        if parsed.query:
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            redacted_pairs = []
            for k, v in pairs:
                k_clean = k.strip()
                if not k_clean:
                    continue
                if k_clean.lower() in _SENSITIVE_PARAM_NAMES:
                    redacted_pairs.append((k_clean, "[REDACTED]"))
                else:
                    redacted_pairs.append((k_clean, v))
            query = urlencode(redacted_pairs)
        else:
            query = ""
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))
    except Exception:
        return url


from dataclasses import dataclass

_UNRESERVED_BYTES = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")


@dataclass(frozen=True)
class UrlNormalizationPolicy:
    """Policy for URL canonicalization and normalization preserving resource identity."""

    strip_fragment: bool = True
    normalize_case: bool = True
    remove_default_port: bool = True
    resolve_dot_segments: bool = True
    normalize_percent_encoding: bool = True
    collapse_path_slashes: bool = True
    sort_query_params: bool = True
    dedup_query_params: bool = True
    strip_tracking_params: bool = True
    redact_sensitive_params: bool = False
    strip_session_ids: bool = True
    trailing_slash: str = "strip"  # "preserve", "strip", "append"


def remove_dot_segments(path: str) -> str:
    """RFC 3986 Section 5.2.4: Remove dot segments from path while preserving leading/trailing slashes."""
    if not path or path == "/":
        return "/"
    is_absolute = path.startswith("/")
    # Path indicates directory if ending in slash or dot-segments
    ends_with_dir = path.endswith("/") or path.endswith("/.") or path.endswith("/..")

    segments = path.split("/")
    output: list[str] = []
    for segment in segments:
        if segment == "" or segment == ".":
            continue
        elif segment == "..":
            if output:
                output.pop()
        else:
            output.append(segment)

    result = ("/" if is_absolute else "") + "/".join(output)
    if not result:
        return "/"
    if ends_with_dir and not result.endswith("/"):
        result += "/"
    return result


def normalize_percent_encoding(text: str) -> str:
    """Decode unreserved percent-encoded characters and uppercase hex digits in reserved sequences (RFC 3986)."""
    def repl(m: re.Match[str]) -> str:
        hex_digits = m.group(1)
        byte_val = int(hex_digits, 16)
        if byte_val in _UNRESERVED_BYTES:
            return chr(byte_val)
        return f"%{hex_digits.upper()}"
    return re.sub(r"%([0-9a-fA-F]{2})", repl, text)


def normalize_query_string(
    query: str,
    strip_tracking: bool = True,
    redact_sensitive: bool = True,
    sort_params: bool = True,
    dedup_params: bool = True,
) -> str:
    """Normalize query string: strip tracking, redact sensitive, dedup identical pairs, and sort deterministically."""
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    seen_pairs: set[tuple[str, str]] = set()
    cleaned_pairs: list[tuple[str, str]] = []

    for k, v in pairs:
        k_clean = k.strip()
        if not k_clean:
            continue
        k_lower = k_clean.lower()
        if strip_tracking and k_lower in _TRACKING_PARAMS:
            continue
        val = "[REDACTED]" if (redact_sensitive and k_lower in _SENSITIVE_PARAM_NAMES) else v
        pair = (k_clean, val)
        if dedup_params:
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
        cleaned_pairs.append(pair)

    if sort_params:
        cleaned_pairs.sort(key=lambda item: (item[0], item[1]))

    return urlencode(cleaned_pairs, safe="[]")


def normalize_url(
    value: str,
    base_url: str | None = None,
    allow_private: bool = False,
    policy: UrlNormalizationPolicy | None = None,
) -> str:
    """Canonicalize a URL: strip fragments, normalize host/port, sort query params, strip tracking, redact secrets."""
    if policy is None:
        policy = UrlNormalizationPolicy()

    candidate = urljoin(base_url, value) if base_url else value
    parsed = urlsplit(candidate.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UrlValidationError("Only http:// and https:// URLs are supported.")
    if not parsed.hostname:
        raise UrlValidationError("Enter a complete URL with a hostname.")
    if parsed.username or parsed.password:
        raise UrlValidationError("URLs containing credentials are not accepted.")

    validate_hostname_ssrf(parsed.hostname, allow_private=allow_private)
    hostname_lower = parsed.hostname.lower().rstrip(".").strip("[]")
    is_ipv6 = ":" in hostname_lower
    formatted_host = f"[{hostname_lower}]" if is_ipv6 else hostname_lower

    port = parsed.port
    netloc = formatted_host
    if port:
        if policy.remove_default_port and (
            (parsed.scheme.lower() == "http" and port == 80)
            or (parsed.scheme.lower() == "https" and port == 443)
        ):
            netloc = formatted_host
        else:
            netloc = f"{formatted_host}:{port}"

    path = parsed.path or "/"
    if policy.strip_session_ids:
        # Strip path-embedded session tokens (Java servlet, ASP.NET cookieless, PHP sid)
        path = re.sub(r";(?:jsessionid|sid|phpsessid)=[A-Za-z0-9_\-]+", "", path, flags=re.IGNORECASE)
        path = re.sub(r"/\([Ss]\([A-Za-z0-9_\-]{6,}\)\)", "", path)
    if policy.resolve_dot_segments:
        path = remove_dot_segments(path)
    if policy.normalize_percent_encoding:
        path = normalize_percent_encoding(path)
    if policy.collapse_path_slashes:
        path = re.sub(r"/+", "/", path)

    if policy.trailing_slash == "strip":
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
    elif policy.trailing_slash == "append":
        if not path.endswith("/"):
            path = path + "/"
    # "preserve": do not modify trailing slash

    query = ""
    if parsed.query:
        query = normalize_query_string(
            parsed.query,
            strip_tracking=policy.strip_tracking_params,
            redact_sensitive=policy.redact_sensitive_params,
            sort_params=policy.sort_query_params,
            dedup_params=policy.dedup_query_params,
        )

    fragment = "" if policy.strip_fragment else parsed.fragment
    scheme = parsed.scheme.lower() if policy.normalize_case else parsed.scheme

    return urlunsplit((scheme, netloc, path, query, fragment))


canonicalize_url = normalize_url


def resolve_canonical_url(
    declared_canonical: str,
    page_url: str,
    allow_private: bool = False,
    policy: UrlNormalizationPolicy | None = None,
) -> str:
    """Resolve and normalize a declared canonical URL link against the page URL."""
    if not declared_canonical or not declared_canonical.strip():
        return page_url
    try:
        resolved = normalize_url(declared_canonical.strip(), page_url, allow_private=allow_private, policy=policy)
        # Ensure it belongs to the same host
        if is_same_host(resolved, page_url):
            return resolved
        return page_url
    except UrlValidationError:
        return page_url


def resolve_redirect_url(
    location: str,
    current_url: str,
    allow_private: bool = False,
    policy: UrlNormalizationPolicy | None = None,
) -> str:
    """Resolve a redirect Location header relative to the current requesting URL."""
    if not location or not location.strip():
        raise UrlValidationError("Empty redirect location.")
    return normalize_url(location.strip(), base_url=current_url, allow_private=allow_private, policy=policy)


def detect_api_pagination(url: str) -> tuple[bool, str, int]:
    """Detect if a URL is an API pagination endpoint and extract pagination offset/page."""
    parsed = urlsplit(url)
    if not parsed.query:
        return False, parsed.path, 0
    pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    pagination_keys = ["skip", "offset", "page", "p", "start", "from", "limit", "size"]
    for key in pagination_keys:
        if key in pairs:
            try:
                val = int(pairs[key])
                return True, parsed.path, val
            except ValueError:
                pass
    if "cursor" in pairs:
        return True, parsed.path, 1
    return False, parsed.path, 0


def _effective_port(parsed) -> int:
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme.lower() == "https" else 80


def is_same_host(url: str, seed_url: str) -> bool:
    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    cand_host = (candidate.hostname or "").lower().rstrip(".")
    seed_host = (seed.hostname or "").lower().rstrip(".")
    return (
        cand_host == seed_host
        and _effective_port(candidate) == _effective_port(seed)
        and candidate.scheme.lower() == seed.scheme.lower()
    )


def safe_filename(value: str, fallback: str = "export") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return (cleaned[:80] or fallback).lower()


def visible_url(value: str, limit: int = 86) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"
    

def detect_path_loop(url_or_path: str, max_repeats: int = 3) -> bool:
    """Detect repeating directory loops / cyclic path traps (e.g. /a/b/a/b/a/b)."""
    if not url_or_path:
        return False
    try:
        path = urlsplit(url_or_path).path if ("://" in url_or_path or url_or_path.startswith("//")) else url_or_path
        path = path.split("?")[0].split("#")[0]
        segments = [s.lower() for s in path.split("/") if s]
        n = len(segments)
        if n < max_repeats:
            return False

        # Check sequence lengths k from 1 to 5
        for k in range(1, min(6, n // max_repeats + 1)):
            for start in range(0, n - k * max_repeats + 1):
                pattern = segments[start : start + k]
                repeats = 1
                curr = start + k
                while curr + k <= n and segments[curr : curr + k] == pattern:
                    repeats += 1
                    curr += k
                if repeats >= max_repeats:
                    return True
        return False
    except Exception:
        return False

