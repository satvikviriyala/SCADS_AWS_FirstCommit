"""The decision engine.

:func:`decide` is a pure function from an :class:`EvidenceBundle` to a
:class:`DecisionResult`. No I/O, no clock, no randomness, no network. Given the
same evidence and the same policy version it returns the same verdict, which is
what makes a SCADS result auditable and re-evaluable (``PLAN.md`` AT-09/AT-10).

Gate order matters and is deliberate:

1. **Decisive contradictions that do not depend on the photograph.** A revoked
   serial is revoked whether or not the picture is sharp.
2. **Scan-quality gate.** Otherwise, a photo too poor to judge yields
   uncertainty, never an accusation.
3. **Evidence availability.** A dimension that could not be assessed is
   excluded from fusion — never silently scored 1.0.
4. **Weighted geometric fusion** over the dimensions that are present.
5. **Hard caps** for severe contradictions.
6. **Thresholds**, then decision-class ceilings.
"""

from typing import Dict, List, Optional, Tuple

from ..contracts.enums import Decision, EvidenceState, VerificationLevel
from ..contracts.models import AppliedCap, DecisionResult, EvidenceBundle
from ..contracts.reason_codes import Category, ReasonCode, Severity, category_of, order_codes, severity_of
from ..util.numeric import clamp01, weighted_geometric_mean
from .policy import DEFAULT_POLICY, FusionPolicy, worst_of

# Contradictions that are established from registry/history records rather than
# from the image, and therefore remain decisive even when the photograph is too
# poor to compare packaging.
_IMAGE_INDEPENDENT_SEVERE = (
    ReasonCode.SERIAL_REVOKED,
    ReasonCode.SERIAL_REUSE,
    ReasonCode.IMPOSSIBLE_TRAVEL,
    ReasonCode.POST_SALE_REUSE,
    ReasonCode.BATCH_UNKNOWN,
)


def decide(bundle: EvidenceBundle, policy: Optional[FusionPolicy] = None) -> DecisionResult:
    """Fuse evidence into a decision. Pure.

    Args:
        bundle: separate identity, physical, history, product and quality evidence.
        policy: the versioned policy to apply; defaults to
            :data:`scads.decision.policy.DEFAULT_POLICY`.
    """
    pol = policy or DEFAULT_POLICY

    codes: List[ReasonCode] = []
    codes.extend(bundle.quality.reason_codes)
    codes.extend(bundle.identity.reason_codes)
    codes.extend(bundle.physical.reason_codes)
    codes.extend(bundle.history.reason_codes)
    codes.extend(bundle.product.reason_codes)
    codes.extend(bundle.system_reason_codes)

    notes: List[str] = []

    # --- Stage 1: contradictions that the camera cannot excuse ------------
    decisive = [c for c in codes if c in _IMAGE_INDEPENDENT_SEVERE]

    # --- Stage 2: scan-quality gate --------------------------------------
    if not bundle.quality.passed and not decisive:
        notes.append(
            "Scan quality {:.2f} is below the {:.2f} floor, so packaging evidence was not "
            "assessable. Poor capture is reported as uncertainty, not as counterfeit "
            "evidence.".format(bundle.quality.score, pol.quality_floor)
        )
        return _unable(bundle, pol, codes, notes)

    if not bundle.quality.passed and decisive:
        notes.append(
            "Scan quality was below the floor, but the registry and scan-history checks "
            "already found a contradiction that does not depend on image quality."
        )

    # --- Stage 3: which dimensions can we actually score? -----------------
    values: Dict[str, float] = {}
    unavailable: List[str] = []

    if bundle.identity.state is EvidenceState.UNKNOWN:
        unavailable.append("identity")
    else:
        values["identity"] = bundle.identity.score

    if bundle.physical.available:
        values["physical"] = bundle.physical.score
    else:
        unavailable.append("physical")

    if bundle.history.available:
        values["history"] = bundle.history.score
    else:
        unavailable.append("history")

    for name in unavailable:
        notes.append(
            name.capitalize() + " evidence was unavailable and was excluded from fusion rather "
            "than scored as a pass."
        )

    # Identity or packaging entirely missing means there is not enough evidence
    # to judge the pack at all — unless a decisive contradiction already settles
    # it (``docs/ARCHITECTURE.md`` section 8).
    if ("identity" in unavailable or "physical" in unavailable) and not decisive:
        return _unable(bundle, pol, codes, notes)

    if not values:
        return _unable(bundle, pol, codes, notes)

    # --- Stage 4: weighted geometric base score --------------------------
    base = weighted_geometric_mean(values, pol.weights)
    weights_used = _renormalised_weights(values, pol)

    # --- Stage 5: hard caps ----------------------------------------------
    caps: List[AppliedCap] = []
    for code in codes:
        if code in pol.score_caps:
            caps.append(
                AppliedCap(
                    code=code,
                    max_score=pol.score_caps[code],
                    rationale=_cap_rationale(code, pol.score_caps[code]),
                )
            )

    severe_physical = _severe_physical_cap(bundle, pol)
    if severe_physical is not None:
        caps.append(severe_physical)

    capped = base
    for cap in caps:
        capped = min(capped, cap.max_score)
    capped = clamp01(capped)

    # --- Stage 6: thresholds, then decision-class ceilings ---------------
    decision = _threshold_decision(capped, pol)

    for code in codes:
        ceiling = _ceiling_for(code, pol)
        if ceiling is not None:
            decision = worst_of(decision, ceiling)
            if not any(c.code is code for c in caps):
                caps.append(
                    AppliedCap(
                        code=code,
                        max_score=pol.low_risk_threshold,
                        rationale=_ceiling_rationale(code, ceiling),
                    )
                )

    if unavailable:
        notes.append(
            "Weights were renormalised over the dimensions that were available, so this "
            "result carries lower assurance than a complete check."
        )

    return DecisionResult(
        decision=decision,
        presentation_score=capped,
        presentation_score_applicable=True,
        base_score=base,
        identity_score=bundle.identity.score,
        physical_score=bundle.physical.score,
        history_score=bundle.history.score,
        scan_quality=bundle.quality.score,
        reason_codes=order_codes(codes),
        applied_caps=caps,
        product_status=bundle.product,
        verification_level=bundle.identity.resolved.verification_level,
        fusion_policy_version=pol.version,
        weights_used=weights_used,
        notes=notes,
    )


