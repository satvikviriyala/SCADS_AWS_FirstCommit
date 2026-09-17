"""Time handling.

Every timestamp SCADS stores is UTC and ISO-8601 with a ``Z`` suffix, because
scan-history rules compare times across locations and a naive local timestamp
would make "impossible travel" unreproducible.

The indirection through a :class:`Clock` exists so history tests can construct
an exact past without sleeping.
"""

import datetime as _dt
from typing import Optional

UTC = _dt.timezone.utc


class Clock:
    """Wall-clock source. Overridden in tests by :class:`FixedClock`."""

    def now(self) -> _dt.datetime:
        return _dt.datetime.now(UTC)

    def now_iso(self) -> str:
        return to_iso(self.now())


class FixedClock(Clock):
    """A clock frozen at a chosen instant."""

    def __init__(self, moment: _dt.datetime) -> None:
        self._moment = ensure_utc(moment)

    def now(self) -> _dt.datetime:
        return self._moment


def ensure_utc(value: _dt.datetime) -> _dt.datetime:
    """Attach UTC to a naive datetime, or convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_iso(value: _dt.datetime) -> str:
    """Serialise to ``YYYY-MM-DDTHH:MM:SSZ`` (second precision)."""
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> Optional[_dt.datetime]:
    """Parse an ISO-8601 timestamp, tolerating ``Z`` and fractional seconds.

    Returns ``None`` rather than raising: timestamps can arrive from stored
    records written by older code, and a history rule must degrade to "cannot
    compare these two events" instead of failing the whole scan.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(_dt.datetime.fromisoformat(text))
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return ensure_utc(_dt.datetime.strptime(text, fmt))
            except ValueError:
                continue
    return None


def parse_date(value: str) -> Optional[_dt.date]:
    parsed = parse_iso(value)
    return parsed.date() if parsed else None


def hours_between(earlier: _dt.datetime, later: _dt.datetime) -> float:
    """Absolute hours between two instants."""
    delta = ensure_utc(later) - ensure_utc(earlier)
    return abs(delta.total_seconds()) / 3600.0


def minutes_between(earlier: _dt.datetime, later: _dt.datetime) -> float:
    delta = ensure_utc(later) - ensure_utc(earlier)
    return abs(delta.total_seconds()) / 60.0
