"""Identity evaluation: from a claim on a pack to evidence about that claim.

The distinction this module exists to preserve:

* **Claimed identity** — what the QR code and the printed text say.
* **Resolved identity** — what the registry actually knows.

A QR-existence checker collapses these and answers "yes, that serial exists".
SCADS keeps them apart, reports which one it resolved, at what specificity
(``verification_level``), and whether the two sources of the claim agree with
each other.
"""

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from ..adapters.base import DependencyUnavailable, Registry
from ..contracts.enums import (
    EvidenceState,
    ProductState,
    RecallStatus,
    SerialStatus,
    VerificationLevel,
)
from ..contracts.models import ClaimedIdentity, IdentityEvidence, ProductStatus, ResolvedIdentity
from ..contracts.reason_codes import ReasonCode
from ..contracts.records import BatchRecord, SerialRecord
from ..util.clock import parse_date
from .normalize import (
    codes_agree,
    normalize_batch_code,
    normalize_manufacturer,
    normalize_serial_code,
    ocr_variants,
)
from .ocr import OcrResult

# Identity scores per outcome. Coarse and few on purpose: a continuous identity
# score invites hiding a hard contradiction behind a plausible-looking number,
# which ``docs/SCORING_AND_DETECTION.md`` section 8 warns against. The hard caps
# in the fusion policy, not these values, are what make contradictions decisive.
SCORE_UNIT_VALID = 0.96
SCORE_UNIT_VALID_QR_ONLY = 0.90
SCORE_BATCH_VALID = 0.62
SCORE_SERIAL_UNKNOWN_BATCH_VALID = 0.30
SCORE_UNKNOWN = 0.08
SCORE_REVOKED = 0.04
QR_OCR_CONFLICT_PENALTY = 0.35


def extract_claim(
    qr_claim: ClaimedIdentity, ocr: Optional[OcrResult]
) -> Tuple[ClaimedIdentity, Dict[str, Any]]:
    """Merge the QR claim with what OCR read from the pack.

    The QR payload wins where both are present, because it is machine-readable
    and not subject to OCR error. OCR fills gaps and — importantly — provides
    the second opinion that makes :func:`cross_check` possible.
    """
    ocr_serial = None
    ocr_batch = None
    ocr_expiry = None

    if ocr is not None and ocr.succeeded:
        ocr_serial, ocr_batch, ocr_expiry = _read_printed_fields(ocr)

    serial = qr_claim.serial or ocr_serial
    batch = qr_claim.batch or ocr_batch
    expiry = qr_claim.expiry or ocr_expiry

    if qr_claim.source == "QR" and (ocr_serial or ocr_batch):
        source = "QR+OCR"
    elif qr_claim.source == "QR":
        source = "QR"
    elif ocr_serial or ocr_batch:
        source = "OCR"
    else:
        source = "NONE"

    merged = ClaimedIdentity(
        serial=serial,
        batch=batch,
        gtin=qr_claim.gtin,
        product_name=qr_claim.product_name,
        manufacturer_name=qr_claim.manufacturer_name,
        expiry=expiry,
        source=source,
    )
    observed = {
        "qr_serial": qr_claim.serial,
        "qr_batch": qr_claim.batch,
        "qr_expiry": qr_claim.expiry,
        "ocr_serial": ocr_serial,
        "ocr_batch": ocr_batch,
        "ocr_expiry": ocr_expiry,
    }
    return merged, observed


_SERIAL_LABELS = ("SN", "S/N", "SERIAL", "SER")
_BATCH_LABELS = ("B.NO", "BNO", "BATCH", "LOT", "BN", "B/NO")
_EXPIRY_LABELS = ("EXP", "EXPY", "EXPIRY", "USEBY", "USE")


