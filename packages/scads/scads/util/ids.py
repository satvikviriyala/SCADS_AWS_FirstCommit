"""Identifier generation.

Two different needs, deliberately kept apart:

* Record ids (``scn_...``) are prefixed and human-sortable enough to debug.
* S3 object keys embed a random component so that knowing one scan id never
  lets a caller guess another object's key (``AGENTS.md`` section 11:
  "randomized object keys").
"""

import datetime as _dt
import re
import secrets
from typing import Optional

_PREFIXES = {
    "manufacturer": "mfg",
    "sku": "sku",
    "batch": "batch",
    "serial": "ser",
    "reference": "ref",
    "scan": "scn",
    "alert": "alert",
}

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _random_suffix(length: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_id(kind: str) -> str:
    """Return a new prefixed random identifier, e.g. ``scn_a3f...``."""
    if kind not in _PREFIXES:
        raise ValueError("unknown id kind: " + kind)
    return _PREFIXES[kind] + "_" + _random_suffix()


def new_scan_id() -> str:
    return new_id("scan")


_SCAN_ID_RE = re.compile(r"^scn_[0-9a-z]{8,32}$")


def is_valid_scan_id(value: object) -> bool:
    """Validate a client-supplied scan id before it reaches storage.

    Scan ids arrive in URL paths and are used to build S3 keys, so they are
    validated against a strict allowlist pattern rather than sanitised. This is
    the path-traversal guard required by ``docs/SECURITY_PRIVACY.md`` section 3.
    """
    return isinstance(value, str) and bool(_SCAN_ID_RE.match(value))


def scan_object_key(scan_id: str, when: Optional[_dt.datetime] = None, name: str = "original") -> str:
    """Build the S3 key for a scan upload.

    Date-partitioned so an S3 lifecycle rule can expire old demo uploads by
    prefix, and salted so keys are unguessable.
    """
    if not is_valid_scan_id(scan_id):
        raise ValueError("invalid scan id")
    ts = when or _dt.datetime.now(_dt.timezone.utc)
    return "scans/{y:04d}/{m:02d}/{d:02d}/{sid}/{salt}-{name}.jpg".format(
        y=ts.year, m=ts.month, d=ts.day, sid=scan_id, salt=_random_suffix(8), name=name
    )


def reference_object_key(sku_id: str, version: str, variant: str) -> str:
    """Build the S3 key for an enrolled reference image."""
    safe = re.compile(r"[^A-Za-z0-9_.-]")
    return "references/{sku}/{ver}/{variant}.png".format(
        sku=safe.sub("_", sku_id), ver=safe.sub("_", version), variant=safe.sub("_", variant)
    )
