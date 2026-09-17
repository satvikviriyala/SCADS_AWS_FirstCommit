"""Shared test fixtures and evidence builders.

The builders here default every dimension to "clean and available" so that each
test states only the one thing it is about. A test named
``test_impossible_travel_caps_result`` should contain exactly the history
anomaly and nothing else.
"""

import datetime as _dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "scads"))

from scads.contracts.enums import (  # noqa: E402
    Decision,
    EvidenceState,
    ProductState,
    RecallStatus,
    SerialStatus,
    VerificationLevel,
)
from scads.contracts.models import (  # noqa: E402
    ClaimedIdentity,
    EvidenceBundle,
    HistoryEvidence,
    IdentityEvidence,
    PhysicalEvidence,
    PhysicalFeature,
    ProductStatus,
    QualityReport,
    ResolvedIdentity,
)
from scads.contracts.reason_codes import ReasonCode  # noqa: E402
from scads.util.clock import FixedClock  # noqa: E402

# A fixed "now" so history arithmetic in tests is exact and never flaky.
NOW = _dt.datetime(2026, 9, 18, 10, 0, 0, tzinfo=_dt.timezone.utc)


@pytest.fixture
def clock():
    return FixedClock(NOW)


@pytest.fixture
def repo_root():
    return ROOT


def good_quality(score=0.91):
    return QualityReport(score=score, passed=True, metrics={"blur": 0.9, "exposure": 0.95})


def bad_quality(score=0.20, codes=None):
    return QualityReport(
        score=score,
        passed=False,
        reason_codes=list(codes or [ReasonCode.IMAGE_TOO_BLURRY]),
        metrics={"blur": 0.05},
    )


def valid_identity(score=0.96, serial="ser_demo_a_001"):
    return IdentityEvidence(
        score=score,
        state=EvidenceState.OK,
        resolved=ResolvedIdentity(
            manufacturer_id="mfg_demo_1",
            manufacturer_name="Demo Pharma Ltd",
            sku_id="sku_demo_a",
            product_name="Paracetamol 500 mg",
            batch_id="batch_demo_a1",
            serial_id=serial,
            verification_level=VerificationLevel.UNIT,
            serial_status=SerialStatus.ACTIVE,
            reference_profile_id="ref_demo_a",
        ),
        claimed=ClaimedIdentity(serial=serial, batch="BND-2026-A1", source="QR"),
        reason_codes=[ReasonCode.IDENTITY_VALID],
    )


def unknown_identity(score=0.12, batch_valid=False):
    codes = [ReasonCode.SERIAL_UNKNOWN]
    level = VerificationLevel.NONE
    if batch_valid:
        codes.append(ReasonCode.BATCH_VALID)
        level = VerificationLevel.BATCH
    return IdentityEvidence(
        score=score,
        state=EvidenceState.FAIL,
        resolved=ResolvedIdentity(
            sku_id="sku_demo_a" if batch_valid else None,
            batch_id="batch_demo_a1" if batch_valid else None,
            verification_level=level,
            serial_status=SerialStatus.UNKNOWN,
        ),
        claimed=ClaimedIdentity(serial="SER-NOT-ISSUED-9", source="QR"),
        reason_codes=codes,
    )


def revoked_identity():
    return IdentityEvidence(
        score=0.05,
        state=EvidenceState.FAIL,
        resolved=ResolvedIdentity(
            sku_id="sku_demo_a",
            batch_id="batch_demo_a1",
            serial_id="ser_demo_a_666",
            verification_level=VerificationLevel.UNIT,
            serial_status=SerialStatus.REVOKED,
        ),
        claimed=ClaimedIdentity(serial="ser_demo_a_666", source="QR"),
        reason_codes=[ReasonCode.SERIAL_REVOKED],
    )


