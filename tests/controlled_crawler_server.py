"""Deterministic local HTTP test server providing controlled endpoints for crawler verification."""

from __future__ import annotations

import gzip
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit


class ControlledHandler(BaseHTTPRequestHandler):
    """HTTP request handler implementing all required controlled crawler test endpoints."""

    def log_message(self, format: str, *args: object) -> None:
        # Silence HTTP access logs during test execution
        pass

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        port = self.server.server_port
        base = f"http://127.0.0.1:{port}"

        if path == "/robots.txt":
            body = "User-agent: *\nAllow: /\nDisallow: /blocked\n"
            self._send_text(200, body, "text/plain")

        elif path == "/blocked":
            body = "<html><body><h1>Disallowed by robots</h1></body></html>"
            self._send_html(200, body)

        elif path == "/":
            body = f"""<!DOCTYPE html>
<html>
<head><title>Controlled Crawler Fixture Root</title></head>
<body>
    <h1>Controlled Test Site</h1>
    <a href="/a">Page A</a>
    <a href="/b">Page B</a>
    <a href="/cycle-a">Cycle A</a>
    <a href="/duplicate-links">Duplicate Links</a>
    <a href="/redirect">Redirect 302</a>
    <a href="/redirect-chain">Redirect Chain</a>
    <a href="/redirect-loop">Redirect Loop</a>
    <a href="/canonical">Canonical Test</a>
    <a href="/query?page=1&sort=asc">Query Test</a>
    <a href="/fragments">Fragments Test</a>
    <a href="/external-link">External Link Test</a>
    <a href="/deep">Deep Hierarchy</a>
    <a href="/404">Not Found</a>
    <a href="/500">Internal Error</a>
    <a href="/429">Rate Limited</a>
    <a href="/slow">Slow Page</a>
    <a href="/large">Large Payload</a>
</body>
</html>"""
            self._send_html(200, body)

        elif path == "/a":
            body = """<!DOCTYPE html>
<html><head><title>Page A</title></head>
<body><h1>Page A</h1><a href="/b">Go to B</a></body></html>"""
            self._send_html(200, body)

        elif path == "/b":
            body = """<!DOCTYPE html>
<html><head><title>Page B</title></head>
<body><h1>Page B</h1><a href="/a">Go to A</a></body></html>"""
            self._send_html(200, body)

        elif path == "/cycle-a":
            body = """<!DOCTYPE html>
<html><head><title>Cycle A</title></head>
<body><h1>Cycle A</h1><a href="/cycle-b">Next Cycle B</a></body></html>"""
            self._send_html(200, body)

        elif path == "/cycle-b":
            body = """<!DOCTYPE html>
<html><head><title>Cycle B</title></head>
<body><h1>Cycle B</h1><a href="/cycle-a">Back to Cycle A</a></body></html>"""
            self._send_html(200, body)

        elif path == "/duplicate-links":
            body = """<!DOCTYPE html>
<html><head><title>Duplicate Links</title></head>
<body>
    <h1>Duplicate Link Fixture</h1>
    <a href="/a">Link A First</a>
    <a href="/a">Link A Second</a>
    <a href="/a#section1">Link A Fragment 1</a>
    <a href="/a#section2">Link A Fragment 2</a>
    <a href="/a/">Link A Trailing Slash</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/a")
            self.end_headers()

        elif path == "/redirect-chain":
            self.send_response(302)
            self.send_header("Location", "/redirect-chain-2")
            self.end_headers()

        elif path == "/redirect-chain-2":
            self.send_response(302)
            self.send_header("Location", "/redirect-chain-target")
            self.end_headers()

        elif path == "/redirect-chain-target":
            body = """<!DOCTYPE html>
<html><head><title>Chain Target</title></head><body><h1>Redirect Chain Reached</h1></body></html>"""
            self._send_html(200, body)

        elif path == "/redirect-loop":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop-target")
            self.end_headers()

        elif path == "/redirect-loop-target":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.end_headers()

        elif path == "/404":
            self._send_text(404, "404 Not Found", "text/plain")

        elif path == "/500":
            self._send_text(500, "500 Internal Server Error", "text/plain")

        elif path == "/429":
            count = getattr(self.server, "_429_hits", 0) + 1
            setattr(self.server, "_429_hits", count)
            if count == 1 and query.get("force") != "ok":
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"429 Too Many Requests - Retry in 1s")
            else:
                body = """<!DOCTYPE html>
