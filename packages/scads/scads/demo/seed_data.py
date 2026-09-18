"""The demo registry, as pure data.

One definition, used by three consumers: the offline unit tests, the AWS seed
script, and the fixture generator. Sharing it means a scenario that passes
locally is backed by exactly the records that exist in the deployed stack —
divergence between test fixtures and demo data is a classic way for a
rehearsed demo to fail live.

Two products are enrolled deliberately. A single-product demo cannot
distinguish a working comparison pipeline from one hard-coded to one pack
(``docs/DATA_MODEL.md`` section 10).
"""

from typing import Dict, List, Optional

from ..contracts.enums import ProductState, RecallStatus, SerialStatus
from ..contracts.records import (
    BatchRecord,
    ManufacturerRecord,
    OcrAnchor,
    ReferenceProfile,
    RoiSpec,
    SerialRecord,
    SkuRecord,
)
from ..identity.qr import build_demo_payload

# Re-exported from contracts.records, which is where the field lives.
from ..contracts.records import DEMO_TAG  # noqa: F401

REFERENCE_VERSION = "ref_v1"

MANUFACTURER = ManufacturerRecord(
    manufacturer_id="mfg_demo_1",
    name="Demo Pharma Ltd",
    country="IN",
    licence_number="DEMO-MFG-0001",
)

SKU_A = SkuRecord(
    sku_id="sku_demo_a",
    manufacturer_id="mfg_demo_1",
    product_name="Paracetamol 500 mg",
    generic_name="Paracetamol",
    strength="500 mg",
    form="Tablet",
    gtin="08901234567890",
    reference_profile_id="ref_demo_a",
)

SKU_B = SkuRecord(
    sku_id="sku_demo_b",
    manufacturer_id="mfg_demo_1",
    product_name="Amoxicillin 250 mg",
    generic_name="Amoxicillin",
    strength="250 mg",
    form="Capsule",
    gtin="08901234567906",
    reference_profile_id="ref_demo_b",
)

BATCHES: List[BatchRecord] = [
    BatchRecord(
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        batch_code="BND-2026-A1",
        mfg_date="2026-04-01",
        expiry_date="2028-03-31",
        state=ProductState.ACTIVE,
        recall_status=RecallStatus.NONE,
    ),
    # Expired but genuine: proves expiry is reported as product status rather
    # than mislabelled as counterfeit evidence (AT-07).
    BatchRecord(
        batch_id="batch_demo_a2",
        sku_id="sku_demo_a",
        batch_code="BND-2024-A2",
        mfg_date="2024-01-01",
        expiry_date="2025-06-30",
        state=ProductState.ACTIVE,
        recall_status=RecallStatus.NONE,
    ),
    # Recalled batch: product status again, separate from authenticity.
    BatchRecord(
        batch_id="batch_demo_a3",
        sku_id="sku_demo_a",
        batch_code="BND-2026-A3",
        mfg_date="2026-02-01",
        expiry_date="2028-01-31",
        state=ProductState.RECALLED,
        recall_status=RecallStatus.RECALLED,
    ),
    BatchRecord(
        batch_id="batch_demo_b1",
        sku_id="sku_demo_b",
        batch_code="BND-2026-B1",
        mfg_date="2026-05-15",
        expiry_date="2028-05-31",
        state=ProductState.ACTIVE,
        recall_status=RecallStatus.NONE,
    ),
]

