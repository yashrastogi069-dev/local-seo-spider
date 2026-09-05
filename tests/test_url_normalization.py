"""Unit and invariant tests for URL normalization and canonicalization policy (Phase 2B)."""

import pytest

from app.urltools import (
    UrlNormalizationPolicy,
    UrlValidationError,
    canonicalize_url,
    normalize_percent_encoding,
    normalize_query_string,
    normalize_url,
    remove_dot_segments,
    resolve_canonical_url,
    resolve_redirect_url,
)


def test_scheme_normalization():
    """Verify schemes are normalized to lowercase and non-http schemes are rejected."""
    assert normalize_url("HTTP://example.com/path") == "http://example.com/path"
    assert normalize_url("HTTPS://example.com/path") == "https://example.com/path"
    assert normalize_url("hTtP://example.com/") == "http://example.com/"

    with pytest.raises(UrlValidationError, match="Only http:// and https:// URLs are supported"):
        normalize_url("ftp://example.com/file")

    with pytest.raises(UrlValidationError, match="Only http:// and https:// URLs are supported"):
        normalize_url("javascript:alert(1)")


def test_host_normalization():
    """Verify hostnames are lowercased, trailing dots stripped, and IPv6 formatted properly."""
    assert normalize_url("https://EXAMPLE.COM/page") == "https://example.com/page"
    assert normalize_url("https://Sub.Example.Com./page") == "https://sub.example.com/page"
    assert normalize_url("http://[2001:db8::1]/path", allow_private=True) == "http://[2001:db8::1]/path"

    with pytest.raises(UrlValidationError, match="Enter a complete URL with a hostname"):
        normalize_url("http:///only-path")


def test_default_port_normalization():
    """Verify default ports (80 for http, 443 for https) are stripped while custom ports remain."""
    assert normalize_url("http://example.com:80/path") == "http://example.com/path"
    assert normalize_url("https://example.com:443/path") == "https://example.com/path"
    # Custom ports preserved
    assert normalize_url("http://example.com:8080/path") == "http://example.com:8080/path"
    assert normalize_url("https://example.com:8443/path") == "https://example.com:8443/path"
    # Custom non-default port policy toggle
    policy_keep_ports = UrlNormalizationPolicy(remove_default_port=False)
    assert normalize_url("http://example.com:80/path", policy=policy_keep_ports) == "http://example.com:80/path"


def test_fragment_stripping():
    """Verify URL fragments are stripped by default for crawl canonicalization."""
    assert normalize_url("https://example.com/page#section1") == "https://example.com/page"
    assert normalize_url("https://example.com/page#") == "https://example.com/page"
    assert normalize_url("https://example.com/page?query=val#heading") == "https://example.com/page?query=val"

    policy_keep_frag = UrlNormalizationPolicy(strip_fragment=False)
    assert normalize_url("https://example.com/page#section1", policy=policy_keep_frag) == "https://example.com/page#section1"


def test_trailing_slash_policy():
    """Verify trailing slash policy options: preserve (conservative), strip, and append."""
    # Default strip policy (backward-compatible with Phase 1 certified baseline)
    assert normalize_url("https://example.com/page") == "https://example.com/page"
    assert normalize_url("https://example.com/page/") == "https://example.com/page"
    assert normalize_url("https://example.com/") == "https://example.com/"
    assert normalize_url("https://example.com") == "https://example.com/"

    # Preserve policy: subpaths and root trailing slashes preserved
    policy_preserve = UrlNormalizationPolicy(trailing_slash="preserve")
    assert normalize_url("https://example.com/page", policy=policy_preserve) == "https://example.com/page"
    assert normalize_url("https://example.com/page/", policy=policy_preserve) == "https://example.com/page/"
    assert normalize_url("https://example.com/", policy=policy_preserve) == "https://example.com/"

    # Strip policy explicitly passed
    policy_strip = UrlNormalizationPolicy(trailing_slash="strip")
    assert normalize_url("https://example.com/page/", policy=policy_strip) == "https://example.com/page"
    assert normalize_url("https://example.com/nested/path/", policy=policy_strip) == "https://example.com/nested/path"
    assert normalize_url("https://example.com/", policy=policy_strip) == "https://example.com/"

    # Append policy
    policy_append = UrlNormalizationPolicy(trailing_slash="append")
    assert normalize_url("https://example.com/page", policy=policy_append) == "https://example.com/page/"
    assert normalize_url("https://example.com/page/", policy=policy_append) == "https://example.com/page/"


def test_path_normalization_dot_segments():
    """Verify RFC 3986 dot-segment resolution (remove_dot_segments)."""
    assert remove_dot_segments("/a/b/../c") == "/a/c"
    assert remove_dot_segments("/a/./b") == "/a/b"
    assert remove_dot_segments("/a/b/c/../../d") == "/a/d"
    assert remove_dot_segments("/../a") == "/a"
    assert remove_dot_segments("/a/b/..") == "/a/"
    assert remove_dot_segments("/a/b/.") == "/a/b/"
    assert remove_dot_segments("/.") == "/"
    assert remove_dot_segments("/..") == "/"
    assert remove_dot_segments("") == "/"

    # In normalize_url
    assert normalize_url("https://example.com/a/b/../c") == "https://example.com/a/c"
    assert normalize_url("https://example.com/dir/./subdir/../target") == "https://example.com/dir/target"


