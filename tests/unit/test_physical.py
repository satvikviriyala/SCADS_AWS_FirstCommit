"""Physical pipeline tests (``phases/PHASE_3_PHYSICAL.md``).

Run against rendered packs put through the capture simulator, so the pipeline
faces the problem it faces in production: recover the artwork through an unknown
camera transform, then decide whether it matches.

Thresholds asserted here come from ``scripts/calibrate.py`` measurements over
the corpus, not from intuition. Ranges are deliberately loose — ``docs/EVALUATION.md``
section 7 warns against asserting fragile floats — but the *orderings* and the
*reason codes* are asserted exactly, because those are the contract.
"""

import numpy as np
import pytest

from scads.contracts.enums import EvidenceState
from scads.contracts.reason_codes import ReasonCode
from scads.demo import seed_data
from scads.demo.fixtures import FIXTURES, build_fixture, build_reference, get_fixture, tamper_sweep
from scads.demo.render import to_jpeg_bytes, to_png_bytes
from scads.identity.ocr import OcrResult, OcrWord
from scads.physical.image import ImageRejected, load_image, sniff_content_type
from scads.physical.pipeline import DEFAULT_THRESHOLDS, compare_packaging
from scads.physical.quality import assess_quality
from scads.physical.registration import compute_homography, register

MAX_BYTES = 8 * 1024 * 1024

pytestmark = pytest.mark.slow

_REFERENCES = {}
_ANALYSES = {}


def reference_gray(serial_id):
    if serial_id not in _REFERENCES:
        pack = build_reference(serial_id)
        _REFERENCES[serial_id] = np.asarray(pack.image.convert("L"), dtype=np.float32) / 255.0
    return _REFERENCES[serial_id]


def analyse(name):
    """Quality + packaging comparison for a named fixture, memoised."""
    if name in _ANALYSES:
        return _ANALYSES[name]
    spec = get_fixture(name)
    image, words, lines, profile = build_fixture(spec)
    loaded = load_image(to_jpeg_bytes(image, 92), MAX_BYTES)
    quality = assess_quality(loaded)
    ocr = OcrResult(
        words=[OcrWord(w.text, w.x, w.y, w.width, w.height, 99.0) for w in words],
        lines=lines,
        provider="fixture",
    )
    evidence = compare_packaging(
        loaded, reference_gray(spec.serial_id), profile, ocr,
        capture_sharpness=quality.metrics["sharpness"],
    )
    result = (spec, quality, evidence)
    _ANALYSES[name] = result
    return result


PHYSICAL_MISMATCH_CODES = {
    ReasonCode.TEXT_CONTENT_MISMATCH,
    ReasonCode.TEXT_LAYOUT_MISMATCH,
    ReasonCode.STRUCTURAL_MISMATCH,
    ReasonCode.PRINT_SHARPNESS_MISMATCH,
}

GENUINE = [f.name for f in FIXTURES if f.label == "genuine"]
ARTWORK_TAMPERS = [f.name for f in FIXTURES if f.label == "synthetic_tamper"]
IDENTITY_TAMPERS = [f.name for f in FIXTURES if f.label == "identity_tamper"]


# --- reference enrollment ------------------------------------------------


def test_dynamic_rois_never_overlap_static_ones():
    """A legitimate batch change must not touch a compared region.

    The batch/expiry overprint and the QR differ between two genuine packs of
    the same product. If either overlapped a region used for structural
    comparison, every pack from a new batch would look tampered.
    """
    for profile in seed_data.reference_profiles():
        for dynamic in (r for r in profile.stable_rois if r.dynamic):
            for static in profile.static_rois:
                overlap = not (
                    dynamic.x + dynamic.width <= static.x
                    or static.x + static.width <= dynamic.x
                    or dynamic.y + dynamic.height <= static.y
                    or static.y + static.height <= dynamic.y
                )
                assert not overlap, (
                    profile.reference_profile_id, dynamic.name, static.name
                )


def test_all_rois_are_inside_the_canonical_frame():
    for profile in seed_data.reference_profiles():
        for roi in profile.stable_rois:
            assert 0.0 <= roi.x and 0.0 <= roi.y
            assert roi.x + roi.width <= 1.0001
            assert roi.y + roi.height <= 1.0001


def test_anchors_are_measured_from_the_rendered_artwork():
    """Enrolled anchor positions must match where the words actually are."""
    for profile in seed_data.reference_profiles():
        assert profile.ocr_anchors, profile.reference_profile_id
        pack = build_reference(
            next(s.serial_id for s in seed_data.SERIALS if s.sku_id == profile.sku_id)
        )
        by_text = {w.text.strip().upper(): w for w in pack.words}
        for anchor in profile.ocr_anchors:
            word = by_text.get(anchor.text)
            assert word is not None, (profile.reference_profile_id, anchor.text)
            distance = ((word.x - anchor.x) ** 2 + (word.y - anchor.y) ** 2) ** 0.5
            assert distance < 0.01, (anchor.name, distance)