SERIALS: List[SerialRecord] = [
    # Scenario A — the clean pack.
    SerialRecord(
        serial_id="ser_demo_a_001",
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-001",
        status=SerialStatus.ACTIVE,
        issued_at="2026-04-01T08:00:00Z",
        reference_profile_id="ref_demo_a",
    ),
    # Scenario B — same valid identity, tampered packaging image.
    SerialRecord(
        serial_id="ser_demo_a_002",
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-002",
        status=SerialStatus.ACTIVE,
        issued_at="2026-04-01T08:00:01Z",
        reference_profile_id="ref_demo_a",
    ),
    # Scenario C — a perfectly valid, perfectly printed unit whose serial has
    # been copied. The registry cannot tell; the history can.
    SerialRecord(
        serial_id="ser_demo_a_clone",
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-777",
        status=SerialStatus.ACTIVE,
        issued_at="2026-04-01T08:00:02Z",
        reference_profile_id="ref_demo_a",
        notes="demo: prior scan event seeded in a distant location",
    ),
    SerialRecord(
        serial_id="ser_demo_a_revoked",
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-666",
        status=SerialStatus.REVOKED,
        issued_at="2026-04-01T08:00:03Z",
        reference_profile_id="ref_demo_a",
    ),
    SerialRecord(
        serial_id="ser_demo_a_dispensed",
        batch_id="batch_demo_a1",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-555",
        status=SerialStatus.DISPENSED,
        issued_at="2026-04-01T08:00:04Z",
        dispensed_at="2026-08-20T11:30:00Z",
        reference_profile_id="ref_demo_a",
    ),
    SerialRecord(
        serial_id="ser_demo_a_expired",
        batch_id="batch_demo_a2",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-900",
        status=SerialStatus.ACTIVE,
        issued_at="2024-01-05T08:00:00Z",
        reference_profile_id="ref_demo_a",
    ),
    SerialRecord(
        serial_id="ser_demo_a_recalled",
        batch_id="batch_demo_a3",
        sku_id="sku_demo_a",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-A-910",
        status=SerialStatus.ACTIVE,
        issued_at="2026-02-05T08:00:00Z",
        reference_profile_id="ref_demo_a",
    ),
    SerialRecord(
        serial_id="ser_demo_b_001",
        batch_id="batch_demo_b1",
        sku_id="sku_demo_b",
        manufacturer_id="mfg_demo_1",
        serial_code="SER-B-001",
        status=SerialStatus.ACTIVE,
        issued_at="2026-05-15T08:00:00Z",
        reference_profile_id="ref_demo_b",
    ),
]

MANUFACTURERS = [MANUFACTURER]
SKUS = [SKU_A, SKU_B]


def _reference_profile(
    profile_id: str, sku_id: str, variant: str, aspect: float
) -> ReferenceProfile:
    """Build a reference profile for a demo pack.

    The ROI layout mirrors how the fixture generator draws the carton. Regions
    carrying the batch overprint and the QR are marked ``dynamic``: they
    legitimately differ between two genuine packs of the same product, and
    including them in a structural comparison would make every real pack look
    tampered (``docs/SCORING_AND_DETECTION.md`` section 6.3).
    """
    return ReferenceProfile(
        reference_profile_id=profile_id,
        sku_id=sku_id,
        packaging_variant=variant,
        version=REFERENCE_VERSION,
        image_s3_key="references/" + sku_id + "/" + REFERENCE_VERSION + "/front.png",
        aspect_ratio=aspect,
        canonical_width=900,
        canonical_height=520,
        stable_rois=[
            RoiSpec("brand_block", 0.04, 0.05, 0.56, 0.22, weight=1.4),
            RoiSpec("generic_line", 0.04, 0.29, 0.52, 0.11, weight=1.0),
            RoiSpec("strength_block", 0.04, 0.42, 0.34, 0.13, weight=1.1),
            RoiSpec("manufacturer_block", 0.04, 0.74, 0.50, 0.20, weight=0.9),
            RoiSpec("logo_mark", 0.66, 0.05, 0.28, 0.22, weight=1.2),
            RoiSpec("warning_strip", 0.04, 0.58, 0.52, 0.12, weight=0.8),
            # Excluded from structural comparison. These must not overlap any
            # static region: a legitimate batch change would otherwise alter a
            # region that is being compared, and every genuine pack from a new
            # batch would look tampered. tests/unit/test_physical.py asserts the
            # separation.
            RoiSpec("batch_overprint", 0.60, 0.60, 0.36, 0.18, dynamic=True),
            RoiSpec("qr_zone", 0.60, 0.30, 0.34, 0.28, dynamic=True),
        ],
        ocr_anchors=[],  # populated per product below
        feature_baselines={},
    )


