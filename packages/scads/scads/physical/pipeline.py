"""Packaging comparison pipeline.

Order is load-bearing:

1. **Quality gate** (caller). A photo too poor to judge never reaches here.
2. **Registration.** If the pack cannot be rectified onto the reference frame,
   the pipeline reports *unavailable* and stops. It does not compare anyway and
   present the resulting mismatch as evidence — that would turn an awkward
   camera angle into an accusation against genuine medicine.
3. **Features**, over the rectified image.
4. **Fusion** of the available features, multiplicatively.

The distinction between "compared, and it did not match" and "could not
compare" is preserved all the way out through ``PhysicalEvidence.available``.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

import numpy as np

from ..contracts.enums import EvidenceState
from ..contracts.models import PhysicalEvidence, PhysicalFeature
from ..contracts.reason_codes import ReasonCode
from ..contracts.records import ReferenceProfile
from ..identity.ocr import OcrResult
from ..util.numeric import clamp01, weighted_geometric_mean
from .features import (
    FeatureResult,
    print_sharpness_feature,
    structural_similarity_feature,
    text_content_feature,
    text_layout_feature,
)
from .image import LoadedImage, resize_gray
from .registration import register

# Feature name -> the reason code emitted when it fails.
FEATURE_CODES: Dict[str, ReasonCode] = {
    "text_content": ReasonCode.TEXT_CONTENT_MISMATCH,
    "text_layout": ReasonCode.TEXT_LAYOUT_MISMATCH,
    "structure": ReasonCode.STRUCTURAL_MISMATCH,
    "print_sharpness": ReasonCode.PRINT_SHARPNESS_MISMATCH,
}


@dataclass(frozen=True)
class PhysicalThresholds:
    """Versioned packaging thresholds.

    Demonstration values measured on the synthetic fixture corpus, not a
    cross-device calibration. ``docs/EVALUATION.md`` section 1 is explicit about
    what that can and cannot support.
    """

    version: str = "physical_0.1.0"

    weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "text_content": 0.20,
            "text_layout": 0.25,
            "structure": 0.35,
            "print_sharpness": 0.20,
        }
    )
    # Per-feature pass marks, used for the individual reason codes.
    feature_floors: Mapping[str, float] = field(
        default_factory=lambda: {
            "text_content": 0.70,
            "text_layout": 0.60,
            "structure": 0.58,
            "print_sharpness": 0.50,
        }
    )

    # Registration confidence below which packaging evidence is unavailable.
    #
    # Measured: clean captures register at 0.69-0.82 and every tampered fixture
    # still registers above 0.60, while a genuine pack photographed small,
    # off-axis and softly reaches only 0.47. At 0.35 that awkward-but-honest
    # capture was graded anyway and reported as a structural mismatch — a false
    # accusation produced by camera geometry. Raising the floor routes it to
    # UNABLE_TO_VERIFY, which is what ``phases/PHASE_3_PHYSICAL.md`` specifies
    # for inadequate registration.
    registration_floor: float = 0.55
    # Fewer available features than this and the comparison is too thin to report.
    min_features: int = 2
    # Combined score at or above which the packaging is reported as matching.
    match_floor: float = 0.68

    # Weakest-region-to-median ratio below which a localised structural anomaly
    # is reported. Measured on the corpus: genuine captures sit at 0.86-0.92
    # (every region degrades together), while a moved logo reaches 0.24 and a
    # replaced block 0.63.
    region_consistency_floor: float = 0.75
    # Registration confidence required before a region-consistency finding is
    # trusted.
    consistency_registration_floor: float = 0.60


DEFAULT_THRESHOLDS = PhysicalThresholds()


def unavailable_evidence(
    codes: List[ReasonCode],
    profile: Optional[ReferenceProfile] = None,
    registration_confidence: float = 0.0,
    diagnostics: Optional[Dict[str, object]] = None,
) -> PhysicalEvidence:
    """Packaging evidence that could not be produced."""
    return PhysicalEvidence(
        score=0.0,
        state=EvidenceState.UNKNOWN,
        available=False,
        features=[],
        reason_codes=list(codes),
        registration_confidence=clamp01(registration_confidence),
        reference_version=profile.version if profile else None,
        reference_profile_id=profile.reference_profile_id if profile else None,
        diagnostics=dict(diagnostics or {}),
    )


def compare_packaging(
    scan: LoadedImage,
    reference_gray: np.ndarray,
    profile: ReferenceProfile,
    ocr: Optional[OcrResult] = None,
    thresholds: PhysicalThresholds = DEFAULT_THRESHOLDS,
    capture_sharpness: float = 1.0,
) -> PhysicalEvidence:
    """Compare a scan's packaging against an enrolled reference.

    ``capture_sharpness`` comes from the quality gate and is passed through to
    the features that cannot be interpreted without it.
    """
    canonical_reference = _canonical_reference(reference_gray, profile)

    registration = register(
        scan_gray=scan.gray,
        reference_gray=canonical_reference,
        canonical_width=profile.canonical_width,
        canonical_height=profile.canonical_height,
        expected_aspect=profile.aspect_ratio,
    )

    diagnostics: Dict[str, object] = {
        "registration": dict(registration.diagnostics),
        "thresholds_version": thresholds.version,
        "reference_version": profile.version,
    }
    if registration.quad is not None:
        diagnostics["pack_quad"] = [[round(float(x), 1), round(float(y), 1)] for x, y in registration.quad]

    if not registration.ok or registration.warped is None:
        code = (
            ReasonCode.PACKAGE_NOT_FOUND
            if registration.failure_reason == "PACKAGE_NOT_FOUND"
            else ReasonCode.REGISTRATION_FAILED
        )
        if registration.failure_reason == "PACKAGE_TOO_SMALL":
            code = ReasonCode.IMAGE_TOO_SMALL
        diagnostics["failure_reason"] = registration.failure_reason
        return unavailable_evidence(
            [code], profile, registration.confidence, diagnostics
        )

    if registration.confidence < thresholds.registration_floor:
        diagnostics["failure_reason"] = "LOW_REGISTRATION_CONFIDENCE"
        return unavailable_evidence(
            [ReasonCode.REGISTRATION_FAILED], profile, registration.confidence, diagnostics
        )

    warped = registration.warped
    ocr_result = ocr if ocr is not None else OcrResult.failed("none", "no OCR provided")

    results: List[FeatureResult] = [
        text_content_feature(ocr_result, profile),
        text_layout_feature(
            ocr_result, profile, registration.homography, scan.width, scan.height
        ),
        structural_similarity_feature(warped, canonical_reference, profile),
        print_sharpness_feature(warped, canonical_reference, profile, capture_sharpness),
    ]

    available = [r for r in results if r.available]
    skipped = {r.name: r.detail for r in results if not r.available}
    if skipped:
        diagnostics["skipped_features"] = skipped

    if len(available) < thresholds.min_features:
        diagnostics["failure_reason"] = "TOO_FEW_FEATURES"
        return unavailable_evidence(
            [ReasonCode.UNSUPPORTED_PACKAGE_VARIANT],
            profile,
            registration.confidence,
            diagnostics,
        )

    features: List[PhysicalFeature] = []
    values: Dict[str, float] = {}
    codes: List[ReasonCode] = []

    for result in available:
        floor = float(thresholds.feature_floors.get(result.name, 0.5))
        weight = float(thresholds.weights.get(result.name, 0.0))
        ok = result.value >= floor
        features.append(
            PhysicalFeature(
                name=result.name,
                value=result.value,
                weight=weight,
                threshold=floor,
                ok=ok,
                description=result.detail,
            )
        )
        values[result.name] = result.value
        if not ok:
            codes.append(FEATURE_CODES[result.name])
        if result.diagnostics:
            diagnostics.setdefault("feature_diagnostics", {})[result.name] = result.diagnostics

    # Weights renormalise across the features actually measured, so a skipped
    # feature lowers assurance rather than silently counting as a pass.
    score = weighted_geometric_mean(values, thresholds.weights)
    diagnostics["feature_values"] = {k: round(v, 4) for k, v in values.items()}

    # A single region far below its peers is a localised structural anomaly, even
    # when the aggregate clears its floor. Averaging six regions hides exactly
    # the change an attacker makes: one altered element among five untouched
    # ones.
    structure_diagnostics = (diagnostics.get("feature_diagnostics", {}) or {}).get("structure", {})
    consistency = structure_diagnostics.get("_region_consistency")
    # Conditioned on registration confidence, for the same reason the
    # severe-physical cap is: per-region variation on a marginally aligned pack
    # reflects geometry, not artwork.
    if (
        consistency is not None
        and consistency < thresholds.region_consistency_floor
        and registration.confidence >= thresholds.consistency_registration_floor
        and ReasonCode.STRUCTURAL_MISMATCH not in codes
    ):
        codes.append(ReasonCode.STRUCTURAL_MISMATCH)
        diagnostics["region_consistency_triggered"] = consistency

    if not codes and score >= thresholds.match_floor:
        codes = [ReasonCode.PHYSICAL_MATCH]
        state = EvidenceState.OK
    elif codes:
        severe = score < thresholds.match_floor * 0.5
        state = EvidenceState.FAIL if severe else EvidenceState.WARN
    else:
        # Every feature individually cleared its floor, but the combined score
        # did not reach the match threshold. That is genuine ambiguity, so it is
        # reported as a soft structural note rather than a clean match.
        codes = [ReasonCode.STRUCTURAL_MISMATCH]
        state = EvidenceState.WARN

    return PhysicalEvidence(
        score=score,
        state=state,
        available=True,
        features=features,
        reason_codes=codes,
        registration_confidence=registration.confidence,
        reference_version=profile.version,
        reference_profile_id=profile.reference_profile_id,
        diagnostics=diagnostics,
    )


def _canonical_reference(reference_gray: np.ndarray, profile: ReferenceProfile) -> np.ndarray:
    """Resize an enrolled reference to the profile's canonical frame."""
    if (
        reference_gray.shape[0] == profile.canonical_height
        and reference_gray.shape[1] == profile.canonical_width
    ):
        return reference_gray
    return resize_gray(reference_gray, profile.canonical_width, profile.canonical_height)
