"""Deterministic explanation of a decision.

Everything a user reads is derived here, from reason codes, by pure functions.
That ordering matters: the backend decides, then explains. An optional Bedrock
rewrite (:mod:`scads.adapters.bedrock_explainer`) may only restyle this text,
and is validated against it, so generated prose can never introduce a finding
the engine did not make (``docs/API_CONTRACTS.md`` rule 5).

The wording rules come from ``docs/SECURITY_PRIVACY.md`` section 8: never claim
a pack is genuine or safe, never create panic, and always say what the scan did
not test.
"""

from typing import Dict, List, Optional

from ..contracts.enums import Decision, EvidenceState, ProductState, VerificationLevel
from ..contracts.models import DecisionResult, DimensionView, EvidenceBundle
from ..contracts.reason_codes import Category, ReasonCode, category_of, meta, severity_of
from ..contracts.reason_codes import Severity

# The sentence that must accompany every result. A packaging scan says nothing
# about what is inside the pack, and SCADS states that rather than implying
# otherwise by omission.
CHEMICAL_LIMITATION = (
    "This check compares the pack's identity, printing and scan history. It does not "
    "test the medicine inside — no phone scan can measure active ingredient, dose or "
    "contamination."
)

_HEADLINES: Dict[Decision, str] = {
    Decision.LOW_OBSERVED_RISK: "No contradictions found",
    Decision.REVIEW_REQUIRED: "Needs a closer look",
    Decision.SUSPICIOUS: "Contradictions found",
    Decision.UNABLE_TO_VERIFY: "Not enough evidence to judge",
}

_NEXT_ACTIONS: Dict[Decision, str] = {
    Decision.LOW_OBSERVED_RISK: (
        "The identity, packaging and scan-history checks agreed. Keep your receipt and "
        "report any unexpected effect to a pharmacist."
    ),
    Decision.REVIEW_REQUIRED: (
        "Some evidence was mixed or incomplete. Ask a pharmacist to check the pack before "
        "using it, and try another scan in good light if you were prompted to."
    ),
    Decision.SUSPICIOUS: (
        "This scan found contradictions that need review. Do not rely on this scan alone. "
        "Avoid using the pack until a pharmacist, the manufacturer or the relevant "
        "authority has checked it, and keep the pack so it can be examined."
    ),
    Decision.UNABLE_TO_VERIFY: (
        "The scan did not contain enough reliable evidence to reach a conclusion. This is "
        "not a finding against the pack. Retake the photo in good, even light with the "
        "whole front of the pack visible, or verify another way."
    ),
}

_DIMENSION_LABELS = {
    "identity": "Identity",
    "physical": "Physical pack",
    "history": "Scan history",
}


def headline(decision: Decision) -> str:
    return _HEADLINES[decision]


def next_action(decision: Decision) -> str:
    return _NEXT_ACTIONS[decision]


def explain_code(code: ReasonCode) -> Dict[str, str]:
    """Render one reason code for display."""
    m = meta(code)
    return {
        "code": code.value,
        "category": m.category.value,
        "severity": m.severity.name,
        "title": m.title,
        "detail": m.detail,
    }


def explain_codes(codes: List[ReasonCode]) -> List[Dict[str, str]]:
    return [explain_code(c) for c in codes]


def _state_for(codes: List[ReasonCode], available: bool) -> EvidenceState:
    """Derive a dimension's displayed state from its own reason codes."""
    if not available:
        return EvidenceState.UNKNOWN
    worst = Severity.INFO
    for code in codes:
        worst = max(worst, severity_of(code))
    if worst >= Severity.SEVERE:
        return EvidenceState.FAIL
    if worst >= Severity.WARNING:
        return EvidenceState.WARN
    return EvidenceState.OK


def _headline_for(dimension: str, codes: List[ReasonCode], available: bool) -> str:
    """One short line summarising a dimension, taken from its strongest code."""
    if not available:
        fallback = {
            "identity": "Identity could not be read",
            "physical": "Packaging was not compared",
            "history": "Scan history was not available",
        }
        for code in codes:
            return meta(code).title
        return fallback.get(dimension, "Not assessed")
    if not codes:
        return "No findings"
    strongest = max(codes, key=lambda c: int(severity_of(c)))
    return meta(strongest).title


