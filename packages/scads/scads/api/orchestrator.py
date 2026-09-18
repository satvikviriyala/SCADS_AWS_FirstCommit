"""The scan pipeline: from an uploaded image to a decided, persisted result.

Stage order is the architecture (``docs/ARCHITECTURE.md`` section 3):

    fetch image -> validate -> quality gate -> extract identity (QR, then OCR)
    -> resolve against registry -> compare packaging -> analyse scan history
    -> fuse -> persist -> explain

Two rules run throughout.

**A failed dependency degrades a dimension; it never fabricates one.** If
Textract is down, text evidence is unavailable and the result says so. If the
history query throws, the history dimension is unavailable and the assurance of
the result drops. Nothing here converts a failure into a passing signal.

**Nothing raises past this boundary.** Every foreseeable failure becomes a
decided result carrying a reason code, because a user holding a medicine packet
needs an answer with advice, not an HTTP 500.
"""

import datetime as _dt
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..adapters.base import DependencyUnavailable
from ..adapters.factory import Adapters
from ..config import Settings
from ..contracts.enums import (
    ActorType,
    Decision,
    EvidenceState,
    LocationMode,
    ProductState,
    RecallStatus,
    ScanStatus,
    VerificationLevel,
)
from ..contracts.models import (
    ClaimedIdentity,
    EvidenceBundle,
    IdentityEvidence,
    ProductStatus,
    QualityReport,
    ResolvedIdentity,
    ScanLocation,
)
from ..contracts.reason_codes import ReasonCode
from ..contracts.records import ReferenceProfile, ScanEvent, SerialRecord
from ..decision import decide, summarise
from ..decision.policy import DEFAULT_POLICY, FusionPolicy
from ..history import evaluate_history
from ..history.locations import resolve_coordinates
from ..identity import evaluate_identity, extract_claim, parse_qr_payload
from ..identity.ocr import OcrResult
from ..physical import compare_packaging, unavailable_evidence
from ..physical.image import ImageRejected, LoadedImage, load_image, to_gray
from ..physical.quality import assess_quality
from ..util.clock import Clock, to_iso
from ..util.jsonlog import log_error, log_event, log_warning
from ..versions import FUSION_POLICY_VERSION, PIPELINE_VERSION

# Upload-validation failures, mapped to the reason code that tells the user what
# to do about it.
_REJECTION_CODES = {
    "EMPTY_UPLOAD": ReasonCode.DEPENDENCY_UNAVAILABLE,
    "FILE_TOO_LARGE": ReasonCode.UNSUPPORTED_PACKAGE_VARIANT,
    "UNSUPPORTED_MEDIA_TYPE": ReasonCode.UNSUPPORTED_PACKAGE_VARIANT,
    "CORRUPT_IMAGE": ReasonCode.DEPENDENCY_UNAVAILABLE,
    "IMAGE_TOO_SMALL": ReasonCode.IMAGE_TOO_SMALL,
}


@dataclass(frozen=True)
class AnalyzeRequest:
    """Validated input to :func:`analyze_scan`."""

    scan_id: str
    qr_payload: Optional[str] = None
    location: ScanLocation = ScanLocation()
    actor_type: ActorType = ActorType.CONSUMER
    consent_coarse_location: bool = False
    correlation_id: Optional[str] = None


@dataclass
class AnalyzeOutcome:
    """Everything the API layer needs to answer, plus what was persisted."""

    scan_id: str
    status: ScanStatus
    decision_result: Any
    bundle: EvidenceBundle
    explanation: Dict[str, Any]
    event: ScanEvent
    latency_ms: int
    ocr_provider: str
    generated_explanation: Optional[str] = None