<html><head><title>429 Recovered</title></head><body><h1>Rate Limit Recovered</h1></body></html>"""
                self._send_html(200, body)

        elif path == "/slow":
            delay = float(query.get("delay", "0.15"))
            time.sleep(delay)
            body = """<!DOCTYPE html>
<html><head><title>Slow Page</title></head><body><h1>Slow Content Loaded</h1></body></html>"""
            self._send_html(200, body)

        elif path == "/large":
            payload = "Large repeated content block. " * 3500
            body = f"""<!DOCTYPE html>
<html><head><title>Large Page</title></head><body><h1>Large Page</h1><p>{payload}</p></body></html>"""
            self._send_html(200, body)

        elif path == "/canonical":
            body = f"""<!DOCTYPE html>
<html>
<head>
    <title>Canonical Source Page</title>
    <link rel="canonical" href="{base}/canonical-target" />
</head>
<body>
    <h1>Canonical Source</h1>
    <a href="/canonical-target">Canonical Target</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/canonical-target":
            body = """<!DOCTYPE html>
<html><head><title>Canonical Target Page</title></head><body><h1>Canonical Target Content</h1></body></html>"""
            self._send_html(200, body)

        elif path == "/query":
            body = """<!DOCTYPE html>
<html><head><title>Query Parameters Page</title></head>
<body>
    <h1>Query Variants</h1>
    <a href="/query?page=1&sort=asc">Page 1 Asc</a>
    <a href="/query?sort=asc&page=1">Sort Asc Page 1 (Permuted)</a>
    <a href="/query?page=1&utm_source=twitter">Campaign Twitter</a>
    <a href="/query?a=1&a=1">Duplicate Params</a>
    <a href="/query?tag=python&tag=crawler">Multi-value Params</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/fragments":
            body = """<!DOCTYPE html>
<html><head><title>Fragments Page</title></head>
<body>
    <h1>Fragment Links</h1>
    <a href="/fragments#intro">Intro</a>
    <a href="/fragments#details">Details</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/external-link":
            body = """<!DOCTYPE html>
<html><head><title>External Link Page</title></head>
<body>
    <h1>External Link</h1>
    <a href="https://external.example.com/outbound">External Site</a>
    <a href="/a">Internal Page A</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/deep":
            body = """<!DOCTYPE html>
<html><head><title>Deep Level 0</title></head><body><h1>Level 0</h1><a href="/deep/1">To Level 1</a></body></html>"""
            self._send_html(200, body)

        elif path == "/deep/1":
            body = """<!DOCTYPE html>
<html><head><title>Deep Level 1</title></head><body><h1>Level 1</h1><a href="/deep/1/2">To Level 2</a></body></html>"""
            self._send_html(200, body)

        elif path == "/deep/1/2":
            body = """<!DOCTYPE html>
<html><head><title>Deep Level 2</title></head><body><h1>Level 2</h1><a href="/deep/1/2/3">To Level 3</a></body></html>"""
            self._send_html(200, body)

        elif path == "/deep/1/2/3":
            body = """<!DOCTYPE html>
<html><head><title>Deep Level 3</title></head><body><h1>Level 3 Leaf</h1><a href="/">Back to Root</a></body></html>"""
            self._send_html(200, body)

        elif path.startswith("/slow-concurrency/"):
            client_pid = self.headers.get("X-Client-PID", "unknown")
            item_id = path.split("/")[-1]
            t_start = time.monotonic()
            
            # Record server concurrency
            server_obj = self.server
            lock = getattr(server_obj, "_concurrency_lock", None)
            if lock:
                with lock:
                    server_obj._active_requests += 1
                    if server_obj._active_requests > server_obj._peak_concurrency:
                        server_obj._peak_concurrency = server_obj._active_requests

            delay = float(query.get("delay", "0.25"))
            time.sleep(delay)
            t_end = time.monotonic()

            if lock:
                with lock:
                    server_obj._active_requests -= 1
                    server_obj._request_logs.append({
                        "id": item_id,
                        "client_pid": client_pid,
                        "t_start": t_start,
                        "t_end": t_end,
                    })

            import json
            import os
            resp_body = json.dumps({
                "id": item_id,
                "server_pid": os.getpid(),
                "client_pid": client_pid,
                "t_start": t_start,
                "t_end": t_end,
            })
            self._send_text(200, resp_body, "application/json")

        elif path == "/timeout":
            time.sleep(2.0)
            self._send_html(200, "<html><body><h1>Timeout Finished</h1></body></html>")

        elif path == "/transient-error":
            server_obj = self.server
            lock = getattr(server_obj, "_concurrency_lock", None)
            fails = 1
            if lock:
                with lock:
                    server_obj._transient_fails = getattr(server_obj, "_transient_fails", 0) + 1
                    fails = server_obj._transient_fails
            if fails <= 1:
                self.send_response(503)
                self.send_header("Retry-After", "0.1")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"503 Service Unavailable (Transient)")
            else:
                self._send_html(200, "<html><body><h1>Transient Recovered</h1></body></html>")

        elif path == "/redirect-301":
            self.send_response(301)
            self.send_header("Location", f"{base}/a")
            self.end_headers()

        elif path in ("/content-dup-1", "/content-dup-2"):
            body = "<html><head><title>Identical Duplicate Content</title></head><body><h1>Duplicate Body Content</h1><p>Exact same text for content hash deduplication.</p></body></html>"
            self._send_html(200, body)

        elif path == "/malformed-links":
            body = """<!DOCTYPE html>