def build_dimensions(bundle: EvidenceBundle, result: DecisionResult) -> List[DimensionView]:
    """The three evidence rows of the result card, always in the same order.

    Always three rows, even when a dimension was not assessable: a missing row
    would read as "nothing to report" when it actually means "not checked".
    """
    identity_codes = [c for c in bundle.identity.reason_codes if category_of(c) is Category.IDENTITY]
    physical_codes = [c for c in bundle.physical.reason_codes]
    history_codes = [c for c in bundle.history.reason_codes]

    identity_available = bundle.identity.state is not EvidenceState.UNKNOWN

    return [
        DimensionView(
            key="identity",
            label=_DIMENSION_LABELS["identity"],
            state=_state_for(identity_codes, identity_available),
            score=bundle.identity.score if identity_available else None,
            available=identity_available,
            headline=_headline_for("identity", identity_codes, identity_available),
        ),
        DimensionView(
            key="physical",
            label=_DIMENSION_LABELS["physical"],
            state=_state_for(physical_codes, bundle.physical.available),
            score=bundle.physical.score if bundle.physical.available else None,
            available=bundle.physical.available,
            headline=_headline_for("physical", physical_codes, bundle.physical.available),
        ),
        DimensionView(
            key="history",
            label=_DIMENSION_LABELS["history"],
            state=_state_for(history_codes, bundle.history.available),
            score=bundle.history.score if bundle.history.available else None,
            available=bundle.history.available,
            headline=_headline_for("history", history_codes, bundle.history.available),
        ),
    ]


def assurance_note(level: VerificationLevel) -> str:
    """State plainly how specifically the pack was identified.

    Batch-level and unit-level results must not be described in the same
    language: matching a batch says the batch exists, not that this pack is a
    genuine unit of it (``phases/PHASE_2_IDENTITY.md``).
    """
    if level is VerificationLevel.UNIT:
        return "This pack was checked as an individual unit using its serial number."
    if level is VerificationLevel.BATCH:
        return (
            "Only the batch could be checked, not this individual pack. A real batch code "
            "can appear on many copied packs, so this is weaker evidence than a unit check."
        )
    if level is VerificationLevel.PRODUCT:
        return "Only the product was recognised, not its batch or this individual pack."
    return "No registry identity could be confirmed for this pack."


def product_status_note(result: DecisionResult) -> Optional[str]:
    """Product-lifecycle guidance, kept separate from the authenticity verdict."""
    status = result.product_status
    if status.state is ProductState.EXPIRED:
        return (
            "This batch is past its expiry date"
            + (" (" + status.expiry_date + ")" if status.expiry_date else "")
            + ". Expired medicine should not be used even when the pack itself looks "
            "authentic."
        )
    if status.state is ProductState.RECALLED:
        return (
            "This batch has been recalled. Return it to a pharmacist rather than using it, "
            "regardless of what the packaging checks found."
        )
    if status.state is ProductState.WITHDRAWN:
        return "This product has been withdrawn from the market."
    return None


def summarise(bundle: EvidenceBundle, result: DecisionResult) -> Dict[str, object]:
    """The complete user-facing explanation of a result.

    Pure and deterministic: this is the text the frontend renders when Bedrock
    is disabled or unavailable, and the reference that any generated rewrite is
    checked against.
    """
    dimensions = build_dimensions(bundle, result)
    contradictions = [
        c
        for c in result.reason_codes
        if severity_of(c) >= Severity.WARNING
        and category_of(c) in (Category.IDENTITY, Category.PHYSICAL, Category.HISTORY)
    ]
    return {
        "headline": headline(result.decision),
        "next_action": next_action(result.decision),
        "limitation": CHEMICAL_LIMITATION,
        "assurance_note": assurance_note(result.verification_level),
        "product_status_note": product_status_note(result),
        "dimensions": [d.to_public() for d in dimensions],
        "reasons": explain_codes(result.reason_codes),
        "primary_reasons": explain_codes(contradictions[:3]),
    }
