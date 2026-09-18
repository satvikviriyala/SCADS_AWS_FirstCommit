"""Geometric registration: bring a handheld photo into the reference frame.

Comparing two photographs directly is meaningless — a structural similarity
score between a phone snap and an enrolled reference measures camera pose, not
packaging. So the pack is located, rectified onto the canonical reference frame,
and only then compared (``docs/SCORING_AND_DETECTION.md`` section 4).

**Why quadrilateral rectification rather than ORB feature matching.** A medicine
carton is a planar rectangle, which is far stronger prior information than
generic keypoints exploit: finding its four corners and solving the exact
four-point homography is more robust on low-texture artwork than descriptor
matching, is fully deterministic, and needs nothing beyond numpy. That last
point is not incidental — it keeps OpenCV (and with it a two-copy OpenBLAS, the
ffmpeg stack, and a Lambda container image that cannot be built without Docker)
out of the deployment entirely.

If the pack cannot be located and rectified confidently, this module says so.
The caller then returns ``UNABLE_TO_VERIFY``; it does not compare anyway and
report the resulting mismatch as evidence.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

from .image import (
    box_filter,
    gaussian_blur,
    gradient_magnitude,
    normalized_cross_correlation,
    resize_gray,
)

# Working width for detection. Small enough to be fast, large enough that a
# carton edge is several pixels wide.
DETECT_WIDTH = 480

# A pack must occupy at least this fraction of the frame, or it is too far away
# to inspect the printing.
MIN_AREA_FRACTION = 0.12
# Above this, the "pack" is almost the whole frame, which usually means the
# detector locked onto the background instead.
MAX_AREA_FRACTION = 0.985

# Tolerance on aspect ratio, as a ratio between detected and expected.
ASPECT_TOLERANCE = 0.45

# Post-rectification agreement with the reference, below which we do not trust
# that we aligned the right thing at all.
MIN_STRUCTURE_AGREEMENT = 0.12


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of rectifying a scan onto the canonical reference frame."""

    ok: bool
    confidence: float
    warped: Optional[np.ndarray] = None
    homography: Optional[np.ndarray] = None
    quad: Optional[np.ndarray] = None
    failure_reason: Optional[str] = None
    diagnostics: Dict[str, float] = field(default_factory=dict)


def otsu_threshold(gray: np.ndarray, bins: int = 64) -> float:
    """Otsu's method: the threshold maximising between-class variance."""
    histogram, edges = np.histogram(gray, bins=bins, range=(0.0, 1.0))
    histogram = histogram.astype(np.float64)
    total = histogram.sum()
    if total <= 0:
        return 0.5
    probability = histogram / total
    centres = (edges[:-1] + edges[1:]) / 2.0

    weight_bg = np.cumsum(probability)
    weight_fg = 1.0 - weight_bg
    mean_bg = np.cumsum(probability * centres)
    mean_total = mean_bg[-1]

    with np.errstate(divide="ignore", invalid="ignore"):
        mu_bg = np.where(weight_bg > 0, mean_bg / weight_bg, 0.0)
        mu_fg = np.where(weight_fg > 0, (mean_total - mean_bg) / weight_fg, 0.0)
    between = weight_bg * weight_fg * (mu_bg - mu_fg) ** 2
    between = np.nan_to_num(between)
    return float(centres[int(np.argmax(between))])


def _clean_mask(mask: np.ndarray, size: int = 7) -> np.ndarray:
    """Remove speckle by majority vote in a local window."""
    return box_filter(mask.astype(np.float32), size) > 0.5


def _largest_span(projection: np.ndarray, threshold: float) -> Tuple[int, int]:
    """Longest contiguous run where ``projection`` exceeds ``threshold``.

    Used on row and column sums of the mask to bracket the pack, which rejects
    scattered bright objects elsewhere in the frame.
    """
    active = projection > threshold
    best_start = best_end = 0
    best_length = 0
    start = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start > best_length:
                best_length, best_start, best_end = index - start, start, index
            start = None
    if start is not None and len(active) - start > best_length:
        best_length, best_start, best_end = len(active) - start, start, len(active)
    if best_length == 0:
        return 0, len(projection)
    return best_start, best_end


