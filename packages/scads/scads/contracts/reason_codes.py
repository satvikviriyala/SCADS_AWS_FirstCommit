"""The reason-code registry.

Reason codes are the authoritative, stable explanation of a SCADS result. The
backend emits codes; the frontend renders language. Prose — including any
optional Bedrock rewrite — may never introduce a code the engine did not
produce, and may never contradict one it did
(``docs/API_CONTRACTS.md`` contract rules 4 and 5).

Renaming a code is a breaking API change.
"""

from enum import Enum
from typing import Dict, List, NamedTuple, Optional

from .enums import StrEnum


class ReasonCode(StrEnum):
    # --- Input / scan quality -------------------------------------------
    IMAGE_TOO_BLURRY = "IMAGE_TOO_BLURRY"
    IMAGE_OVEREXPOSED = "IMAGE_OVEREXPOSED"
    IMAGE_UNDEREXPOSED = "IMAGE_UNDEREXPOSED"
    IMAGE_TOO_SMALL = "IMAGE_TOO_SMALL"
    PACKAGE_OCCLUDED = "PACKAGE_OCCLUDED"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    UNSUPPORTED_PACKAGE_VARIANT = "UNSUPPORTED_PACKAGE_VARIANT"

    # --- Identity --------------------------------------------------------
    IDENTITY_VALID = "IDENTITY_VALID"
    BATCH_VALID = "BATCH_VALID"
    SERIAL_UNKNOWN = "SERIAL_UNKNOWN"
    BATCH_UNKNOWN = "BATCH_UNKNOWN"
    SERIAL_REVOKED = "SERIAL_REVOKED"
    QR_OCR_CONFLICT = "QR_OCR_CONFLICT"
    IDENTITY_PARSE_FAILED = "IDENTITY_PARSE_FAILED"

    # --- Physical packaging ---------------------------------------------
    PHYSICAL_MATCH = "PHYSICAL_MATCH"
    TEXT_CONTENT_MISMATCH = "TEXT_CONTENT_MISMATCH"
    TEXT_LAYOUT_MISMATCH = "TEXT_LAYOUT_MISMATCH"
    STRUCTURAL_MISMATCH = "STRUCTURAL_MISMATCH"
    PRINT_SHARPNESS_MISMATCH = "PRINT_SHARPNESS_MISMATCH"
    COLOR_MISMATCH = "COLOR_MISMATCH"
    COPY_PATTERN_MISMATCH = "COPY_PATTERN_MISMATCH"

    # --- Scan history ----------------------------------------------------
    NO_HISTORY_CONTRADICTION = "NO_HISTORY_CONTRADICTION"
    SERIAL_REUSE = "SERIAL_REUSE"
    IMPOSSIBLE_TRAVEL = "IMPOSSIBLE_TRAVEL"
    POST_SALE_REUSE = "POST_SALE_REUSE"
    SCAN_VELOCITY_ANOMALY = "SCAN_VELOCITY_ANOMALY"
    LIFECYCLE_CONFLICT = "LIFECYCLE_CONFLICT"
    HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"

    # --- Product status (not authenticity) -------------------------------
    PRODUCT_EXPIRED = "PRODUCT_EXPIRED"
    PRODUCT_RECALLED = "PRODUCT_RECALLED"

    # --- System ----------------------------------------------------------
    REFERENCE_NOT_FOUND = "REFERENCE_NOT_FOUND"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


class Category(StrEnum):
    QUALITY = "QUALITY"
    IDENTITY = "IDENTITY"
    PHYSICAL = "PHYSICAL"
    HISTORY = "HISTORY"
    PRODUCT_STATUS = "PRODUCT_STATUS"
    SYSTEM = "SYSTEM"


class Severity(int, Enum):
    """How strongly a code argues against relying on the pack.

    ``INFO`` codes are confirmations (``IDENTITY_VALID``). ``SEVERE`` codes are
    contradictions that a good-looking photograph must not be able to average
    away, and which therefore drive the hard caps in
    :mod:`scads.decision.policy`.
    """

    INFO = 0
    NOTICE = 1
    WARNING = 2
    SEVERE = 3


