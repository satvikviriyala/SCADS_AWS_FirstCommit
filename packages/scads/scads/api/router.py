"""Request routing for API Gateway HTTP API (payload format 2.0).

A small explicit table rather than a framework. The whole surface is seven
routes, and a dependency-free router keeps the Lambda package to numpy and
Pillow — which is what lets it deploy as a plain zip
(``AGENTS.md`` section 4.2: a boring function beats a generic abstraction with
no current caller).
"""

import re
import time
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple

from ..adapters.base import DependencyUnavailable
from ..adapters.factory import Adapters, build_adapters
from ..config import ConfigError, Settings, load_settings
from ..util.clock import Clock
from ..util.ids import new_id
from ..util.jsonlog import log_error, log_event, log_warning
from . import handlers, http

# Route table: (method, compiled path pattern, handler name).
_ROUTES: List[Tuple[str, Pattern, str]] = [
    ("GET", re.compile(r"^/(?:v1/)?health/?$"), "health"),
    ("POST", re.compile(r"^/v1/uploads/?$"), "create_upload"),
    ("POST", re.compile(r"^/v1/scans/(?P<scan_id>[A-Za-z0-9_-]{1,64})/analyze/?$"), "analyze"),
    ("GET", re.compile(r"^/v1/scans/(?P<scan_id>[A-Za-z0-9_-]{1,64})/?$"), "get_scan"),
    ("GET", re.compile(r"^/v1/locations/?$"), "get_locations"),
    ("GET", re.compile(r"^/v1/catalogue/?$"), "get_catalogue"),
    ("POST", re.compile(r"^/v1/admin/demo/reset/?$"), "admin_reset"),
    # Offline development only: stands in for a presigned S3 PUT.
    ("PUT", re.compile(r"^/v1/local-upload/(?P<bucket>[a-z]+)/(?P<key>.+)$"), "local_upload"),
]


