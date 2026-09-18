"""End-to-end API tests: upload -> analyze -> retrieve.

These exercise the real router, the real orchestrator and the real detection
pipeline over the offline backends. Nothing is mocked except AWS itself, and
the AWS boundary is the adapter interface the deployed stack also uses.

The three demo scenarios in ``docs/DEMO_AND_SUBMISSION.md`` are asserted here,
so a regression that breaks the demo breaks the test suite first.
"""

import base64
import datetime as _dt
import json
import os

import pytest

from scads.adapters.factory import build_adapters
from scads.adapters.fixture_ocr import FixtureOcrProvider
from scads.config import local_settings
from scads.contracts.enums import Decision, LocationMode, ScanStatus, VerificationLevel
from scads.demo import seed_data
from scads.demo.fixtures import build_fixture, build_reference, get_fixture
from scads.demo.render import ocr_payload, to_jpeg_bytes, to_png_bytes
from scads.history.locations import get_location
from scads.util.clock import FixedClock, to_iso
from scads.api.router import Router

pytestmark = pytest.mark.slow

NOW = _dt.datetime(2026, 9, 18, 12, 0, 0, tzinfo=_dt.timezone.utc)


class Harness:
    """A fully seeded offline SCADS, driven through the HTTP router."""

    def __init__(self, root: str):
        self.settings = local_settings(root)
        self.adapters = build_adapters(self.settings)
        self.clock = FixedClock(NOW)
        self.router = Router(settings=self.settings, adapters=self.adapters, clock=self.clock)
        self.ocr = FixtureOcrProvider(os.path.join(root, "ocr"))
        self._seed()

    def _seed(self):
        seed_data.seed_registry(self.adapters.registry)
        for profile in seed_data.reference_profiles():
            self.adapters.references.put_reference_profile(profile)
            serial = next(s for s in seed_data.SERIALS if s.sku_id == profile.sku_id)
            pack = build_reference(serial.serial_id)
            self.adapters.store.put_bytes(
                "references", profile.image_s3_key, to_png_bytes(pack.image), "image/png"
            )

    # --- HTTP driving -----------------------------------------------------

    def call(self, method, path, body=None, headers=None):
        event = {
            "requestContext": {"http": {"method": method, "path": path}},
            "headers": headers or {},
        }
        if body is not None:
            event["body"] = json.dumps(body)
        response = self.router.handle(event)
        parsed = json.loads(response["body"]) if response.get("body") else {}
        return response["statusCode"], parsed

    def upload_bytes(self, url, data):
        """PUT bytes to the offline upload route, as the browser would."""
        path = url.split("http://localhost:8000", 1)[-1]
        event = {
            "requestContext": {"http": {"method": "PUT", "path": path}},
            "headers": {},
            "body": base64.b64encode(data).decode("ascii"),
            "isBase64Encoded": True,
        }
        response = self.router.handle(event)
        assert response["statusCode"] == 200, response["body"]

    def scan(self, fixture_name, location_key="BENGALURU_DEMO", with_qr=True):
        """Run one fixture through the whole path and return the result body."""
        spec = get_fixture(fixture_name)
        image, words, lines, profile = build_fixture(spec)
        data = to_jpeg_bytes(image, 92)

        # Register OCR ground truth for exactly these bytes.
        self.ocr.write_sidecar(data, ocr_payload(words, lines))

        status, created = self.call(
            "POST", "/v1/uploads",
            {"content_type": "image/jpeg", "content_length": len(data)},
        )
        assert status == 200, created
        scan_id = created["scan_id"]
        self.upload_bytes(created["upload"]["url"], data)

        body = {}
        if with_qr:
            serial = seed_data.serial_by_id(spec.serial_id)
            qr_serial = spec.qr_serial_override or serial.serial_code
            batch = seed_data.batch_by_id(serial.batch_id)
            sku = seed_data.sku_by_id(serial.sku_id)
            body["qr_payload"] = seed_data.build_qr_payload(
                serial_code=qr_serial, batch_code=batch.batch_code,
                gtin=sku.gtin, expiry=batch.expiry_date, product=sku.product_name,
            )
        if location_key:
            location = get_location(location_key)
            body["location"] = {
                "mode": "DEMO", "label": location.key,
                "lat_bucket": location.lat, "lon_bucket": location.lon,
            }

        status, result = self.call("POST", "/v1/scans/%s/analyze" % scan_id, body)
        assert status == 200, result
        return result

    def seed_prior_scan(self, serial_id, location_key, minutes_ago, scan_id="scn_seedprior0001"):
        from scads.contracts.enums import ActorType
        from scads.contracts.records import ScanEvent

        location = get_location(location_key)
        serial = seed_data.serial_by_id(serial_id)
        self.adapters.events.put_event(
            ScanEvent(
                scan_id=scan_id,
                event_time=to_iso(NOW - _dt.timedelta(minutes=minutes_ago)),
                status=ScanStatus.COMPLETED,
                actor_type=ActorType.CONSUMER,
                serial_id=serial.serial_id,
                batch_id=serial.batch_id,
                sku_id=serial.sku_id,
                location_mode=LocationMode.DEMO,
                location_label=location.key,
                location_lat=location.lat,
                location_lon=location.lon,
                decision=Decision.LOW_OBSERVED_RISK,
                reason_codes=["IDENTITY_VALID", "PHYSICAL_MATCH"],
                demo_tag=seed_data.DEMO_TAG,
            )
        )