class ReasonMeta(NamedTuple):
    category: Category
    severity: Severity
    # Consumer-facing sentence. Deterministic: this is the fallback and the
    # ground truth that any generated prose must stay consistent with.
    title: str
    detail: str


_M = ReasonMeta

REASON_META: Dict[ReasonCode, ReasonMeta] = {
    # --- quality ---------------------------------------------------------
    ReasonCode.IMAGE_TOO_BLURRY: _M(
        Category.QUALITY, Severity.WARNING,
        "Photo too blurry to judge",
        "The image did not contain enough fine detail to compare printing. Retake it "
        "in steady light with the pack flat and in focus.",
    ),
    ReasonCode.IMAGE_OVEREXPOSED: _M(
        Category.QUALITY, Severity.WARNING,
        "Too much glare",
        "Bright reflections covered part of the pack. Move away from direct light or "
        "tilt the pack slightly and retake the photo.",
    ),
    ReasonCode.IMAGE_UNDEREXPOSED: _M(
        Category.QUALITY, Severity.WARNING,
        "Photo too dark",
        "The image was too dark to compare printing reliably. Retake it in brighter light.",
    ),
    ReasonCode.IMAGE_TOO_SMALL: _M(
        Category.QUALITY, Severity.WARNING,
        "Pack too small in frame",
        "The pack covered too few pixels to inspect. Move closer so the pack fills most "
        "of the frame.",
    ),
    ReasonCode.PACKAGE_OCCLUDED: _M(
        Category.QUALITY, Severity.WARNING,
        "Part of the pack is hidden",
        "Fingers, shadow or cropping covered areas the check needs. Retake the photo "
        "with the whole front face visible.",
    ),
    ReasonCode.PACKAGE_NOT_FOUND: _M(
        Category.QUALITY, Severity.WARNING,
        "No pack detected",
        "A rectangular medicine pack could not be located in the photo. Place the pack "
        "on a plain background and retake it.",
    ),
    ReasonCode.REGISTRATION_FAILED: _M(
        Category.QUALITY, Severity.WARNING,
        "Could not align the pack",
        "The pack could not be aligned to the enrolled reference artwork, so packaging "
        "comparison was not attempted. This is not evidence for or against the pack.",
    ),
    ReasonCode.UNSUPPORTED_PACKAGE_VARIANT: _M(
        Category.QUALITY, Severity.NOTICE,
        "Packaging variant not enrolled",
        "This packaging layout is not in the reference set, so packaging evidence is "
        "unavailable for it.",
    ),

    # --- identity --------------------------------------------------------
    ReasonCode.IDENTITY_VALID: _M(
        Category.IDENTITY, Severity.INFO,
        "Unit identity recognised",
        "The unit serial on this pack matches an issued record in the registry.",
    ),
    ReasonCode.BATCH_VALID: _M(
        Category.IDENTITY, Severity.NOTICE,
        "Batch recognised, unit not verified",
        "The batch is a real issued batch, but no unit serial was read, so this pack "
        "was not verified as an individual unit.",
    ),
    ReasonCode.SERIAL_UNKNOWN: _M(
        Category.IDENTITY, Severity.SEVERE,
        "Serial not in the registry",
        "The serial read from this pack was never issued by the manufacturer. A pack "
        "that looks correct but carries an unissued serial needs review.",
    ),
    ReasonCode.BATCH_UNKNOWN: _M(
        Category.IDENTITY, Severity.SEVERE,
        "Batch not in the registry",
        "The batch code read from this pack does not correspond to any issued batch.",
    ),
    ReasonCode.SERIAL_REVOKED: _M(
        Category.IDENTITY, Severity.SEVERE,
        "Serial revoked",
        "The manufacturer or regulator has revoked this serial. Do not rely on this pack.",
    ),
    ReasonCode.QR_OCR_CONFLICT: _M(
        Category.IDENTITY, Severity.WARNING,
        "Code and printed text disagree",
        "The data inside the pack's code does not match the text printed on the pack. "
        "On a genuine pack these agree.",
    ),
    ReasonCode.IDENTITY_PARSE_FAILED: _M(
        Category.IDENTITY, Severity.WARNING,
        "No identity could be read",
        "Neither a readable code nor readable batch/serial text was found, so identity "
        "could not be checked.",
    ),

    # --- physical --------------------------------------------------------
    ReasonCode.PHYSICAL_MATCH: _M(
        Category.PHYSICAL, Severity.INFO,
        "Packaging matches the reference",
        "Layout, structure and print characteristics were consistent with the enrolled "
        "reference for this product.",
    ),
    ReasonCode.TEXT_CONTENT_MISMATCH: _M(
        Category.PHYSICAL, Severity.WARNING,
        "Printed wording differs",
        "Fixed wording that should be identical on every pack of this product did not "
        "match the reference.",
    ),
    ReasonCode.TEXT_LAYOUT_MISMATCH: _M(
        Category.PHYSICAL, Severity.WARNING,
        "Text is in the wrong place",
        "Printed text sat measurably away from where it appears on the enrolled "
        "reference artwork.",
    ),
    ReasonCode.STRUCTURAL_MISMATCH: _M(
        Category.PHYSICAL, Severity.WARNING,
        "Artwork structure differs",
        "After aligning the pack to the reference, stable areas of the artwork did not "
        "match structurally.",
    ),
    ReasonCode.PRINT_SHARPNESS_MISMATCH: _M(
        Category.PHYSICAL, Severity.WARNING,
        "Print quality differs",
        "Edge sharpness in printed areas did not match the enrolled reference, which can "
        "indicate a reprinted or photocopied pack.",
    ),
    ReasonCode.COLOR_MISMATCH: _M(
        Category.PHYSICAL, Severity.NOTICE,
        "Colour differs",
        "Colour in stable areas differed from the reference. Lighting and camera white "
        "balance also cause this, so it is treated as weak evidence.",
    ),
    ReasonCode.COPY_PATTERN_MISMATCH: _M(
        Category.PHYSICAL, Severity.SEVERE,
        "Copy-detection pattern failed",
        "The pack's copy-sensitive printed region did not reproduce as an original print "
        "would.",
    ),

    # --- history ---------------------------------------------------------
    ReasonCode.NO_HISTORY_CONTRADICTION: _M(
        Category.HISTORY, Severity.INFO,
        "Scan history consistent",
        "Nothing in this unit's recorded scan history contradicts this scan.",
    ),
    ReasonCode.SERIAL_REUSE: _M(
        Category.HISTORY, Severity.SEVERE,
        "Serial already seen elsewhere",
        "This exact unit serial has already been scanned as a separate pack. A unit "
        "serial is meant to identify one physical pack, so duplicates suggest the code "
        "was copied.",
    ),
    ReasonCode.IMPOSSIBLE_TRAVEL: _M(
        Category.HISTORY, Severity.SEVERE,
        "Same serial too far away, too recently",
        "The same serial was recorded in a distant location too recently for one pack to "
        "have travelled between them.",
    ),
    ReasonCode.POST_SALE_REUSE: _M(
        Category.HISTORY, Severity.SEVERE,
        "Unit was already dispensed",
        "The registry records this unit as already dispensed or decommissioned, so it "
        "should not be appearing as a new pack for sale.",
    ),
    ReasonCode.SCAN_VELOCITY_ANOMALY: _M(
        Category.HISTORY, Severity.WARNING,
        "Unusual scan burst",
        "This serial was scanned from an unusual number of distinct places in a short "
        "window, a pattern consistent with a code copied onto many packs.",
    ),
    ReasonCode.LIFECYCLE_CONFLICT: _M(
        Category.HISTORY, Severity.WARNING,
        "Supply-chain events out of order",
        "Recorded custody events for this unit do not follow a plausible order.",
    ),
    ReasonCode.HISTORY_UNAVAILABLE: _M(
        Category.HISTORY, Severity.WARNING,
        "Scan history could not be read",
        "The scan-history check could not run, so this scan is not backed by history "
        "evidence. Absent history is not treated as clean history.",
    ),

    # --- product status --------------------------------------------------
    ReasonCode.PRODUCT_EXPIRED: _M(
        Category.PRODUCT_STATUS, Severity.WARNING,
        "Past its expiry date",
        "This batch is past its printed expiry date. That is a product-status problem, "
        "separate from whether the pack is authentic. Do not use expired medicine.",
    ),
    ReasonCode.PRODUCT_RECALLED: _M(
        Category.PRODUCT_STATUS, Severity.SEVERE,
        "This batch is recalled",
        "The manufacturer or regulator has recalled this batch. Return it to a pharmacist "
        "rather than using it, whatever the packaging checks say.",
    ),

    # --- system ----------------------------------------------------------
    ReasonCode.REFERENCE_NOT_FOUND: _M(
        Category.SYSTEM, Severity.NOTICE,
        "No enrolled reference for this product",
        "SCADS has no enrolled reference artwork for this product, so packaging could not "
        "be compared. Only identity and history evidence applied.",
    ),
    ReasonCode.ANALYSIS_TIMEOUT: _M(
        Category.SYSTEM, Severity.WARNING,
        "Check timed out",
        "The analysis did not finish in time. Please try again.",
    ),
    ReasonCode.DEPENDENCY_UNAVAILABLE: _M(
        Category.SYSTEM, Severity.WARNING,
        "A check could not run",
        "One of the verification services was unavailable, so this result is incomplete.",
    ),
}