def test_two_products_have_distinct_references():
    """Guards against a pipeline accidentally hard-coded to one pack."""
    profiles = seed_data.reference_profiles()
    assert len(profiles) >= 2
    texts = [tuple(a.text for a in p.ocr_anchors) for p in profiles]
    assert len(set(texts)) == len(texts)


# --- upload validation ---------------------------------------------------


def test_magic_bytes_are_checked_not_just_the_declared_type():
    with pytest.raises(ImageRejected) as excinfo:
        load_image(b"GIF89a" + b"\x00" * 4000, MAX_BYTES, declared_type="image/jpeg")
    assert excinfo.value.code == "UNSUPPORTED_MEDIA_TYPE"


def test_oversized_upload_is_rejected_before_decoding():
    with pytest.raises(ImageRejected) as excinfo:
        load_image(b"\xff\xd8\xff" + b"\x00" * 200, max_bytes=100)
    assert excinfo.value.code == "FILE_TOO_LARGE"


def test_empty_upload_is_rejected():
    with pytest.raises(ImageRejected) as excinfo:
        load_image(b"", MAX_BYTES)
    assert excinfo.value.code == "EMPTY_UPLOAD"


def test_truncated_image_is_rejected_without_crashing():
    with pytest.raises(ImageRejected):
        load_image(b"\xff\xd8\xff\xe0" + b"\x11" * 500, MAX_BYTES)


def test_tiny_image_is_rejected():
    from PIL import Image

    tiny = Image.new("RGB", (64, 48), (200, 200, 200))
    with pytest.raises(ImageRejected) as excinfo:
        load_image(to_png_bytes(tiny), MAX_BYTES)
    assert excinfo.value.code == "IMAGE_TOO_SMALL"


def test_png_and_jpeg_are_both_accepted():
    image, _, _, _ = build_fixture(get_fixture("genuine_clean_a"))
    assert load_image(to_png_bytes(image), MAX_BYTES).content_type == "image/png"
    assert load_image(to_jpeg_bytes(image, 90), MAX_BYTES).content_type == "image/jpeg"


def test_sniffer_rejects_non_images():
    assert sniff_content_type(b"not an image at all") is None
    assert sniff_content_type(b"RIFF....NOTWEBP") is None


# --- quality gate --------------------------------------------------------


@pytest.mark.parametrize("name", GENUINE)
def test_genuine_captures_pass_the_quality_gate(name):
    """The false-positive side: an honest photo must not be blocked."""
    _, quality, _ = analyse(name)
    assert quality.passed, (name, quality.score, quality.reason_codes)


@pytest.mark.parametrize(
    "name,expected_code",
    [
        ("quality_blurred", ReasonCode.IMAGE_TOO_BLURRY),
        ("quality_dark", ReasonCode.IMAGE_UNDEREXPOSED),
        ("quality_glare", ReasonCode.IMAGE_OVEREXPOSED),
        ("quality_pack_too_small", ReasonCode.IMAGE_TOO_SMALL),
    ],
)
def test_bad_captures_fail_with_actionable_advice(name, expected_code):
    """Each failure mode must name the problem the user can actually fix.

    A dark photo told to "hold still" wastes the retake, so the codes are
    asserted individually rather than as a generic failure.
    """
    _, quality, _ = analyse(name)
    assert not quality.passed, name
    assert expected_code in quality.reason_codes, (name, quality.reason_codes)


def test_darkness_is_not_reported_as_blur():
    """Sharpness is measured on contrast-normalised pixels for this reason."""
    _, quality, _ = analyse("quality_dark")
    assert ReasonCode.IMAGE_UNDEREXPOSED in quality.reason_codes
    assert quality.metrics["sharpness"] > 0.5


def test_a_bright_carton_is_not_mistaken_for_glare():
    """A medicine carton is a large flat bright region; glare is clipped.

    An earlier metric measured "bright and locally flat", which describes the
    carton itself and failed every genuine capture.
    """
    _, clean, _ = analyse("genuine_clean_a")
    _, glare, _ = analyse("quality_glare")
    assert clean.passed
    assert clean.metrics["clipped_fraction"] < 0.1
    assert glare.metrics["clipped_fraction"] > 0.4


# --- registration --------------------------------------------------------


