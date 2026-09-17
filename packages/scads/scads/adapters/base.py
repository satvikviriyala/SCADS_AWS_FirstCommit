"""Ports for everything outside the pure core.

Each port has a real AWS implementation and an offline one. The offline
implementations exist so the detection logic and the whole request path can be
tested without an AWS account — not to stand in for AWS in a deployed
environment. Which one is active is always reported
(:meth:`scads.config.Settings.describe_backends`).
"""

import abc
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.records import (
    BatchRecord,
    ManufacturerRecord,
    ReferenceProfile,
    ScanEvent,
    SerialRecord,
    SkuRecord,
)


class DependencyUnavailable(RuntimeError):
    """A backend call failed.

    Raised rather than swallowed. A history query that fails must surface as
    ``HISTORY_UNAVAILABLE`` and lower the assurance of the result; returning an
    empty list would masquerade as "clean history", which
    ``docs/AWS_DEPLOYMENT.md`` section 11 explicitly forbids.
    """

    def __init__(self, dependency: str, detail: str = "") -> None:
        super().__init__(dependency + (": " + detail if detail else ""))
        self.dependency = dependency
        self.detail = detail


class ObjectStore(abc.ABC):
    """Blob storage for scan uploads and enrolled reference images."""

    backend_name = "abstract"

    @abc.abstractmethod
    def presign_put(
        self, bucket_kind: str, key: str, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> Dict[str, Any]:
        """Return an upload target: ``{method, url, headers, expires_in_seconds}``."""

    @abc.abstractmethod
    def get_bytes(self, bucket_kind: str, key: str) -> bytes:
        """Fetch an object. Raises :class:`DependencyUnavailable` if unreadable."""

    @abc.abstractmethod
    def put_bytes(self, bucket_kind: str, key: str, data: bytes, content_type: str) -> None:
        """Store an object. Used by the reference-enrollment script only."""

    @abc.abstractmethod
    def head(self, bucket_kind: str, key: str) -> Optional[Dict[str, Any]]:
        """Return ``{content_length, content_type}`` or ``None`` if absent."""

    @abc.abstractmethod
    def exists(self, bucket_kind: str, key: str) -> bool:
        ...


class Registry(abc.ABC):
    """Read access to manufacturer/product/batch/serial records.

    Read-only on purpose. Enrollment is an authenticated admin-plane operation
    performed by :mod:`scripts.seed_demo`, never by the request path
    (``docs/THREAT_MODEL.md`` section 5).
    """

    backend_name = "abstract"

    @abc.abstractmethod
    def get_manufacturer(self, manufacturer_id: str) -> Optional[ManufacturerRecord]:
        ...

    @abc.abstractmethod
    def get_sku(self, sku_id: str) -> Optional[SkuRecord]:
        ...

    @abc.abstractmethod
    def get_batch(self, batch_id: str) -> Optional[BatchRecord]:
        ...

    @abc.abstractmethod
    def find_batch_by_code(self, batch_code: str) -> Optional[BatchRecord]:
        """Resolve a printed batch code to a batch record."""

    @abc.abstractmethod
    def get_serial(self, serial_id: str) -> Optional[SerialRecord]:
        ...

    @abc.abstractmethod
    def find_serial_by_code(self, serial_code: str) -> Optional[SerialRecord]:
        """Resolve a printed/encoded serial to a unit record."""


class RegistryWriter(abc.ABC):
    """Admin-plane writes. Implemented separately from :class:`Registry` so the
    request-path code cannot reach them even by mistake."""

    @abc.abstractmethod
    def put_manufacturer(self, record: ManufacturerRecord) -> None:
        ...

    @abc.abstractmethod
    def put_sku(self, record: SkuRecord) -> None:
        ...

    @abc.abstractmethod
    def put_batch(self, record: BatchRecord) -> None:
        ...

    @abc.abstractmethod
    def put_serial(self, record: SerialRecord) -> None:
        ...

    @abc.abstractmethod
    def put_reference_profile(self, record: ReferenceProfile) -> None:
        ...


class ReferenceStore(abc.ABC):
    """Reference-profile metadata lookup."""

    backend_name = "abstract"

    @abc.abstractmethod
    def get_profile(self, reference_profile_id: str) -> Optional[ReferenceProfile]:
        ...

    @abc.abstractmethod
    def list_profiles(self) -> List[ReferenceProfile]:
        ...


class ScanEventStore(abc.ABC):
    """Append-only scan-event log."""

    backend_name = "abstract"

    @abc.abstractmethod
    def put_event(self, event: ScanEvent) -> None:
        ...

    @abc.abstractmethod
    def get_event(self, scan_id: str) -> Optional[ScanEvent]:
        ...

    @abc.abstractmethod
    def query_by_serial(self, serial_id: str, limit: int = 50) -> List[ScanEvent]:
        """Prior events for one unit, newest first.

        Must raise :class:`DependencyUnavailable` on failure rather than
        returning ``[]``: an empty list means "this unit has never been seen",
        which is the opposite of "we could not check".
        """

    @abc.abstractmethod
    def delete_events_by_demo_tag(self, demo_tag: str) -> int:
        """Remove seeded demo events. Admin plane only; returns the count."""


class OcrProvider(abc.ABC):
    """Text and word-box extraction from a scan image."""

    provider_name = "abstract"

    @abc.abstractmethod
    def detect_text(self, image_bytes: bytes, hint: Optional[Dict[str, Any]] = None) -> "OcrResult":
        ...


class Explainer(abc.ABC):
    """Optional prose rewriting of an already-decided result.

    Cannot change the decision, cannot add reason codes, and must fail closed to
    the deterministic text. A Bedrock outage must not affect a verdict
    (``docs/ARCHITECTURE.md`` section 2).
    """

    provider_name = "abstract"

    @abc.abstractmethod
    def rewrite(self, decision: str, reason_codes: List[str], dimensions: Dict[str, float]) -> Optional[str]:
        ...


# Imported at the end to avoid a circular import: OcrResult lives with the
# identity code that consumes it, but the port above must reference it.
from ..identity.ocr import OcrResult  # noqa: E402,F401
