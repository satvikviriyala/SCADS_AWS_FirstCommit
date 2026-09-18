"""HTTP plumbing: request parsing, validation, responses and CORS.

Two principles from ``docs/SECURITY_PRIVACY.md`` section 4 shape this module.

**Errors are generic to the caller and specific in the logs.** A response
carries a stable machine code and a short sentence; it never carries a stack
trace, an internal identifier, a table name or a presigned URL.

**Everything from the wire is validated before use.** Bounded strings, closed
enumerations, explicit numeric ranges. A scan id is checked against an allowlist
pattern because it ends up in an S3 object key.
"""

import json
from typing import Any, Dict, List, Optional, Tuple


class ApiError(Exception):
    """An error with a public code, a safe message and an HTTP status."""

    def __init__(self, status: int, code: str, message: str, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        # For logs only. Never serialised into a response.
        self.detail = detail

    def to_body(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


def bad_request(code: str, message: str, detail: Optional[str] = None) -> ApiError:
    return ApiError(400, code, message, detail)


def not_found(code: str = "NOT_FOUND", message: str = "That scan could not be found.") -> ApiError:
    return ApiError(404, code, message)


def unauthorized() -> ApiError:
    return ApiError(401, "UNAUTHORIZED", "This endpoint requires an admin credential.")


def rate_limited() -> ApiError:
    return ApiError(429, "RATE_LIMITED", "Too many requests. Please wait and try again.")


def internal_error(detail: Optional[str] = None) -> ApiError:
    return ApiError(
        500, "INTERNAL_ERROR", "Something went wrong on our side. Please try again.", detail
    )


# --- request parsing -----------------------------------------------------


def parse_json_body(event: Dict[str, Any], max_bytes: int = 64 * 1024) -> Dict[str, Any]:
    """Parse and bound a JSON request body.

    A missing body is an empty object: several endpoints take only optional
    fields, and requiring ``{}`` would be a needless client trap.
    """
    raw = event.get("body")
    if raw is None or raw == "":
        return {}

    if event.get("isBase64Encoded"):
        import base64

        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            raise bad_request("MALFORMED_BODY", "The request body could not be decoded.")

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    if len(raw) > max_bytes:
        raise bad_request("BODY_TOO_LARGE", "The request body is too large.")

    try:
        parsed = json.loads(raw)
    except ValueError:
        raise bad_request("MALFORMED_BODY", "The request body is not valid JSON.")

    if not isinstance(parsed, dict):
        raise bad_request("MALFORMED_BODY", "The request body must be a JSON object.")
    return parsed


def require_string(
    data: Dict[str, Any],
    field: str,
    max_length: int = 256,
    allowed: Optional[Tuple[str, ...]] = None,
) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("INVALID_FIELD", "The field '" + field + "' is required.")
    value = value.strip()
    if len(value) > max_length:
        raise bad_request("INVALID_FIELD", "The field '" + field + "' is too long.")
    if allowed is not None and value not in allowed:
        raise bad_request(
            "INVALID_FIELD", "The field '" + field + "' is not one of the accepted values."
        )
    return value


def optional_string(
    data: Dict[str, Any],
    field: str,
    max_length: int = 2048,
    allowed: Optional[Tuple[str, ...]] = None,
) -> Optional[str]:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise bad_request("INVALID_FIELD", "The field '" + field + "' must be text.")
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise bad_request("INVALID_FIELD", "The field '" + field + "' is too long.")
    if allowed is not None and value not in allowed:
        raise bad_request(
            "INVALID_FIELD", "The field '" + field + "' is not one of the accepted values."
        )
    return value


def require_int(data: Dict[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("INVALID_FIELD", "The field '" + field + "' must be a whole number.")
    if value < minimum or value > maximum:
        raise bad_request(
            "INVALID_FIELD",
            "The field '" + field + "' must be between {} and {}.".format(minimum, maximum),
        )
    return value


def optional_float(
    data: Dict[str, Any], field: str, minimum: float, maximum: float
) -> Optional[float]:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("INVALID_FIELD", "The field '" + field + "' must be a number.")
    value = float(value)
    if value != value or value < minimum or value > maximum:  # NaN-safe
        raise bad_request(
            "INVALID_FIELD",
            "The field '" + field + "' must be between {} and {}.".format(minimum, maximum),
        )
    return value


def optional_object(data: Dict[str, Any], field: str) -> Dict[str, Any]:
    value = data.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise bad_request("INVALID_FIELD", "The field '" + field + "' must be an object.")
    return value


# --- responses -----------------------------------------------------------


def cors_headers(origin: Optional[str], allowed_origins: List[str]) -> Dict[str, str]:
    """Build CORS headers, echoing the origin only when it is allowed.

    Reflecting an arbitrary ``Origin`` would defeat the purpose of the
    allowlist, so an unrecognised origin gets the first configured origin and
    the browser refuses the response — which is the correct outcome.
    """
    headers = {
        "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-Admin-Token,X-Correlation-Id",
        "Access-Control-Max-Age": "600",
    }
    if "*" in allowed_origins:
        headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    elif allowed_origins:
        headers["Access-Control-Allow-Origin"] = allowed_origins[0]
        headers["Vary"] = "Origin"
    return headers


def json_response(
    status: int,
    body: Dict[str, Any],
    origin: Optional[str] = None,
    allowed_origins: Optional[List[str]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        # A verification result must never be served from a cache: the history
        # dimension makes the same request genuinely produce a different answer.
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    headers.update(cors_headers(origin, allowed_origins or []))
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


# --- event accessors -----------------------------------------------------


def request_method(event: Dict[str, Any]) -> str:
    context = event.get("requestContext") or {}
    http = context.get("http") or {}
    return (http.get("method") or event.get("httpMethod") or "GET").upper()


def request_path(event: Dict[str, Any]) -> str:
    context = event.get("requestContext") or {}
    http = context.get("http") or {}
    path = http.get("path") or event.get("rawPath") or event.get("path") or "/"
    # Strip an API Gateway stage prefix so routes are stage-independent.
    stage = context.get("stage")
    if stage and stage != "$default" and path.startswith("/" + stage + "/"):
        path = path[len(stage) + 1 :]
    return path or "/"


def header(event: Dict[str, Any], name: str) -> Optional[str]:
    headers = event.get("headers") or {}
    lowered = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == lowered:
            return value
    return None


def source_ip(event: Dict[str, Any]) -> Optional[str]:
    context = event.get("requestContext") or {}
    http = context.get("http") or {}
    return http.get("sourceIp")
