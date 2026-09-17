"""Scan-history rule tests (``phases/PHASE_4_HISTORY_AND_FUSION.md``).

The rules are what make SCADS more than a database lookup, so they are tested
against exact seeded fixtures with a frozen clock — never against wall time.
"""

import datetime as _dt

import pytest

from scads.adapters.local_backend import LocalScanEventStore, reset_local_root
from scads.adapters.base import DependencyUnavailable, ScanEventStore
from scads.contracts.enums import (
    ActorType,
    Decision,
    EvidenceState,
    LocationMode,
    ScanStatus,
    SerialStatus,
)
from scads.contracts.models import ScanLocation
from scads.contracts.reason_codes import ReasonCode
from scads.contracts.records import ScanEvent, SerialRecord
from scads.history import evaluate_history
from scads.history.locations import get_location
from scads.util.clock import to_iso

NOW = _dt.datetime(2026, 9, 18, 10, 0, 0, tzinfo=_dt.timezone.utc)
SERIAL = "ser_demo_a_clone"


@pytest.fixture
def events(tmp_path):
    root = str(tmp_path / "state")
    reset_local_root(root)
    return LocalScanEventStore(root)


def at(minutes_ago):
    return to_iso(NOW - _dt.timedelta(minutes=minutes_ago))


def location(key):
    loc = get_location(key)
    return ScanLocation(mode=LocationMode.DEMO, label=loc.key, lat=loc.lat, lon=loc.lon)


def seed_event(
    events,
    scan_id,
    minutes_ago,
    location_key,
    serial=SERIAL,
    status=ScanStatus.COMPLETED,
    decision=Decision.LOW_OBSERVED_RISK,
):
    loc = get_location(location_key)
    events.put_event(
        ScanEvent(
            scan_id=scan_id,
            event_time=at(minutes_ago),
            status=status,
            actor_type=ActorType.CONSUMER,
            serial_id=serial,
            location_mode=LocationMode.DEMO,
            location_label=loc.key,
            location_lat=loc.lat,
            location_lon=loc.lon,
            decision=decision,
            demo_tag="test",
        )
    )


def evaluate(events, current_location="BENGALURU_DEMO", serial=SERIAL, record=None):
    return evaluate_history(
        events,
        serial_id=serial,
        location=location(current_location),
        now=NOW,
        serial_record=record,
        current_scan_id="scn_current",
    )


# --- clean cases --------------------------------------------------------


def test_first_scan_of_a_unit_is_clean(events):
    result = evaluate(events)
    assert result.available
    assert result.state is EvidenceState.OK
    assert result.reason_codes == [ReasonCode.NO_HISTORY_CONTRADICTION]
    assert result.details["first_scan_of_unit"] is True


