"""SCADS — Supply-Chain-Aware Drug Screening.

Counterfeit-medicine risk screening that compares three independent kinds of
evidence about a pack — claimed identity, physical packaging and observed scan
history — and reports contradictions between them rather than averaging them
into a single trust number.
"""

from .versions import (  # noqa: F401
    CONTRACT_VERSION,
    FUSION_POLICY_VERSION,
    PIPELINE_VERSION,
    SERVICE_NAME,
    SERVICE_VERSION,
)

__version__ = SERVICE_VERSION