@pytest.mark.parametrize("name", GENUINE)
def test_genuine_packs_register_confidently(name):
    _, _, evidence = analyse(name)
    assert evidence.available, (name, evidence.reason_codes)
    assert evidence.registration_confidence >= DEFAULT_THRESHOLDS.registration_floor


def test_marginal_registration_returns_unavailable_not_a_mismatch():
    """``phases/PHASE_3_PHYSICAL.md``: inadequate registration is unverifiable.

    A genuine pack photographed small, off-axis and softly cannot be compared.
    Comparing it anyway and reporting the resulting difference would turn camera
    geometry into an accusation.
    """
    _, quality, evidence = analyse("genuine_hard_capture")
    assert not evidence.available
    assert ReasonCode.REGISTRATION_FAILED in evidence.reason_codes
    assert not (PHYSICAL_MISMATCH_CODES & set(evidence.reason_codes))
    assert evidence.state is EvidenceState.UNKNOWN


def test_pack_not_found_when_there_is_no_pack():
    from PIL import Image

    blank = Image.new("RGB", (900, 700), (128, 128, 128))
    loaded = load_image(to_png_bytes(blank), MAX_BYTES)
    profile = seed_data.reference_profile_by_id("ref_demo_a")
    evidence = compare_packaging(loaded, reference_gray("ser_demo_a_001"), profile)
    assert not evidence.available
    assert evidence.reason_codes[0] in (
        ReasonCode.PACKAGE_NOT_FOUND,
        ReasonCode.REGISTRATION_FAILED,
    )


def test_homography_recovers_the_capture_geometry():
    """Corner accuracy, asserted directly against the simulator's geometry."""
    from scads.demo.render import _destination_quad
    from scads.physical.registration import detect_pack_quad

    spec = get_fixture("genuine_clean_a")
    image, _, _, _ = build_fixture(spec)
    loaded = load_image(to_jpeg_bytes(image, 92), MAX_BYTES)
    quad, _ = detect_pack_quad(loaded.gray)
    truth = _destination_quad(spec.capture, 900 / 520)
    assert quad is not None
    # Within 1% of the pack's width. Corner error propagates as a scale error
    # across the pack, so this bound is what keeps SSIM meaningful.
    assert float(np.abs(quad - truth).max()) < 0.012 * loaded.width


# --- detection: the headline result --------------------------------------


@pytest.mark.parametrize("name", GENUINE)
def test_genuine_packaging_reports_a_match(name):
    _, _, evidence = analyse(name)
    assert ReasonCode.PHYSICAL_MATCH in evidence.reason_codes, (
        name, evidence.score, evidence.reason_codes
    )
    assert not (PHYSICAL_MISMATCH_CODES & set(evidence.reason_codes))
    assert evidence.state is EvidenceState.OK


@pytest.mark.parametrize("name", ARTWORK_TAMPERS)
def test_every_artwork_tamper_is_flagged(name):
    """5/5 on the corpus. The reason codes are the discriminator, not the score."""
    _, quality, evidence = analyse(name)
    if not evidence.available:
        # An unverifiable capture is an acceptable outcome for a tamper; what is
        # not acceptable is calling it a match.
        assert ReasonCode.PHYSICAL_MATCH not in evidence.reason_codes
        return
    assert PHYSICAL_MISMATCH_CODES & set(evidence.reason_codes), (
        name, evidence.score, evidence.reason_codes
    )
    assert ReasonCode.PHYSICAL_MATCH not in evidence.reason_codes


@pytest.mark.parametrize("name", IDENTITY_TAMPERS)
def test_identity_tampering_leaves_packaging_evidence_clean(name):
    """An altered serial does not change the artwork, so packaging must pass.

    This is the separation of dimensions working: identity tampering is caught
    by the identity evaluator and the QR/print cross-check, and it would be
    wrong for the packaging comparison to also object.
    """
    _, _, evidence = analyse(name)
    assert evidence.available
    assert ReasonCode.PHYSICAL_MATCH in evidence.reason_codes, (
        name, evidence.reason_codes
    )


def test_localised_tamper_is_caught_even_though_the_aggregate_looks_fine():
    """Averaging regions hides exactly the change an attacker makes."""
    _, _, evidence = analyse("tamper_logo_shift")
    diagnostics = evidence.diagnostics["feature_diagnostics"]["structure"]
    assert diagnostics["logo_mark"] < 0.4
    assert diagnostics["_region_aggregate"] > 0.6  # aggregate alone looks acceptable
    assert diagnostics["_region_consistency"] < 0.5  # the peer comparison exposes it
    assert ReasonCode.STRUCTURAL_MISMATCH in evidence.reason_codes