def _corners_from_mask(mask: np.ndarray) -> Optional[np.ndarray]:
    """Extract an ordered quadrilateral from a filled region mask.

    The four extreme points of ``x+y`` and ``x-y`` give the corners of a convex
    quadrilateral directly, with no contour tracing. For a rectangular carton at
    any rotation or moderate perspective this recovers the corners exactly, and
    it is a pure array reduction.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 64:
        return None

    row_projection = mask.sum(axis=1).astype(np.float64)
    column_projection = mask.sum(axis=0).astype(np.float64)
    top, bottom = _largest_span(row_projection, row_projection.max() * 0.12)
    left, right = _largest_span(column_projection, column_projection.max() * 0.12)

    inside = (ys >= top) & (ys < bottom) & (xs >= left) & (xs < right)
    if inside.sum() < 64:
        return None
    xs, ys = xs[inside], ys[inside]

    total = xs.astype(np.float64) + ys.astype(np.float64)
    difference = xs.astype(np.float64) - ys.astype(np.float64)

    top_left = (xs[np.argmin(total)], ys[np.argmin(total)])
    bottom_right = (xs[np.argmax(total)], ys[np.argmax(total)])
    top_right = (xs[np.argmax(difference)], ys[np.argmax(difference)])
    bottom_left = (xs[np.argmin(difference)], ys[np.argmin(difference)])

    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float64)


def _full_resolution_mask(gray: np.ndarray, threshold: float, bright: bool) -> np.ndarray:
    """Rebuild the chosen candidate's mask at full image resolution."""
    smoothed = gaussian_blur(gray, 1.2)
    mask = smoothed > threshold if bright else smoothed <= threshold
    return _clean_mask(mask, size=5)


def _mask_boundary(mask: np.ndarray) -> np.ndarray:
    """Boundary pixels of a filled mask, as an ``(N, 2)`` array of ``(x, y)``."""
    interior = box_filter(mask.astype(np.float32), 3) > 0.999
    edge = np.logical_and(mask, np.logical_not(interior))
    ys, xs = np.nonzero(edge)
    return np.stack([xs, ys], axis=1).astype(np.float64)