def _unable(
    bundle: EvidenceBundle,
    pol: FusionPolicy,
    codes: List[ReasonCode],
    notes: List[str],
) -> DecisionResult:
    """Build an ``UNABLE_TO_VERIFY`` result.

    Guarantees the contract rule that this decision always carries at least one
    quality or system reason (``docs/API_CONTRACTS.md`` rule 1): if nothing
    explained the gap, ``DEPENDENCY_UNAVAILABLE`` is added so the user is never
    shown an unexplained failure.
    """
    explained = [
        c for c in codes if category_of(c) in (Category.QUALITY, Category.SYSTEM)
    ]
    if not explained:
        codes = list(codes) + [ReasonCode.DEPENDENCY_UNAVAILABLE]

    return DecisionResult(
        decision=Decision.UNABLE_TO_VERIFY,
        presentation_score=0.0,
        presentation_score_applicable=False,
        base_score=0.0,
        identity_score=bundle.identity.score,
        physical_score=bundle.physical.score,
        history_score=bundle.history.score,
        scan_quality=bundle.quality.score,
        reason_codes=order_codes(codes),
        applied_caps=[],
        product_status=bundle.product,
        verification_level=bundle.identity.resolved.verification_level,
        fusion_policy_version=pol.version,
        weights_used={},
        notes=notes,
    )


def _threshold_decision(score: float, pol: FusionPolicy) -> Decision:
    if score >= pol.low_risk_threshold:
        return Decision.LOW_OBSERVED_RISK
    if score >= pol.review_threshold:
        return Decision.REVIEW_REQUIRED
    return Decision.SUSPICIOUS


def _renormalised_weights(values: Dict[str, float], pol: FusionPolicy) -> Dict[str, float]:
    """The effective weights, after dropping unavailable dimensions."""
    raw = {k: float(pol.weights.get(k, 0.0)) for k in values}
    total = sum(raw.values())
    if total <= 0.0:
        return raw
    return {k: round(v / total, 4) for k, v in raw.items()}


def _severe_physical_cap(bundle: EvidenceBundle, pol: FusionPolicy) -> Optional[AppliedCap]:
    """Cap a confidently-measured, severe packaging mismatch.

    Conditioned on registration confidence on purpose. A low physical score
    produced by a failed alignment is a statement about the photograph, not
    about the pack, and capping on it would turn awkward camera angles into
    counterfeit accusations.
    """
    phys = bundle.physical
    if not phys.available:
        return None
    if phys.registration_confidence < pol.severe_physical_registration_floor:
        return None
    if phys.score >= pol.severe_physical_score:
        return None

    failing = [f.name for f in phys.features if not f.ok]
    return AppliedCap(
        code=ReasonCode.STRUCTURAL_MISMATCH,
        max_score=pol.severe_physical_cap,
        rationale=(
            "Packaging evidence scored {:.2f} after a confident alignment "
            "(confidence {:.2f}); failing features: {}.".format(
                phys.score,
                phys.registration_confidence,
                ", ".join(failing) if failing else "none individually",
            )
        ),
    )


def _ceiling_for(code: ReasonCode, pol: FusionPolicy) -> Optional[Decision]:
    """The best decision class ``code`` permits, or ``None`` if it permits any.

    Two sources, most cautious wins: an explicit per-code entry in the policy,
    and the general rule that an actively contradicting authenticity dimension
    rules out a low-risk result.
    """
    explicit = pol.decision_ceilings.get(code)

    general = None
    if (
        category_of(code) in pol.contradiction_categories
        and severity_of(code) >= pol.contradiction_min_severity
    ):
        general = pol.contradiction_ceiling

    if explicit is not None and general is not None:
        return worst_of(explicit, general)
    return explicit if explicit is not None else general


def _cap_rationale(code: ReasonCode, cap: float) -> str:
    return "{} caps the result at {:.2f}: a convincing photograph cannot offset it.".format(
        code.value, cap
    )


def _ceiling_rationale(code: ReasonCode, ceiling: Decision) -> str:
    return "{} prevents a result better than {}.".format(code.value, ceiling.value)


def compare_with_average(bundle: EvidenceBundle, policy: Optional[FusionPolicy] = None) -> Tuple[float, float]:
    """Return ``(geometric, arithmetic)`` base scores for the same evidence.

    Used by the evaluation ablation and by the UI's "why not an average?"
    explanation. Keeping the comparison in the engine means the number shown to
    a judge is computed by the same code that makes the decision, not restated
    by hand.
    """
    from ..util.numeric import arithmetic_mean

    pol = policy or DEFAULT_POLICY
    values: Dict[str, float] = {"identity": bundle.identity.score}
    if bundle.physical.available:
        values["physical"] = bundle.physical.score
    if bundle.history.available:
        values["history"] = bundle.history.score
    return (
        weighted_geometric_mean(values, pol.weights),
        arithmetic_mean(values, pol.weights),
    )


def highest_severity(codes: List[ReasonCode]) -> Severity:
    if not codes:
        return Severity.INFO
    return max(severity_of(c) for c in codes)