def analyze_scan(
    request: AnalyzeRequest,
    adapters: Adapters,
    settings: Settings,
    clock: Clock,
    policy: Optional[FusionPolicy] = None,
) -> AnalyzeOutcome:
    """Run the full evidence pipeline for one scan."""
    started = time.time()
    policy = policy or DEFAULT_POLICY
    now = clock.now()

    existing = _load_existing_event(adapters, request.scan_id)
    system_codes: List[ReasonCode] = []

    # --- fetch the uploaded image ---------------------------------------
    image_key = existing.image_s3_key if existing else None
    if not image_key:
        raise LookupError("scan has no uploaded image")

    try:
        raw = adapters.store.get_bytes("scans", image_key)
    except DependencyUnavailable as exc:
        log_error("scan.image_unavailable", scan_id=request.scan_id, dependency=exc.dependency)
        return _fail_closed(
            request, adapters, settings, clock, existing,
            [ReasonCode.DEPENDENCY_UNAVAILABLE], started, policy,
            note="The uploaded image could not be read.",
        )

    # --- validate and decode --------------------------------------------
    try:
        loaded = load_image(raw, settings.upload_max_bytes, existing.content_type)
    except ImageRejected as exc:
        log_warning("scan.image_rejected", scan_id=request.scan_id, rejection=exc.code)
        return _fail_closed(
            request, adapters, settings, clock, existing,
            [_REJECTION_CODES.get(exc.code, ReasonCode.UNSUPPORTED_PACKAGE_VARIANT)],
            started, policy,
            note="The uploaded file was not a usable pack photo.",
        )

    # --- quality gate ----------------------------------------------------
    quality = assess_quality(loaded)

    # --- identity: QR first, then OCR ------------------------------------
    qr_claim = parse_qr_payload(request.qr_payload)

    ocr = _run_ocr(adapters, raw, settings, quality)
    if not ocr.succeeded and ocr.provider != "none":
        # OCR is one source among several. Losing it weakens identity and layout
        # evidence; it does not invalidate the scan.
        log_warning("scan.ocr_failed", scan_id=request.scan_id, provider=ocr.provider)

    claimed, observed = extract_claim(qr_claim, ocr)

    try:
        identity, product = evaluate_identity(
            adapters.registry, claimed, observed, today=now.date()
        )
        serial_record = _load_serial_record(adapters, identity.resolved.serial_id)
    except DependencyUnavailable as exc:
        log_error("scan.registry_unavailable", scan_id=request.scan_id, dependency=exc.dependency)
        identity = IdentityEvidence(
            score=0.0,
            state=EvidenceState.UNKNOWN,
            resolved=ResolvedIdentity(),
            claimed=claimed,
            reason_codes=[ReasonCode.DEPENDENCY_UNAVAILABLE],
            details={"dependency": exc.dependency},
        )
        product = ProductStatus(state=ProductState.UNKNOWN, recall_status=RecallStatus.UNKNOWN)
        serial_record = None
        system_codes.append(ReasonCode.DEPENDENCY_UNAVAILABLE)

    # --- physical packaging ----------------------------------------------
    physical = _compare_packaging(
        adapters, loaded, identity.resolved.reference_profile_id, ocr, quality,
        scan_id=request.scan_id,
    )

    # --- scan history ----------------------------------------------------
    history = evaluate_history(
        adapters.events,
        serial_id=identity.resolved.serial_id,
        location=request.location,
        now=now,
        serial_record=serial_record,
        current_scan_id=request.scan_id,
    )

    # --- fuse -------------------------------------------------------------
    bundle = EvidenceBundle(
        quality=quality,
        identity=identity,
        physical=physical,
        history=history,
        product=product,
        system_reason_codes=system_codes,
    )
    result = decide(bundle, policy)
    explanation = summarise(bundle, result)
    latency_ms = int((time.time() - started) * 1000)

    # --- persist -----------------------------------------------------------
    event = _build_event(
        request, existing, result, bundle, ocr, now, latency_ms, ScanStatus.COMPLETED
    )
    _persist(adapters, event, request.scan_id)

    # --- optional generated prose ----------------------------------------
    generated = _maybe_rewrite(adapters, result)

    log_event(
        "scan.completed",
        scan_id=request.scan_id,
        decision=result.decision.value,
        presentation_score=round(result.presentation_score, 4),
        identity_score=round(result.identity_score, 4),
        physical_score=round(result.physical_score, 4),
        history_score=round(result.history_score, 4),
        scan_quality=round(result.scan_quality, 4),
        verification_level=result.verification_level.value,
        reason_codes=[c.value for c in result.reason_codes],
        product_state=product.state.value,
        latency_ms=latency_ms,
        pipeline_version=PIPELINE_VERSION,
        fusion_policy_version=result.fusion_policy_version,
        ocr_provider=ocr.provider,
        backends=adapters.describe(),
    )

    return AnalyzeOutcome(
        scan_id=request.scan_id,
        status=ScanStatus.COMPLETED,
        decision_result=result,
        bundle=bundle,
        explanation=explanation,
        event=event,
        latency_ms=latency_ms,
        ocr_provider=ocr.provider,
        generated_explanation=generated,
    )


# --- stage helpers -------------------------------------------------------


def _load_existing_event(adapters: Adapters, scan_id: str) -> Optional[ScanEvent]:
    try:
        return adapters.events.get_event(scan_id)
    except DependencyUnavailable:
        return None


