#!/usr/bin/env python3
"""Local development server: the real API plus the static web app.

Serves the same Lambda handler code the deployed stack runs, by translating
plain HTTP into API Gateway HTTP API v2 events. So a bug found here is a bug in
the deployed path, not in a parallel implementation.

Built on ``http.server`` from the standard library because there is no Node or
web framework in this environment — and because the dependency the deployed
Lambda does *not* have is the dependency that cannot break it.

Usage::

    python scripts/seed_demo.py                    # seed first
    python scripts/dev_server.py                   # http://localhost:8000
    python scripts/dev_server.py --port 8080
"""

import argparse
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import unquote, urlparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "packages", "scads"))

from scads.config import local_settings  # noqa: E402
from scads.adapters.factory import build_adapters  # noqa: E402
from scads.api.router import Router  # noqa: E402

WEB_ROOT = os.path.abspath(os.path.join(ROOT, "apps", "web"))
FIXTURE_ROOT = os.path.abspath(os.path.join(ROOT, "apps", "web", "fixtures"))
LEGACY_FIXTURE_ROOT = os.path.abspath(os.path.join(ROOT, "tests", "fixtures", "generated"))

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}

_LOCK = threading.Lock()
_ROUTER: Router = None  # set in main()
_MAX_BODY = 32 * 1024 * 1024


class DevHandler(BaseHTTPRequestHandler):
    server_version = "scads-dev"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # The router already emits structured logs; this would duplicate them.
        pass

    # --- HTTP verbs -------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if self._is_api(path):
            self._serve_api("GET")
        else:
            self._serve_static(path)

    def do_POST(self):
        self._serve_api("POST")

    def do_PUT(self):
        self._serve_api("PUT")

    def do_OPTIONS(self):
        self._serve_api("OPTIONS")

    # --- API --------------------------------------------------------------

    @staticmethod
    def _is_api(path: str) -> bool:
        return path.startswith("/v1/") or path in ("/health", "/v1/health")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > _MAX_BODY:
            return b""
        return self.rfile.read(length)

    def _serve_api(self, method: str):
        parsed = urlparse(self.path)
        raw = self._read_body()

        event: Dict[str, Any] = {
            "requestContext": {"http": {"method": method, "path": unquote(parsed.path)}},
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "rawQueryString": parsed.query,
        }
        if raw:
            content_type = (self.headers.get("Content-Type") or "").lower()
            if content_type.startswith("application/json") or content_type.startswith("text/"):
                event["body"] = raw.decode("utf-8", errors="replace")
            else:
                # Binary uploads arrive base64-encoded from API Gateway, so the
                # dev server does the same and the handler sees one shape.
                event["body"] = base64.b64encode(raw).decode("ascii")
                event["isBase64Encoded"] = True

        with _LOCK:
            response = _ROUTER.handle(event, None)

        body = (response.get("body") or "").encode("utf-8")
        self.send_response(int(response.get("statusCode", 200)))
        for key, value in (response.get("headers") or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    # --- static -----------------------------------------------------------

    def _serve_static(self, path: str):
        if path == "/" or path == "":
            path = "/index.html"

        # Fixture images, so the demo panel can post a known capture without a
        # camera. Development only: the route is defined here, not in the API.
        if path.startswith("/fixtures/"):
            relative = path[len("/fixtures/") :]
            base = FIXTURE_ROOT
            if not os.path.exists(os.path.join(FIXTURE_ROOT, relative)):
                base = LEGACY_FIXTURE_ROOT
        else:
            base, relative = WEB_ROOT, path.lstrip("/")

        target = os.path.abspath(os.path.join(base, unquote(relative)))
        if not target.startswith(base):
            self._send_text(403, "forbidden")
            return
        if not os.path.isfile(target):
            self._send_text(404, "not found")
            return

        extension = os.path.splitext(target)[1].lower()
        with open(target, "rb") as handle:
            payload = handle.read()

        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(extension, "application/octet-stream"))
        self.send_header("Content-Length", str(len(payload)))
        # No caching in development: an edited file should appear on reload.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, message: str):
        payload = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    global _ROUTER

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("SCADS_DEV_PORT", 8000)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--local-root", default=".scads-local")
    args = parser.parse_args()

    settings = local_settings(os.path.join(ROOT, args.local_root))
    adapters = build_adapters(settings, upload_base_url="http://localhost:%d" % args.port)
    _ROUTER = Router(settings=settings, adapters=adapters)

    registry_file = os.path.join(settings.local_root, "registry", "serials.json")
    if not os.path.exists(registry_file):
        print("WARNING: no seeded registry found. Run:")
        print("    python scripts/seed_demo.py")
        print()

    print("SCADS dev server")
    print("  web    http://localhost:%d/" % args.port)
    print("  api    http://localhost:%d/v1/health" % args.port)
    print("  state  %s" % settings.local_root)
    print("  note   offline backends; the deployed stack uses S3/DynamoDB/Textract")
    print()

    server = ThreadingHTTPServer((args.host, args.port), DevHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
