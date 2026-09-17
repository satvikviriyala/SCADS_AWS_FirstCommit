"""Closed enumerations that form part of the public API contract.

These strings are wire values. Renaming one is a breaking change; see
``docs/API_CONTRACTS.md``.
"""

from enum import Enum


class StrEnum(str, Enum):
    """``str``-valued enum that serialises to its value.

    Python 3.11 has ``enum.StrEnum``; SCADS targets 3.9 locally so we define the
    minimal equivalent.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class Decision(StrEnum):
    """The only four result classes SCADS is permitted to emit.

    Deliberately absent: anything asserting the medicine is genuine, safe or
    chemically verified. A packaging scan cannot support such a claim
    (``docs/SECURITY_PRIVACY.md`` section 8).
    """

    LOW_OBSERVED_RISK = "LOW_OBSERVED_RISK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUSPICIOUS = "SUSPICIOUS"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"


class VerificationLevel(StrEnum):
    """How specifically the pack's identity was resolved.

    ``UNIT`` means a unique serial was matched. ``BATCH`` means only the batch
    was matched, which is a materially weaker claim and must be surfaced as
    such rather than presented with unit-level language.
    """

    NONE = "NONE"
    PRODUCT = "PRODUCT"
    BATCH = "BATCH"
    UNIT = "UNIT"


class ProductState(StrEnum):
    """Lifecycle state of the product itself, independent of authenticity.

    An expired pack can be entirely authentic. Never fold this into the
    authenticity dimensions.
    """

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


class RecallStatus(StrEnum):
    NONE = "NONE"
    RECALLED = "RECALLED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UNKNOWN = "UNKNOWN"


class SerialStatus(StrEnum):
    """Registry status of a unit serial."""

    ACTIVE = "ACTIVE"
    DISPENSED = "DISPENSED"
    DECOMMISSIONED = "DECOMMISSIONED"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


class ScanStatus(StrEnum):
    """State machine for a scan record, used by ``GET /v1/scans/{id}``."""

    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LocationMode(StrEnum):
    """Provenance of the location attached to a scan.

    ``DEMO`` is a named synthetic location chosen in the UI for demonstrating
    the history rules. It is never presented as a real observation.
    ``COARSE`` is a consented, bucketed real location. ``NONE`` is the default.
    """

    NONE = "NONE"
    DEMO = "DEMO"
    COARSE = "COARSE"


class ActorType(StrEnum):
    CONSUMER = "CONSUMER"
    PHARMACIST = "PHARMACIST"
    DISTRIBUTOR = "DISTRIBUTOR"
    MANUFACTURER = "MANUFACTURER"
    SEED = "SEED"


class EvidenceState(StrEnum):
    """Per-dimension qualitative state shown on the result card.

    The UI shows these words; the numeric scores are secondary
    (``docs/SCORING_AND_DETECTION.md`` section 12).
    """

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