def matching_physical(score=0.89, registration=0.88):
    return PhysicalEvidence(
        score=score,
        state=EvidenceState.OK,
        available=True,
        features=[
            PhysicalFeature("text_content", 0.94, 0.20, 0.70, True),
            PhysicalFeature("text_layout", 0.90, 0.25, 0.70, True),
            PhysicalFeature("structure", 0.86, 0.35, 0.65, True),
            PhysicalFeature("print_sharpness", 0.88, 0.20, 0.60, True),
        ],
        reason_codes=[ReasonCode.PHYSICAL_MATCH],
        registration_confidence=registration,
        reference_version="ref_v1",
        reference_profile_id="ref_demo_a",
    )


def mismatched_physical(score=0.22, registration=0.85, codes=None):
    return PhysicalEvidence(
        score=score,
        state=EvidenceState.FAIL,
        available=True,
        features=[
            PhysicalFeature("text_content", 0.62, 0.20, 0.70, False),
            PhysicalFeature("text_layout", 0.28, 0.25, 0.70, False),
            PhysicalFeature("structure", 0.14, 0.35, 0.65, False),
            PhysicalFeature("print_sharpness", 0.31, 0.20, 0.60, False),
        ],
        reason_codes=list(codes or [ReasonCode.STRUCTURAL_MISMATCH, ReasonCode.TEXT_LAYOUT_MISMATCH]),
        registration_confidence=registration,
        reference_version="ref_v1",
        reference_profile_id="ref_demo_a",
    )


def unavailable_physical(codes=None):
    return PhysicalEvidence(
        score=0.0,
        state=EvidenceState.UNKNOWN,
        available=False,
        reason_codes=list(codes or [ReasonCode.REFERENCE_NOT_FOUND]),
        registration_confidence=0.0,
    )


def clean_history(score=0.95):
    return HistoryEvidence(
        score=score,
        state=EvidenceState.OK,
        available=True,
        reason_codes=[ReasonCode.NO_HISTORY_CONTRADICTION],
    )


def contradicted_history(score=0.10, codes=None, findings=None):
    from scads.contracts.models import HistoryFinding

    codes = list(codes or [ReasonCode.SERIAL_REUSE, ReasonCode.IMPOSSIBLE_TRAVEL])
    return HistoryEvidence(
        score=score,
        state=EvidenceState.FAIL,
        available=True,
        reason_codes=codes,
        findings=list(
            findings
            or [
                HistoryFinding(
                    code=c,
                    summary="seeded contradiction for test",
                    evidence={"distance_km": 1739.8, "elapsed_minutes": 58.0},
                )
                for c in codes
            ]
        ),
    )


def unavailable_history():
    return HistoryEvidence(
        score=0.0,
        state=EvidenceState.UNKNOWN,
        available=False,
        reason_codes=[ReasonCode.HISTORY_UNAVAILABLE],
    )


def active_product(expiry="2028-03-31"):
    return ProductStatus(
        state=ProductState.ACTIVE, expiry_date=expiry, recall_status=RecallStatus.NONE
    )


def expired_product(expiry="2025-01-31"):
    return ProductStatus(
        state=ProductState.EXPIRED,
        expiry_date=expiry,
        recall_status=RecallStatus.NONE,
        reason_codes=[ReasonCode.PRODUCT_EXPIRED],
    )


def recalled_product(expiry="2028-03-31"):
    return ProductStatus(
        state=ProductState.RECALLED,
        expiry_date=expiry,
        recall_status=RecallStatus.RECALLED,
        reason_codes=[ReasonCode.PRODUCT_RECALLED],
    )


def bundle(
    quality=None,
    identity=None,
    physical=None,
    history=None,
    product=None,
    system=None,
):
    """Build an evidence bundle that is clean unless a dimension is overridden."""
    return EvidenceBundle(
        quality=quality if quality is not None else good_quality(),
        identity=identity if identity is not None else valid_identity(),
        physical=physical if physical is not None else matching_physical(),
        history=history if history is not None else clean_history(),
        product=product if product is not None else active_product(),
        system_reason_codes=list(system or []),
    )
