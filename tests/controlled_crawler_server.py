"""Deterministic local HTTP test server providing controlled endpoints for crawler verification."""

from __future__ import annotations

import threading
import time
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

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