def test_path_collapse_consecutive_slashes():
    """Verify duplicate slashes within the path are collapsed into single slashes."""
    assert normalize_url("https://example.com/a//b///c") == "https://example.com/a/b/c"
    assert normalize_url("https://example.com//index.html") == "https://example.com/index.html"


def test_percent_encoding_normalization():
    """Verify RFC 3986 unreserved percent-encoded characters are decoded and reserved hex digits uppercased."""
    # Unreserved chars: A-Z, a-z, 0-9, -, _, ., ~
    assert normalize_percent_encoding("%41%42%43") == "ABC"
    assert normalize_percent_encoding("%7e") == "~"
    assert normalize_percent_encoding("%2d%5f%2e") == "-_."
    # Reserved chars: hex digits uppercased, characters NOT decoded
    assert normalize_percent_encoding("%2f") == "%2F"
    assert normalize_percent_encoding("%3d") == "%3D"
    assert normalize_percent_encoding("%3f") == "%3F"
    assert normalize_percent_encoding("%20") == "%20"

    # In normalize_url
    assert normalize_url("https://example.com/%41%42/file%2fname") == "https://example.com/AB/file%2Fname"


def test_query_string_sorting_and_deduplication():
    """Verify query strings sort deterministically and deduplicate exact duplicate pairs."""
    # Alphabetical sorting of parameter keys and values
    assert normalize_url("https://example.com/search?z=3&a=1&m=2") == "https://example.com/search?a=1&m=2&z=3"
    # Permuted parameter ordering resolves to identical URL
    u1 = normalize_url("https://example.com/search?sort=asc&page=1")
    u2 = normalize_url("https://example.com/search?page=1&sort=asc")
    assert u1 == u2 == "https://example.com/search?page=1&sort=asc"

    # Exact duplicate pairs deduplicated
    assert normalize_url("https://example.com/search?a=1&a=1") == "https://example.com/search?a=1"

    # Multiple distinct values for the same key preserved and sorted
    assert normalize_url("https://example.com/filter?tag=python&tag=crawler") == "https://example.com/filter?tag=crawler&tag=python"
    assert normalize_url("https://example.com/filter?tag=crawler&tag=python") == "https://example.com/filter?tag=crawler&tag=python"


def test_query_tracking_and_sensitive_redaction():
    """Verify tracking parameters are stripped and sensitive parameters are safely redacted when enabled."""
    # Tracking stripped by default
    assert normalize_url("https://example.com/page?utm_source=google&utm_medium=cpc&q=seo") == "https://example.com/page?q=seo"
    assert normalize_url("https://example.com/page?fbclid=123&gclid=456&id=99") == "https://example.com/page?id=99"

    # Default policy does NOT redact sensitive tokens during crawler HTTP dispatch
    assert normalize_url("https://example.com/api?token=secret123&action=read") == "https://example.com/api?action=read&token=secret123"

    # Sensitive parameters redacted when redact_sensitive_params=True
    redact_policy = UrlNormalizationPolicy(redact_sensitive_params=True)
    assert normalize_url("https://example.com/api?token=secret123&action=read", policy=redact_policy) == "https://example.com/api?action=read&token=[REDACTED]"
    assert normalize_url("https://example.com/api?api_key=mykey456&client=web", policy=redact_policy) == "https://example.com/api?api_key=[REDACTED]&client=web"


def test_canonical_url_resolution():
    """Verify canonical tag resolution against page URL."""
    base = "https://example.com/articles/intro"
    # Relative canonical resolved against page
    assert resolve_canonical_url("../intro", base) == "https://example.com/intro"
    # Absolute path canonical
    assert resolve_canonical_url("/canonical-intro", base) == "https://example.com/canonical-intro"
    # Full same-host URL
    assert resolve_canonical_url("https://example.com/canonical-intro#frag", base) == "https://example.com/canonical-intro"
    # External host canonical rejected (returns page_url for safety)
    assert resolve_canonical_url("https://malicious.example/hijack", base) == base
    # Empty canonical returns page_url
    assert resolve_canonical_url("", base) == base


def test_redirect_url_resolution():
    """Verify redirect Location header resolution against requesting URL."""
    origin = "https://example.com/folder/page"
    # Relative redirect
    assert resolve_redirect_url("next-page", origin) == "https://example.com/folder/next-page"
    assert resolve_redirect_url("/root-page", origin) == "https://example.com/root-page"
    assert resolve_redirect_url("../parent-page", origin) == "https://example.com/parent-page"
    # Absolute redirect
    assert resolve_redirect_url("https://example.com/target?b=2&a=1#fragment", origin) == "https://example.com/target?a=1&b=2"
    # Empty redirect raises
    with pytest.raises(UrlValidationError):
        resolve_redirect_url("", origin)


def test_conservative_identity_preservation():
    """Verify normalizer never alters semantics or resource identity unexpectedly."""
    # Query case is preserved
    assert normalize_url("https://example.com/search?CaseSensitive=Value") == "https://example.com/search?CaseSensitive=Value"
    # Path case is preserved
    assert normalize_url("https://example.com/CamelCasePath") == "https://example.com/CamelCasePath"
    # Empty query vs no query
    assert normalize_url("https://example.com/page?") == "https://example.com/page"