@pytest.fixture
def scads(tmp_path):
    return Harness(str(tmp_path / "state"))


# --- health and basics ---------------------------------------------------


def test_health_reports_the_backends_in_use(scads):
    status, body = scads.call("GET", "/v1/health")
    assert status == 200
    assert body["ok"] is True
    assert body["backends"]["store"] == "local"
    assert body["pipeline_version"]
    assert body["fusion_policy_version"]
    # No account identifiers or resource names in a public response.
    serialised = json.dumps(body)
    assert "arn:" not in serialised
    assert "AKIA" not in serialised


def test_unknown_route_is_a_clean_404(scads):
    status, body = scads.call("GET", "/v1/nonexistent")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_catalogue_lists_enrolled_products(scads):
    status, body = scads.call("GET", "/v1/catalogue")
    assert status == 200
    assert len(body["products"]) == 2
    names = {p["product_name"] for p in body["products"]}
    assert "Paracetamol 500 mg" in names


def test_locations_are_labelled_as_simulated(scads):
    status, body = scads.call("GET", "/v1/locations")
    assert status == 200
    assert all(loc["simulated"] for loc in body["locations"])
    assert "does not collect your real location" in body["note"]


# --- upload contract -----------------------------------------------------


def test_upload_rejects_an_unsupported_content_type(scads):
    status, body = scads.call(
        "POST", "/v1/uploads", {"content_type": "application/pdf", "content_length": 1000}
    )
    assert status == 400
    assert body["error"]["code"] == "INVALID_FIELD"


def test_upload_rejects_an_oversized_declared_length(scads):
    status, body = scads.call(
        "POST", "/v1/uploads", {"content_type": "image/jpeg", "content_length": 99_000_000}
    )
    assert status == 400


def test_analyze_before_upload_is_rejected(scads):
    status, created = scads.call(
        "POST", "/v1/uploads", {"content_type": "image/jpeg", "content_length": 1000}
    )
    scan_id = created["scan_id"]
    status, body = scads.call("POST", "/v1/scans/%s/analyze" % scan_id, {})
    assert status == 400
    assert body["error"]["code"] == "UPLOAD_MISSING"


def test_analyze_rejects_a_malformed_scan_id(scads):
    status, body = scads.call("POST", "/v1/scans/..%2Fetc%2Fpasswd/analyze", {})
    assert status in (400, 404)


def test_analyze_of_an_unknown_scan_is_404(scads):
    status, body = scads.call("POST", "/v1/scans/scn_doesnotexist01/analyze", {})
    assert status == 404


# --- demo scenario A: the clean pack -------------------------------------


