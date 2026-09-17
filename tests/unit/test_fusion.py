"""Acceptance tests for the decision engine (``PLAN.md`` section 4, AT-01..AT-10).

Each test here corresponds to a named architecture acceptance test or to a
required fusion test in ``docs/EVALUATION.md`` section 6.
"""

import pytest

from conftest import (
    active_product,
    bad_quality,
    bundle,
    clean_history,
    contradicted_history,
    expired_product,
    good_quality,
    matching_physical,
    mismatched_physical,
    recalled_product,
    revoked_identity,
    unavailable_history,
    unavailable_physical,
    unknown_identity,
    valid_identity,
)
from scads.contracts.enums import Decision, VerificationLevel
from scads.contracts.reason_codes import Category, ReasonCode, category_of
from scads.decision import DEFAULT_POLICY, compare_with_average, decide
from scads.decision.policy import FusionPolicy
from scads.util.numeric import InvalidScore


# --- AT-01 valid pack ---------------------------------------------------


def test_at01_clean_pack_is_low_observed_risk():
    """A valid identity, matching packaging and clean history is not suspicious."""
    result = decide(bundle())
    assert result.decision is Decision.LOW_OBSERVED_RISK
    assert result.presentation_score_applicable
    assert ReasonCode.IDENTITY_VALID in result.reason_codes
    assert ReasonCode.PHYSICAL_MATCH in result.reason_codes
    assert ReasonCode.NO_HISTORY_CONTRADICTION in result.reason_codes
    assert result.applied_caps == []


def test_clean_pack_keeps_dimensions_separate():
    """The three dimensions survive to the result; no single trust score."""
    result = decide(bundle())
    assert result.identity_score == pytest.approx(0.96)
    assert result.physical_score == pytest.approx(0.89)
    assert result.history_score == pytest.approx(0.95)
    assert result.scan_quality == pytest.approx(0.91)
    # And the presentation score is derived, never a substitute for them.
    assert result.presentation_score < max(
        result.identity_score, result.physical_score, result.history_score
    )


# --- AT-02 unknown identity ---------------------------------------------


def test_at02_unknown_serial_cannot_be_rescued_by_perfect_image():
    """A flawless photograph must not launder an unissued serial."""
    result = decide(
        bundle(identity=unknown_identity(), physical=matching_physical(score=0.99, registration=0.97))
    )
    assert result.decision is not Decision.LOW_OBSERVED_RISK
    assert ReasonCode.SERIAL_UNKNOWN in result.reason_codes


def test_unknown_serial_with_valid_batch_degrades_to_batch_assurance():
    """Falling back to batch level must be explicit, not silent."""
    result = decide(bundle(identity=unknown_identity(batch_valid=True, score=0.45)))
    assert result.decision in (Decision.REVIEW_REQUIRED, Decision.SUSPICIOUS)
    assert result.verification_level is VerificationLevel.BATCH
    assert ReasonCode.SERIAL_UNKNOWN in result.reason_codes
    assert ReasonCode.BATCH_VALID in result.reason_codes


# --- AT-03 visual tamper ------------------------------------------------


def test_at03_known_identity_cannot_mask_strong_physical_mismatch():
    """Scenario B: same valid serial, tampered packaging."""
    result = decide(bundle(physical=mismatched_physical(score=0.22, registration=0.85)))
    assert result.decision is Decision.SUSPICIOUS
    assert ReasonCode.IDENTITY_VALID in result.reason_codes
    assert ReasonCode.STRUCTURAL_MISMATCH in result.reason_codes
    assert any(c.code is ReasonCode.STRUCTURAL_MISMATCH for c in result.applied_caps)


def test_moderate_physical_mismatch_is_review_not_suspicious():
    """A marginal packaging difference should ask for review, not accuse."""
    result = decide(bundle(physical=mismatched_physical(score=0.55, registration=0.85)))
    assert result.decision is Decision.REVIEW_REQUIRED


