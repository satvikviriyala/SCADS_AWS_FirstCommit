"""Evidence models.

These dataclasses are the boundary between the messy world (images, OCR, AWS)
and the pure decision function. Each evidence dimension stays separate all the
way to the response: SCADS never collapses identity, packaging and history into
one number internally (``CLAUDE.md``, product invariant).

Every ``score`` is a real number in [0, 1] and every constructor validates that,
because a NaN or an out-of-range score silently corrupts the fusion arithmetic
rather than failing a test.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..util.numeric import require_unit_scalar
from .enums import (
    ActorType,
    Decision,
    EvidenceState,
    LocationMode,
    ProductState,
    RecallStatus,
    SerialStatus,
    VerificationLevel,
)
from .reason_codes import ReasonCode


@dataclass(frozen=True)
class ScanLocation:
    """Where a scan was reported from.

    ``mode`` records provenance so the UI and the history rules can distinguish
    a synthetic demo location from a consented coarse one. ``label`` is a named
    bucket (for example ``BENGALURU_DEMO``), never a street address, and
    lat/lon are bucket centroids rather than device coordinates
    (``docs/SECURITY_PRIVACY.md`` section 2).
    """

    mode: LocationMode = LocationMode.NONE
    label: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None

    def to_public(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "label": self.label,
            "simulated": self.mode is LocationMode.DEMO,
        }


@dataclass(frozen=True)
class QualityReport:
    """Output of the scan-quality gate.

    The gate runs before any comparison. A pack photographed badly must produce
    uncertainty, never counterfeit evidence (``AGENTS.md`` section 6.2), so
    ``passed=False`` routes to ``UNABLE_TO_VERIFY``.
    """

    score: float
    passed: bool
    reason_codes: List[ReasonCode] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_unit_scalar(self.score, "QualityReport.score")


@dataclass(frozen=True)
class ResolvedIdentity:
    """Identity as resolved against the registry (not as claimed by the pack)."""

    manufacturer_id: Optional[str] = None
    manufacturer_name: Optional[str] = None
    sku_id: Optional[str] = None
    product_name: Optional[str] = None
    batch_id: Optional[str] = None
    serial_id: Optional[str] = None
    verification_level: VerificationLevel = VerificationLevel.NONE
    serial_status: SerialStatus = SerialStatus.UNKNOWN
    reference_profile_id: Optional[str] = None

    def to_public(self) -> Dict[str, Any]:
        return {
            "manufacturer_id": self.manufacturer_id,
            "manufacturer_name": self.manufacturer_name,
            "sku_id": self.sku_id,
            "product_name": self.product_name,
            "batch_id": self.batch_id,
            "serial_id": self.serial_id,
            "verification_level": self.verification_level.value,
        }


@dataclass(frozen=True)
class ClaimedIdentity:
    """Identity as claimed by the pack, before any registry check.

    Kept separate from :class:`ResolvedIdentity` so that "the pack says serial
    X" and "the registry knows serial X" can never be confused — that confusion
    is precisely the weakness of a QR-existence check.
    """

    serial: Optional[str] = None
    batch: Optional[str] = None
    gtin: Optional[str] = None
    product_name: Optional[str] = None
    manufacturer_name: Optional[str] = None
    expiry: Optional[str] = None
    source: str = "NONE"  # QR | OCR | QR+OCR | CLIENT | NONE

    def to_public(self) -> Dict[str, Any]:
        return {
            "serial": self.serial,
            "batch": self.batch,
            "source": self.source,
        }


@dataclass(frozen=True)
class IdentityEvidence:
    score: float
    state: EvidenceState
    resolved: ResolvedIdentity
    claimed: ClaimedIdentity
    reason_codes: List[ReasonCode] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_unit_scalar(self.score, "IdentityEvidence.score")


@dataclass(frozen=True)
class PhysicalFeature:
    """One named packaging feature with the value and threshold that judged it.

    Carrying the threshold alongside the value makes a result self-describing in
    logs and in the evidence drawer, and keeps ``docs/EVALUATION.md`` ablations
    honest: you can see which feature moved.
    """

    name: str
    value: float
    weight: float
    threshold: float
    ok: bool
    description: str = ""

    def __post_init__(self) -> None:
        require_unit_scalar(self.value, "PhysicalFeature.value:" + self.name)

    def to_public(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "weight": self.weight,
            "threshold": self.threshold,
            "ok": self.ok,
            "description": self.description,
        }


@dataclass(frozen=True)
class PhysicalEvidence:
    """Packaging comparison result.

    ``available=False`` means the comparison did not run — no enrolled
    reference, or registration failed. That is materially different from
    "compared and matched", and the fusion policy must not treat it as a pass.
    """

    score: float
    state: EvidenceState
    available: bool
    features: List[PhysicalFeature] = field(default_factory=list)
    reason_codes: List[ReasonCode] = field(default_factory=list)
    registration_confidence: float = 0.0
    reference_version: Optional[str] = None
    reference_profile_id: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_unit_scalar(self.score, "PhysicalEvidence.score")
        require_unit_scalar(
            self.registration_confidence, "PhysicalEvidence.registration_confidence"
        )


@dataclass(frozen=True)
class HistoryFinding:
    """A single history anomaly, with the observation that produced it.

    ``evidence`` holds the concrete numbers (distance, elapsed minutes, implied
    speed) so the UI can say *why* rather than just naming a rule, and so an
    investigator can reproduce the judgement.
    """

    code: ReasonCode
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> Dict[str, Any]:
        return {"code": self.code.value, "summary": self.summary, "evidence": self.evidence}


@dataclass(frozen=True)
class PriorScanSummary:
    """A prior observation of the same unit, for the history timeline."""

    scan_id: str
    event_time: str
    location_label: Optional[str]
    location_mode: LocationMode
    actor_type: ActorType
    decision: Optional[Decision] = None

    def to_public(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "event_time": self.event_time,
            "location_label": self.location_label,
            "location_mode": self.location_mode.value,
            "actor_type": self.actor_type.value,
            "decision": self.decision.value if self.decision else None,
        }


@dataclass(frozen=True)
class HistoryEvidence:
    score: float
    state: EvidenceState
    available: bool
    findings: List[HistoryFinding] = field(default_factory=list)
    reason_codes: List[ReasonCode] = field(default_factory=list)
    prior_scans: List[PriorScanSummary] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_unit_scalar(self.score, "HistoryEvidence.score")


@dataclass(frozen=True)
class ProductStatus:
    """Product lifecycle state.

    Deliberately not a score. An expired or recalled pack can be perfectly
    authentic; blending expiry into an authenticity number would both mislabel
    genuine packs and hide real recalls (``AGENTS.md`` section 6.3).
    """

    state: ProductState = ProductState.UNKNOWN
    expiry_date: Optional[str] = None
    recall_status: RecallStatus = RecallStatus.UNKNOWN
    reason_codes: List[ReasonCode] = field(default_factory=list)

    def to_public(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "expiry_date": self.expiry_date,
            "recall_status": self.recall_status.value,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """The complete, ordered input to :func:`scads.decision.fusion.decide`.

    ``decide`` is a pure function of this bundle. Same bundle in, same decision
    out, for a given policy version (AT-09).
    """

    quality: QualityReport
    identity: IdentityEvidence
    physical: PhysicalEvidence
    history: HistoryEvidence
    product: ProductStatus
    system_reason_codes: List[ReasonCode] = field(default_factory=list)


@dataclass(frozen=True)
class AppliedCap:
    """Record of a hard cap that constrained the result.

    Persisted so that "why was this not low risk?" is answerable from the stored
    record alone.
    """

    code: ReasonCode
    max_score: float
    rationale: str

    def to_public(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "max_score": self.max_score,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class DimensionView:
    """One row of the result card: a name, a state and a score."""

    key: str
    label: str
    state: EvidenceState
    score: Optional[float]
    available: bool
    headline: str

    def to_public(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state.value,
            "score": None if self.score is None else round(self.score, 4),
            "available": self.available,
            "headline": self.headline,
        }


@dataclass(frozen=True)
class DecisionResult:
    """Output of the decision engine.

    ``presentation_score`` is UI sugar only. ``dimensions`` and
    ``reason_codes`` are authoritative (``docs/API_CONTRACTS.md`` rule 4).
    """

    decision: Decision
    presentation_score: float
    # False when the decision is UNABLE_TO_VERIFY. A scan that could not be
    # judged has no meaningful score, and rendering 0.0 would read as "certainly
    # fake" — the exact false accusation the quality gate exists to prevent.
    presentation_score_applicable: bool
    base_score: float
    identity_score: float
    physical_score: float
    history_score: float
    scan_quality: float
    reason_codes: List[ReasonCode]
    applied_caps: List[AppliedCap] = field(default_factory=list)
    product_status: ProductStatus = field(default_factory=ProductStatus)
    verification_level: VerificationLevel = VerificationLevel.NONE
    fusion_policy_version: str = ""
    weights_used: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        require_unit_scalar(self.presentation_score, "DecisionResult.presentation_score")
        require_unit_scalar(self.base_score, "DecisionResult.base_score")