<html><head><title>Malformed Links Page</title></head>
<body>
    <h1>Malformed and Valid Links</h1>
    <a href="javascript:void(0)">JavaScript Link</a>
    <a href="mailto:test@example.com">Email Link</a>
    <a href="http://:invalid">Invalid URI</a>
    <a href="/a">Valid Page A</a>
</body></html>"""
            self._send_html(200, body)

        elif path == "/drop-mid-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                self.wfile.write(b"<html><body><h1>Incomplete Stream")
                self.wfile.flush()
                self.request.shutdown(2)
            except Exception:
                pass
            self.close_connection = True

        elif path == "/half-written":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "5000")
            self.end_headers()
            try:
                self.wfile.write(b"<html><body><h1>Half Written Stream</h1>")
                self.wfile.flush()
                self.request.close()
            except Exception:
                pass
            self.close_connection = True

        elif path == "/malformed-gzip":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", "24")
            self.end_headers()
            self.wfile.write(b"NOT_A_VALID_GZIP_STREAM!")

        elif path.startswith("/burst-500/"):
            item_id = path.split("/")[-1]
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"500 Internal Error {item_id}".encode("utf-8"))

        elif path.startswith("/burst-429/"):
            item_id = path.split("/")[-1]
            self.send_response(429)
            self.send_header("Retry-After", "0.05")
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"429 Rate Limited {item_id}".encode("utf-8"))

        elif path == "/rapid-discovery":
            links = "".join(f'<a href="/rapid-target/{i}">Target {i}</a>\n' for i in range(25))
            self._send_html(200, f"<html><body><h1>Discovery Hub</h1>{links}</body></html>")

        elif path.startswith("/rapid-target/"):
            item_id = path.split("/")[-1]
            self._send_html(200, f"<html><body><h1>Target {item_id}</h1></body></html>")

        elif path == "/simultaneous-duplicate-hub":
            self._send_html(200, """<html><body><h1>Duplicate Hub</h1>
    <a href="/dup-src-1">Source 1</a>
    <a href="/dup-src-2">Source 2</a>
    <a href="/dup-src-3">Source 3</a>
    <a href="/dup-src-4">Source 4</a>
</body></html>""")

        elif path in ("/dup-src-1", "/dup-src-2", "/dup-src-3", "/dup-src-4"):
            self._send_html(200, f"""<html><body><h1>Source {path}</h1><a href="/shared-duplicate-target">Shared Target</a></body></html>""")

        elif path == "/shared-duplicate-target":
            self._send_html(200, "<html><body><h1>Shared Target Page</h1></body></html>")

        elif path.startswith("/slow-mixed/"):
            is_slow = "slow" in path
            delay = 0.25 if is_slow else 0.01
            time.sleep(delay)
            self._send_html(200, f"<html><body><h1>Mixed Delay Page {path}</h1></body></html>")

        elif path == "/static-clean":
            self._send_html(200, """<!DOCTYPE html>
<html>
<head><title>Clean Static Editorial Page</title></head>
<body>
    <h1>Clean Static Article</h1>
    <p>This is a standard server-rendered HTML document containing rich editorial prose, semantic markup, and comprehensive documentation for local SEO crawlers.</p>
    <p>It contains multiple distinct paragraphs of descriptive content and requires zero client-side JavaScript hydration or execution to be completely understood.</p>
    <a href="/static-with-scripts">Next Article</a>
</body>
</html>""")

        elif path == "/static-with-scripts":
            self._send_html(200, """<!DOCTYPE html>
<html>
<head>
    <title>Static Page With Analytics Scripts</title>
    <script src="https://example.com/analytics.js" async></script>