def _load_serial_record(adapters: Adapters, serial_id: Optional[str]) -> Optional[SerialRecord]:
    """Fetch the registry record for a resolved serial.

    Needed by the post-sale-reuse rule, which fires on registry state rather
    than on observed history, and so catches a diverted pack on its first scan.
    """
    if not serial_id:
        return None
    try:
        return adapters.registry.get_serial(serial_id)
    except DependencyUnavailable:
        return None


def _run_ocr(
    adapters: Adapters, raw: bytes, settings: Settings, quality: QualityReport
) -> OcrResult:
    """Extract text, skipping the call when the image cannot support it.

    Skipping below the quality floor is a cost decision as much as a correctness
    one: Textract is billed per page, and calling it on a photo already known to
    be ungradeable spends money to learn nothing
    (``docs/AWS_DEPLOYMENT.md`` section 12).
    """
    if not quality.passed and quality.score < 0.2:
        return OcrResult.failed(
            adapters.ocr.provider_name, "skipped: capture quality too low for text extraction"
        )
    try:
        return adapters.ocr.detect_text(raw)
    except Exception as exc:  # noqa: BLE001 - provider adapters may raise anything
        return OcrResult.failed(adapters.ocr.provider_name, type(exc).__name__)


def _compare_packaging(
    adapters: Adapters,
    loaded: LoadedImage,
    reference_profile_id: Optional[str],
    ocr: OcrResult,
    quality: QualityReport,
    scan_id: str,
):
    """Load the enrolled reference and compare, or report why we could not.

    Deliberately never compares a phone photo against an unregistered image: if
    no reference is enrolled for this product, packaging evidence is
    unavailable. Treating the difference from some arbitrary stock photo as
    counterfeit evidence is the specific mistake ``docs/ARCHITECTURE.md``
    section 6 warns against.
    """
    if not reference_profile_id:
        return unavailable_evidence([ReasonCode.REFERENCE_NOT_FOUND])

    try:
        profile = adapters.references.get_profile(reference_profile_id)
    except DependencyUnavailable as exc:
        log_error("scan.reference_unavailable", scan_id=scan_id, dependency=exc.dependency)
        return unavailable_evidence([ReasonCode.DEPENDENCY_UNAVAILABLE])

    if profile is None:
        return unavailable_evidence([ReasonCode.REFERENCE_NOT_FOUND])

    try:
        reference_bytes = adapters.store.get_bytes("references", profile.image_s3_key)
    except DependencyUnavailable as exc:
        log_error("scan.reference_image_unavailable", scan_id=scan_id, dependency=exc.dependency)
        return unavailable_evidence([ReasonCode.REFERENCE_NOT_FOUND], profile)

    try:
        reference_image = load_image(reference_bytes, 16 * 1024 * 1024)
    except ImageRejected:
        log_error("scan.reference_image_invalid", scan_id=scan_id, profile=reference_profile_id)
        return unavailable_evidence([ReasonCode.REFERENCE_NOT_FOUND], profile)

    return compare_packaging(
        scan=loaded,
        reference_gray=reference_image.gray,
        profile=profile,
        ocr=ocr,
        capture_sharpness=float(quality.metrics.get("sharpness", 1.0)),
    )


def _maybe_rewrite(adapters: Adapters, result) -> Optional[str]:
    """Ask the optional explainer to restyle the verdict.

    Receives the decision, the codes and the numeric dimensions — never the
    pack's OCR text, which is attacker-controlled. Any failure returns ``None``
    and the caller keeps the deterministic wording, so a Bedrock outage cannot
    affect a result (``docs/ARCHITECTURE.md`` section 2).
    """
    if adapters.explainer is None:
        return None
    try:
        return adapters.explainer.rewrite(
            decision=result.decision.value,
            reason_codes=[c.value for c in result.reason_codes],
            dimensions={
                "identity": result.identity_score,
                "physical": result.physical_score,
                "history": result.history_score,
            },
        )
    except Exception:  # noqa: BLE001 - never let the explainer break a verdict
        log_warning("scan.explainer_failed")
        return None