class Router:
    """Holds settings and adapters across warm invocations.

    Built once per container. Cold-start cost — importing numpy, constructing
    boto3 clients — is paid on the first request rather than on every one.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        adapters: Optional[Adapters] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self._settings = settings
        self._adapters = adapters
        self._clock = clock or Clock()
        self._config_error: Optional[str] = None

        if self._settings is None:
            try:
                self._settings = load_settings()
            except ConfigError as exc:
                # Recorded rather than raised: /health must still answer, and
                # answer with ok=false, so a misconfigured deployment is
                # diagnosable instead of returning opaque 500s.
                self._config_error = str(exc)

    @property
    def settings(self) -> Optional[Settings]:
        return self._settings

    def adapters(self) -> Adapters:
        if self._adapters is None:
            if self._settings is None:
                raise http.internal_error("configuration is invalid")
            self._adapters = build_adapters(self._settings)
        return self._adapters

    # --- dispatch --------------------------------------------------------

    def handle(self, event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
        started = time.time()
        method = http.request_method(event)
        path = http.request_path(event)
        origin = http.header(event, "origin")
        allowed = self._settings.allowed_origins if self._settings else ["*"]
        correlation_id = http.header(event, "x-correlation-id") or new_id("scan")

        if method == "OPTIONS":
            return http.json_response(204, {}, origin, allowed, correlation_id)

        try:
            if self._config_error and not _is_health(path):
                raise http.internal_error("configuration is invalid")

            name, params = self._match(method, path)
            if name is None:
                raise http.not_found("NOT_FOUND", "No such endpoint.")

            body = self._invoke(name, params, event, correlation_id)
            status = 200
            if name == "local_upload":
                status = 200
            return http.json_response(status, body, origin, allowed, correlation_id)

        except http.ApiError as exc:
            if exc.status >= 500:
                log_error(
                    "request.failed",
                    path=path, method=method, code=exc.code,
                    detail=exc.detail, correlation_id=correlation_id,
                )
            else:
                log_warning(
                    "request.rejected",
                    path=path, method=method, status=exc.status,
                    code=exc.code, correlation_id=correlation_id,
                )
            return http.json_response(exc.status, exc.to_body(), origin, allowed, correlation_id)

        except DependencyUnavailable as exc:
            log_error(
                "request.dependency_unavailable",
                path=path, dependency=exc.dependency, correlation_id=correlation_id,
            )
            error = http.ApiError(
                503, "DEPENDENCY_UNAVAILABLE",
                "A verification service is temporarily unavailable. Please try again.",
            )
            return http.json_response(503, error.to_body(), origin, allowed, correlation_id)

        except LookupError as exc:
            return http.json_response(
                404, http.not_found().to_body(), origin, allowed, correlation_id
            )

        except Exception as exc:  # noqa: BLE001 - the outermost boundary
            # Nothing escapes as an unhandled exception: a stack trace in a
            # response body leaks internals, and a bare 502 from API Gateway
            # gives the user nothing to act on.
            log_error(
                "request.unhandled",
                path=path, method=method,
                exception_type=type(exc).__name__,
                correlation_id=correlation_id,
            )
            return http.json_response(
                500, http.internal_error().to_body(), origin, allowed, correlation_id
            )

        finally:
            log_event(
                "request.completed",
                path=path, method=method,
                latency_ms=int((time.time() - started) * 1000),
                correlation_id=correlation_id,
            )

    def _match(self, method: str, path: str) -> Tuple[Optional[str], Dict[str, str]]:
        for route_method, pattern, name in _ROUTES:
            match = pattern.match(path)
            if match:
                if route_method != method:
                    continue
                return name, match.groupdict()
        return None, {}

    def _invoke(
        self, name: str, params: Dict[str, str], event: Dict[str, Any], correlation_id: str
    ) -> Dict[str, Any]:
        if name == "health":
            adapters = None
            if self._settings is not None and self._config_error is None:
                try:
                    adapters = self.adapters()
                except Exception:  # noqa: BLE001
                    adapters = None
            if self._settings is None:
                return {
                    "ok": False,
                    "service": "scads-api",
                    "error": "configuration is invalid",
                }
            body = handlers.health(self._settings, adapters)
            if self._config_error:
                body["ok"] = False
            return body

        if name == "get_locations":
            return handlers.get_locations()

        if name == "create_upload":
            return handlers.create_upload(
                http.parse_json_body(event), self.adapters(), self._settings, self._clock
            )

        if name == "analyze":
            return handlers.analyze(
                params["scan_id"], http.parse_json_body(event),
                self.adapters(), self._settings, self._clock, correlation_id,
            )

        if name == "get_scan":
            return handlers.get_scan(params["scan_id"], self.adapters())

        if name == "get_catalogue":
            return handlers.get_reference_catalogue(self.adapters())

        if name == "admin_reset":
            return handlers.admin_reset(
                http.parse_json_body(event),
                http.header(event, "x-admin-token"),
                self.adapters(), self._settings, self._clock,
            )

        if name == "local_upload":
            return self._local_upload(params, event)

        raise http.not_found("NOT_FOUND", "No such endpoint.")

    def _local_upload(self, params: Dict[str, str], event: Dict[str, Any]) -> Dict[str, Any]:
        """Accept an upload for the offline object store.

        Exists only so the browser flow is identical offline: request a target,
        PUT the bytes to it, then ask for analysis. Refused unless the local
        backend is configured, so it can never become a public write endpoint on
        a deployed stack.
        """
        from ..config import STORE_LOCAL

        if self._settings is None or self._settings.store_backend != STORE_LOCAL:
            raise http.not_found("NOT_FOUND", "No such endpoint.")

        import base64

        raw = event.get("body") or ""
        data = base64.b64decode(raw) if event.get("isBase64Encoded") else (
            raw.encode("latin-1") if isinstance(raw, str) else raw
        )
        if len(data) > self._settings.upload_max_bytes:
            raise http.bad_request("FILE_TOO_LARGE", "That image is larger than the limit.")

        bucket = params["bucket"]
        key = params["key"]
        if bucket not in ("scans", "references") or ".." in key:
            raise http.bad_request("INVALID_UPLOAD_TARGET", "That upload target is not valid.")

        self.adapters().store.put_bytes(bucket, key, data, "application/octet-stream")
        return {"ok": True, "bytes": len(data)}


def _is_health(path: str) -> bool:
    return bool(re.match(r"^/(?:v1/)?health/?$", path))


# Module-level singleton, reused across warm Lambda invocations.
_ROUTER: Optional[Router] = None


def get_router() -> Router:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = Router()
    return _ROUTER


def handle_request(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    return get_router().handle(event, context)
