"""Deterministic decision engine and its explanation layer."""

from .explain import CHEMICAL_LIMITATION, build_dimensions, summarise  # noqa: F401
from .fusion import compare_with_average, decide  # noqa: F401
from .policy import DEFAULT_POLICY, FusionPolicy  # noqa: F401