def _build_event(
    request: AnalyzeRequest,
    existing: Optional[ScanEvent],
    result,
    bundle: EvidenceBundle,
    ocr: OcrResult,
    now: _dt.datetime,
    latency_ms: int,
    status: ScanStatus,
) -> ScanEvent:
    """Build the scan event to persist.

    The stored evidence is deliberately bounded: feature values, versions and
    reason codes — enough to re-derive and audit the decision — but not the raw
    OCR text or the full diagnostics blob (``AGENTS.md`` section 6.5).
    """
    resolved = bundle.identity.resolved
    lat, lon = resolve_coordinates(
        request.location.label, request.location.lat, request.location.lon
    )

    evidence: Dict[str, Any] = {
        "quality_metrics": bundle.quality.metrics,
        "physical_features": {f.name: round(f.value, 4) for f in bundle.physical.features},
        "physical_available": bundle.physical.available,
        "registration_confidence": round(bundle.physical.registration_confidence, 4),
        "history_findings": [f.to_public() for f in bundle.history.findings],
        "history_available": bundle.history.available,
        "weights_used": result.weights_used,
        "applied_caps": [c.to_public() for c in result.applied_caps],
        "base_score": round(result.base_score, 4),
        "claimed": bundle.identity.claimed.to_public(),
        "verification_level": result.verification_level.value,
        "ocr_word_count": len(ocr.words),
    }

    return ScanEvent(
        scan_id=request.scan_id,
        event_time=to_iso(now),
        status=status,
        actor_type=request.actor_type,
        serial_id=resolved.serial_id,
        batch_id=resolved.batch_id,
        sku_id=resolved.sku_id,
        claimed_serial=bundle.identity.claimed.serial,
        claimed_batch=bundle.identity.claimed.batch,
        location_mode=request.location.mode,
        location_label=request.location.label,
        location_lat=lat,
        location_lon=lon,
        image_s3_key=existing.image_s3_key if existing else None,
        content_type=existing.content_type if existing else None,
        decision=result.decision,
        presentation_score=(
            round(result.presentation_score, 4) if result.presentation_score_applicable else None
        ),
        identity_score=round(result.identity_score, 4),
        physical_score=round(result.physical_score, 4),
        history_score=round(result.history_score, 4),
        scan_quality=round(result.scan_quality, 4),
        reason_codes=[c.value for c in result.reason_codes],
        pipeline_version=PIPELINE_VERSION,
        fusion_policy_version=result.fusion_policy_version,
        reference_version=bundle.physical.reference_version,
        ocr_provider=ocr.provider,
        evidence=evidence,
        latency_ms=latency_ms,
        demo_tag=existing.demo_tag if existing else None,
    )


def _persist(adapters: Adapters, event: ScanEvent, scan_id: str) -> None:
    """Store the completed event.

    A persistence failure is logged and swallowed *at this point only*: the user
    already has a correct answer, and refusing to return it because the audit
    write failed would be the worse outcome. The failure is visible in logs and
    the scan simply will not appear in future history queries.
    """
    try:
        adapters.events.put_event(event)
    except DependencyUnavailable as exc:
        log_error("scan.persist_failed", scan_id=scan_id, dependency=exc.dependency)


def _fail_closed(
    request: AnalyzeRequest,
    adapters: Adapters,
    settings: Settings,
    clock: Clock,
    existing: Optional[ScanEvent],
    codes: List[ReasonCode],
    started: float,
    policy: FusionPolicy,
    note: str,
) -> AnalyzeOutcome:
    """Produce an ``UNABLE_TO_VERIFY`` outcome for a pre-analysis failure.

    Runs the real decision engine over an all-unavailable bundle rather than
    hand-building a response, so a failure path cannot drift from the contract
    that the success path satisfies.
    """
    now = clock.now()
    bundle = EvidenceBundle(
        quality=QualityReport(score=0.0, passed=False, reason_codes=[], metrics={}),
        identity=IdentityEvidence(
            score=0.0,
            state=EvidenceState.UNKNOWN,
            resolved=ResolvedIdentity(),
            claimed=ClaimedIdentity(),
            reason_codes=[],
        ),
        physical=unavailable_evidence([]),
        history=evaluate_history(
            adapters.events, None, request.location, now, None, request.scan_id
        ),
        product=ProductStatus(),
        system_reason_codes=list(codes),
    )
    result = decide(bundle, policy)
    explanation = summarise(bundle, result)
    explanation["headline"] = explanation["headline"]
    latency_ms = int((time.time() - started) * 1000)

    event = _build_event(
        request, existing, result, bundle, OcrResult.failed("none", note),
        now, latency_ms, ScanStatus.FAILED,
    )
    _persist(adapters, event, request.scan_id)

    log_event(
        "scan.unverifiable",
        scan_id=request.scan_id,
        decision=result.decision.value,
        reason_codes=[c.value for c in result.reason_codes],
        latency_ms=latency_ms,
    )

    return AnalyzeOutcome(
        scan_id=request.scan_id,
        status=ScanStatus.FAILED,
        decision_result=result,
        bundle=bundle,
        explanation=explanation,
        event=event,
        latency_ms=latency_ms,
        ocr_provider="none",
    )
