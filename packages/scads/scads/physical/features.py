"""Packaging comparison features.

Four independent measurements, each answering a different question about a
rectified pack:

``text_content``    Are the fixed words that belong on this product present?
``text_layout``     Are they where the enrolled artwork puts them?
``structure``       Does the artwork itself match, region by region?
``print_sharpness`` Does the printing carry the fine detail an original does?

Independence is the point. A counterfeiter who copies the wording still has to
place it correctly; one who reproduces the layout still has to print it at
original quality. A single global similarity score would let any one of these
compensate for the others, which is why they are fused multiplicatively rather
than averaged (``docs/SCORING_AND_DETECTION.md`` section 7).

Two rules protect genuine packs from false accusation:

* Regions that legitimately vary between packs — the batch/expiry overprint and
  the QR — are excluded from structural comparison. Including them would flag
  every real pack.
* A feature that could not be measured is reported as unavailable, never as
  zero. An unreadable batch overprint is missing evidence, not counter-evidence.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..contracts.records import OcrAnchor, ReferenceProfile, RoiSpec
from ..identity.ocr import OcrResult
from ..util.numeric import clamp01
from .image import gaussian_blur, gradient_magnitude
from .registration import apply_homography

# SSIM stabilising constants for data on [0, 1] (Wang et al. 2004, L = 1).
_C1 = (0.01 * 1.0) ** 2
_C2 = (0.03 * 1.0) ** 2
SSIM_SIGMA = 1.5


@dataclass(frozen=True)
class FeatureResult:
    name: str
    value: float
    available: bool
    detail: str = ""
    diagnostics: Optional[Dict[str, float]] = None

    @staticmethod
    def unavailable(name: str, reason: str) -> "FeatureResult":
        return FeatureResult(name=name, value=0.0, available=False, detail=reason)


def ssim(a: np.ndarray, b: np.ndarray, sigma: float = SSIM_SIGMA) -> float:
    """Mean structural similarity between two equally shaped arrays.

    Implemented directly rather than pulled from scikit-image: the formulation
    is a dozen lines over a Gaussian blur, and scikit-image would drag scipy
    (~110 MB) into the Lambda for this one function.

    SSIM ranges over [-1, 1]; the negative tail means anti-correlated, which for
    our purposes is simply "no match", so the result is clamped to [0, 1].
    """
    if a.shape != b.shape:
        raise ValueError("ssim needs equal shapes, got {} and {}".format(a.shape, b.shape))
    if a.size == 0:
        raise ValueError("ssim needs a non-empty window")

    a = a.astype(np.float32)
    b = b.astype(np.float32)

    mu_a = gaussian_blur(a, sigma)
    mu_b = gaussian_blur(b, sigma)
    mu_a_sq = mu_a * mu_a
    mu_b_sq = mu_b * mu_b
    mu_ab = mu_a * mu_b

    sigma_a = np.maximum(0.0, gaussian_blur(a * a, sigma) - mu_a_sq)
    sigma_b = np.maximum(0.0, gaussian_blur(b * b, sigma) - mu_b_sq)
    sigma_ab = gaussian_blur(a * b, sigma) - mu_ab

    numerator = (2.0 * mu_ab + _C1) * (2.0 * sigma_ab + _C2)
    denominator = (mu_a_sq + mu_b_sq + _C1) * (sigma_a + sigma_b + _C2)
    return clamp01(float(np.mean(numerator / denominator)))


def _crop(image: np.ndarray, roi: RoiSpec) -> Optional[np.ndarray]:
    height, width = image.shape[:2]
    left, top, right, bottom = roi.pixel_box(width, height)
    if right - left < 8 or bottom - top < 8:
        return None
    return image[top:bottom, left:right]


def structural_similarity_feature(
    warped: np.ndarray, reference: np.ndarray, profile: ReferenceProfile
) -> FeatureResult:
    """Weighted SSIM over the enrolled *static* regions of the artwork.

    Per-region rather than whole-frame so that a localised change — a shifted
    logo, a replaced warning block — registers as a strong failure in its own
    region instead of being diluted across the whole pack.
    """
    rois = profile.static_rois
    if not rois:
        # No enrolled regions: fall back to the whole frame, which is weaker but
        # still meaningful, and say so.
        return FeatureResult(
            name="structure",
            value=ssim(warped, reference),
            available=True,
            detail="whole-frame comparison; no stable regions were enrolled",
        )

    scores: List[Tuple[float, float]] = []
    per_roi: Dict[str, float] = {}
    offsets: Dict[str, str] = {}
    for roi in rois:
        reference_patch = _crop(reference, roi)
        if reference_patch is None:
            continue
        value, offset = _best_local_ssim(warped, reference, roi)
        if value is None:
            continue
        per_roi[roi.name] = round(value, 4)
        offsets[roi.name] = "{},{}".format(offset[0], offset[1])
        scores.append((value, max(0.0, roi.weight)))

    if not scores:
        return FeatureResult.unavailable("structure", "no comparable regions")

    total_weight = sum(weight for _, weight in scores)
    if total_weight <= 0:
        return FeatureResult.unavailable("structure", "enrolled regions carry no weight")

    # Weighted geometric mean across regions: one badly failing region should
    # pull the feature down rather than be averaged out by five good ones.
    log_sum = 0.0
    for value, weight in scores:
        log_sum += (weight / total_weight) * np.log(max(1e-6, value))
    aggregate = clamp01(float(np.exp(log_sum)))

    # Region consistency: the weakest region measured against its peers.
    #
    # This is the statistic that actually separates tampering from a bad
    # photograph, and it does so because the two have different *shapes*. A
    # difficult capture degrades every region together — soft focus does not
    # pick favourites — so the weakest region stays close to the median. A
    # localised alteration, which is what someone modifying a pack actually
    # does, drives one region far below its neighbours while they stay pristine.
    #
    # Being a ratio, it is invariant to overall capture quality: the absolute
    # scores can all slide down without triggering it. That is what lets SCADS
    # flag a moved logo on a mediocre photo without accusing a genuine pack
    # photographed in poor light.
    values_only = sorted(per_roi.values())
    median = values_only[len(values_only) // 2]
    weakest = values_only[0]
    consistency = clamp01(weakest / median) if median > 1e-6 else 0.0

    # The reported value combines "do the regions match" with "do they match
    # uniformly". Six regions averaged together hide a single altered element,
    # which is exactly the change someone modifying a pack makes: measured on
    # the corpus, a moved logo left the aggregate at 0.70 — inside the genuine
    # range — while its own region sat at 0.22. Weighting is 0.7/0.3 so the
    # aggregate still leads and a merely uneven-but-adequate pack is not
    # punished as though it failed outright.
    combined = clamp01(float((aggregate ** 0.7) * (max(1e-6, consistency) ** 0.3)))

    worst_name = min(per_roi, key=per_roi.get)
    diagnostics = dict(per_roi)
    diagnostics["_region_consistency"] = round(consistency, 4)
    diagnostics["_region_median"] = round(median, 4)
    diagnostics["_region_aggregate"] = round(aggregate, 4)

    return FeatureResult(
        name="structure",
        value=combined,
        available=True,
        detail="weakest region: {} ({:.2f}), {:.0f}% of the median region".format(
            worst_name, weakest, consistency * 100.0
        ),
        diagnostics=diagnostics,
    )


# Radius, in canonical pixels, of the per-region alignment search.
#
# Corner fitting leaves one or two pixels of residual error, and SSIM on thin
# high-contrast line art is brutally sensitive to that: a genuine pack
# photographed from a different angle scored *worse* on its own logo than a pack
# whose logo had been deliberately moved. Searching a small window per region
# removes that geometric noise floor.
#
# The bound matters. This radius must stay well below the smallest displacement
# SCADS claims to detect, or the search would absorb real tampering. At 4 px on
# a 900 px canonical frame it compensates registration error of well under 1% of
# pack width, while the displacement fixtures move artwork by 26-30 px. The
# chosen offset is reported per region, so a systematic misregistration shows up
# in diagnostics instead of being silently absorbed.
LOCAL_SEARCH_RADIUS = 4
LOCAL_SEARCH_STEP = 2

# Slight blur before comparison, for the same reason: it makes SSIM tolerant of
# sub-pixel error while preserving the structural differences the feature exists
# to find, which are one to two orders of magnitude larger.
STRUCTURE_PREBLUR = 1.0


def _best_local_ssim(
    warped: np.ndarray, reference: np.ndarray, roi: RoiSpec
):
    """SSIM for one region, maximised over a small alignment window.

    Returns ``(value, (dy, dx))``, or ``(None, (0, 0))`` if the region cannot be
    compared.
    """
    reference_patch = _crop(reference, roi)
    if reference_patch is None:
        return None, (0, 0)

    height, width = warped.shape[:2]
    left, top, right, bottom = roi.pixel_box(width, height)
    patch_h = bottom - top
    patch_w = right - left
    if patch_h < 8 or patch_w < 8:
        return None, (0, 0)

    reference_blurred = gaussian_blur(reference_patch, STRUCTURE_PREBLUR)

    best_value = None
    best_offset = (0, 0)
    for dy in range(-LOCAL_SEARCH_RADIUS, LOCAL_SEARCH_RADIUS + 1, LOCAL_SEARCH_STEP):
        for dx in range(-LOCAL_SEARCH_RADIUS, LOCAL_SEARCH_RADIUS + 1, LOCAL_SEARCH_STEP):
            y0 = top + dy
            x0 = left + dx
            if y0 < 0 or x0 < 0 or y0 + patch_h > height or x0 + patch_w > width:
                continue
            candidate = warped[y0 : y0 + patch_h, x0 : x0 + patch_w]
            if candidate.shape != reference_patch.shape:
                continue
            value = ssim(gaussian_blur(candidate, STRUCTURE_PREBLUR), reference_blurred)
            if best_value is None or value > best_value:
                best_value = value
                best_offset = (dy, dx)

    return best_value, best_offset


def _canonical_ocr_points(
    ocr: OcrResult,
    homography: Optional[np.ndarray],
    scan_width: int,
    scan_height: int,
    canonical_width: int,
    canonical_height: int,
) -> Dict[int, Tuple[float, float]]:
    """Project OCR word centres into normalised canonical coordinates.

    OCR runs on the original photograph, so its coordinates are in the camera's
    frame. Comparing them to reference anchor positions without projecting them
    through the same homography that rectified the image would measure camera
    pose rather than print position — the exact error this pipeline exists to
    avoid.
    """
    if not ocr.words:
        return {}

    pixels = np.array(
        [[w.x * scan_width, w.y * scan_height] for w in ocr.words], dtype=np.float64
    )

    if homography is None:
        mapped = np.array([[w.x * canonical_width, w.y * canonical_height] for w in ocr.words])
    else:
        # `homography` maps canonical -> image, so invert it to go the other way.
        try:
            inverse = np.linalg.inv(homography)
        except np.linalg.LinAlgError:
            return {}
        mapped = apply_homography(inverse, pixels)

    result: Dict[int, Tuple[float, float]] = {}
    for index, (x, y) in enumerate(mapped):
        result[index] = (float(x) / canonical_width, float(y) / canonical_height)
    return result


def text_layout_feature(
    ocr: OcrResult,
    profile: ReferenceProfile,
    homography: Optional[np.ndarray],
    scan_width: int,
    scan_height: int,
) -> FeatureResult:
    """How closely printed text sits to its enrolled position.

    Catches the counterfeit that prints all the right words in subtly wrong
    places — invisible to a text-only check and easy to miss by eye.
    """
    anchors = profile.ocr_anchors
    if not anchors:
        return FeatureResult.unavailable("text_layout", "no OCR anchors enrolled")
    if not ocr.succeeded:
        return FeatureResult.unavailable(
            "text_layout", "text extraction unavailable: " + (ocr.error or "unknown")
        )
    if not ocr.words:
        return FeatureResult.unavailable("text_layout", "no words were detected on the pack")

    positions = _canonical_ocr_points(
        ocr,
        homography,
        scan_width,
        scan_height,
        profile.canonical_width,
        profile.canonical_height,
    )
    if not positions:
        return FeatureResult.unavailable("text_layout", "OCR positions could not be projected")

    scores: List[float] = []
    per_anchor: Dict[str, float] = {}
    exceeded: List[str] = []

    for anchor in anchors:
        best: Optional[float] = None
        needle = anchor.text.strip().upper()
        for index, word in enumerate(ocr.words):
            if needle not in word.normalised_text:
                continue
            x, y = positions.get(index, (None, None))
            if x is None:
                continue
            distance = float(np.hypot(x - anchor.x, y - anchor.y))
            if best is None or distance < best:
                best = distance

        if best is None:
            # The anchor word was not found at all. That is a *content* problem,
            # measured by the content feature; scoring it as a layout failure
            # would double-count one defect across two supposedly independent
            # features.
            per_anchor[anchor.name] = -1.0
            continue

        tolerance = max(1e-3, anchor.tolerance)
        score = clamp01(1.0 - (best / (tolerance * 3.0)))
        per_anchor[anchor.name] = round(best, 4)
        scores.append(score)
        if best > tolerance:
            exceeded.append(anchor.name)

    if not scores:
        return FeatureResult.unavailable(
            "text_layout", "none of the enrolled anchor words were found"
        )

    # Geometric, for the same reason the regions are: averaging five correctly
    # placed anchors with one displaced one produced 0.97 for a pack whose
    # brand block had been moved 26 px — indistinguishable from an untouched
    # pack. In log space the displaced anchor dominates.
    log_sum = float(np.mean([np.log(max(1e-6, s)) for s in scores]))
    value = clamp01(float(np.exp(log_sum)))

    displaced = [name for name, distance in per_anchor.items() if distance >= 0]
    worst = max(displaced, key=lambda n: per_anchor[n]) if displaced else ""
    diagnostics = {k: v for k, v in per_anchor.items()}
    diagnostics["_anchors_beyond_tolerance"] = float(len(exceeded))
    return FeatureResult(
        name="text_layout",
        value=value,
        available=True,
        detail=(
            "{} moved {:.1f}% of the pack width from its enrolled position".format(
                worst, per_anchor[worst] * 100.0
            )
            if worst
            else ""
        ),
        diagnostics=diagnostics,
    )


def text_content_feature(ocr: OcrResult, profile: ReferenceProfile) -> FeatureResult:
    """Whether the fixed wording for this product is present.

    Only *stable* wording is compared. Batch and expiry are checked against the
    registry instead, because they differ legitimately between packs and a
    static reference string would mark every new batch as a mismatch
    (``docs/SCORING_AND_DETECTION.md`` section 6.1).
    """
    anchors = profile.ocr_anchors
    if not anchors:
        return FeatureResult.unavailable("text_content", "no expected text enrolled")
    if not ocr.succeeded:
        return FeatureResult.unavailable(
            "text_content", "text extraction unavailable: " + (ocr.error or "unknown")
        )

    haystack = ocr.upper_text.replace("\n", " ")
    found: List[str] = []
    missing: List[str] = []
    for anchor in anchors:
        needle = anchor.text.strip().upper()
        if not needle:
            continue
        if needle in haystack or any(needle in w.normalised_text for w in ocr.words):
            found.append(anchor.name)
        else:
            missing.append(anchor.name)

    total = len(found) + len(missing)
    if total == 0:
        return FeatureResult.unavailable("text_content", "no comparable expected text")

    value = clamp01(len(found) / float(total))
    return FeatureResult(
        name="text_content",
        value=value,
        available=True,
        detail="missing expected text: " + ", ".join(missing) if missing else "all expected text present",
        diagnostics={"found": float(len(found)), "missing": float(len(missing))},
    )


def _print_edge_energy(image: np.ndarray, rois: List[RoiSpec]) -> Optional[float]:
    """Edge energy inside the printed regions.

    A high percentile rather than a mean: most pixels inside a text region are
    blank card, and averaging them in would let the amount of whitespace
    dominate a measure that is supposed to be about ink.

    **This is an absolute measurement, and it is only meaningful because the
    quality gate runs first.** Camera defocus and poor printing both reduce
    edge energy, and no single image can separate them — so SCADS separates
    them by order of operations: an out-of-focus photograph is rejected as an
    inadequate capture before this feature is ever computed. By the time it
    runs, the capture is known to be sharp, and remaining softness in the
    printing is attributable to the pack. An earlier version normalised by the
    pack's overall edge energy to try to cancel defocus; that cancelled the
    reprint signal along with it, because a reprint softens the whole artwork
    uniformly.
    """
    gradient = gradient_magnitude(image)
    values: List[float] = []
    for roi in rois:
        patch = _crop(gradient, roi)
        if patch is None:
            continue
        values.append(float(np.percentile(patch, 95)))
    if not values:
        return None
    return float(np.mean(values))


# Capture sharpness below which print quality cannot be judged at all.
PRINT_CAPTURE_SHARPNESS_FLOOR = 0.75


def print_sharpness_feature(
    warped: np.ndarray,
    reference: np.ndarray,
    profile: ReferenceProfile,
    capture_sharpness: float = 1.0,
) -> FeatureResult:
    """Compare print crispness against the enrolled reference.

    Sensitive to reprints and photocopies, which lose fine detail in printed
    areas.

    ``capture_sharpness`` is the quality gate's sharpness component, and this
    feature **refuses to report** below a floor. Defocus and poor printing both
    reduce edge energy and a single image cannot distinguish them, so rather
    than guess, the feature declares itself unavailable on a soft capture. That
    is not a technicality: without it, a genuine pack photographed slightly out
    of focus scored 0.28 here and was reported as a print mismatch — a false
    accusation manufactured entirely out of camera focus.

    Calibration across camera models is the work this feature would need before
    any accuracy claim (``docs/EVALUATION.md`` section 9).
    """
    if capture_sharpness < PRINT_CAPTURE_SHARPNESS_FLOOR:
        return FeatureResult.unavailable(
            "print_sharpness",
            "capture is not sharp enough to judge print quality "
            "(sharpness {:.2f} below {:.2f})".format(
                capture_sharpness, PRINT_CAPTURE_SHARPNESS_FLOOR
            ),
        )

    rois = profile.static_rois or profile.stable_rois
    if not rois:
        return FeatureResult.unavailable("print_sharpness", "no regions enrolled")

    scan_ratio = _print_edge_energy(warped, rois)
    reference_ratio = _print_edge_energy(reference, rois)
    if scan_ratio is None or reference_ratio is None:
        return FeatureResult.unavailable("print_sharpness", "no measurable edge energy")

    if reference_ratio <= 1e-6:
        return FeatureResult.unavailable("print_sharpness", "reference has no edge structure")

    ratio = scan_ratio / reference_ratio
    # Symmetric: printing that is markedly *sharper* than the reference is as
    # much of a difference as printing that is softer.
    agreement = min(ratio, 1.0 / ratio) if ratio > 0 else 0.0
    value = clamp01(agreement)

    return FeatureResult(
        name="print_sharpness",
        value=value,
        available=True,
        detail="relative print detail is {:.0f}% of the reference".format(ratio * 100.0),
        diagnostics={
            "scan_ratio": round(scan_ratio, 4),
            "reference_ratio": round(reference_ratio, 4),
            "ratio": round(ratio, 4),
        },
    )
