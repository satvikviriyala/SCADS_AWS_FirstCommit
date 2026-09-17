"""Contract tests.

These guard the promises in ``docs/API_CONTRACTS.md`` that are easy to break by
accident: an unregistered reason code, a decision that claims safety, or prose
that contradicts the structured result.
"""

import pytest

from conftest import (
    bad_quality,
    bundle,
    contradicted_history,
    expired_product,
    mismatched_physical,
    recalled_product,
    revoked_identity,
    unavailable_history,
    unavailable_physical,
    unknown_identity,
)
from scads.contracts.enums import Decision, EvidenceState, VerificationLevel
from scads.contracts.reason_codes import (
    REASON_META,
    Category,
    ReasonCode,
    Severity,
    find_unregistered,
    order_codes,
)
from scads.decision import decide, summarise
from scads.decision.explain import CHEMICAL_LIMITATION, assurance_note

ALL_BUNDLES = [
    ("clean", bundle()),
    ("tampered", bundle(physical=mismatched_physical())),
    ("cloned", bundle(history=contradicted_history())),
    ("revoked", bundle(identity=revoked_identity())),
    ("unknown_serial", bundle(identity=unknown_identity())),
    ("blurred", bundle(quality=bad_quality())),
    ("expired", bundle(product=expired_product())),
    ("recalled", bundle(product=recalled_product())),
    ("no_reference", bundle(physical=unavailable_physical())),
    ("no_history", bundle(history=unavailable_history())),
]


def test_every_reason_code_has_registry_metadata():
    """An unregistered code would render as a bare enum name to a user."""
    assert find_unregistered() == []


def test_reason_metadata_is_complete_and_sane():
    for code, m in REASON_META.items():
        assert m.title and m.title[0].isupper(), code
        assert m.detail and m.detail.endswith("."), code
        assert isinstance(m.category, Category), code
        assert isinstance(m.severity, Severity), code
        # Titles are UI-sized; long ones wrap badly on a phone.
        assert len(m.title) <= 48, (code, len(m.title))


def test_confirmation_codes_are_informational_only():
    """A confirmation must never carry weight that could cap a result."""
    for code in (
        ReasonCode.IDENTITY_VALID,
        ReasonCode.PHYSICAL_MATCH,
        ReasonCode.NO_HISTORY_CONTRADICTION,
    ):
        assert REASON_META[code].severity is Severity.INFO


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_no_result_ever_claims_safety_or_genuineness(name, b):
    """The safety-language invariant, checked over every scenario shape.

    ``CLAUDE.md`` forbids asserting a pack is genuine or safe to consume from a
    phone scan. This test reads all rendered prose for such a claim.
    """
    result = decide(b)
    rendered = summarise(b, result)

    text = " ".join(
        [
            str(rendered["headline"]),
            str(rendered["next_action"]),
            str(rendered["limitation"]),
            str(rendered["assurance_note"]),
            str(rendered["product_status_note"] or ""),
        ]
        + [r["title"] + " " + r["detail"] for r in rendered["reasons"]]
        + [d["headline"] for d in rendered["dimensions"]]
    ).lower()

    for forbidden in (
        "100% genuine",
        "safe to consume",
        "safe to use",
        "chemically genuine",
        "chemical authenticity verified",
        "guaranteed authentic",
        "certified genuine",
        "proven genuine",
        "is genuine",
        "definitely fake",
        "confirmed counterfeit",
    ):
        assert forbidden not in text, (name, forbidden)


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_every_result_states_the_chemical_limitation(name, b):
    result = decide(b)
    assert summarise(b, result)["limitation"] == CHEMICAL_LIMITATION


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_decision_is_always_one_of_the_four_classes(name, b):
    assert decide(b).decision in set(Decision)


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_severe_contradiction_never_returns_low_observed_risk(name, b):
    """``docs/API_CONTRACTS.md`` contract rule 2."""
    result = decide(b)
    severe = [c for c in result.reason_codes if REASON_META[c].severity is Severity.SEVERE]
    severe_authenticity = [
        c
        for c in severe
        if REASON_META[c].category in (Category.IDENTITY, Category.PHYSICAL, Category.HISTORY)
    ]
    if severe_authenticity:
        assert result.decision is not Decision.LOW_OBSERVED_RISK, (name, severe_authenticity)


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_unable_to_verify_implies_no_presentation_score(name, b):
    result = decide(b)
    if result.decision is Decision.UNABLE_TO_VERIFY:
        assert not result.presentation_score_applicable


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_result_card_always_shows_three_dimensions(name, b):
    """A dimension that was not checked must say so rather than be omitted."""
    result = decide(b)
    dims = summarise(b, result)["dimensions"]
    assert [d["key"] for d in dims] == ["identity", "physical", "history"]
    for d in dims:
        if not d["available"]:
            assert d["state"] == EvidenceState.UNKNOWN.value
            assert d["score"] is None
            assert d["headline"]


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_prose_never_contradicts_the_structured_codes(name, b):
    """AT-08: explanation consistency.

    Every rendered reason must correspond to a code the engine emitted, and
    every emitted code must be rendered. Neither direction may drift.
    """
    result = decide(b)
    rendered = summarise(b, result)
    rendered_codes = [r["code"] for r in rendered["reasons"]]
    assert rendered_codes == [c.value for c in result.reason_codes]
    assert set(rendered_codes) == {c.value for c in result.reason_codes}


@pytest.mark.parametrize("name,b", ALL_BUNDLES, ids=[n for n, _ in ALL_BUNDLES])
def test_primary_reasons_are_a_subset_of_all_reasons(name, b):
    result = decide(b)
    rendered = summarise(b, result)
    all_codes = {r["code"] for r in rendered["reasons"]}
    assert {r["code"] for r in rendered["primary_reasons"]} <= all_codes


def test_batch_level_assurance_language_differs_from_unit_level():
    """``phases/PHASE_2_IDENTITY.md``: batch-only must not borrow unit language."""
    unit = assurance_note(VerificationLevel.UNIT)
    batch = assurance_note(VerificationLevel.BATCH)
    assert unit != batch
    assert "individual unit" in unit
    assert "weaker evidence" in batch


def test_order_codes_is_stable_and_idempotent():
    codes = [
        ReasonCode.PHYSICAL_MATCH,
        ReasonCode.IMPOSSIBLE_TRAVEL,
        ReasonCode.IDENTITY_VALID,
        ReasonCode.PRODUCT_EXPIRED,
        ReasonCode.SERIAL_REUSE,
    ]
    once = order_codes(codes)
    assert once == order_codes(once)
    assert once == order_codes(list(reversed(codes)))