# Templates carry the geometry and ROI layout. Anchor positions are *measured*
# from the rendered artwork at enrollment time rather than written by hand —
# see :mod:`scads.demo.enroll` for why guessed coordinates cannot work.
REFERENCE_TEMPLATE_A = _reference_profile("ref_demo_a", "sku_demo_a", "CARTON_FRONT_v1", 900 / 520)
REFERENCE_TEMPLATE_B = _reference_profile("ref_demo_b", "sku_demo_b", "CARTON_FRONT_v1", 900 / 520)

REFERENCE_TEMPLATES = [REFERENCE_TEMPLATE_A, REFERENCE_TEMPLATE_B]

_ENROLLED_CACHE: Optional[List[ReferenceProfile]] = None


def reference_profiles() -> List[ReferenceProfile]:
    """The enrolled reference profiles, with measured anchor positions.

    Cached: enrollment renders the artwork, which is not free, and the result is
    deterministic for a given template.
    """
    global _ENROLLED_CACHE
    if _ENROLLED_CACHE is None:
        from .enroll import enroll_all

        _ENROLLED_CACHE = enroll_all(REFERENCE_TEMPLATES, SKUS, BATCHES)
    return list(_ENROLLED_CACHE)


def reference_profile_by_id(reference_profile_id: str) -> ReferenceProfile:
    for profile in reference_profiles():
        if profile.reference_profile_id == reference_profile_id:
            return profile
    raise KeyError(reference_profile_id)


def serial_by_id(serial_id: str) -> SerialRecord:
    for record in SERIALS:
        if record.serial_id == serial_id:
            return record
    raise KeyError(serial_id)


def batch_by_id(batch_id: str) -> BatchRecord:
    for record in BATCHES:
        if record.batch_id == batch_id:
            return record
    raise KeyError(batch_id)


def sku_by_id(sku_id: str) -> SkuRecord:
    for record in SKUS:
        if record.sku_id == sku_id:
            return record
    raise KeyError(sku_id)


def build_qr_payload(
    serial_code: str,
    batch_code: str,
    gtin=None,
    expiry=None,
    product=None,
) -> str:
    """Build a pack QR payload from explicit field values.

    Separate from :func:`qr_payload_for` so a fixture can encode a serial that
    differs from what is printed on the carton — the QR-versus-print conflict
    case — without inventing a registry record for it.
    """
    return build_demo_payload(
        serial=serial_code,
        batch=batch_code,
        gtin=gtin,
        expiry=expiry,
        product=product,
        manufacturer=MANUFACTURER.name,
    )


def qr_payload_for(serial_id: str) -> str:
    """The QR payload printed on a demo pack."""
    serial = serial_by_id(serial_id)
    batch = batch_by_id(serial.batch_id)
    sku = sku_by_id(serial.sku_id)
    return build_demo_payload(
        serial=serial.serial_code,
        batch=batch.batch_code,
        gtin=sku.gtin,
        expiry=batch.expiry_date,
        product=sku.product_name,
        manufacturer=MANUFACTURER.name,
    )


def seed_registry(writer) -> Dict[str, int]:
    """Write the demo registry through a :class:`RegistryWriter`."""
    for manufacturer in MANUFACTURERS:
        writer.put_manufacturer(manufacturer)
    for sku in SKUS:
        writer.put_sku(sku)
    for batch in BATCHES:
        writer.put_batch(batch)
    for serial in SERIALS:
        writer.put_serial(serial)
    return {
        "manufacturers": len(MANUFACTURERS),
        "skus": len(SKUS),
        "batches": len(BATCHES),
        "serials": len(SERIALS),
    }


def seed_reference_profiles(writer) -> int:
    """Enroll the demo reference profiles through a :class:`RegistryWriter`."""
    profiles = reference_profiles()
    for profile in profiles:
        writer.put_reference_profile(profile)
    return len(profiles)