def test_immediate_rescan_in_the_same_place_is_not_reuse(events):
    """A consumer looking at the pack twice is not a cloned serial."""
    seed_event(events, "scn_prior", minutes_ago=4, location_key="BENGALURU_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert result.reason_codes == [ReasonCode.NO_HISTORY_CONTRADICTION]
    assert result.state is EvidenceState.OK


def test_nearby_rescan_within_grace_is_not_reuse(events):
    """The pharmacy and the city centre are the same area for this purpose."""
    seed_event(events, "scn_prior", minutes_ago=10, location_key="PHARMACY_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert result.reason_codes == [ReasonCode.NO_HISTORY_CONTRADICTION]


def test_plausible_travel_over_days_is_not_flagged(events):
    """A pack genuinely moving through the supply chain must pass."""
    seed_event(events, "scn_prior", minutes_ago=60 * 72, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.IMPOSSIBLE_TRAVEL not in result.reason_codes


def test_domestic_flight_speed_is_plausible(events):
    """Delhi to Bengaluru in three hours is a flight, not a clone."""
    seed_event(events, "scn_prior", minutes_ago=180, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.IMPOSSIBLE_TRAVEL not in result.reason_codes


# --- the demo scenario --------------------------------------------------


def test_impossible_travel_is_detected_with_checkable_numbers(events):
    """Scenario C: same serial, Delhi 58 minutes ago, now Bengaluru."""
    seed_event(events, "scn_prior", minutes_ago=58, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")

    assert ReasonCode.IMPOSSIBLE_TRAVEL in result.reason_codes
    assert result.state is EvidenceState.FAIL
    assert result.score <= 0.15

    finding = next(f for f in result.findings if f.code is ReasonCode.IMPOSSIBLE_TRAVEL)
    assert finding.evidence["distance_km"] == pytest.approx(1739.8, abs=5.0)
    assert finding.evidence["elapsed_minutes"] == pytest.approx(58.0, abs=0.2)
    assert finding.evidence["implied_speed_kmh"] > 900
    assert "Delhi" in finding.summary or "DELHI" in finding.summary


def test_impossible_travel_also_reports_serial_reuse(events):
    """Both facts are true and both are reported; neither replaces the other."""
    seed_event(events, "scn_prior", minutes_ago=58, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.SERIAL_REUSE in result.reason_codes
    assert ReasonCode.IMPOSSIBLE_TRAVEL in result.reason_codes


def test_history_timeline_is_returned_for_the_ui(events):
    seed_event(events, "scn_prior", minutes_ago=58, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert len(result.prior_scans) == 1
    prior = result.prior_scans[0]
    assert prior.location_label == "DELHI_DEMO"
    assert prior.location_mode is LocationMode.DEMO


# --- reuse and burst ----------------------------------------------------


def test_distant_repeat_is_serial_reuse_even_when_travel_is_plausible(events):
    seed_event(events, "scn_prior", minutes_ago=60 * 96, location_key="DELHI_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.SERIAL_REUSE in result.reason_codes
    assert ReasonCode.IMPOSSIBLE_TRAVEL not in result.reason_codes


def test_scan_burst_across_many_cities(events):
    """A code copied across a print run shows up from everywhere at once."""
    seed_event(events, "scn_1", minutes_ago=300, location_key="DELHI_DEMO")
    seed_event(events, "scn_2", minutes_ago=400, location_key="MUMBAI_DEMO")
    seed_event(events, "scn_3", minutes_ago=500, location_key="KOLKATA_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.SCAN_VELOCITY_ANOMALY in result.reason_codes
    finding = next(f for f in result.findings if f.code is ReasonCode.SCAN_VELOCITY_ANOMALY)
    assert len(finding.evidence["distinct_locations"]) >= 3


def test_post_sale_reuse_fires_on_registry_state_alone(events):
    """A diverted pack is caught on its first scan, before any duplicate exists."""
    record = SerialRecord(
        serial_id=SERIAL,
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-555",
        status=SerialStatus.DISPENSED,
        dispensed_at="2026-08-20T11:30:00Z",
    )
    result = evaluate(events, record=record)
    assert ReasonCode.POST_SALE_REUSE in result.reason_codes
    assert result.state is EvidenceState.FAIL
    assert result.details["first_scan_of_unit"] is True


def test_active_serial_does_not_trigger_post_sale_reuse(events):
    record = SerialRecord(
        serial_id=SERIAL,
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-001",
        status=SerialStatus.ACTIVE,
    )
    result = evaluate(events, record=record)
    assert ReasonCode.POST_SALE_REUSE not in result.reason_codes


# --- availability semantics ---------------------------------------------


def test_no_serial_means_history_unavailable_not_clean(events):
    """A batch-level scan has no unit history; saying "clean" would be false."""
    result = evaluate(events, serial=None)
    assert not result.available
    assert result.reason_codes == [ReasonCode.HISTORY_UNAVAILABLE]
    assert result.state is EvidenceState.UNKNOWN


def test_event_store_failure_is_reported_not_swallowed(events):
    """``docs/AWS_DEPLOYMENT.md`` 11: never present a failed query as H=1."""

    class BrokenStore(ScanEventStore):
        backend_name = "broken"

        def put_event(self, event):
            raise NotImplementedError

        def get_event(self, scan_id):
            raise NotImplementedError

        def query_by_serial(self, serial_id, limit=50):
            raise DependencyUnavailable("dynamodb_query", "throttled")

        def delete_events_by_demo_tag(self, demo_tag):
            raise NotImplementedError

    result = evaluate(BrokenStore())
    assert not result.available
    assert ReasonCode.HISTORY_UNAVAILABLE in result.reason_codes
    assert result.score == 0.0
    assert result.details["dependency"] == "dynamodb_query"


def test_the_current_scan_does_not_detect_itself(events):
    """The scan record exists before analysis runs, so it must be excluded."""
    seed_event(events, "scn_current", minutes_ago=0, location_key="BENGALURU_DEMO")
    result = evaluate(events, "BENGALURU_DEMO")
    assert result.reason_codes == [ReasonCode.NO_HISTORY_CONTRADICTION]


def test_failed_and_unverifiable_prior_scans_are_not_evidence(events):
    """A flaky upload must not manufacture a duplicate-serial finding."""
    seed_event(
        events, "scn_failed", minutes_ago=58, location_key="DELHI_DEMO",
        status=ScanStatus.FAILED, decision=None,
    )
    seed_event(
        events, "scn_unverifiable", minutes_ago=57, location_key="MUMBAI_DEMO",
        status=ScanStatus.COMPLETED, decision=Decision.UNABLE_TO_VERIFY,
    )
    seed_event(
        events, "scn_created", minutes_ago=56, location_key="CHENNAI_DEMO",
        status=ScanStatus.CREATED, decision=None,
    )
    result = evaluate(events, "BENGALURU_DEMO")
    assert result.reason_codes == [ReasonCode.NO_HISTORY_CONTRADICTION]


def test_history_rules_are_deterministic(events):
    seed_event(events, "scn_prior", minutes_ago=58, location_key="DELHI_DEMO")
    runs = [evaluate(events, "BENGALURU_DEMO") for _ in range(5)]
    assert len({tuple(r.reason_codes) for r in runs}) == 1
    assert len({r.score for r in runs}) == 1


def test_prior_event_without_a_location_is_handled(events):
    """A scan with no consented location still counts as an observation."""
    events.put_event(
        ScanEvent(
            scan_id="scn_nolocation",
            event_time=at(58),
            status=ScanStatus.COMPLETED,
            serial_id=SERIAL,
            location_mode=LocationMode.NONE,
            decision=Decision.LOW_OBSERVED_RISK,
        )
    )
    result = evaluate(events, "BENGALURU_DEMO")
    assert ReasonCode.SERIAL_REUSE in result.reason_codes
    assert ReasonCode.IMPOSSIBLE_TRAVEL not in result.reason_codes


def test_unparseable_prior_timestamp_does_not_crash(events):
    events.put_event(
        ScanEvent(
            scan_id="scn_bad_time",
            event_time="not-a-timestamp",
            status=ScanStatus.COMPLETED,
            serial_id=SERIAL,
            location_mode=LocationMode.DEMO,
            location_label="DELHI_DEMO",
            decision=Decision.LOW_OBSERVED_RISK,
        )
    )
    result = evaluate(events, "BENGALURU_DEMO")
    assert result.available