</head>
<body>
    <h1>Static Page With Script Tags</h1>
    <p>This page includes third-party marketing tags, tracking scripts, and widget loaders, but the entire body copy is fully materialized in the initial static HTML payload.</p>
    <p>A smart crawler must examine this page and determine that visible content is rich and readable, thereby avoiding expensive headless browser escalation.</p>
    <script>console.log("analytics initialized");</script>
</body>
</html>""")

        elif path == "/spa-empty-shell":
            self._send_html(200, """<!DOCTYPE html>
<html>
<head><title>Single Page App Shell</title></head>
<body>
    <div id="root"></div>
    <script>
        document.getElementById('root').innerHTML = '<h1>SPA Rendered Client Heading</h1><p>Dynamic client-side content populated exclusively by JavaScript execution in a real browser engine.</p>';
    </script>
</body>
</html>""")

        elif path == "/js-challenge":
            self._send_html(200, """<!DOCTYPE html>
<html>
<head><title>Just a moment...</title></head>
<body>
    <h1>Checking your browser before accessing...</h1>
    <noscript><p>Please enable JavaScript and cookies to continue</p></noscript>
    <div id="challenge-running">Verification in progress</div>
    <script>
        document.body.innerHTML = '<h1>Protected Content Unlocked</h1><p>Full article access granted following browser verification.</p>';
    </script>
</body>
</html>""")

        elif path == "/js-broken":
            self._send_html(200, """<!DOCTYPE html>
<html>
<head>
    <title>Broken JavaScript Page</title>
    <script>throw new Error("Deliberate client script exception in inline execution");</script>
</head>
<body>
    <h1>Broken Script Page Heading</h1>
    <p>Despite the client JavaScript throwing an uncaught runtime error, the static DOM elements remain fully structured and readable.</p>
</body>
</html>""")

        elif path == "/browser-timeout":
            # Endpoint that sleeps 3 seconds, exceeding a 500ms browser render timeout
            time.sleep(1.5)
            self._send_html(200, "<html><body><h1>Timeout Page Rendered</h1></body></html>")

        elif path == "/gzip-encoded":
            content = b"<html><body><h1>Gzip Compressed Content</h1><p>Payload delivered using gzip content encoding.</p></body></html>"
            compressed = gzip.compress(content)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)

        elif path == "/deflate-encoded":
            content = b"<html><body><h1>Deflate Compressed Content</h1><p>Payload delivered using deflate content encoding.</p></body></html>"
            compressed = zlib.compress(content)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Encoding", "deflate")
            self.send_header("Content-Length", str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)

        elif path == "/content-types/json":
            self._send_text(200, '{"service": "crawler", "status": "active", "version": "2.0"}', "application/json")

        elif path == "/content-types/text":
            self._send_text(200, "Plain text document content for non-HTML fetch verification.", "text/plain")

        elif path == "/content-types/pdf":
            dummy_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0>>endobj\nxref\n0 3\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\ntrailer<</Size 3/Root 1 0 R>>\nstartxref\n101\n%%EOF"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(dummy_pdf)))
            self.end_headers()
            self.wfile.write(dummy_pdf)

        elif path == "/large-payload":
            repeated_body = "<p>Repeated paragraph for response size measurement.</p>\n" * 1200
            self._send_html(200, f"<html><body><h1>Large Document</h1>{repeated_body}</body></html>")

        else:
            self._send_text(404, f"404 Not Found: {path}", "text/plain")

    def _send_html(self, status: int, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, status: int, text: str, content_type: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ControlledCrawlerServer:
    """Manager for the controlled crawler test server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> str:
        self.server = ThreadingHTTPServer((self.host, self.port), ControlledHandler)
        self.server._concurrency_lock = threading.Lock()
        self.server._active_requests = 0
        self.server._peak_concurrency = 0
        self.server._request_logs = []
        self.server._transient_fails = 0
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # Brief pause to ensure socket listening
        time.sleep(0.05)
        return f"http://{self.host}:{self.port}"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def reset_counts(self) -> None:
        if self.server:
            setattr(self.server, "_429_hits", 0)
            setattr(self.server, "_transient_fails", 0)

    def reset_concurrency_stats(self) -> None:
        if self.server:
            with self.server._concurrency_lock:
                self.server._active_requests = 0
                self.server._peak_concurrency = 0
                self.server._request_logs = []

    def get_peak_concurrency(self) -> int:
        if self.server:
            with self.server._concurrency_lock:
                return getattr(self.server, "_peak_concurrency", 0)
        return 0

    def get_request_logs(self) -> list[dict]:
        if self.server:
            with self.server._concurrency_lock:
                return list(getattr(self.server, "_request_logs", []))
        return []

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