def _fit_line(points: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Total-least-squares line fit, returned as ``(centroid, direction)``.

    Principal-component fit rather than ``y = mx + c``: a carton edge can be
    vertical in the frame, where the slope form is singular.
    """
    if points.shape[0] < 8:
        return None
    centroid = points.mean(axis=0)
    centred = points - centroid
    try:
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    direction = vt[0]
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        return None
    return centroid, direction / norm


def _intersect_lines(
    a: Tuple[np.ndarray, np.ndarray], b: Tuple[np.ndarray, np.ndarray]
) -> Optional[np.ndarray]:
    """Intersection of two lines given as ``(point, direction)``."""
    (p1, d1), (p2, d2) = a, b
    denominator = d1[0] * d2[1] - d1[1] * d2[0]
    # Near-parallel edges give an intersection far outside the image; reject.
    if abs(denominator) < 1e-6:
        return None
    diff = p2 - p1
    t = (diff[0] * d2[1] - diff[1] * d2[0]) / denominator
    return p1 + t * d1


def _point_segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Perpendicular distance from each point to segment ``a``-``b``."""
    segment = b - a
    length_sq = float(segment @ segment)
    if not np.isfinite(length_sq) or length_sq < 1e-6:
        return np.linalg.norm(points - a, axis=1)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        t = np.clip(((points - a) @ segment) / length_sq, 0.0, 1.0)
    t = np.nan_to_num(t, nan=0.0, posinf=1.0, neginf=0.0)
    projection = a + t[:, None] * segment
    return np.linalg.norm(points - projection, axis=1)


def _refine_quad(mask: np.ndarray, quad: np.ndarray) -> Tuple[np.ndarray, Dict[str, float]]:
    """Refine corners by fitting the four carton edges and intersecting them.

    The extreme-point estimate (argmin/argmax of x+y and x-y) finds corners
    exactly for a strongly rotated rectangle, but degrades near axis-alignment:
    at a few degrees of rotation, x+y is almost constant along *both* edges
    meeting a corner, so the argmin can land several pixels down an edge.

    That error is not cosmetic. Corner error propagates through the homography
    as a progressive scale error across the pack — measured at ~6 px of vertical
    drift by the bottom of a 520 px canonical frame, which is enough to depress
    SSIM on thin printed text and make a genuine pack look mismatched.

    Fitting each edge over hundreds of boundary pixels averages that error away
    and locates the corners to sub-pixel accuracy.
    """
    diagnostics: Dict[str, float] = {}
    boundary = _mask_boundary(mask)
    if boundary.shape[0] < 64:
        diagnostics["refine"] = 0.0
        return quad, diagnostics

    diagonal = float(np.linalg.norm(quad[2] - quad[0]))
    band = max(3.0, diagonal * 0.012)

    lines = []
    for index in range(4):
        a = quad[index]
        b = quad[(index + 1) % 4]
        distances = _point_segment_distance(boundary, a, b)
        near = boundary[distances < band]
        # Drop points close to either corner: the boundary curves there, and
        # including it biases both adjoining edge fits.
        if near.shape[0] > 16:
            along = np.linalg.norm(near - a, axis=1)
            edge_length = float(np.linalg.norm(b - a))
            if edge_length > 1.0:
                keep = (along > edge_length * 0.12) & (along < edge_length * 0.88)
                if keep.sum() > 16:
                    near = near[keep]
        lines.append(_fit_line(near))

    if any(line is None for line in lines):
        diagnostics["refine"] = 0.0
        return quad, diagnostics

    refined = []
    for index in range(4):
        previous = lines[(index - 1) % 4]
        current = lines[index]
        point = _intersect_lines(previous, current)
        if point is None:
            diagnostics["refine"] = 0.0
            return quad, diagnostics
        refined.append(point)

    refined_quad = np.array(refined, dtype=np.float64)

    # Sanity: a refined corner should be near the estimate it replaces. A large
    # jump means an edge fit latched onto something else, so keep the estimate.
    shift = float(np.abs(refined_quad - quad).max())
    diagnostics["refine_shift_px"] = round(shift, 2)
    if shift > diagonal * 0.08 or not np.all(np.isfinite(refined_quad)):
        diagnostics["refine"] = 0.0
        return quad, diagnostics

    diagnostics["refine"] = 1.0
    return refined_quad, diagnostics


def _quad_area(quad: np.ndarray) -> float:
    """Shoelace area of a polygon."""
    x = quad[:, 0]
    y = quad[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _quad_is_convex(quad: np.ndarray) -> bool:
    """Reject self-intersecting or degenerate quads via cross-product signs."""
    signs = []
    for index in range(4):
        a = quad[index]
        b = quad[(index + 1) % 4]
        c = quad[(index + 2) % 4]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        signs.append(np.sign(cross))
    signs = [s for s in signs if s != 0]
    return len(signs) == 4 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))


