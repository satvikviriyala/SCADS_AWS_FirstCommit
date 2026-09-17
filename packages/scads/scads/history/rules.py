"""Scan-history anomaly rules.

This is the evidence layer that a QR/database check structurally cannot have.
A copied serial is *valid* in the registry and can sit on a *beautifully
printed* pack — so identity and packaging both pass. What gives it away is the
behaviour of the identifier over time: the same unit appearing twice, appearing
somewhere it could not have travelled to, or reappearing after it was already
dispensed.

Every rule is written as a pure function over prior events so it can be tested
against exact fixtures, and every finding carries the numbers that produced it.

Thresholds here are demonstration values. ``MAX_PLAUSIBLE_SPEED_KMH`` is a
deliberately generous bound chosen so that ordinary travel — including
domestic flights — does not trigger the rule; it is not a calibrated
logistics model (``docs/SCORING_AND_DETECTION.md`` section 9.2).
"""

import datetime as _dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..contracts.enums import Decision, LocationMode, SerialStatus
from ..contracts.models import HistoryFinding, ScanLocation
from ..contracts.reason_codes import ReasonCode
from ..contracts.records import ScanEvent, SerialRecord
from ..util.clock import hours_between, minutes_between, parse_iso
from ..util.geo import haversine_km, implied_speed_kmh
from .locations import resolve_coordinates

# Faster than a commercial flight plus transfers. Above this, one physical pack
# cannot have been in both places.
MAX_PLAUSIBLE_SPEED_KMH = 900.0

# Distance below which two scans are "the same place" and travel time is not
# meaningful. Covers a city and its metropolitan area.
SAME_AREA_KM = 60.0

# A consumer re-scanning the pack they are holding is normal. Only a repeat from
# a *different* place, or after a long gap, is treated as a second observation
# of a supposedly unique unit.
RESCAN_GRACE_MINUTES = 30.0

# Rolling window and threshold for the burst rule.
VELOCITY_WINDOW_HOURS = 24.0
VELOCITY_DISTINCT_LOCATIONS = 3


@dataclass(frozen=True)
class HistoryContext:
    """Everything the rules need, gathered once."""

    serial_id: Optional[str]
    now: _dt.datetime
    location: ScanLocation
    prior_events: List[ScanEvent]
    serial_record: Optional[SerialRecord] = None


def _event_position(event: ScanEvent) -> Tuple[Optional[float], Optional[float]]:
    return resolve_coordinates(event.location_label, event.location_lat, event.location_lon)


def _current_position(location: ScanLocation) -> Tuple[Optional[float], Optional[float]]:
    return resolve_coordinates(location.label, location.lat, location.lon)


def _label(event: ScanEvent) -> str:
    return event.location_label or "an unrecorded location"


def rule_serial_reuse(ctx: HistoryContext) -> Optional[HistoryFinding]:
    """The same unit serial observed as more than one pack.

    A unit serial is meant to identify one physical pack. The nuance that keeps
    this from firing on normal behaviour: a repeat scan from the same area
    within the grace window is the same person looking at the same pack, and is
    not counted.
    """
    if not ctx.prior_events:
        return None

    current_lat, current_lon = _current_position(ctx.location)
    independent: List[ScanEvent] = []

    for event in ctx.prior_events:
        event_time = parse_iso(event.event_time)
        if event_time is None:
            continue
        elapsed = minutes_between(event_time, ctx.now)

        prior_lat, prior_lon = _event_position(event)
        distance = None
        if None not in (current_lat, current_lon, prior_lat, prior_lon):
            distance = haversine_km(current_lat, current_lon, prior_lat, prior_lon)

        same_place_recently = (
            elapsed <= RESCAN_GRACE_MINUTES
            and distance is not None
            and distance <= SAME_AREA_KM
        )
        if not same_place_recently:
            independent.append(event)

    if not independent:
        return None

    newest = independent[0]
    return HistoryFinding(
        code=ReasonCode.SERIAL_REUSE,
        summary=(
            "This serial has already been recorded {count} time{plural} before, most "
            "recently at {place}.".format(
                count=len(independent),
                plural="" if len(independent) == 1 else "s",
                place=_label(newest),
            )
        ),
        evidence={
            "prior_independent_scans": len(independent),
            "most_recent_event_time": newest.event_time,
            "most_recent_location": newest.location_label,
        },
    )