def test_scenario_a_clean_pack_is_low_observed_risk(scads):
    result = scads.scan("genuine_clean_a")

    assert result["decision"] == Decision.LOW_OBSERVED_RISK.value
    assert result["reason_codes"][:0] == []
    assert "IDENTITY_VALID" in result["reason_codes"]
    assert "PHYSICAL_MATCH" in result["reason_codes"]
    assert "NO_HISTORY_CONTRADICTION" in result["reason_codes"]

    assert result["identity"]["verification_level"] == VerificationLevel.UNIT.value
    assert result["identity"]["product_name"] == "Paracetamol 500 mg"
    assert result["product_status"]["state"] == "ACTIVE"

    dimensions = result["dimensions"]
    assert dimensions["identity_score"] > 0.9
    assert dimensions["physical_score"] > 0.7
    assert dimensions["history_score"] > 0.8
    assert dimensions["scan_quality"] > 0.6


def test_scenario_a_states_the_chemical_limitation(scads):
    result = scads.scan("genuine_clean_a")
    assert "does not test the medicine inside" in result["limitation"]
    assert result["explanation"]["limitation"] == result["limitation"]


def test_second_product_resolves_to_its_own_reference(scads):
    """Guards against a pipeline hard-coded to one pack."""
    result = scads.scan("genuine_clean_b")
    assert result["decision"] == Decision.LOW_OBSERVED_RISK.value
    assert result["identity"]["product_name"] == "Amoxicillin 250 mg"
    assert result["identity"]["sku_id"] == "sku_demo_b"


# --- demo scenario B: visual tamper --------------------------------------


def test_scenario_b_visual_tamper_with_a_valid_serial(scads):
    """The identity is genuine and recognised; the packaging is not."""
    result = scads.scan("tamper_logo_shift")

    assert result["decision"] in (
        Decision.SUSPICIOUS.value, Decision.REVIEW_REQUIRED.value
    )
    # Identity still passes — that is the whole point of the scenario.
    assert "IDENTITY_VALID" in result["reason_codes"]
    assert "PHYSICAL_MATCH" not in result["reason_codes"]
    assert any(
        code in result["reason_codes"]
        for code in ("STRUCTURAL_MISMATCH", "TEXT_LAYOUT_MISMATCH", "PRINT_SHARPNESS_MISMATCH")
    )
    assert result["dimensions"]["identity_score"] > 0.8
    assert result["dimensions"]["physical_score"] < result["dimensions"]["identity_score"]


def test_scenario_b_names_the_region_that_failed(scads):
    """A judge should see *what* did not match, not just that something did."""
    result = scads.scan("tamper_logo_shift")
    features = {f["name"]: f for f in result["evidence"]["physical_features"]}
    assert "structure" in features
    assert not features["structure"]["ok"]
    assert features["structure"]["description"]


# --- demo scenario C: the cloned serial ----------------------------------


def test_scenario_c_cloned_serial_is_suspicious(scads):
    """The decisive scenario.

    A flawless pack carrying a serial the registry recognises. Identity passes.
    Packaging passes. A QR-existence check returns "valid" and stops there.
    SCADS looks at where that serial has already been seen.
    """
    scads.seed_prior_scan("ser_demo_a_clone", "DELHI_DEMO", minutes_ago=58)
    result = scads.scan("genuine_clone_serial", location_key="BENGALURU_DEMO")

    assert result["decision"] == Decision.SUSPICIOUS.value
    assert "IDENTITY_VALID" in result["reason_codes"]
    assert "PHYSICAL_MATCH" in result["reason_codes"]
    assert "IMPOSSIBLE_TRAVEL" in result["reason_codes"]
    assert "SERIAL_REUSE" in result["reason_codes"]

    # Identity and packaging genuinely look good; history is what objects.
    assert result["dimensions"]["identity_score"] > 0.9
    assert result["dimensions"]["physical_score"] > 0.7
    assert result["dimensions"]["history_score"] < 0.2