def _read_printed_fields(ocr: OcrResult):
    """Find labelled serial/batch/expiry in OCR output.

    Label-driven, scanning the words that follow a recognised label rather than
    pattern-matching every token on the pack. A pack is covered in
    alphanumerics — dosage, licence numbers, addresses — and treating any of
    them as a serial would fabricate identity claims.
    """
    words = [w for w in ocr.words if w.text.strip()]
    serial = batch = expiry = None

    for index, word in enumerate(words):
        token = word.normalised_text.rstrip(":.")
        following = words[index + 1 : index + 4]

        if serial is None and token in _SERIAL_LABELS:
            serial = _first_code(following, normalize_serial_code)
        elif batch is None and token in _BATCH_LABELS:
            batch = _first_code(following, normalize_batch_code)
        elif expiry is None and token in _EXPIRY_LABELS:
            expiry = _first_expiry(following)

    # Also handle labels fused to their value by the OCR ("SN:SERA001").
    if serial is None or batch is None or expiry is None:
        for word in words:
            text = word.normalised_text
            for label in _SERIAL_LABELS:
                if serial is None and text.startswith(label) and len(text) > len(label) + 2:
                    serial = normalize_serial_code(text[len(label) :].lstrip(":."))
            for label in _BATCH_LABELS:
                if batch is None and text.startswith(label) and len(text) > len(label) + 2:
                    batch = normalize_batch_code(text[len(label) :].lstrip(":."))
            for label in _EXPIRY_LABELS:
                if expiry is None and text.startswith(label) and len(text) > len(label) + 2:
                    from .normalize import normalize_expiry

                    expiry = normalize_expiry(text[len(label) :].lstrip(":."))

    return serial, batch, expiry


def _first_code(words, normaliser):
    for word in words:
        candidate = normaliser(word.text)
        if candidate:
            return candidate
    return None


def _first_expiry(words):
    from .normalize import normalize_expiry

    joined = " ".join(w.text for w in words)
    for candidate in (joined, *[w.text for w in words]):
        parsed = normalize_expiry(candidate)
        if parsed:
            return parsed
    return None


def cross_check(observed: Dict[str, Any]) -> List[ReasonCode]:
    """Compare what the code claims with what the pack prints.

    On a genuine pack these agree, because both are applied by the same
    packaging line. A valid code married to different printed text is a
    meaningful signal — and one that neither a database lookup nor a purely
    visual check would produce on its own.
    """
    codes: List[ReasonCode] = []
    if not codes_agree(observed.get("qr_serial"), observed.get("ocr_serial")):
        codes.append(ReasonCode.QR_OCR_CONFLICT)
    elif not codes_agree(observed.get("qr_batch"), observed.get("ocr_batch")):
        codes.append(ReasonCode.QR_OCR_CONFLICT)
    elif (
        observed.get("qr_expiry")
        and observed.get("ocr_expiry")
        and observed["qr_expiry"] != observed["ocr_expiry"]
    ):
        codes.append(ReasonCode.QR_OCR_CONFLICT)
    return codes


def _lookup_serial(
    registry: Registry, code: str
) -> Tuple[Optional[SerialRecord], Optional[str]]:
    """Look up a serial, tolerating an OCR glyph confusion.

    Returns the record and the variant spelling that matched, or ``None`` when
    the code matched exactly. The caller records the variant in the evidence so
    a tolerated misread is visible rather than presented as an exact read.
    """
    record = registry.find_serial_by_code(code)
    if record is not None:
        return record, None
    for variant in ocr_variants(code):
        record = registry.find_serial_by_code(variant)
        if record is not None:
            return record, variant
    return None, None


def _lookup_batch(
    registry: Registry, code: str
) -> Tuple[Optional[BatchRecord], Optional[str]]:
    record = registry.find_batch_by_code(code)
    if record is not None:
        return record, None
    for variant in ocr_variants(code):
        record = registry.find_batch_by_code(variant)
        if record is not None:
            return record, variant
    return None, None