def rule_impossible_travel(ctx: HistoryContext) -> Optional[HistoryFinding]:
    """The same serial in two places too far apart for the time between them.

    Reported with the distance, the elapsed time and the implied speed, so the
    finding is checkable rather than asserted.
    """
    current_lat, current_lon = _current_position(ctx.location)
    if current_lat is None or current_lon is None:
        return None

    worst: Optional[Dict[str, object]] = None

    for event in ctx.prior_events:
        prior_lat, prior_lon = _event_position(event)
        event_time = parse_iso(event.event_time)
        if prior_lat is None or prior_lon is None or event_time is None:
            continue

        distance = haversine_km(current_lat, current_lon, prior_lat, prior_lon)
        if distance <= SAME_AREA_KM:
            continue

        elapsed_hours = hours_between(event_time, ctx.now)
        speed = implied_speed_kmh(distance, elapsed_hours)
        if speed <= MAX_PLAUSIBLE_SPEED_KMH:
            continue

        if worst is None or speed > worst["implied_speed_kmh"]:
            worst = {
                "distance_km": round(distance, 1),
                "elapsed_minutes": round(elapsed_hours * 60.0, 1),
                "implied_speed_kmh": round(speed, 1),
                "max_plausible_speed_kmh": MAX_PLAUSIBLE_SPEED_KMH,
                "from_location": event.location_label,
                "to_location": ctx.location.label,
                "prior_event_time": event.event_time,
                "prior_scan_id": event.scan_id,
            }

    if worst is None:
        return None

    return HistoryFinding(
        code=ReasonCode.IMPOSSIBLE_TRAVEL,
        summary=(
            "The same serial was recorded at {frm} about {mins:.0f} minutes ago, "
            "{km:.0f} km away. One pack would have had to travel at {speed:.0f} km/h "
            "to be in both places.".format(
                frm=worst["from_location"] or "another location",
                mins=worst["elapsed_minutes"],
                km=worst["distance_km"],
                speed=worst["implied_speed_kmh"],
            )
        ),
        evidence=worst,
    )


def rule_post_sale_reuse(ctx: HistoryContext) -> Optional[HistoryFinding]:
    """A unit the registry records as already dispensed or decommissioned.

    Registry state, not an inference from scan history, so this fires on the
    first scan of a diverted pack — before any duplicate exists to detect.
    """
    record = ctx.serial_record
    if record is None:
        return None
    if record.status not in (SerialStatus.DISPENSED, SerialStatus.DECOMMISSIONED):
        return None

    when = record.dispensed_at or record.decommissioned_at
    return HistoryFinding(
        code=ReasonCode.POST_SALE_REUSE,
        summary=(
            "The registry records this unit as {state} already"
            + (" (on " + when[:10] + ")" if when else "")
            + ", so it should not be appearing as a new pack."
        ).format(state=record.status.value.lower()),
        evidence={
            "registry_status": record.status.value,
            "dispensed_at": record.dispensed_at,
            "decommissioned_at": record.decommissioned_at,
        },
    )


def rule_scan_velocity(ctx: HistoryContext) -> Optional[HistoryFinding]:
    """One serial appearing from many distinct places in a short window.

    The signature of a code copied onto a print run rather than one pack
    changing hands.
    """
    if not ctx.prior_events:
        return None

    places = set()
    if ctx.location.label:
        places.add(ctx.location.label)

    for event in ctx.prior_events:
        event_time = parse_iso(event.event_time)
        if event_time is None:
            continue
        if hours_between(event_time, ctx.now) > VELOCITY_WINDOW_HOURS:
            continue
        if event.location_label:
            places.add(event.location_label)

    if len(places) < VELOCITY_DISTINCT_LOCATIONS:
        return None

    return HistoryFinding(
        code=ReasonCode.SCAN_VELOCITY_ANOMALY,
        summary=(
            "This serial was scanned from {n} different places in the last "
            "{h:.0f} hours.".format(n=len(places), h=VELOCITY_WINDOW_HOURS)
        ),
        evidence={
            "distinct_locations": sorted(places),
            "window_hours": VELOCITY_WINDOW_HOURS,
            "threshold": VELOCITY_DISTINCT_LOCATIONS,
        },
    )


# Evaluated in this order; the resulting findings drive both reason codes and
# the history score.
ALL_RULES = (
    rule_post_sale_reuse,
    rule_impossible_travel,
    rule_serial_reuse,
    rule_scan_velocity,
)


def evaluate_rules(ctx: HistoryContext) -> List[HistoryFinding]:
    findings: List[HistoryFinding] = []
    for rule in ALL_RULES:
        finding = rule(ctx)
        if finding is not None:
            findings.append(finding)
    return findings
