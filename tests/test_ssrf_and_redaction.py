"""Unit tests for SSRF defenses and secret redaction invariants."""

import pytest
from app.urltools import (
    UrlValidationError,
    is_ssrf_forbidden_ip,
    normalize_url,
    parse_ip_literal,
    redact_secrets_in_text,
    redact_sensitive_url,
    validate_hostname_ssrf,
)


@pytest.mark.parametrize(
    "forbidden_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.253/",
        "http://100.100.100.200/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://instance-data/latest/meta-data/",
        # Octal IPv4
        "http://0177.0.0.1/",
        # Hex IPv4
        "http://0x7f000001/",
        # Dword / Decimal integer IPv4
        "http://2130706433/",
        # IPv6 loopback
        "http://[::1]/",
        # IPv4-mapped IPv6
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        # RFC 1918 Private ranges
        "http://10.0.0.1/admin",
        "http://192.168.1.1/router",
        "http://172.16.0.1/internal",
        "http://127.0.0.1:8080/metrics",
        # Named localhost / internal domains
        "http://localhost:3000/",
        "http://api.localhost/",
        "http://corp.internal/",
        "http://router.local/",
    ],
)
def test_ssrf_forbidden_destinations_blocked(forbidden_url: str) -> None:
    with pytest.raises(UrlValidationError):
        normalize_url(forbidden_url)


def test_ssrf_allowed_public_destinations() -> None:
    assert normalize_url("https://example.com/path") == "https://example.com/path"
    assert normalize_url("http://example.com:8080/api") == "http://example.com:8080/api"
    assert normalize_url("https://owned.example/blog") == "https://owned.example/blog"


def test_ssrf_allow_private_override_still_blocks_cloud_metadata() -> None:
    # When allow_private is True, loopback is allowed (e.g. for local dev/testing)
    assert normalize_url("http://127.0.0.1:8000/api", allow_private=True) == "http://127.0.0.1:8000/api"
    # But cloud metadata is STILL strictly blocked
    with pytest.raises(UrlValidationError):
        normalize_url("http://169.254.169.254/", allow_private=True)
    with pytest.raises(UrlValidationError):
        normalize_url("http://[::ffff:169.254.169.254]/", allow_private=True)


def test_secret_redaction_in_text() -> None:
    sample_text = (
        "Here is the authorization token: Bearer abc123def456ghi789jkl012mno345\n"
        "JWT session: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n"
        "Stripe key: sk_live_51Abcdefghijklmnopqrstuvwx\n"
        "Google API key: AIzaSyD9xExampleKey_abcdefghijklmnop\n"
        "AWS access key: AKIAIOSFODNN7EXAMPLE\n"
        "GitHub token: ghp_1234567890abcdefghijklmnopqrstuvwxyz12\n"
        "Slack token: xoxb-1234567890-abcdefghijklmnop\n"
        "Database: postgres://app_user:SuperSecretPassword123@db.example.com:5432/prod\n"
        "API key config: api_key = 'sec_val_9876543210fedcba'\n"
    )

    redacted = redact_secrets_in_text(sample_text)

    assert "abc123def456ghi789jkl012mno345" not in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "sk_live_51Abcdefghijklmnopqrstuvwx" not in redacted
    assert "AIzaSyD9xExampleKey_abcdefghijklmnop" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz12" not in redacted
    assert "xoxb-1234567890-abcdefghijklmnop" not in redacted
    assert "SuperSecretPassword123" not in redacted
    assert "sec_val_9876543210fedcba" not in redacted
    assert "[REDACTED]" in redacted


def test_sensitive_url_redaction() -> None:
    url = "https://example.com/api?token=secret123&user=jane&api_key=key456"
    redacted = redact_sensitive_url(url)
    assert "secret123" not in redacted
    assert "key456" not in redacted
    assert "user=jane" in redacted
    assert "token=%5BREDACTED%5D" in redacted or "token=[REDACTED]" in redacted