def evaluate_identity(
    registry: Registry,
    claimed: ClaimedIdentity,
    observed: Dict[str, Any],
    today: Optional[_dt.date] = None,
) -> Tuple[IdentityEvidence, ProductStatus]:
    """Resolve a claim against the registry and report identity evidence.

    Returns identity evidence and product status as two separate values,
    because a pack can be an authentic unit of an expired batch and the two
    facts must not contaminate one another.
    """
    conflict_codes = cross_check(observed)
    today = today or _dt.datetime.now(_dt.timezone.utc).date()

    serial_code = normalize_serial_code(claimed.serial)
    batch_code = normalize_batch_code(claimed.batch)

    if not serial_code and not batch_code:
        return (
            IdentityEvidence(
                score=0.0,
                state=EvidenceState.UNKNOWN,
                resolved=ResolvedIdentity(verification_level=VerificationLevel.NONE),
                claimed=claimed,
                reason_codes=[ReasonCode.IDENTITY_PARSE_FAILED],
                details={"observed": observed},
            ),
            ProductStatus(state=ProductState.UNKNOWN, recall_status=RecallStatus.UNKNOWN),
        )

    serial_variant = batch_variant = None
    serial_record = None
    if serial_code:
        serial_record, serial_variant = _lookup_serial(registry, serial_code)

    batch_record: Optional[BatchRecord] = None
    if serial_record is not None:
        batch_record = registry.get_batch(serial_record.batch_id)
    elif batch_code:
        batch_record, batch_variant = _lookup_batch(registry, batch_code)

    sku_record = None
    if serial_record is not None:
        sku_record = registry.get_sku(serial_record.sku_id)
    elif batch_record is not None:
        sku_record = registry.get_sku(batch_record.sku_id)

    manufacturer_name = None
    if sku_record is not None:
        manufacturer = registry.get_manufacturer(sku_record.manufacturer_id)
        manufacturer_name = manufacturer.name if manufacturer else None

    product = _product_status(batch_record, today)

    codes: List[ReasonCode] = []
    details: Dict[str, Any] = {"observed": observed}
    if serial_variant:
        details["serial_matched_via_ocr_variant"] = serial_variant
    if batch_variant:
        details["batch_matched_via_ocr_variant"] = batch_variant

    # --- resolved unit ---------------------------------------------------
    if serial_record is not None:
        resolved = ResolvedIdentity(
            manufacturer_id=sku_record.manufacturer_id if sku_record else None,
            manufacturer_name=manufacturer_name,
            sku_id=serial_record.sku_id,
            product_name=sku_record.product_name if sku_record else None,
            batch_id=serial_record.batch_id,
            serial_id=serial_record.serial_id,
            verification_level=VerificationLevel.UNIT,
            serial_status=serial_record.status,
            reference_profile_id=(
                serial_record.reference_profile_id
                or (sku_record.reference_profile_id if sku_record else None)
            ),
        )

        if serial_record.status is SerialStatus.REVOKED:
            codes.append(ReasonCode.SERIAL_REVOKED)
            score = SCORE_REVOKED
            state = EvidenceState.FAIL
        else:
            codes.append(ReasonCode.IDENTITY_VALID)
            score = SCORE_UNIT_VALID if observed.get("ocr_serial") else SCORE_UNIT_VALID_QR_ONLY
            state = EvidenceState.OK

        # A batch claim that contradicts the serial's registered batch means the
        # two identifiers on this pack belong to different units.
        if batch_code and batch_record and not codes_agree(
            batch_code, normalize_batch_code(batch_record.batch_code)
        ):
            conflict_codes = list(conflict_codes) + [ReasonCode.QR_OCR_CONFLICT]
            details["batch_claim_mismatch"] = {
                "claimed": batch_code,
                "registered": batch_record.batch_code,
            }

        codes.extend(conflict_codes)
        if ReasonCode.QR_OCR_CONFLICT in codes:
            score = max(0.0, score - QR_OCR_CONFLICT_PENALTY)
            state = EvidenceState.WARN if state is EvidenceState.OK else state

        return (
            IdentityEvidence(
                score=score,
                state=state,
                resolved=resolved,
                claimed=claimed,
                reason_codes=codes,
                details=details,
            ),
            product,
        )

    # --- serial claimed but not issued -----------------------------------
    if serial_code:
        codes.append(ReasonCode.SERIAL_UNKNOWN)
        if batch_record is not None:
            # Degrade to batch assurance, explicitly. The pack is not verified as
            # a unit, and the response says so through verification_level.
            codes.append(ReasonCode.BATCH_VALID)
            resolved = ResolvedIdentity(
                manufacturer_id=sku_record.manufacturer_id if sku_record else None,
                manufacturer_name=manufacturer_name,
                sku_id=batch_record.sku_id,
                product_name=sku_record.product_name if sku_record else None,
                batch_id=batch_record.batch_id,
                serial_id=None,
                verification_level=VerificationLevel.BATCH,
                serial_status=SerialStatus.UNKNOWN,
                reference_profile_id=sku_record.reference_profile_id if sku_record else None,
            )
            codes.extend(conflict_codes)
            return (
                IdentityEvidence(
                    score=SCORE_SERIAL_UNKNOWN_BATCH_VALID,
                    state=EvidenceState.FAIL,
                    resolved=resolved,
                    claimed=claimed,
                    reason_codes=codes,
                    details=details,
                ),
                product,
            )

        codes.append(ReasonCode.BATCH_UNKNOWN)
        codes.extend(conflict_codes)
        return (
            IdentityEvidence(
                score=SCORE_UNKNOWN,
                state=EvidenceState.FAIL,
                resolved=ResolvedIdentity(verification_level=VerificationLevel.NONE),
                claimed=claimed,
                reason_codes=codes,
                details=details,
            ),
            product,
        )

    # --- batch only ------------------------------------------------------
    if batch_record is not None:
        codes.append(ReasonCode.BATCH_VALID)
        resolved = ResolvedIdentity(
            manufacturer_id=sku_record.manufacturer_id if sku_record else None,
            manufacturer_name=manufacturer_name,
            sku_id=batch_record.sku_id,
            product_name=sku_record.product_name if sku_record else None,
            batch_id=batch_record.batch_id,
            verification_level=VerificationLevel.BATCH,
            serial_status=SerialStatus.UNKNOWN,
            reference_profile_id=sku_record.reference_profile_id if sku_record else None,
        )
        codes.extend(conflict_codes)
        return (
            IdentityEvidence(
                score=SCORE_BATCH_VALID,
                state=EvidenceState.WARN,
                resolved=resolved,
                claimed=claimed,
                reason_codes=codes,
                details=details,
            ),
            product,
        )

    codes.append(ReasonCode.BATCH_UNKNOWN)
    codes.extend(conflict_codes)
    return (
        IdentityEvidence(
            score=SCORE_UNKNOWN,
            state=EvidenceState.FAIL,
            resolved=ResolvedIdentity(verification_level=VerificationLevel.NONE),
            claimed=claimed,
            reason_codes=codes,
            details=details,
        ),
        product,
    )


