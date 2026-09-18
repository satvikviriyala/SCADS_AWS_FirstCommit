"""Endpoint implementations for the contract in ``docs/API_CONTRACTS.md``."""

import datetime as _dt
import hmac
from typing import Any, Dict, List, Optional

from ..adapters.base import DependencyUnavailable
from ..adapters.factory import Adapters
from ..config import Settings
from ..contracts.enums import ActorType, LocationMode, ScanStatus
from ..contracts.models import ScanLocation
from ..contracts.records import ScanEvent
from ..decision.explain import CHEMICAL_LIMITATION
from ..history.locations import list_locations, resolve_coordinates
from ..physical.image import ALLOWED_CONTENT_TYPES
from ..util.clock import Clock, to_iso
from ..util.ids import is_valid_scan_id, new_scan_id, scan_object_key
from ..util.jsonlog import log_event, log_warning
from ..versions import CONTRACT_VERSION, FUSION_POLICY_VERSION, PIPELINE_VERSION, SERVICE_NAME, SERVICE_VERSION
from . import http
from .orchestrator import AnalyzeRequest, analyze_scan


def health(settings: Settings, adapters: Optional[Adapters]) -> Dict[str, Any]:
    """Deployment metadata safe for public display.

    Reports which backends are actually in use. That is the point: an
    environment silently running on offline stubs would otherwise be
    indistinguishable from a real one, and the deployed smoke test asserts these
    values (``docs/API_CONTRACTS.md`` section 4). No account ids, no ARNs, no
    table names.
    """
    body: Dict[str, Any] = {
        "ok": True,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "environment": settings.env,
        "region": settings.region,
        "contract_version": CONTRACT_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "fusion_policy_version": FUSION_POLICY_VERSION,
        "backends": settings.describe_backends(),
        "admin_enabled": settings.admin_enabled,
    }
    if adapters is not None:
        body["adapters"] = adapters.describe()
    return body


def create_upload(
    body: Dict[str, Any], adapters: Adapters, settings: Settings, clock: Clock
) -> Dict[str, Any]:
    """``POST /v1/uploads`` — create a scan and a constrained upload target.

    The image goes straight from the phone to private S3. Routing megabytes
    through API Gateway and Lambda would add latency and cost for no benefit,
    and API Gateway's payload limit would cap photo quality
    (``docs/ARCHITECTURE.md`` section 3.2).
    """
    content_type = http.require_string(
        body, "content_type", max_length=64, allowed=ALLOWED_CONTENT_TYPES
    )
    content_length = http.require_int(
        body, "content_length", minimum=1, maximum=settings.upload_max_bytes
    )
    client_sha = http.optional_string(body, "sha256", max_length=64)

    scan_id = new_scan_id()
    now = clock.now()
    key = scan_object_key(scan_id, now)

    upload = adapters.store.presign_put(
        bucket_kind="scans",
        key=key,
        content_type=content_type,
        max_bytes=settings.upload_max_bytes,
        ttl_seconds=settings.upload_url_ttl_seconds,
    )

    # Persist the scan before handing out the upload target, so the object key
    # is known to the system even if the client abandons the upload. An orphan
    # CREATED record is harmless; an uploaded object nothing knows about is not.
    event = ScanEvent(
        scan_id=scan_id,
        event_time=to_iso(now),
        status=ScanStatus.CREATED,
        image_s3_key=key,
        content_type=content_type,
        evidence={"declared_content_length": content_length, "client_sha256": client_sha},
    )
    adapters.events.put_event(event)

    log_event(
        "upload.created",
        scan_id=scan_id,
        content_type=content_type,
        declared_bytes=content_length,
        store=adapters.store.backend_name,
    )

    return {
        "scan_id": scan_id,
        "object_key": key,
        "upload": {
            "method": upload["method"],
            "url": upload["url"],
            "headers": upload.get("headers", {}),
            "expires_in_seconds": upload.get("expires_in_seconds"),
        },
        "max_bytes": settings.upload_max_bytes,
    }


