"""Identity evaluation tests (``phases/PHASE_2_IDENTITY.md``).

Run against the real evaluator and a real (offline) registry seeded with the
same demo data the deployed stack uses.
"""

import datetime as _dt

import pytest

from scads.adapters.local_backend import LocalRegistry, reset_local_root
from scads.contracts.enums import EvidenceState, ProductState, RecallStatus, VerificationLevel
from scads.contracts.reason_codes import ReasonCode
from scads.demo import seed_data
from scads.identity import evaluate_identity, extract_claim, parse_qr_payload
from scads.identity.normalize import normalize_expiry
from scads.identity.ocr import OcrResult, OcrWord

TODAY = _dt.date(2026, 9, 18)


@pytest.fixture
def registry(tmp_path):
    root = str(tmp_path / "state")
    reset_local_root(root)
    reg = LocalRegistry(root)
    seed_data.seed_registry(reg)
    return reg


def resolve(registry, payload, ocr=None, today=TODAY):
    claim = parse_qr_payload(payload)
    merged, observed = extract_claim(claim, ocr)
    return evaluate_identity(registry, merged, observed, today=today)


def ocr_with(serial=None, batch=None, expiry=None):
    """Minimal OCR result with labelled fields, as printed on a pack."""
    words = []
    x = 0.6
    for label, value in (("SN", serial), ("B.NO", batch), ("EXP", expiry)):
        if value is None:
            continue
        words.append(OcrWord(label, x, 0.7, 0.05, 0.03, 99.0))
        words.append(OcrWord(value, x + 0.08, 0.7, 0.10, 0.03, 99.0))
        x += 0.02
    return OcrResult(words=words, lines=[], provider="fixture", succeeded=True)


# --- valid unit ---------------------------------------------------------


def test_valid_unit_resolves_to_unit_level(registry):
    identity, product = resolve(registry, seed_data.qr_payload_for("ser_demo_a_001"))
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes
    assert identity.resolved.verification_level is VerificationLevel.UNIT
    assert identity.resolved.serial_id == "ser_demo_a_001"
    assert identity.resolved.product_name == "Paracetamol 500 mg"
    assert identity.resolved.manufacturer_name == "Demo Pharma Ltd"
    assert identity.state is EvidenceState.OK
    assert product.state is ProductState.ACTIVE


def test_second_demo_product_resolves_independently(registry):
    """Two enrolled products, so nothing is hard-coded to one pack."""
    identity, _ = resolve(registry, seed_data.qr_payload_for("ser_demo_b_001"))
    assert identity.resolved.sku_id == "sku_demo_b"
    assert identity.resolved.product_name == "Amoxicillin 250 mg"
    assert identity.resolved.reference_profile_id == "ref_demo_b"


def test_claimed_identity_is_preserved_alongside_resolved(registry):
    """"The pack says X" and "the registry knows X" stay distinguishable."""
    identity, _ = resolve(registry, seed_data.qr_payload_for("ser_demo_a_001"))
    assert identity.claimed.serial == "SER-A-001"
    assert identity.resolved.serial_id == "ser_demo_a_001"
    assert identity.claimed.serial != identity.resolved.serial_id


# --- unknown and revoked -----------------------------------------------


def test_unknown_serial_with_known_batch_degrades_to_batch(registry):
    payload = "SCADS1|SN:SER-A-NEVER-ISSUED|BN:BND-2026-A1"
    identity, product = resolve(registry, payload)
    assert ReasonCode.SERIAL_UNKNOWN in identity.reason_codes
    assert ReasonCode.BATCH_VALID in identity.reason_codes
    assert identity.resolved.verification_level is VerificationLevel.BATCH
    assert identity.resolved.serial_id is None
    assert product.state is ProductState.ACTIVE