def detect_pack_quad(gray: np.ndarray) -> Tuple[Optional[np.ndarray], Dict[str, float]]:
    """Locate the pack's four corners in image pixel coordinates.

    Both threshold polarities are tried. A carton is usually lighter than the
    surface it rests on, but not always — a white pack on a white counter, or a
    dark carton on a light table, invert the assumption. Each candidate is
    scored on how plausibly pack-shaped it is, and the better one wins, so the
    detector does not depend on a guess about the background.
    """
    scale = DETECT_WIDTH / float(gray.shape[1])
    if scale < 1.0:
        small = resize_gray(gray, DETECT_WIDTH, max(1, int(round(gray.shape[0] * scale))))
    else:
        small = gray
        scale = 1.0

    smoothed = gaussian_blur(small, 1.6)
    threshold = otsu_threshold(smoothed)

    best_quad = None
    best_mask = None
    best_score = -1.0
    bright_polarity = True
    diagnostics: Dict[str, float] = {"otsu_threshold": round(threshold, 4)}

    for polarity, mask in (
        ("bright", smoothed > threshold),
        ("dark", smoothed <= threshold),
    ):
        cleaned = _clean_mask(mask)
        fill = float(cleaned.mean())
        # A mask covering nearly everything or nearly nothing is not an object.
        if fill < 0.05 or fill > 0.97:
            continue
        quad = _corners_from_mask(cleaned)
        if quad is None:
            continue

        area_fraction = _quad_area(quad) / float(small.shape[0] * small.shape[1])
        if not _quad_is_convex(quad):
            continue

        # Prefer a candidate whose quad is well filled by its own mask: a true
        # rectangular pack fills its bounding quad, a ragged background region
        # does not. Area enters as *plausibility*, not as magnitude — scoring
        # "bigger is better" made the background win whenever it was the
        # majority of the frame, because a mask surrounding the pack has its
        # extreme points at the image corners and so yields a quad covering
        # 99% of the frame.
        inside_fill = _fill_ratio(cleaned, quad)
        score = inside_fill * _area_plausibility(area_fraction)
        diagnostics["candidate_" + polarity + "_area"] = round(area_fraction, 4)
        diagnostics["candidate_" + polarity + "_fill"] = round(inside_fill, 4)

        if score > best_score:
            best_score = score
            best_quad = quad
            best_mask = cleaned
            bright_polarity = polarity == "bright"
            diagnostics["polarity"] = 1.0 if bright_polarity else 0.0
            diagnostics["candidate_score"] = round(score, 4)

    if best_quad is None:
        return None, diagnostics

    # Refine against a full-resolution mask. Refining on the downsampled mask
    # caps accuracy at the downsample factor: at a 480 px detection width, one
    # mask pixel is ~2.7 image pixels, which measured as ~6 px of corner error
    # on a clean capture and ~17 px on an off-axis one. Corner error propagates
    # through the homography as a scale error across the whole pack, so this is
    # the difference between a genuine pack scoring 0.89 and 0.54.
    coarse_quad = best_quad / scale
    full_mask = _full_resolution_mask(gray, threshold, bright=bright_polarity)
    refined, refine_diagnostics = _refine_quad(full_mask, coarse_quad)
    diagnostics.update(refine_diagnostics)
    return refined, diagnostics


def _area_plausibility(area_fraction: float) -> float:
    """How plausibly pack-shaped a candidate's area is.

    Flat across the range a photographed pack actually occupies, tapering to
    zero for a speck and for a region that spans the whole frame. The upper
    taper is what stops the background being chosen as the object.
    """
    if area_fraction <= 0.05 or area_fraction >= 0.97:
        return 0.0
    if area_fraction < MIN_AREA_FRACTION:
        return (area_fraction - 0.05) / (MIN_AREA_FRACTION - 0.05)
    if area_fraction <= 0.80:
        return 1.0
    return max(0.0, (0.97 - area_fraction) / (0.97 - 0.80))