def analyze(
    scan_id: str,
    body: Dict[str, Any],
    adapters: Adapters,
    settings: Settings,
    clock: Clock,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """``POST /v1/scans/{scan_id}/analyze`` — run the evidence pipeline."""
    if not is_valid_scan_id(scan_id):
        raise http.bad_request("INVALID_SCAN_ID", "That scan reference is not valid.")

    qr_payload = http.optional_string(body, "qr_payload", max_length=2048)
    location = _parse_location(body)
    actor = http.optional_string(
        body, "actor_type", max_length=32,
        allowed=tuple(a.value for a in ActorType),
    )

    existing = adapters.events.get_event(scan_id)
    if existing is None:
        raise http.not_found()

    if not existing.image_s3_key:
        raise http.bad_request(
            "UPLOAD_MISSING", "No image has been uploaded for this scan yet."
        )

    # Confirm the object actually arrived, and enforce the size limit on the
    # real body: a presigned PUT cannot bound content length by itself.
    head = adapters.store.head("scans", existing.image_s3_key)
    if head is None:
        raise http.bad_request(
            "UPLOAD_MISSING", "The image upload has not completed. Please try again."
        )
    if head.get("content_length", 0) > settings.upload_max_bytes:
        raise http.bad_request("FILE_TOO_LARGE", "That image is larger than the limit.")

    request = AnalyzeRequest(
        scan_id=scan_id,
        qr_payload=qr_payload,
        location=location,
        actor_type=ActorType(actor) if actor else ActorType.CONSUMER,
        consent_coarse_location=bool(
            http.optional_object(body, "consent").get("coarse_location", False)
        ),
        correlation_id=correlation_id,
    )

    outcome = analyze_scan(request, adapters, settings, clock)
    return _scan_response(outcome)


def get_scan(scan_id: str, adapters: Adapters) -> Dict[str, Any]:
    """``GET /v1/scans/{scan_id}`` — retrieve a stored result.

    Used by the async fallback and by the demo history timeline. Returns the
    persisted evidence, never internal diagnostics.
    """
    if not is_valid_scan_id(scan_id):
        raise http.bad_request("INVALID_SCAN_ID", "That scan reference is not valid.")

    event = adapters.events.get_event(scan_id)
    if event is None:
        raise http.not_found()

    body: Dict[str, Any] = {
        "scan_id": event.scan_id,
        "status": event.status.value,
        "event_time": event.event_time,
        "decision": event.decision.value if event.decision else None,
        "dimensions": {
            "identity_score": event.identity_score,
            "physical_score": event.physical_score,
            "history_score": event.history_score,
            "scan_quality": event.scan_quality,
        },
        "presentation_score": event.presentation_score,
        "reason_codes": list(event.reason_codes),
        "identity": {
            "serial_id": event.serial_id,
            "batch_id": event.batch_id,
            "sku_id": event.sku_id,
            "verification_level": (event.evidence or {}).get("verification_level"),
        },
        "location": {
            "mode": event.location_mode.value,
            "label": event.location_label,
            "simulated": event.location_mode is LocationMode.DEMO,
        },
        "evidence": {
            "pipeline_version": event.pipeline_version,
            "fusion_policy_version": event.fusion_policy_version,
            "reference_version": event.reference_version,
            "ocr_provider": event.ocr_provider,
        },
        "limitation": CHEMICAL_LIMITATION,
    }
    return body


def get_locations() -> Dict[str, Any]:
    """``GET /v1/locations`` — the named demo locations for the UI selector.

    Every entry is flagged ``simulated``. The UI must label them as simulation
    rather than implying a real position was observed
    (``docs/SECURITY_PRIVACY.md`` section 2).
    """
    return {
        "locations": [loc.to_public() for loc in list_locations()],
        "note": (
            "These are named simulated locations used to demonstrate the scan-history "
            "checks. SCADS does not collect your real location."
        ),
    }


def get_reference_catalogue(adapters: Adapters) -> Dict[str, Any]:
    """``GET /v1/catalogue`` — which products have enrolled references.

    Lets the UI say "this pack is supported" up front, so a user is not asked
    to photograph something SCADS cannot compare.
    """
    try:
        profiles = adapters.references.list_profiles()
    except DependencyUnavailable:
        raise http.internal_error("reference catalogue unavailable")

    items: List[Dict[str, Any]] = []
    for profile in profiles:
        product_name = None
        try:
            sku = adapters.registry.get_sku(profile.sku_id)
            product_name = sku.product_name if sku else None
        except DependencyUnavailable:
            pass
        items.append(
            {
                "reference_profile_id": profile.reference_profile_id,
                "sku_id": profile.sku_id,
                "product_name": product_name,
                "packaging_variant": profile.packaging_variant,
                "reference_version": profile.version,
            }
        )
    return {"products": items}


def admin_reset(
    body: Dict[str, Any],
    token: Optional[str],
    adapters: Adapters,
    settings: Settings,
    clock: Clock,
) -> Dict[str, Any]:
    """``POST /v1/admin/demo/reset`` — reset seeded demo scan history.

    Authenticated, and scoped to the seed script's ``demo_tag``. It removes only
    fixtures the seeding created; it can touch neither the registry nor any real
    observation (``docs/API_CONTRACTS.md`` section 5). Absent a configured
    token the route does not exist at all.
    """
    if not settings.admin_enabled:
        raise http.not_found("NOT_FOUND", "No such endpoint.")
    if not token or not settings.admin_api_token:
        raise http.unauthorized()
    # Constant-time comparison: a token check that leaks timing is a token check
    # that can be brute-forced character by character.
    if not hmac.compare_digest(token, settings.admin_api_token):
        log_warning("admin.reset_rejected")
        raise http.unauthorized()

    from ..demo.seed_data import DEMO_TAG

    demo_tag = http.optional_string(body, "demo_tag", max_length=64) or DEMO_TAG
    removed = adapters.events.delete_events_by_demo_tag(demo_tag)

    log_event("admin.reset", demo_tag=demo_tag, removed=removed)
    return {"ok": True, "demo_tag": demo_tag, "events_removed": removed}


# --- helpers -------------------------------------------------------------


def _parse_location(body: Dict[str, Any]) -> ScanLocation:
    """Validate the reported location.

    A named bucket wins over any coordinates sent alongside it, so a client
    cannot relocate a named demo location by sending different numbers with it.
    """
    raw = http.optional_object(body, "location")
    if not raw:
        return ScanLocation()

    mode = http.optional_string(
        raw, "mode", max_length=16, allowed=tuple(m.value for m in LocationMode)
    )
    label = http.optional_string(raw, "label", max_length=64)
    lat = http.optional_float(raw, "lat_bucket", -90.0, 90.0)
    lon = http.optional_float(raw, "lon_bucket", -180.0, 180.0)

    resolved_lat, resolved_lon = resolve_coordinates(label, lat, lon)
    if resolved_lat is None:
        return ScanLocation(mode=LocationMode(mode) if mode else LocationMode.NONE, label=label)

    return ScanLocation(
        mode=LocationMode(mode) if mode else LocationMode.DEMO,
        label=label,
        lat=resolved_lat,
        lon=resolved_lon,
    )


def _scan_response(outcome) -> Dict[str, Any]:
    """Serialise an analysis outcome to the API contract shape."""
    result = outcome.decision_result
    bundle = outcome.bundle
    explanation = outcome.explanation

    body: Dict[str, Any] = {
        "scan_id": outcome.scan_id,
        "status": ScanStatus.COMPLETED.value,
        "decision": result.decision.value,
        "presentation_score": (
            round(result.presentation_score, 4) if result.presentation_score_applicable else None
        ),
        "presentation_score_applicable": result.presentation_score_applicable,
        "dimensions": {
            "identity_score": round(result.identity_score, 4),
            "physical_score": round(result.physical_score, 4),
            "history_score": round(result.history_score, 4),
            "scan_quality": round(result.scan_quality, 4),
        },
        "product_status": result.product_status.to_public(),
        "identity": bundle.identity.resolved.to_public(),
        "claimed_identity": bundle.identity.claimed.to_public(),
        "reason_codes": [c.value for c in result.reason_codes],
        "explanation": explanation,
        "evidence": {
            "pipeline_version": PIPELINE_VERSION,
            "fusion_policy_version": result.fusion_policy_version,
            "reference_version": bundle.physical.reference_version,
            "contract_version": CONTRACT_VERSION,
            "ocr_provider": outcome.ocr_provider,
            "registration_confidence": round(bundle.physical.registration_confidence, 4),
            "weights_used": result.weights_used,
            "applied_caps": [c.to_public() for c in result.applied_caps],
            "base_score": round(result.base_score, 4),
            "quality_metrics": bundle.quality.metrics,
            "physical_features": [f.to_public() for f in bundle.physical.features],
            "notes": result.notes,
            "latency_ms": outcome.latency_ms,
        },
        "history": {
            "available": bundle.history.available,
            "findings": [f.to_public() for f in bundle.history.findings],
            "prior_scans": [p.to_public() for p in bundle.history.prior_scans],
        },
        "next_action": explanation["next_action"],
        "limitation": CHEMICAL_LIMITATION,
    }

    if outcome.generated_explanation:
        # Marked as generated, and additional to the deterministic text rather
        # than a replacement for it, so a reader can always see the canonical
        # wording (``docs/API_CONTRACTS.md`` rule 5).
        body["generated_summary"] = {
            "text": outcome.generated_explanation,
            "source": "bedrock",
            "note": "Wording only. The decision and findings above are unchanged.",
        }
    return body