def test_moved_text_is_caught_by_layout_or_structure():
    _, _, evidence = analyse("tamper_text_shift")
    codes = set(evidence.reason_codes)
    assert codes & {ReasonCode.TEXT_LAYOUT_MISMATCH, ReasonCode.STRUCTURAL_MISMATCH}


def test_degraded_printing_is_caught_when_the_capture_is_sharp():
    _, quality, evidence = analyse("tamper_resample")
    assert quality.passed
    assert ReasonCode.PRINT_SHARPNESS_MISMATCH in evidence.reason_codes


def test_print_sharpness_is_withheld_on_a_soft_capture():
    """Defocus and poor printing are confounded; the feature refuses to guess."""
    _, quality, evidence = analyse("quality_blurred")
    skipped = evidence.diagnostics.get("skipped_features", {})
    assert "print_sharpness" in skipped
    assert "sharp enough" in skipped["print_sharpness"]


def test_altered_batch_digit_does_not_move_the_structural_score():
    """The batch overprint is a dynamic region and must be excluded."""
    _, _, clean = analyse("genuine_clean_a")
    _, _, altered = analyse("identity_altered_batch_digit")
    clean_structure = clean.diagnostics["feature_values"]["structure"]
    altered_structure = altered.diagnostics["feature_values"]["structure"]
    assert abs(clean_structure - altered_structure) < 0.05


# --- reproducibility and provenance --------------------------------------


def test_comparison_is_deterministic():
    """AT-09 at the pipeline level: identical bytes, identical evidence."""
    spec = get_fixture("genuine_clean_a")
    image, words, lines, profile = build_fixture(spec)
    data = to_jpeg_bytes(image, 92)
    ocr = OcrResult(
        words=[OcrWord(w.text, w.x, w.y, w.width, w.height, 99.0) for w in words],
        lines=lines, provider="fixture",
    )
    runs = []
    for _ in range(3):
        loaded = load_image(data, MAX_BYTES)
        quality = assess_quality(loaded)
        runs.append(
            compare_packaging(
                loaded, reference_gray(spec.serial_id), profile, ocr,
                capture_sharpness=quality.metrics["sharpness"],
            )
        )
    assert len({round(r.score, 12) for r in runs}) == 1
    assert len({tuple(r.reason_codes) for r in runs}) == 1


def test_evidence_records_the_reference_version_that_judged_it():
    _, _, evidence = analyse("genuine_clean_a")
    assert evidence.reference_version == seed_data.REFERENCE_VERSION
    assert evidence.reference_profile_id == "ref_demo_a"
    assert evidence.diagnostics["thresholds_version"]


def test_features_carry_their_threshold_and_verdict():
    _, _, evidence = analyse("genuine_clean_a")
    assert evidence.features
    for feature in evidence.features:
        assert 0.0 <= feature.value <= 1.0
        assert 0.0 <= feature.threshold <= 1.0
        assert isinstance(feature.ok, bool)


def test_missing_ocr_degrades_gracefully():
    """Without OCR, text features are unavailable — not zero."""
    spec = get_fixture("genuine_clean_a")
    image, _, _, profile = build_fixture(spec)
    loaded = load_image(to_jpeg_bytes(image, 92), MAX_BYTES)
    evidence = compare_packaging(
        loaded, reference_gray(spec.serial_id), profile,
        ocr=OcrResult.failed("none", "no provider"), capture_sharpness=1.0,
    )
    assert evidence.available
    skipped = evidence.diagnostics["skipped_features"]
    assert "text_content" in skipped and "text_layout" in skipped
    assert set(evidence.diagnostics["feature_values"]) == {"structure", "print_sharpness"}


# --- sensitivity sweep ---------------------------------------------------


def test_tamper_sweep_is_monotonic_enough_to_be_useful():
    """A sensitivity curve, not a severity scale for real counterfeits.

    Asserts only that a larger perturbation does not score *better*, with
    tolerance for measurement noise — ``docs/EVALUATION.md`` section 3 warns
    against implying the slider maps to counterfeit severity.
    """
    scores = []
    for spec in tamper_sweep(kind="logo_shift", steps=5):
        image, words, lines, profile = build_fixture(spec)
        loaded = load_image(to_jpeg_bytes(image, 92), MAX_BYTES)
        quality = assess_quality(loaded)
        ocr = OcrResult(
            words=[OcrWord(w.text, w.x, w.y, w.width, w.height, 99.0) for w in words],
            lines=lines, provider="fixture",
        )
        evidence = compare_packaging(
            loaded, reference_gray(spec.serial_id), profile, ocr,
            capture_sharpness=quality.metrics["sharpness"],
        )
        scores.append(evidence.score if evidence.available else 0.0)

    assert scores[0] > scores[-1], scores
    assert scores[-1] < scores[0] - 0.05, scores