def test_low_physical_score_from_poor_alignment_is_not_accused():
    """A mismatch measured through a bad alignment says nothing about the pack.

    The aggressive severe-physical score cap is conditioned on registration
    confidence precisely so that camera geometry cannot manufacture an
    accusation. The cautious ceiling still applies — a reported mismatch is not
    called low risk — but the outcome is "review", not "suspicious".
    """
    poor = decide(bundle(physical=mismatched_physical(score=0.20, registration=0.30)))
    confident = decide(bundle(physical=mismatched_physical(score=0.20, registration=0.85)))

    severe_cap = DEFAULT_POLICY.severe_physical_cap
    assert not any(c.max_score == severe_cap for c in poor.applied_caps)
    assert any(c.max_score == severe_cap for c in confident.applied_caps)

    assert poor.decision is Decision.REVIEW_REQUIRED
    assert confident.decision is Decision.SUSPICIOUS


# --- AT-04 quality failure ----------------------------------------------


def test_at04_low_quality_returns_unable_to_verify_not_suspicious():
    """A blurred photo of a genuine pack must never be reported as a fake."""
    result = decide(bundle(quality=bad_quality()))
    assert result.decision is Decision.UNABLE_TO_VERIFY
    assert not result.presentation_score_applicable
    assert ReasonCode.IMAGE_TOO_BLURRY in result.reason_codes


def test_unable_to_verify_always_carries_a_quality_or_system_reason():
    """``docs/API_CONTRACTS.md`` contract rule 1."""
    result = decide(bundle(quality=bad_quality(score=0.1, codes=[])))
    assert result.decision is Decision.UNABLE_TO_VERIFY
    assert any(
        category_of(c) in (Category.QUALITY, Category.SYSTEM) for c in result.reason_codes
    )


def test_quality_gate_runs_before_fusion():
    """Even excellent identity and packaging cannot promote an unjudgeable scan."""
    result = decide(
        bundle(
            quality=bad_quality(),
            identity=valid_identity(score=0.99),
            physical=matching_physical(score=0.99),
        )
    )
    assert result.decision is Decision.UNABLE_TO_VERIFY


def test_registry_contradiction_survives_a_bad_photograph():
    """A revoked serial is revoked whether or not the picture is sharp.

    Returning UNABLE_TO_VERIFY here would hide decisive, image-independent
    evidence behind a camera problem.
    """
    result = decide(bundle(quality=bad_quality(), identity=revoked_identity()))
    assert result.decision is Decision.SUSPICIOUS
    assert ReasonCode.SERIAL_REVOKED in result.reason_codes


# --- AT-05 / AT-06 cloned serial and impossible travel -------------------


def test_at05_at06_perfect_pack_with_cloned_serial_is_suspicious():
    """Scenario C: the demo's central claim.

    Valid registry identity, excellent packaging match, but the same serial was
    recorded far away minutes earlier. A QR-existence check passes this pack;
    SCADS must not.
    """
    result = decide(
        bundle(
            identity=valid_identity(score=0.97),
            physical=matching_physical(score=0.94, registration=0.93),
            history=contradicted_history(score=0.10),
        )
    )
    assert result.decision is Decision.SUSPICIOUS
    assert ReasonCode.IDENTITY_VALID in result.reason_codes
    assert ReasonCode.PHYSICAL_MATCH in result.reason_codes
    assert ReasonCode.SERIAL_REUSE in result.reason_codes
    assert ReasonCode.IMPOSSIBLE_TRAVEL in result.reason_codes
    assert result.presentation_score <= DEFAULT_POLICY.score_caps[ReasonCode.IMPOSSIBLE_TRAVEL]


def test_history_cap_applies_even_when_other_dimensions_are_near_perfect():
    """``docs/EVALUATION.md``: the hard cap always applies."""
    result = decide(
        bundle(
            identity=valid_identity(score=0.99),
            physical=matching_physical(score=0.99, registration=0.99),
            history=contradicted_history(score=0.99, codes=[ReasonCode.IMPOSSIBLE_TRAVEL]),
        )
    )
    assert result.decision is Decision.SUSPICIOUS
    assert result.presentation_score <= 0.25


