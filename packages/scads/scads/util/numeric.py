"""Numeric guards and the fusion primitives.

Scores flow from image processing into log-space arithmetic, so a NaN or an
out-of-range value would propagate silently and produce a plausible-looking but
meaningless verdict. Everything that enters the decision engine is validated
here instead (``docs/EVALUATION.md`` section 6: "NaN/None rejected").
"""

import math
from typing import Dict, Iterable, Mapping, Optional

# Floor used inside logarithms. A feature value of exactly 0 must drive the
# geometric mean toward zero without raising, so we clamp rather than special-case.
EPS = 1e-6


class InvalidScore(ValueError):
    """Raised when a value that must be a score in [0, 1] is not."""


def require_unit_scalar(value: object, name: str) -> float:
    """Validate that ``value`` is a real number in [0, 1] and return it.

    Rejects ``None``, ``bool``, NaN and infinities explicitly. ``bool`` is
    rejected because ``True`` would silently become the score 1.0 and mask a
    type error at the call site.
    """
    if value is None:
        raise InvalidScore(name + " is None; scores must be explicit")
    if isinstance(value, bool):
        raise InvalidScore(name + " is a bool; expected a float score")
    if not isinstance(value, (int, float)):
        raise InvalidScore(name + " is " + type(value).__name__ + "; expected a float score")
    v = float(value)
    if math.isnan(v):
        raise InvalidScore(name + " is NaN")
    if math.isinf(v):
        raise InvalidScore(name + " is infinite")
    if v < 0.0 or v > 1.0:
        raise InvalidScore(name + " is " + repr(v) + "; must be within [0, 1]")
    return v


def clamp01(value: float) -> float:
    """Clamp a finite number into [0, 1]; NaN is rejected rather than coerced."""
    v = float(value)
    if math.isnan(v):
        raise InvalidScore("cannot clamp NaN")
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def normalize_linear(value: float, low: float, high: float) -> float:
    """Map ``value`` from the range [low, high] onto [0, 1] with clamping.

    Used to turn raw image metrics (Laplacian variance, pixel counts) into
    comparable scores. ``low`` maps to 0 and ``high`` to 1; the direction may be
    inverted by passing ``low > high``.
    """
    if low == high:
        raise ValueError("normalize_linear requires low != high")
    return clamp01((float(value) - low) / (high - low))


def weighted_geometric_mean(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted geometric mean over the keys present in ``values``.

    SCADS fuses evidence multiplicatively, not additively. An arithmetic mean
    lets one strong signal pay for a catastrophic one — a beautiful photograph
    would offset an unissued serial. In log-space, a near-zero input drags the
    result down no matter how good the others are, which is the behaviour the
    product claim requires (``docs/SCORING_AND_DETECTION.md`` section 7).

    Weights are renormalised over the keys actually supplied, so a missing
    dimension does not silently count as 1.0. Callers that omit a dimension must
    decide separately what its absence means; see
    :mod:`scads.decision.fusion`.
    """
    if not values:
        raise ValueError("weighted_geometric_mean requires at least one value")

    present = {}
    for key, raw in values.items():
        weight = float(weights.get(key, 0.0))
        if weight <= 0.0:
            continue
        present[key] = (require_unit_scalar(raw, "value:" + key), weight)

    if not present:
        raise ValueError("weighted_geometric_mean: no positively weighted values supplied")

    total_weight = sum(w for _, w in present.values())
    if total_weight <= 0.0:
        raise ValueError("weighted_geometric_mean: total weight must be positive")

    log_sum = 0.0
    for value, weight in present.values():
        log_sum += (weight / total_weight) * math.log(max(EPS, value))
    return clamp01(math.exp(log_sum))


def arithmetic_mean(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted arithmetic mean.

    Not used for the verdict. It exists so tests can demonstrate the concrete
    gap between averaging evidence and fusing it multiplicatively — the
    comparison required by ``docs/EVALUATION.md`` section 6.
    """
    present: Dict[str, float] = {}
    for key, raw in values.items():
        weight = float(weights.get(key, 0.0))
        if weight <= 0.0:
            continue
        present[key] = require_unit_scalar(raw, "value:" + key) * weight
    total_weight = sum(float(weights.get(k, 0.0)) for k in present)
    if total_weight <= 0.0:
        raise ValueError("arithmetic_mean: total weight must be positive")
    return clamp01(sum(present.values()) / total_weight)


def safe_min(values: Iterable[Optional[float]]) -> Optional[float]:
    """Minimum over the non-``None`` values, or ``None`` if there are none."""
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return min(present)