def _fill_ratio(mask: np.ndarray, quad: np.ndarray) -> float:
    """Fraction of the quad's bounding box that the mask actually covers."""
    x0 = max(0, int(np.floor(quad[:, 0].min())))
    x1 = min(mask.shape[1], int(np.ceil(quad[:, 0].max())) + 1)
    y0 = max(0, int(np.floor(quad[:, 1].min())))
    y1 = min(mask.shape[0], int(np.ceil(quad[:, 1].max())) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    window = mask[y0:y1, x0:x1]
    return float(window.mean())


def compute_homography(source: np.ndarray, destination: np.ndarray) -> Optional[np.ndarray]:
    """Exact four-point homography mapping ``source`` onto ``destination``.

    Direct linear solve of the eight unknowns (the ninth is fixed to 1), which
    is exact for four correspondences — no RANSAC needed, because the four
    corners are the correspondences rather than candidate matches among many.
    """
    if source.shape != (4, 2) or destination.shape != (4, 2):
        raise ValueError("homography needs exactly four point pairs")

    a = np.zeros((8, 8), dtype=np.float64)
    b = np.zeros(8, dtype=np.float64)
    for index in range(4):
        x, y = float(source[index, 0]), float(source[index, 1])
        u, v = float(destination[index, 0]), float(destination[index, 1])
        a[index * 2] = [x, y, 1.0, 0.0, 0.0, 0.0, -x * u, -y * u]
        b[index * 2] = u
        a[index * 2 + 1] = [0.0, 0.0, 0.0, x, y, 1.0, -x * v, -y * v]
        b[index * 2 + 1] = v

    try:
        solution = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        # Degenerate correspondences (collinear corners).
        return None
    if not np.all(np.isfinite(solution)):
        return None

    homography = np.append(solution, 1.0).reshape(3, 3)

    # A near-frontal pack yields perspective terms of order 1e-19 — subnormal
    # floats, which are numerically meaningless here (1e-19 over 1000 pixels is
    # a distortion of 1e-16) but do raise underflow flags inside BLAS on every
    # subsequent matmul. Snapping them to zero keeps the transform exact to
    # double precision and keeps the logs clean.
    scale = float(np.abs(homography).max())
    if scale > 0.0:
        homography[np.abs(homography) < scale * 1e-12] = 0.0
    return homography


def apply_homography(homography: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Map an ``(N, 2)`` array of points through a homography."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        projected = homogeneous @ homography.T
        w = projected[:, 2:3]
        # Guard the projective divide. A point on the homography's vanishing
        # line has w == 0; clamping keeps the warp finite so the caller sees a
        # low agreement score rather than a NaN propagating through the image.
        w = np.where(np.abs(w) < 1e-12, 1e-12, w)
        mapped = projected[:, :2] / w
    return np.nan_to_num(mapped, nan=0.0, posinf=0.0, neginf=0.0)


def warp_to_canonical(
    gray: np.ndarray, canonical_to_image: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Rectify ``gray`` into a ``width`` x ``height`` canonical image.

    Inverse mapping with bilinear sampling: every output pixel is projected back
    into the source and interpolated, which leaves no holes. Fully vectorised.
    """
    ys, xs = np.mgrid[0:height, 0:width]
    grid = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], axis=1).astype(np.float64)
    source = apply_homography(canonical_to_image, grid)

    sx = source[:, 0] - 0.5
    sy = source[:, 1] - 0.5
    max_x = gray.shape[1] - 1
    max_y = gray.shape[0] - 1

    sx = np.clip(sx, 0.0, max_x)
    sy = np.clip(sy, 0.0, max_y)

    x0 = np.floor(sx).astype(np.int64)
    y0 = np.floor(sy).astype(np.int64)
    x1 = np.minimum(x0 + 1, max_x)
    y1 = np.minimum(y0 + 1, max_y)
    fx = (sx - x0).astype(np.float32)
    fy = (sy - y0).astype(np.float32)

    top = gray[y0, x0] * (1.0 - fx) + gray[y0, x1] * fx
    bottom = gray[y1, x0] * (1.0 - fx) + gray[y1, x1] * fx
    return (top * (1.0 - fy) + bottom * fy).reshape(height, width).astype(np.float32)


def estimate_translation(moving: np.ndarray, fixed: np.ndarray) -> Tuple[int, int, float]:
    """Sub-pixel-free translation estimate via FFT phase correlation.

    Corner detection is accurate to a pixel or two, and at canonical resolution
    that offset is enough to depress a structural comparison noticeably. Phase
    correlation recovers the residual shift cheaply. A Hann window suppresses
    the spurious peak that the image borders would otherwise create.

    Returns ``(dy, dx, peak_strength)``.
    """
    if moving.shape != fixed.shape:
        raise ValueError("translation estimate needs equal shapes")

    height, width = moving.shape
    window = np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)
    a = (moving - moving.mean()) * window
    b = (fixed - fixed.mean()) * window

    fa = np.fft.rfft2(a)
    fb = np.fft.rfft2(b)
    cross = fa * np.conj(fb)
    magnitude = np.abs(cross)
    magnitude[magnitude < 1e-12] = 1e-12
    correlation = np.fft.irfft2(cross / magnitude, s=moving.shape)

    peak_index = int(np.argmax(correlation))
    dy, dx = np.unravel_index(peak_index, correlation.shape)
    peak = float(correlation.flat[peak_index])

    # Wrap shifts greater than half a period into negative offsets.
    if dy > height // 2:
        dy -= height
    if dx > width // 2:
        dx -= width
    return int(dy), int(dx), peak


def shift_image(gray: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Translate by whole pixels, replicating the edge rather than wrapping."""
    if dy == 0 and dx == 0:
        return gray
    output = np.empty_like(gray)
    height, width = gray.shape
    src_y0, dst_y0 = (0, dy) if dy >= 0 else (-dy, 0)
    src_x0, dst_x0 = (0, dx) if dx >= 0 else (-dx, 0)
    copy_h = height - abs(dy)
    copy_w = width - abs(dx)
    if copy_h <= 0 or copy_w <= 0:
        return gray
    output[:] = float(gray.mean())
    output[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w] = gray[
        src_y0 : src_y0 + copy_h, src_x0 : src_x0 + copy_w
    ]
    return output


# Maximum residual translation we will correct, as a fraction of canonical size.
MAX_REFINE_FRACTION = 0.08


def register(
    scan_gray: np.ndarray,
    reference_gray: np.ndarray,
    canonical_width: int,
    canonical_height: int,
    expected_aspect: Optional[float] = None,
) -> RegistrationResult:
    """Rectify a scan onto the reference frame and score the alignment.

    The returned ``confidence`` is the product of geometric plausibility (is
    this shaped like the enrolled pack?) and structural agreement (does the
    rectified image actually line up with the reference?). Both must hold: a
    convincing rectangle that rectifies to something unrelated is a failed
    registration, not a packaging mismatch, and the distinction decides whether
    the scan is judged at all.
    """
    quad, diagnostics = detect_pack_quad(scan_gray)
    if quad is None:
        return RegistrationResult(
            ok=False,
            confidence=0.0,
            failure_reason="PACKAGE_NOT_FOUND",
            diagnostics=diagnostics,
        )

    image_area = float(scan_gray.shape[0] * scan_gray.shape[1])
    area_fraction = _quad_area(quad) / image_area
    diagnostics["area_fraction"] = round(area_fraction, 4)

    if area_fraction < MIN_AREA_FRACTION:
        return RegistrationResult(
            ok=False,
            confidence=0.0,
            quad=quad,
            failure_reason="PACKAGE_TOO_SMALL",
            diagnostics=diagnostics,
        )

    # Aspect ratio of the detected quad, from its mean edge lengths.
    top_edge = np.linalg.norm(quad[1] - quad[0])
    bottom_edge = np.linalg.norm(quad[2] - quad[3])
    left_edge = np.linalg.norm(quad[3] - quad[0])
    right_edge = np.linalg.norm(quad[2] - quad[1])
    mean_width = (top_edge + bottom_edge) / 2.0
    mean_height = (left_edge + right_edge) / 2.0
    if mean_height < 1.0 or mean_width < 1.0:
        return RegistrationResult(
            ok=False, confidence=0.0, quad=quad,
            failure_reason="PACKAGE_DEGENERATE", diagnostics=diagnostics,
        )

    detected_aspect = mean_width / mean_height
    target_aspect = expected_aspect or (canonical_width / float(canonical_height))
    aspect_ratio = detected_aspect / target_aspect
    diagnostics["detected_aspect"] = round(detected_aspect, 4)
    diagnostics["aspect_agreement"] = round(min(aspect_ratio, 1.0 / aspect_ratio), 4)

    aspect_score = _tolerance_score(aspect_ratio, ASPECT_TOLERANCE)
    area_score = min(1.0, area_fraction / 0.45)
    if area_fraction > MAX_AREA_FRACTION:
        # The whole frame: almost certainly the background, not the pack.
        area_score *= 0.2

    canonical_corners = np.array(
        [
            [0.0, 0.0],
            [canonical_width, 0.0],
            [canonical_width, canonical_height],
            [0.0, canonical_height],
        ],
        dtype=np.float64,
    )
    homography = compute_homography(canonical_corners, quad)
    if homography is None:
        return RegistrationResult(
            ok=False, confidence=0.0, quad=quad,
            failure_reason="REGISTRATION_FAILED", diagnostics=diagnostics,
        )

    warped = warp_to_canonical(scan_gray, homography, canonical_width, canonical_height)

    # Residual translation refinement, on blurred copies so the estimate follows
    # layout rather than print texture.
    reference_resized = (
        reference_gray
        if reference_gray.shape == warped.shape
        else resize_gray(reference_gray, canonical_width, canonical_height)
    )
    dy, dx, peak = estimate_translation(
        gaussian_blur(warped, 2.0), gaussian_blur(reference_resized, 2.0)
    )
    limit_y = int(canonical_height * MAX_REFINE_FRACTION)
    limit_x = int(canonical_width * MAX_REFINE_FRACTION)
    applied_dy = int(np.clip(dy, -limit_y, limit_y))
    applied_dx = int(np.clip(dx, -limit_x, limit_x))

    before = normalized_cross_correlation(
        gaussian_blur(warped, 1.5), gaussian_blur(reference_resized, 1.5)
    )
    if applied_dy or applied_dx:
        candidate = shift_image(warped, applied_dy, applied_dx)
        after = normalized_cross_correlation(
            gaussian_blur(candidate, 1.5), gaussian_blur(reference_resized, 1.5)
        )
        # Keep the refinement only if it genuinely improved agreement. Phase
        # correlation on a tampered pack can suggest a shift that makes things
        # worse, and accepting it would hide the very mismatch we are looking for.
        if after > before:
            warped = candidate
            agreement = after
        else:
            applied_dy = applied_dx = 0
            agreement = before
    else:
        agreement = before

    diagnostics["translation_dy"] = float(applied_dy)
    diagnostics["translation_dx"] = float(applied_dx)
    diagnostics["phase_peak"] = round(peak, 5)
    diagnostics["structure_agreement"] = round(agreement, 4)
    diagnostics["aspect_score"] = round(aspect_score, 4)
    diagnostics["area_score"] = round(area_score, 4)

    agreement_score = max(0.0, min(1.0, (agreement + 0.2) / 1.2))
    confidence = float(
        np.clip((aspect_score ** 0.5) * (area_score ** 0.3) * (agreement_score ** 0.6), 0.0, 1.0)
    )

    if agreement < MIN_STRUCTURE_AGREEMENT:
        return RegistrationResult(
            ok=False,
            confidence=confidence,
            warped=warped,
            homography=homography,
            quad=quad,
            failure_reason="REGISTRATION_FAILED",
            diagnostics=diagnostics,
        )

    return RegistrationResult(
        ok=True,
        confidence=confidence,
        warped=warped,
        homography=homography,
        quad=quad,
        diagnostics=diagnostics,
    )


def _tolerance_score(ratio: float, tolerance: float) -> float:
    """Score a ratio's closeness to 1.0, reaching 0 at ``tolerance`` away."""
    deviation = abs(float(ratio) - 1.0)
    if deviation >= tolerance:
        return 0.0
    return 1.0 - (deviation / tolerance)