def test_geometric_fusion_beats_averaging_on_the_clone_scenario():
    """The headline argument for product-of-experts fusion, computed not asserted.

    With identity and packaging near-perfect and history near-zero, a weighted
    average still clears the low-risk threshold. The geometric mean does not.
    """
    b = bundle(
        identity=valid_identity(score=0.99),
        physical=matching_physical(score=0.99, registration=0.95),
        history=contradicted_history(score=0.10),
    )
    geometric, arithmetic = compare_with_average(b)
    assert arithmetic >= DEFAULT_POLICY.low_risk_threshold
    assert geometric < DEFAULT_POLICY.low_risk_threshold
    assert geometric < arithmetic


# --- AT-07 product status is separate ------------------------------------


def test_at07_expiry_does_not_become_counterfeit_evidence():
    """An expired pack can be entirely genuine."""
    clean = decide(bundle())
    expired = decide(bundle(product=expired_product()))

    assert expired.decision is Decision.LOW_OBSERVED_RISK
    assert expired.product_status.state.value == "EXPIRED"
    assert ReasonCode.PRODUCT_EXPIRED in expired.reason_codes
    # Authenticity dimensions are untouched by expiry.
    assert expired.identity_score == clean.identity_score
    assert expired.physical_score == clean.physical_score
    assert expired.presentation_score == pytest.approx(clean.presentation_score)


def test_recall_forces_review_without_touching_authenticity_scores():
    """A recalled batch needs action, but recall is not counterfeit evidence."""
    clean = decide(bundle())
    recalled = decide(bundle(product=recalled_product()))
    assert recalled.decision is Decision.REVIEW_REQUIRED
    assert ReasonCode.PRODUCT_RECALLED in recalled.reason_codes
    assert recalled.physical_score == clean.physical_score
    assert recalled.identity_score == clean.identity_score


# --- Missing evidence is not good evidence -------------------------------


def test_unavailable_history_is_not_treated_as_clean_history():
    """``docs/AWS_DEPLOYMENT.md`` section 11: never silently return H=1."""
    result = decide(bundle(history=unavailable_history()))
    assert result.decision is not Decision.LOW_OBSERVED_RISK
    assert ReasonCode.HISTORY_UNAVAILABLE in result.reason_codes
    assert "history" not in result.weights_used


def test_unavailable_history_renormalises_remaining_weights():
    result = decide(bundle(history=unavailable_history()))
    assert set(result.weights_used) == {"identity", "physical"}
    assert sum(result.weights_used.values()) == pytest.approx(1.0, abs=1e-3)


def test_missing_reference_returns_unable_to_verify():
    """No enrolled artwork means packaging was not checked, not that it passed."""
    result = decide(bundle(physical=unavailable_physical()))
    assert result.decision is Decision.UNABLE_TO_VERIFY
    assert ReasonCode.REFERENCE_NOT_FOUND in result.reason_codes


def test_missing_reference_still_reports_a_history_contradiction():
    """An absent reference must not bury a decisive history finding."""
    result = decide(
        bundle(physical=unavailable_physical(), history=contradicted_history())
    )
    assert result.decision is Decision.SUSPICIOUS
    assert ReasonCode.IMPOSSIBLE_TRAVEL in result.reason_codes


# --- Caps, ordering, determinism ----------------------------------------


def test_revoked_serial_caps_hardest():
    result = decide(bundle(identity=revoked_identity()))
    assert result.decision is Decision.SUSPICIOUS
    assert result.presentation_score <= DEFAULT_POLICY.score_caps[ReasonCode.SERIAL_REVOKED]


def test_applied_caps_are_recorded_with_a_rationale():
    """AT-10: a stored result must explain itself without re-running anything."""
    result = decide(bundle(history=contradicted_history()))
    assert result.applied_caps
    for cap in result.applied_caps:
        assert cap.rationale
        assert 0.0 <= cap.max_score <= 1.0