def _product_status(batch: Optional[BatchRecord], today: _dt.date) -> ProductStatus:
    """Derive product lifecycle status from the batch record.

    Recall state from the registry takes precedence over a date comparison: a
    recalled batch is recalled whether or not it has also expired.
    """
    if batch is None:
        return ProductStatus(state=ProductState.UNKNOWN, recall_status=RecallStatus.UNKNOWN)

    codes: List[ReasonCode] = []

    if batch.recall_status is RecallStatus.RECALLED or batch.state is ProductState.RECALLED:
        return ProductStatus(
            state=ProductState.RECALLED,
            expiry_date=batch.expiry_date,
            recall_status=RecallStatus.RECALLED,
            reason_codes=[ReasonCode.PRODUCT_RECALLED],
        )

    if batch.state is ProductState.WITHDRAWN:
        return ProductStatus(
            state=ProductState.WITHDRAWN,
            expiry_date=batch.expiry_date,
            recall_status=batch.recall_status,
            reason_codes=[],
        )

    expiry = parse_date(batch.expiry_date) if batch.expiry_date else None
    if expiry is not None and expiry < today:
        codes.append(ReasonCode.PRODUCT_EXPIRED)
        return ProductStatus(
            state=ProductState.EXPIRED,
            expiry_date=batch.expiry_date,
            recall_status=batch.recall_status,
            reason_codes=codes,
        )

    return ProductStatus(
        state=ProductState.ACTIVE,
        expiry_date=batch.expiry_date,
        recall_status=batch.recall_status,
        reason_codes=codes,
    )
