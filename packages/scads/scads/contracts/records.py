"""Persistence records.

These are the shapes stored in DynamoDB, defined in ``docs/DATA_MODEL.md``. They
are deliberately separate from the evidence models in :mod:`scads.contracts.models`:
evidence is what one scan concluded, records are what the system knows.

A scan event is an **observation, not a truth mutation**. Nothing here has a
mutable ``verified`` flag, and a correction is a new event rather than an edit to
an old one (``docs/DATA_MODEL.md`` section 5).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums import (
    ActorType,
    Decision,
    LocationMode,
    ProductState,
    RecallStatus,
    ScanStatus,
    SerialStatus,
)


def _clean(data: Dict[str, Any]) -> Dict[str, Any]:
    """Drop ``None`` values so DynamoDB items stay sparse."""
    return {k: v for k, v in data.items() if v is not None}


@dataclass(frozen=True)
class ManufacturerRecord:
    manufacturer_id: str
    name: str
    country: Optional[str] = None
    licence_number: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        return _clean(
            {
                "pk": "MFG#" + self.manufacturer_id,
                "sk": "META",
                "entity": "MANUFACTURER",
                "manufacturer_id": self.manufacturer_id,
                "name": self.name,
                "country": self.country,
                "licence_number": self.licence_number,
            }
        )

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "ManufacturerRecord":
        return ManufacturerRecord(
            manufacturer_id=item["manufacturer_id"],
            name=item["name"],
            country=item.get("country"),
            licence_number=item.get("licence_number"),
        )


@dataclass(frozen=True)
class SkuRecord:
    sku_id: str
    manufacturer_id: str
    product_name: str
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    gtin: Optional[str] = None
    reference_profile_id: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        return _clean(
            {
                "pk": "SKU#" + self.sku_id,
                "sk": "META",
                "entity": "SKU",
                "sku_id": self.sku_id,
                "manufacturer_id": self.manufacturer_id,
                "product_name": self.product_name,
                "generic_name": self.generic_name,
                "strength": self.strength,
                "form": self.form,
                "gtin": self.gtin,
                "reference_profile_id": self.reference_profile_id,
            }
        )

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "SkuRecord":
        return SkuRecord(
            sku_id=item["sku_id"],
            manufacturer_id=item["manufacturer_id"],
            product_name=item["product_name"],
            generic_name=item.get("generic_name"),
            strength=item.get("strength"),
            form=item.get("form"),
            gtin=item.get("gtin"),
            reference_profile_id=item.get("reference_profile_id"),
        )


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    sku_id: str
    batch_code: str
    mfg_date: Optional[str] = None
    expiry_date: Optional[str] = None
    state: ProductState = ProductState.ACTIVE
    recall_status: RecallStatus = RecallStatus.NONE

    def to_item(self) -> Dict[str, Any]:
        return _clean(
            {
                "pk": "BATCH#" + self.batch_id,
                "sk": "META",
                "entity": "BATCH",
                "batch_id": self.batch_id,
                "sku_id": self.sku_id,
                "batch_code": self.batch_code,
                "batch_code_norm": self.batch_code.upper().replace(" ", ""),
                "mfg_date": self.mfg_date,
                "expiry_date": self.expiry_date,
                "state": self.state.value,
                "recall_status": self.recall_status.value,
            }
        )

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "BatchRecord":
        return BatchRecord(
            batch_id=item["batch_id"],
            sku_id=item["sku_id"],
            batch_code=item["batch_code"],
            mfg_date=item.get("mfg_date"),
            expiry_date=item.get("expiry_date"),
            state=ProductState(item.get("state", "ACTIVE")),
            recall_status=RecallStatus(item.get("recall_status", "NONE")),
        )


@dataclass(frozen=True)
class SerialRecord:
    """One physical unit's issued identity.

    ``status`` is registry state set by the manufacturer/admin plane. A consumer
    scan never writes it (``docs/ARCHITECTURE.md`` section 9).
    """

    serial_id: str
    batch_id: str
    sku_id: str
    manufacturer_id: str
    serial_code: str
    status: SerialStatus = SerialStatus.ACTIVE
    issued_at: Optional[str] = None
    dispensed_at: Optional[str] = None
    decommissioned_at: Optional[str] = None
    reference_profile_id: Optional[str] = None
    notes: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        return _clean(
            {
                "pk": "SERIAL#" + self.serial_id,
                "sk": "META",
                "entity": "SERIAL",
                "serial_id": self.serial_id,
                "batch_id": self.batch_id,
                "sku_id": self.sku_id,
                "manufacturer_id": self.manufacturer_id,
                "serial_code": self.serial_code,
                "status": self.status.value,
                "issued_at": self.issued_at,
                "dispensed_at": self.dispensed_at,
                "decommissioned_at": self.decommissioned_at,
                "reference_profile_id": self.reference_profile_id,
                "notes": self.notes,
            }
        )

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "SerialRecord":
        return SerialRecord(
            serial_id=item["serial_id"],
            batch_id=item["batch_id"],
            sku_id=item["sku_id"],
            manufacturer_id=item["manufacturer_id"],
            serial_code=item["serial_code"],
            status=SerialStatus(item.get("status", "ACTIVE")),
            issued_at=item.get("issued_at"),
            dispensed_at=item.get("dispensed_at"),
            decommissioned_at=item.get("decommissioned_at"),
            reference_profile_id=item.get("reference_profile_id"),
            notes=item.get("notes"),
        )


@dataclass(frozen=True)
class RoiSpec:
    """A stable region of the reference artwork, in normalised coordinates.

    Normalised to [0, 1] against the canonical reference frame so a ROI is
    resolution-independent. ``dynamic`` marks regions that legitimately differ
    between packs — the batch/expiry overprint and the QR — which must be
    excluded from structural comparison or every genuine pack would look
    tampered (``docs/SCORING_AND_DETECTION.md`` section 6.3).
    """

    name: str
    x: float
    y: float
    width: float
    height: float
    dynamic: bool = False
    weight: float = 1.0

    def to_item(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "dynamic": self.dynamic,
            "weight": self.weight,
        }

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "RoiSpec":
        return RoiSpec(
            name=item["name"],
            x=float(item["x"]),
            y=float(item["y"]),
            width=float(item["width"]),
            height=float(item["height"]),
            dynamic=bool(item.get("dynamic", False)),
            weight=float(item.get("weight", 1.0)),
        )

    def pixel_box(self, width: int, height: int):
        """Convert to an integer pixel box ``(left, top, right, bottom)``."""
        left = int(round(self.x * width))
        top = int(round(self.y * height))
        right = int(round((self.x + self.width) * width))
        bottom = int(round((self.y + self.height) * height))
        return (
            max(0, min(left, width - 1)),
            max(0, min(top, height - 1)),
            max(1, min(right, width)),
            max(1, min(bottom, height)),
        )


@dataclass(frozen=True)
class OcrAnchor:
    """Text expected at a known place on the reference artwork.

    Both halves matter: ``text`` supports the content comparison, ``x``/``y``
    the layout comparison. A counterfeit that prints the right words in the
    wrong place fails the second even when it passes the first.
    """

    name: str
    text: str
    x: float
    y: float
    tolerance: float = 0.06

    def to_item(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "tolerance": self.tolerance,
        }

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "OcrAnchor":
        return OcrAnchor(
            name=item["name"],
            text=item["text"],
            x=float(item["x"]),
            y=float(item["y"]),
            tolerance=float(item.get("tolerance", 0.06)),
        )


@dataclass(frozen=True)
class ReferenceProfile:
    """An enrolled genuine packaging reference.

    Versioned, because a reference change silently reinterprets every future
    comparison. Results record which ``version`` judged them.
    """

    reference_profile_id: str
    sku_id: str
    packaging_variant: str
    version: str
    image_s3_key: str
    aspect_ratio: float
    canonical_width: int = 900
    canonical_height: int = 520
    stable_rois: List[RoiSpec] = field(default_factory=list)
    ocr_anchors: List[OcrAnchor] = field(default_factory=list)
    feature_baselines: Dict[str, float] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        return _clean(
            {
                "reference_profile_id": self.reference_profile_id,
                "sku_id": self.sku_id,
                "packaging_variant": self.packaging_variant,
                "version": self.version,
                "image_s3_key": self.image_s3_key,
                "aspect_ratio": self.aspect_ratio,
                "canonical_width": self.canonical_width,
                "canonical_height": self.canonical_height,
                "stable_rois": [r.to_item() for r in self.stable_rois],
                "ocr_anchors": [a.to_item() for a in self.ocr_anchors],
                "feature_baselines": dict(self.feature_baselines),
                "created_at": self.created_at,
            }
        )

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "ReferenceProfile":
        return ReferenceProfile(
            reference_profile_id=item["reference_profile_id"],
            sku_id=item["sku_id"],
            packaging_variant=item["packaging_variant"],
            version=item["version"],
            image_s3_key=item["image_s3_key"],
            aspect_ratio=float(item["aspect_ratio"]),
            canonical_width=int(item.get("canonical_width", 900)),
            canonical_height=int(item.get("canonical_height", 520)),
            stable_rois=[RoiSpec.from_item(r) for r in item.get("stable_rois", [])],
            ocr_anchors=[OcrAnchor.from_item(a) for a in item.get("ocr_anchors", [])],
            feature_baselines={
                k: float(v) for k, v in (item.get("feature_baselines") or {}).items()
            },
            created_at=item.get("created_at"),
        )

    @property
    def static_rois(self) -> List[RoiSpec]:
        return [r for r in self.stable_rois if not r.dynamic]


@dataclass(frozen=True)
class ScanEvent:
    """One observation of one pack at one moment.

    Append-only by design. The evidence fields and the algorithm/policy versions
    are stored together so the decision can be re-derived and re-evaluated later
    (``PLAN.md`` AT-10).
    """

    scan_id: str
    event_time: str
    status: ScanStatus = ScanStatus.CREATED
    actor_type: ActorType = ActorType.CONSUMER

    serial_id: Optional[str] = None
    batch_id: Optional[str] = None
    sku_id: Optional[str] = None
    claimed_serial: Optional[str] = None
    claimed_batch: Optional[str] = None

    location_mode: LocationMode = LocationMode.NONE
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None

    image_s3_key: Optional[str] = None
    content_type: Optional[str] = None

    decision: Optional[Decision] = None
    presentation_score: Optional[float] = None
    identity_score: Optional[float] = None
    physical_score: Optional[float] = None
    history_score: Optional[float] = None
    scan_quality: Optional[float] = None
    reason_codes: List[str] = field(default_factory=list)

    pipeline_version: Optional[str] = None
    fusion_policy_version: Optional[str] = None
    reference_version: Optional[str] = None
    ocr_provider: Optional[str] = None

    evidence: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    latency_ms: Optional[int] = None

    # Grouping key for demo fixtures, so a reset can remove seeded history
    # without touching anything a judge or user created.
    demo_tag: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        item = _clean(
            {
                "scan_id": self.scan_id,
                "event_time": self.event_time,
                "status": self.status.value,
                "actor_type": self.actor_type.value,
                "serial_id": self.serial_id,
                "batch_id": self.batch_id,
                "sku_id": self.sku_id,
                "claimed_serial": self.claimed_serial,
                "claimed_batch": self.claimed_batch,
                "location_mode": self.location_mode.value,
                "location_label": self.location_label,
                "location_lat": self.location_lat,
                "location_lon": self.location_lon,
                "image_s3_key": self.image_s3_key,
                "content_type": self.content_type,
                "decision": self.decision.value if self.decision else None,
                "presentation_score": self.presentation_score,
                "identity_score": self.identity_score,
                "physical_score": self.physical_score,
                "history_score": self.history_score,
                "scan_quality": self.scan_quality,
                "reason_codes": list(self.reason_codes),
                "pipeline_version": self.pipeline_version,
                "fusion_policy_version": self.fusion_policy_version,
                "reference_version": self.reference_version,
                "ocr_provider": self.ocr_provider,
                "evidence": self.evidence,
                "error_code": self.error_code,
                "latency_ms": self.latency_ms,
                "demo_tag": self.demo_tag,
            }
        )
        # GSI partition key. DynamoDB omits index entries for items without the
        # key, which is what we want: scans with no resolved serial simply do not
        # appear in the by-serial history index.
        if self.serial_id:
            item["serial_index_key"] = self.serial_id
        return item

    @staticmethod
    def from_item(item: Dict[str, Any]) -> "ScanEvent":
        def opt_float(key):
            value = item.get(key)
            return None if value is None else float(value)

        return ScanEvent(
            scan_id=item["scan_id"],
            event_time=item["event_time"],
            status=ScanStatus(item.get("status", "CREATED")),
            actor_type=ActorType(item.get("actor_type", "CONSUMER")),
            serial_id=item.get("serial_id"),
            batch_id=item.get("batch_id"),
            sku_id=item.get("sku_id"),
            claimed_serial=item.get("claimed_serial"),
            claimed_batch=item.get("claimed_batch"),
            location_mode=LocationMode(item.get("location_mode", "NONE")),
            location_label=item.get("location_label"),
            location_lat=opt_float("location_lat"),
            location_lon=opt_float("location_lon"),
            image_s3_key=item.get("image_s3_key"),
            content_type=item.get("content_type"),
            decision=Decision(item["decision"]) if item.get("decision") else None,
            presentation_score=opt_float("presentation_score"),
            identity_score=opt_float("identity_score"),
            physical_score=opt_float("physical_score"),
            history_score=opt_float("history_score"),
            scan_quality=opt_float("scan_quality"),
            reason_codes=list(item.get("reason_codes", [])),
            pipeline_version=item.get("pipeline_version"),
            fusion_policy_version=item.get("fusion_policy_version"),
            reference_version=item.get("reference_version"),
            ocr_provider=item.get("ocr_provider"),
            evidence=dict(item.get("evidence") or {}),
            error_code=item.get("error_code"),
            latency_ms=int(item["latency_ms"]) if item.get("latency_ms") is not None else None,
            demo_tag=item.get("demo_tag"),
        )