def test_scenario_c_explains_itself_with_real_numbers(scads):
    scads.seed_prior_scan("ser_demo_a_clone", "DELHI_DEMO", minutes_ago=58)
    result = scads.scan("genuine_clone_serial")

    findings = {f["code"]: f for f in result["history"]["findings"]}
    travel = findings["IMPOSSIBLE_TRAVEL"]
    assert travel["evidence"]["distance_km"] == pytest.approx(1739.8, abs=5)
    assert travel["evidence"]["elapsed_minutes"] == pytest.approx(58.0, abs=0.5)
    assert travel["evidence"]["implied_speed_kmh"] > 900
    assert "Delhi" in travel["summary"] or "DELHI" in travel["summary"]

    assert result["history"]["prior_scans"]
    assert result["history"]["prior_scans"][0]["location_label"] == "DELHI_DEMO"


def test_scenario_c_records_why_it_was_capped(scads):
    scads.seed_prior_scan("ser_demo_a_clone", "DELHI_DEMO", minutes_ago=58)
    result = scads.scan("genuine_clone_serial")
    caps = {c["code"]: c for c in result["evidence"]["applied_caps"]}
    assert "IMPOSSIBLE_TRAVEL" in caps
    assert caps["IMPOSSIBLE_TRAVEL"]["rationale"]
    # The unconstrained fusion score was higher; the cap is what decided this.
    assert result["evidence"]["base_score"] > result["presentation_score"]


def test_same_serial_scanned_twice_nearby_is_not_flagged(scads):
    """The false-positive side of the clone rule: a person rescanning a pack."""
    scads.seed_prior_scan("ser_demo_a_001", "PHARMACY_DEMO", minutes_ago=6)
    result = scads.scan("genuine_clean_a", location_key="BENGALURU_DEMO")
    assert "IMPOSSIBLE_TRAVEL" not in result["reason_codes"]
    assert "SERIAL_REUSE" not in result["reason_codes"]
    assert result["decision"] == Decision.LOW_OBSERVED_RISK.value


# --- other evidence combinations -----------------------------------------


def test_unknown_serial_on_a_perfect_pack_is_not_low_risk(scads):
    """AT-02: a flawless photograph cannot launder an unissued serial."""
    result = scads.scan("identity_unknown_serial")
    assert result["decision"] != Decision.LOW_OBSERVED_RISK.value
    assert "SERIAL_UNKNOWN" in result["reason_codes"]
    # The packaging really is genuine, and the result says so.
    assert "PHYSICAL_MATCH" in result["reason_codes"]


def test_qr_and_print_conflict_is_detected(scads):
    result = scads.scan("identity_qr_print_conflict")
    assert "QR_OCR_CONFLICT" in result["reason_codes"]
    assert result["decision"] != Decision.LOW_OBSERVED_RISK.value


def test_revoked_serial_is_suspicious(scads):
    result = scads.scan("genuine_revoked_unit")
    assert result["decision"] == Decision.SUSPICIOUS.value
    assert "SERIAL_REVOKED" in result["reason_codes"]


def test_dispensed_unit_triggers_post_sale_reuse(scads):
    result = scads.scan("genuine_dispensed_unit")
    assert "POST_SALE_REUSE" in result["reason_codes"]
    assert result["decision"] == Decision.SUSPICIOUS.value


def test_expired_batch_is_reported_as_product_status_not_counterfeit(scads):
    """AT-07: an expired pack can be entirely authentic."""
    result = scads.scan("genuine_expired_batch")
    assert result["product_status"]["state"] == "EXPIRED"
    assert "PRODUCT_EXPIRED" in result["reason_codes"]
    assert "IDENTITY_VALID" in result["reason_codes"]
    assert "PHYSICAL_MATCH" in result["reason_codes"]
    assert result["decision"] == Decision.LOW_OBSERVED_RISK.value
    assert "expired" in result["explanation"]["product_status_note"].lower()


def test_recalled_batch_requires_review(scads):
    result = scads.scan("genuine_recalled_batch")
    assert result["product_status"]["recall_status"] == "RECALLED"
    assert result["decision"] == Decision.REVIEW_REQUIRED.value


