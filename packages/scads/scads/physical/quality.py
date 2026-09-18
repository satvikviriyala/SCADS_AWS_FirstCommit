"""Scan-quality gate.

The single most important safety mechanism in the packaging pipeline. A phone
photograph of a genuine pack taken in a dim shop at an angle will differ from an
enrolled reference — and a system that scores that difference as evidence will
accuse genuine medicine of being counterfeit. So quality is measured first, and
an inadequate capture produces ``UNABLE_TO_VERIFY`` with advice on retaking the
photo, never a finding against the pack (``AGENTS.md`` section 6.2).

Each component is reported individually so the user is told *what* to fix.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping

import numpy as np

from ..contracts.models import QualityReport
from ..contracts.reason_codes import ReasonCode
from ..util.numeric import normalize_linear, weighted_geometric_mean
from .image import LoadedImage, gradient_magnitude


@dataclass(frozen=True)
class QualityThresholds:
    """Versioned capture-quality thresholds.

    The blur bounds are in units of Laplacian variance on images scaled to
    [0, 1]. They were chosen by measuring the fixture corpus
    (``scripts/calibrate_quality.py``) rather than guessed, but they are still
    demonstration values tuned on synthetic packs and one camera model — not a
    cross-device calibration (``docs/EVALUATION.md`` section 1).
    """

    version: str = "quality_0.2.0"

    # Sharpness is the 95th percentile of gradient magnitude on a
    # contrast-normalised image. Measured across the fixture corpus: a competent
    # capture sits near 1.47, an awkward-but-usable one near 0.63, a heavily
    # blurred one near 0.28. The floor is set below the awkward capture so an
    # imperfect photo of a genuine pack is still graded.
    sharpness_floor: float = 0.30
    sharpness_target: float = 1.00

    # Exposure is a two-sided band on mean luma. Both tails destroy evidence: a
    # dark frame has no detail, a washed-out one has no ink. Measured: usable
    # captures sit between 0.35 and 0.77; the glare fixture reaches 0.96 and the
    # dark fixture 0.08.
    luma_floor: float = 0.16
    luma_low_target: float = 0.30
    luma_high_target: float = 0.82
    luma_ceiling: float = 0.93

    # Fraction of the frame clipped at the sensor maximum. A bright carton is
    # not clipped; specular glare is. Generous, because a slightly hot exposure
    # can blow out the white card while leaving the dark printing perfectly
    # readable — measured at 0.24 for a genuine capture versus 0.64 for glare.
    clipped_fraction_limit: float = 0.45

    min_megapixels: float = 0.20
    target_megapixels: float = 1.20

    weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "sharpness": 0.45,
            "exposure": 0.40,
            "resolution": 0.15,
        }
    )

    # A component at or below this value fails individually and contributes its
    # own reason code, even when the overall score squeaks past the gate.
    component_fail: float = 0.35
    pass_floor: float = 0.45


DEFAULT_THRESHOLDS = QualityThresholds()


def contrast_normalised(gray: np.ndarray) -> np.ndarray:
    """Stretch the 1st-99th percentile range to [0, 1].

    Separates *how much detail* from *how bright*. Without this, a dark frame
    and a blurred frame both score low on any gradient measure, and the user is
    told to hold still when they should turn on a light. Percentiles rather
    than min/max so one hot pixel cannot set the scale.
    """
    low, high = np.percentile(gray, (1.0, 99.0))
    span = float(high - low)
    if span < 1e-3:
        return np.zeros_like(gray)
    return np.clip((gray - low) / span, 0.0, 1.0).astype(np.float32)


def measure_sharpness(gray: np.ndarray) -> float:
    """High-percentile gradient magnitude: a detail-density focus measure.

    Variance of the Laplacian is the textbook choice but proved unusable here.
    It is a *mean* statistic, so a single strong edge — the boundary between
    carton and table, which survives any amount of blur — dominates it. Measured
    on the corpus, a heavily blurred capture scored higher on Laplacian variance
    than a sharp one, because normalisation amplified its sensor noise.

    The 95th percentile of gradient magnitude asks a better question: does this
    image contain *many* crisp edges? Printed text does; a blurred photograph of
    it does not, however strong its one carton edge. Measured separation across
    the corpus is 1.47 for sharp captures against 0.23-0.28 for blurred and
    glare-washed ones.
    """
    gradient = gradient_magnitude(contrast_normalised(gray))
    return float(np.percentile(gradient, 95))


def measure_exposure(gray: np.ndarray) -> Dict[str, float]:
    """Luma statistics and the clipped fraction."""
    total = float(gray.size)
    return {
        "mean_luma": float(gray.mean()),
        "clipped_fraction": float((gray >= 0.99).sum()) / total,
        "dark_fraction": float((gray <= 0.03).sum()) / total,
    }


def _band_score(
    value: float, floor: float, low_target: float, high_target: float, ceiling: float
) -> float:
    """Score a value inside a preferred band, tapering to 0 outside it."""
    if value <= floor or value >= ceiling:
        return 0.0
    if value < low_target:
        return (value - floor) / (low_target - floor)
    if value > high_target:
        return (ceiling - value) / (ceiling - high_target)
    return 1.0


def assess_quality(
    image: LoadedImage, thresholds: QualityThresholds = DEFAULT_THRESHOLDS
) -> QualityReport:
    """Measure capture quality and decide whether comparison may proceed."""
    gray = image.gray

    sharpness_raw = measure_sharpness(gray)
    exposure_raw = measure_exposure(gray)

    sharpness = normalize_linear(
        sharpness_raw, thresholds.sharpness_floor, thresholds.sharpness_target
    )
    luma_score = _band_score(
        exposure_raw["mean_luma"],
        thresholds.luma_floor,
        thresholds.luma_low_target,
        thresholds.luma_high_target,
        thresholds.luma_ceiling,
    )
    clipping_score = normalize_linear(
        exposure_raw["clipped_fraction"], thresholds.clipped_fraction_limit, 0.0
    )
    exposure = min(luma_score, clipping_score)
    resolution = normalize_linear(
        image.megapixels, thresholds.min_megapixels, thresholds.target_megapixels
    )

    components = {
        "sharpness": sharpness,
        "exposure": exposure,
        "resolution": resolution,
    }
    # Geometric, so one unusable component cannot be averaged away by two good
    # ones — the same weakest-link reasoning the evidence fusion uses.
    score = weighted_geometric_mean(components, thresholds.weights)

    codes: List[ReasonCode] = []
    if sharpness <= thresholds.component_fail:
        codes.append(ReasonCode.IMAGE_TOO_BLURRY)
    too_bright = (
        clipping_score <= thresholds.component_fail
        or exposure_raw["mean_luma"] >= thresholds.luma_high_target
        and luma_score <= thresholds.component_fail
    )
    too_dark = (
        luma_score <= thresholds.component_fail
        and exposure_raw["mean_luma"] < thresholds.luma_low_target
    )
    if too_bright:
        codes.append(ReasonCode.IMAGE_OVEREXPOSED)
    if too_dark:
        codes.append(ReasonCode.IMAGE_UNDEREXPOSED)
    if resolution <= thresholds.component_fail:
        codes.append(ReasonCode.IMAGE_TOO_SMALL)

    passed = score >= thresholds.pass_floor and not codes

    # A capture that clears the gate but has a weak component keeps its advisory
    # code: the user gets "a bit blurry, here is how to improve it" without being
    # blocked, and the evidence records why the physical score may be soft.
    advisory = codes if codes else []
    if not passed and not advisory:
        advisory = [ReasonCode.IMAGE_TOO_BLURRY]

    return QualityReport(
        score=score,
        passed=passed,
        reason_codes=advisory,
        metrics={
            "sharpness": round(sharpness, 4),
            "exposure": round(exposure, 4),
            "resolution": round(resolution, 4),
            "gradient_p95": round(sharpness_raw, 4),
            "mean_luma": round(exposure_raw["mean_luma"], 4),
            "clipped_fraction": round(exposure_raw["clipped_fraction"], 4),
            "dark_fraction": round(exposure_raw["dark_fraction"], 4),
            "luma_score": round(luma_score, 4),
            "clipping_score": round(clipping_score, 4),
            "megapixels": round(image.megapixels, 3),
            "thresholds_version": thresholds.version,
        },
    )