def test_unknown_serial_and_unknown_batch(registry):
    identity, product = resolve(registry, "SCADS1|SN:SER-X-000|BN:NOT-A-BATCH")
    assert ReasonCode.SERIAL_UNKNOWN in identity.reason_codes
    assert ReasonCode.BATCH_UNKNOWN in identity.reason_codes
    assert identity.resolved.verification_level is VerificationLevel.NONE
    assert product.state is ProductState.UNKNOWN


def test_batch_only_pack_is_batch_level(registry):
    """A legacy pack with no serial is verifiable only at batch level."""
    identity, _ = resolve(registry, "SCADS1|BN:BND-2026-A1")
    assert ReasonCode.BATCH_VALID in identity.reason_codes
    assert ReasonCode.SERIAL_UNKNOWN not in identity.reason_codes
    assert identity.resolved.verification_level is VerificationLevel.BATCH


def test_revoked_serial_is_a_severe_identity_finding(registry):
    identity, _ = resolve(registry, seed_data.qr_payload_for("ser_demo_a_revoked"))
    assert ReasonCode.SERIAL_REVOKED in identity.reason_codes
    assert ReasonCode.IDENTITY_VALID not in identity.reason_codes
    assert identity.state is EvidenceState.FAIL
    assert identity.score < 0.1


def test_unreadable_pack_reports_parse_failure(registry):
    identity, product = resolve(registry, None)
    assert ReasonCode.IDENTITY_PARSE_FAILED in identity.reason_codes
    assert identity.state is EvidenceState.UNKNOWN
    assert product.state is ProductState.UNKNOWN


def test_llm_cannot_be_needed_to_validate_a_serial(registry):
    """``AGENTS.md`` 6.1: an unknown serial stays unknown.

    Guards against a regression where fuzzy matching is widened until an
    unissued serial resolves to a real one.
    """
    for near_miss in ("SER-A-0011", "SER-A-01", "SERA0011", "SER-A-002X"):
        identity, _ = resolve(registry, "SCADS1|SN:" + near_miss + "|BN:BND-2026-A1")
        assert identity.resolved.serial_id is None, near_miss
        assert ReasonCode.SERIAL_UNKNOWN in identity.reason_codes


def test_single_ocr_character_confusion_still_resolves(registry):
    """A genuine pack misread as O-for-0 should not be called unknown."""
    identity, _ = resolve(registry, None, ocr=ocr_with(serial="SER-A-OO1", batch="BND-2026-A1"))
    assert identity.resolved.serial_id == "ser_demo_a_001"
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes


# --- QR vs OCR cross-check ---------------------------------------------


def test_qr_and_ocr_agreement_raises_no_conflict(registry):
    identity, _ = resolve(
        registry,
        seed_data.qr_payload_for("ser_demo_a_001"),
        ocr=ocr_with(serial="SER-A-001", batch="BND-2026-A1"),
    )
    assert ReasonCode.QR_OCR_CONFLICT not in identity.reason_codes
    assert identity.claimed.source == "QR+OCR"


def test_qr_serial_disagreeing_with_printed_serial_is_a_conflict(registry):
    """A valid code married to different printed text is its own signal."""
    identity, _ = resolve(
        registry,
        seed_data.qr_payload_for("ser_demo_a_001"),
        ocr=ocr_with(serial="SER-A-002", batch="BND-2026-A1"),
    )
    assert ReasonCode.QR_OCR_CONFLICT in identity.reason_codes
    assert identity.state is EvidenceState.WARN


def test_batch_conflict_between_code_and_print_is_detected(registry):
    identity, _ = resolve(
        registry,
        seed_data.qr_payload_for("ser_demo_a_001"),
        ocr=ocr_with(serial="SER-A-001", batch="BND-2026-B1"),
    )
    assert ReasonCode.QR_OCR_CONFLICT in identity.reason_codes


def test_missing_ocr_field_is_not_a_conflict(registry):
    """An unreadable batch overprint must not flag a genuine pack."""
    identity, _ = resolve(
        registry, seed_data.qr_payload_for("ser_demo_a_001"), ocr=ocr_with(serial="SER-A-001")
    )
    assert ReasonCode.QR_OCR_CONFLICT not in identity.reason_codes