def test_reason_codes_are_ordered_most_severe_first():
    result = decide(
        bundle(identity=valid_identity(), history=contradicted_history(), product=expired_product())
    )
    codes = result.reason_codes
    assert codes[0] in (ReasonCode.SERIAL_REUSE, ReasonCode.IMPOSSIBLE_TRAVEL)
    assert codes.index(ReasonCode.PRODUCT_EXPIRED) < codes.index(ReasonCode.IDENTITY_VALID)


def test_reason_codes_are_deduplicated():
    result = decide(
        bundle(
            physical=mismatched_physical(
                codes=[ReasonCode.STRUCTURAL_MISMATCH, ReasonCode.STRUCTURAL_MISMATCH]
            )
        )
    )
    assert result.reason_codes.count(ReasonCode.STRUCTURAL_MISMATCH) == 1


def test_at09_same_evidence_yields_same_decision():
    """Reproducibility: decide() is pure."""
    b = bundle(history=contradicted_history())
    runs = [decide(b) for _ in range(5)]
    assert len({r.decision for r in runs}) == 1
    assert len({round(r.presentation_score, 12) for r in runs}) == 1
    assert len({tuple(r.reason_codes) for r in runs}) == 1


def test_at10_result_records_the_policy_that_judged_it():
    result = decide(bundle())
    assert result.fusion_policy_version == DEFAULT_POLICY.version
    assert result.weights_used


def test_policy_version_is_carried_through_a_custom_policy():
    strict = FusionPolicy(version="fusion_test_strict", low_risk_threshold=0.99)
    result = decide(bundle(), policy=strict)
    assert result.fusion_policy_version == "fusion_test_strict"
    assert result.decision is Decision.REVIEW_REQUIRED


# --- Threshold boundaries and numeric hygiene ----------------------------


@pytest.mark.parametrize(
    "identity_score,physical_score,history_score,expected",
    [
        (0.99, 0.99, 0.99, Decision.LOW_OBSERVED_RISK),
        (0.90, 0.85, 0.80, Decision.LOW_OBSERVED_RISK),
        (0.70, 0.60, 0.65, Decision.REVIEW_REQUIRED),
        (0.40, 0.40, 0.40, Decision.SUSPICIOUS),
    ],
)
def test_threshold_bands(identity_score, physical_score, history_score, expected):
    result = decide(
        bundle(
            identity=valid_identity(score=identity_score),
            # Keep registration low so the conditional severe-physical cap does
            # not fire; this test is about the threshold bands alone.
            physical=matching_physical(score=physical_score, registration=0.50),
            history=clean_history(score=history_score),
        )
    )
    assert result.decision is expected


def test_exact_threshold_boundary_is_inclusive():
    """A score exactly at a threshold takes the better band, deterministically."""
    policy = FusionPolicy(version="fusion_test_boundary", low_risk_threshold=0.5, review_threshold=0.2)
    at_boundary = decide(
        bundle(
            identity=valid_identity(score=0.5),
            physical=matching_physical(score=0.5, registration=0.50),
            history=clean_history(score=0.5),
        ),
        policy=policy,
    )
    assert at_boundary.presentation_score == pytest.approx(0.5)
    assert at_boundary.decision is Decision.LOW_OBSERVED_RISK


def test_scores_out_of_range_are_rejected_at_construction():
    with pytest.raises(InvalidScore):
        valid_identity(score=1.5)
    with pytest.raises(InvalidScore):
        good_quality(score=-0.1)


def test_nan_score_is_rejected():
    with pytest.raises(InvalidScore):
        good_quality(score=float("nan"))


def test_presentation_score_is_always_in_range():
    for b in (
        bundle(),
        bundle(identity=revoked_identity()),
        bundle(quality=bad_quality()),
        bundle(history=contradicted_history()),
        bundle(physical=unavailable_physical()),
    ):
        result = decide(b)
        assert 0.0 <= result.presentation_score <= 1.0