def meta(code: ReasonCode) -> ReasonMeta:
    """Return registry metadata for ``code``.

    Raises ``KeyError`` for an unregistered code. That is intentional: an
    unregistered code must never reach a user, so failing loudly in tests is
    preferable to rendering a bare enum name on the result screen.
    """
    return REASON_META[code]


def severity_of(code: ReasonCode) -> Severity:
    return REASON_META[code].severity


def category_of(code: ReasonCode) -> Category:
    return REASON_META[code].category


# Presentation order of the evidence categories on the result card.
_CATEGORY_ORDER: Dict[Category, int] = {
    Category.IDENTITY: 0,
    Category.PHYSICAL: 1,
    Category.HISTORY: 2,
    Category.PRODUCT_STATUS: 3,
    Category.QUALITY: 4,
    Category.SYSTEM: 5,
}


def order_codes(codes: List[ReasonCode]) -> List[ReasonCode]:
    """Sort reason codes most-actionable-first and de-duplicate.

    Severe contradictions lead, because they are what the user must act on.
    Within equal severity the order is by evidence category then by code name,
    so the same evidence always renders in the same order — a requirement of
    AT-09 (reproducibility) in ``PLAN.md``.
    """
    seen = set()
    unique = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique.append(code)
    return sorted(
        unique,
        key=lambda c: (
            -int(severity_of(c)),
            _CATEGORY_ORDER.get(category_of(c), 99),
            str(c.value),
        ),
    )


def severe_codes(codes: List[ReasonCode]) -> List[ReasonCode]:
    return [c for c in codes if severity_of(c) is Severity.SEVERE]


def has_severe(codes: List[ReasonCode]) -> bool:
    return any(severity_of(c) is Severity.SEVERE for c in codes)


def codes_in(codes: List[ReasonCode], category: Category) -> List[ReasonCode]:
    return [c for c in codes if category_of(c) is category]


def find_unregistered() -> List[str]:
    """Every ``ReasonCode`` must carry metadata. Used by a contract test."""
    return [c.value for c in ReasonCode if c not in REASON_META]