def test_failed_ocr_does_not_invent_a_conflict(registry):
    identity, _ = resolve(
        registry,
        seed_data.qr_payload_for("ser_demo_a_001"),
        ocr=OcrResult.failed("fixture", "no ground truth"),
    )
    assert ReasonCode.QR_OCR_CONFLICT not in identity.reason_codes
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes


def test_ocr_only_pack_resolves_without_a_qr(registry):
    """Textract-read text is a real fallback when the code will not decode."""
    identity, _ = resolve(registry, None, ocr=ocr_with(serial="SER-A-001", batch="BND-2026-A1"))
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes
    assert identity.claimed.source == "OCR"


# --- product status is separate from identity ---------------------------


def test_expired_batch_reports_product_status_not_identity_failure(registry):
    identity, product = resolve(registry, seed_data.qr_payload_for("ser_demo_a_expired"))
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes
    assert identity.score > 0.8
    assert product.state is ProductState.EXPIRED
    assert ReasonCode.PRODUCT_EXPIRED in product.reason_codes
    assert ReasonCode.PRODUCT_EXPIRED not in identity.reason_codes


def test_recalled_batch_reports_recall_separately(registry):
    identity, product = resolve(registry, seed_data.qr_payload_for("ser_demo_a_recalled"))
    assert ReasonCode.IDENTITY_VALID in identity.reason_codes
    assert product.state is ProductState.RECALLED
    assert product.recall_status is RecallStatus.RECALLED
    assert ReasonCode.PRODUCT_RECALLED in product.reason_codes


def test_expiry_is_evaluated_against_the_supplied_date(registry):
    """Determinism: product status must not depend on the wall clock."""
    _, before = resolve(
        registry, seed_data.qr_payload_for("ser_demo_a_expired"), today=_dt.date(2025, 1, 1)
    )
    _, after = resolve(
        registry, seed_data.qr_payload_for("ser_demo_a_expired"), today=_dt.date(2026, 1, 1)
    )
    assert before.state is ProductState.ACTIVE
    assert after.state is ProductState.EXPIRED


def test_recall_takes_precedence_over_expiry(registry):
    """A recalled batch is recalled whether or not it also expired."""
    identity, product = resolve(
        registry, seed_data.qr_payload_for("ser_demo_a_recalled"), today=_dt.date(2030, 1, 1)
    )
    assert product.state is ProductState.RECALLED


# --- parsing regression -------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08/2027", "2027-08-31"),
        ("AUG 2027", "2027-08-31"),
        ("270831", "2027-08-31"),
        ("270800", "2027-08-31"),
        ("2027-08-31", "2027-08-31"),
        ("2/27", "2027-02-28"),
        ("FEB-28", "2028-02-29"),
        ("not a date", None),
        ("13/2027", None),
    ],
)
def test_expiry_normalisation(raw, expected):
    assert normalize_expiry(raw) == expected


def test_month_only_expiry_resolves_to_end_of_month():
    """Pharmaceutical convention: a pack marked 08/2027 is usable through the 31st."""
    assert normalize_expiry("08/2027") == "2027-08-31"


def test_oversized_payload_is_rejected_without_parsing():
    claim = parse_qr_payload("SCADS1|SN:" + "A" * 5000)
    assert claim.serial is None
    assert claim.source == "NONE"


def test_variant_match_is_recorded_in_the_evidence(registry):
    """A tolerated misread must be visible, not presented as an exact read."""
    identity, _ = resolve(registry, None, ocr=ocr_with(serial="SER-A-OO1", batch="BND-2026-A1"))
    assert identity.resolved.serial_id == "ser_demo_a_001"
    assert identity.details.get("serial_matched_via_ocr_variant") == "SER-A-001"


def test_exact_match_records_no_variant(registry):
    identity, _ = resolve(registry, seed_data.qr_payload_for("ser_demo_a_001"))
    assert "serial_matched_via_ocr_variant" not in identity.details
