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
    "fbclid", "gclid", "msclkid", "mc_eid", "ref", "source", "session_id",
    "sid", "spm", "_ga", "_gl", "trk", "yclid", "jsessionid", "phpsessid",
    "aspsessionid", "csrf_token", "state", "__hsfp", "__hssc", "__hstc",
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


def _normalize_path_percent_encoding(path: str) -> str:
    """Decode unreserved percent-encoded characters (RFC 3986) in path."""
    def repl(m: re.Match[str]) -> str:
        code = int(m.group(1), 16)
        ch = chr(code)
        if ch.isalnum() or ch in "-_.~":
            return ch
        return m.group(0).upper()
    return re.sub(r"%([0-9a-fA-F]{2})", repl, path)


def normalize_url(value: str, base_url: str | None = None, allow_private: bool = False) -> str:
    """Canonicalize a URL: strip fragments, normalize host/port, sort query params, strip tracking, redact secrets."""
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

    port = parsed.port
    netloc = hostname_lower
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        netloc = f"{hostname_lower}:{port}"
    
    path = parsed.path or "/"
    path = _normalize_path_percent_encoding(path)
    # Clean duplicate slashes in path
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    
    query = ""
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = []
        for k, v in pairs:
            k_clean = k.strip()
            if not k_clean:
                continue
            if k_clean.lower() in _TRACKING_PARAMS:
                continue
            if k_clean.lower() in _SENSITIVE_PARAM_NAMES:
                filtered_pairs.append((k_clean, "[REDACTED]"))
            else:
                filtered_pairs.append((k_clean, v))
        # Sort query parameters deterministically by key and value
        filtered_pairs.sort(key=lambda item: (item[0], item[1]))
        query = urlencode(filtered_pairs)
    
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


canonicalize_url = normalize_url


def resolve_canonical_url(declared_canonical: str, page_url: str) -> str:
    """Resolve and normalize a declared canonical URL link against the page URL."""
    if not declared_canonical or not declared_canonical.strip():
        return page_url
    try:
        resolved = normalize_url(declared_canonical.strip(), page_url)
        # Ensure it belongs to the same host
        if is_same_host(resolved, page_url):
            return resolved
        return page_url
    except UrlValidationError:
        return page_url


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


def is_same_host(url: str, seed_url: str) -> bool:
    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    return candidate.hostname == seed.hostname and candidate.port == seed.port and candidate.scheme == seed.scheme


def safe_filename(value: str, fallback: str = "export") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return (cleaned[:80] or fallback).lower()


def visible_url(value: str, limit: int = 86) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"

