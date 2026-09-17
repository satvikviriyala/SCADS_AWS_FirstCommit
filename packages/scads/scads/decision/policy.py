"""The versioned fusion policy.

Every number that can change a verdict lives here, in one place, behind a
version string. Nothing in :mod:`scads.decision.fusion` hard-codes a threshold.
That separation is what makes ``docs/EVALUATION.md`` ablations and later
recalibration possible: you change a policy, bump its version, and every stored
result still says which policy judged it.

These are **demonstration values chosen by hand**. They are not calibrated
against adjudicated counterfeit samples and must not be described as validated
(``docs/RESEARCH_NOTES.md``; ``docs/EVALUATION.md`` section 1).
"""

from dataclasses import dataclass, field
from typing import Dict, Mapping, Tuple

from ..contracts.enums import Decision
from ..contracts.reason_codes import Category, ReasonCode, Severity


@dataclass(frozen=True)
class FusionPolicy:
    """A complete, immutable decision policy."""

    version: str

    # --- Stage 1: scan-quality gate -------------------------------------
    # Below this, packaging evidence is not trustworthy enough to judge and the
    # scan returns UNABLE_TO_VERIFY rather than accusing a badly lit pack.
    quality_floor: float = 0.45

    # --- Stage 3: base fusion -------------------------------------------
    # Weights for the weighted geometric mean over the available dimensions.
    # Renormalised across whichever dimensions are actually present.
    weights: Mapping[str, float] = field(
        default_factory=lambda: {"identity": 0.35, "physical": 0.40, "history": 0.25}
    )

    # --- Stage 5: decision thresholds -----------------------------------
    low_risk_threshold: float = 0.75
    review_threshold: float = 0.45

    # --- Stage 4: hard caps ---------------------------------------------
    # A cap is a ceiling on the presentation score. Its purpose is to stop a
    # flattering photograph from averaging away a decisive contradiction: this
    # is the mechanism behind the product claim that a copied-but-valid serial
    # cannot pass just because the pack looks perfect.
    score_caps: Mapping[ReasonCode, float] = field(
        default_factory=lambda: {
            ReasonCode.SERIAL_REVOKED: 0.05,
            ReasonCode.BATCH_UNKNOWN: 0.20,
            ReasonCode.SERIAL_REUSE: 0.25,
            ReasonCode.IMPOSSIBLE_TRAVEL: 0.25,
            ReasonCode.POST_SALE_REUSE: 0.25,
            ReasonCode.COPY_PATTERN_MISMATCH: 0.25,
            ReasonCode.QR_OCR_CONFLICT: 0.35,
            ReasonCode.SCAN_VELOCITY_ANOMALY: 0.40,
        }
    )

    # A ceiling on the *decision class*, used where a score cap would be the
    # wrong tool. An unissued serial on an otherwise convincing pack must not be
    # called low risk, but the right outcome is "needs review", not a
    # near-zero score that implies certainty SCADS does not have.
    decision_ceilings: Mapping[ReasonCode, Decision] = field(
        default_factory=lambda: {
            ReasonCode.SERIAL_UNKNOWN: Decision.REVIEW_REQUIRED,
            ReasonCode.HISTORY_UNAVAILABLE: Decision.REVIEW_REQUIRED,
            ReasonCode.PRODUCT_RECALLED: Decision.REVIEW_REQUIRED,
            ReasonCode.UNSUPPORTED_PACKAGE_VARIANT: Decision.REVIEW_REQUIRED,
            ReasonCode.REFERENCE_NOT_FOUND: Decision.REVIEW_REQUIRED,
            ReasonCode.DEPENDENCY_UNAVAILABLE: Decision.REVIEW_REQUIRED,
        }
    )

    # --- General contradiction ceiling -----------------------------------
    # A pack may not be reported as low observed risk while any evidence
    # dimension is actively contradicting. Without this rule the weighted
    # geometric mean alone still clears the low-risk threshold when one
    # dimension is failing but the other two are near-perfect — which is exactly
    # the "contradictions must not average away" property SCADS claims
    # (``docs/API_CONTRACTS.md`` contract rule 2, generalised from identity and
    # history to packaging).
    #
    # Scoped to the three authenticity dimensions. Product status is excluded
    # because expiry is not counterfeit evidence, and scan quality is excluded
    # because the quality gate already owns that decision.
    contradiction_categories: Tuple[Category, ...] = (
        Category.IDENTITY,
        Category.PHYSICAL,
        Category.HISTORY,
    )
    # NOTICE-level findings are deliberately below the bar. COLOR_MISMATCH sits
    # there because camera white balance moves it, and a lighting artefact must
    # not downgrade a genuine pack.
    contradiction_min_severity: Severity = Severity.WARNING
    contradiction_ceiling: Decision = Decision.REVIEW_REQUIRED

    # --- Conditional severe-physical-mismatch cap ------------------------
    # Applied only when the pack was confidently aligned to its reference. A
    # low physical score from a poor alignment says nothing about the pack, so
    # penalising it would manufacture false accusations out of camera geometry
    # (``docs/SCORING_AND_DETECTION.md`` section 3).
    severe_physical_score: float = 0.30
    severe_physical_registration_floor: float = 0.60
    severe_physical_cap: float = 0.35

    # --- Product status --------------------------------------------------
    # Expiry never changes the authenticity verdict. An expired pack can be
    # entirely genuine; it is reported through product_status and the UI's "do
    # not use" guidance instead (``PLAN.md`` AT-07).
    expiry_affects_decision: bool = False

    def describe(self) -> Dict[str, object]:
        """Policy as plain data, for the evidence drawer and for logs."""
        return {
            "version": self.version,
            "quality_floor": self.quality_floor,
            "weights": dict(self.weights),
            "low_risk_threshold": self.low_risk_threshold,
            "review_threshold": self.review_threshold,
            "score_caps": {k.value: v for k, v in self.score_caps.items()},
            "decision_ceilings": {k.value: v.value for k, v in self.decision_ceilings.items()},
            "severe_physical_score": self.severe_physical_score,
            "severe_physical_registration_floor": self.severe_physical_registration_floor,
            "severe_physical_cap": self.severe_physical_cap,
            "expiry_affects_decision": self.expiry_affects_decision,
            "contradiction_categories": [c.value for c in self.contradiction_categories],
            "contradiction_min_severity": self.contradiction_min_severity.name,
            "contradiction_ceiling": self.contradiction_ceiling.value,
        }


# Ordering used when more than one decision ceiling applies: lowest wins.
_DECISION_RANK: Dict[Decision, int] = {
    Decision.SUSPICIOUS: 0,
    Decision.UNABLE_TO_VERIFY: 1,
    Decision.REVIEW_REQUIRED: 2,
    Decision.LOW_OBSERVED_RISK: 3,
}


def decision_rank(decision: Decision) -> int:
    return _DECISION_RANK[decision]


def worst_of(*decisions: Decision) -> Decision:
    """Return the most cautious of the supplied decisions."""
    return min(decisions, key=decision_rank)


DEFAULT_POLICY = FusionPolicy(version="fusion_0.1.0")