@pytest.mark.parametrize(
    "fixture", ["quality_blurred", "quality_dark", "quality_glare", "quality_pack_too_small"]
)
def test_poor_captures_are_unverifiable_never_suspicious(scads, fixture):
    """AT-04, through the whole API. The most important safety property."""
    result = scads.scan(fixture)
    assert result["decision"] == Decision.UNABLE_TO_VERIFY.value
    assert result["presentation_score"] is None
    assert result["presentation_score_applicable"] is False
    assert "retake" in result["next_action"].lower() or "not enough" in result["next_action"].lower()


def test_scan_without_a_qr_falls_back_to_printed_text(scads):
    """Textract OCR of the printed serial is a real fallback path."""
    result = scads.scan("genuine_clean_a", with_qr=False)
    assert result["claimed_identity"]["source"] == "OCR"
    assert "IDENTITY_VALID" in result["reason_codes"]


# --- persistence and provenance ------------------------------------------


def test_result_is_retrievable_afterwards(scads):
    result = scads.scan("genuine_clean_a")
    status, fetched = scads.call("GET", "/v1/scans/%s" % result["scan_id"])
    assert status == 200
    assert fetched["decision"] == result["decision"]
    assert fetched["reason_codes"] == result["reason_codes"]
    assert fetched["status"] == ScanStatus.COMPLETED.value


def test_every_result_records_its_versions(scads):
    """AT-10: a stored result must be re-evaluable."""
    result = scads.scan("genuine_clean_a")
    evidence = result["evidence"]
    assert evidence["pipeline_version"]
    assert evidence["fusion_policy_version"]
    assert evidence["reference_version"] == seed_data.REFERENCE_VERSION
    assert evidence["contract_version"]
    assert evidence["ocr_provider"] == "fixture"


def test_stored_event_carries_the_evidence_not_the_raw_ocr(scads):
    """``AGENTS.md`` 6.5: bounded evidence, no unbounded sensitive metadata."""
    result = scads.scan("genuine_clean_a")
    event = scads.adapters.events.get_event(result["scan_id"])
    assert event.reason_codes
    assert event.evidence["physical_features"]
    assert event.evidence["weights_used"]
    serialised = json.dumps(event.evidence)
    assert "PARACETAMOL" not in serialised  # no raw OCR text
    assert "ocr_word_count" in event.evidence


def test_a_scan_does_not_detect_itself_as_a_duplicate(scads):
    result = scads.scan("genuine_clean_a")
    assert "SERIAL_REUSE" not in result["reason_codes"]


def test_repeated_analysis_of_the_same_image_is_deterministic(scads):
    """AT-09 through the API, holding history constant."""
    first = scads.scan("tamper_logo_shift")
    second = scads.scan("tamper_logo_shift")
    assert first["decision"] == second["decision"]
    assert first["dimensions"]["physical_score"] == second["dimensions"]["physical_score"]
    assert first["dimensions"]["identity_score"] == second["dimensions"]["identity_score"]


# --- admin plane ---------------------------------------------------------


def test_demo_reset_requires_the_admin_token(scads):
    status, body = scads.call("POST", "/v1/admin/demo/reset", {})
    assert status == 401
    status, body = scads.call(
        "POST", "/v1/admin/demo/reset", {}, headers={"X-Admin-Token": "wrong"}
    )
    assert status == 401


def test_demo_reset_removes_only_seeded_events(scads):
    scads.seed_prior_scan("ser_demo_a_clone", "DELHI_DEMO", minutes_ago=58)
    real = scads.scan("genuine_clean_a")

    status, body = scads.call(
        "POST", "/v1/admin/demo/reset", {},
        headers={"X-Admin-Token": scads.settings.admin_api_token},
    )
    assert status == 200
    assert body["events_removed"] >= 1

    # The seeded fixture is gone; the real observation is untouched.
    assert scads.adapters.events.get_event("scn_seedprior0001") is None
    assert scads.adapters.events.get_event(real["scan_id"]) is not None
