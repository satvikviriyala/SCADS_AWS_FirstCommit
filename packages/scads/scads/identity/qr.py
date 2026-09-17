"""QR payload parsing.

Three payload shapes are accepted, in order of specificity:

1. **SCADS demo payload** — a pipe-delimited key/value form used by the seeded
   demo packs.
2. **GS1 element strings** — ``(01)`` GTIN, ``(10)`` batch, ``(21)`` serial,
   ``(17)`` expiry, as used by DSCSA/FMD serialisation and by Indian Schedule
   H2 QR requirements (``docs/RESEARCH_NOTES.md``).
3. **JSON** — an object with recognisable field names.

The parser's contract is deliberately narrow: **a parsed payload is a claim, not
a verification.** Successfully decoding a QR code establishes only that
something was printed on the pack. Whether that identity was ever issued is a
separate registry question, and whether this is the pack it was issued for is a
physical and historical question. Conflating the three is exactly the weakness
SCADS exists to expose.
"""

import json
import re
from typing import Dict, Optional

from ..contracts.models import ClaimedIdentity
from .normalize import normalize_batch_code, normalize_expiry, normalize_serial_code

# Upper bound on anything we will try to parse. QR payloads on medicine packs
# are short; a megabyte of "payload" is an abuse attempt, not a pack.
MAX_PAYLOAD_CHARS = 2048

_SCADS_PREFIX = "SCADS1"

# GS1 element strings, with and without human-readable parentheses.
_GS1_AI_PATTERN = re.compile(
    r"\((?P<ai>01|10|17|21|11)\)(?P<value>[^(]{1,48})"
)
_GS1_FIXED = {
    "01": 14,  # GTIN-14
    "17": 6,   # YYMMDD expiry
    "11": 6,   # YYMMDD production date
}
_GS1_SEPARATOR = "\x1d"  # FNC1 / group separator


def parse_qr_payload(payload: Optional[str]) -> ClaimedIdentity:
    """Parse a raw QR payload into a claimed identity.

    Never raises on malformed input: an unreadable payload means "no identity
    claim from the code", which the identity evaluator handles by falling back
    to OCR. A parser exception would turn a smudged code into a server error.
    """
    if not payload or not isinstance(payload, str):
        return ClaimedIdentity(source="NONE")

    text = payload.strip()
    if len(text) > MAX_PAYLOAD_CHARS:
        return ClaimedIdentity(source="NONE")

    for parser in (_parse_scads, _parse_json, _parse_gs1, _parse_loose):
        claimed = parser(text)
        if claimed is not None:
            return claimed
    return ClaimedIdentity(source="NONE")


def _parse_scads(text: str) -> Optional[ClaimedIdentity]:
    """``SCADS1|SN:<serial>|BN:<batch>|GTIN:<gtin>|EXP:<yyyy-mm-dd>|...``"""
    if not text.upper().startswith(_SCADS_PREFIX):
        return None
    fields: Dict[str, str] = {}
    for part in text.split("|")[1:]:
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        fields[key.strip().upper()] = value.strip()
    return ClaimedIdentity(
        serial=normalize_serial_code(fields.get("SN")),
        batch=normalize_batch_code(fields.get("BN")),
        gtin=fields.get("GTIN") or None,
        product_name=fields.get("PN") or None,
        manufacturer_name=fields.get("MFG") or None,
        expiry=normalize_expiry(fields.get("EXP")),
        source="QR",
    )


def _parse_json(text: str) -> Optional[ClaimedIdentity]:
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def pick(*names):
        for name in names:
            value = data.get(name)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        return None

    return ClaimedIdentity(
        serial=normalize_serial_code(pick("serial", "sn", "serial_number", "unique_code")),
        batch=normalize_batch_code(pick("batch", "bn", "batch_no", "lot", "lot_number")),
        gtin=pick("gtin", "product_code", "upc"),
        product_name=pick("product", "product_name", "brand"),
        manufacturer_name=pick("manufacturer", "mfg", "mfr"),
        expiry=normalize_expiry(pick("expiry", "exp", "expiry_date", "use_by")),
        source="QR",
    )


def _parse_gs1(text: str) -> Optional[ClaimedIdentity]:
    """Parse GS1 element strings.

    Handles the bracketed human-readable form, and the FNC1-separated form by
    consuming the fixed-length AIs (01/17/11) and treating 10/21 as
    variable-length up to the next separator.
    """
    fields: Dict[str, str] = {}

    for match in _GS1_AI_PATTERN.finditer(text):
        fields.setdefault(match.group("ai"), match.group("value").strip())

    if not fields and (_GS1_SEPARATOR in text or text[:2] in _GS1_FIXED):
        fields.update(_parse_gs1_unbracketed(text))

    if not fields:
        return None

    return ClaimedIdentity(
        serial=normalize_serial_code(fields.get("21")),
        batch=normalize_batch_code(fields.get("10")),
        gtin=fields.get("01"),
        expiry=normalize_expiry(fields.get("17")),
        source="QR",
    )


def _parse_gs1_unbracketed(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    cursor = 0
    length = len(text)
    while cursor + 2 <= length:
        ai = text[cursor : cursor + 2]
        cursor += 2
        if ai in _GS1_FIXED:
            size = _GS1_FIXED[ai]
            fields.setdefault(ai, text[cursor : cursor + size])
            cursor += size
        elif ai in ("10", "21"):
            end = text.find(_GS1_SEPARATOR, cursor)
            if end == -1:
                end = length
            fields.setdefault(ai, text[cursor:end])
            cursor = end + 1
        else:
            # Unknown AI: we cannot know its length, so stop rather than guess
            # and mis-slice the remainder into the wrong fields.
            break
    return {k: v.strip() for k, v in fields.items() if v.strip()}


_LOOSE_SERIAL = re.compile(r"\b(?:SN|SERIAL)[:=\s-]*([A-Z0-9][A-Z0-9-]{3,31})\b", re.I)
_LOOSE_BATCH = re.compile(r"\b(?:BN|BATCH|LOT|B\.?NO)[:=\s.]*([A-Z0-9][A-Z0-9-]{2,23})\b", re.I)


def _parse_loose(text: str) -> Optional[ClaimedIdentity]:
    """Last resort: labelled serial/batch inside arbitrary text.

    Some manufacturers encode a URL with query parameters, or plain labelled
    text. Only explicitly *labelled* values are accepted — guessing that a bare
    alphanumeric token is a serial would invent identity claims the pack never
    made.
    """
    serial_match = _LOOSE_SERIAL.search(text)
    batch_match = _LOOSE_BATCH.search(text)
    if not serial_match and not batch_match:
        return None
    return ClaimedIdentity(
        serial=normalize_serial_code(serial_match.group(1)) if serial_match else None,
        batch=normalize_batch_code(batch_match.group(1)) if batch_match else None,
        source="QR",
    )


def build_demo_payload(
    serial: str,
    batch: str,
    gtin: Optional[str] = None,
    expiry: Optional[str] = None,
    product: Optional[str] = None,
    manufacturer: Optional[str] = None,
) -> str:
    """Build a SCADS demo QR payload. Used by the fixture generator and seeds."""
    parts = [_SCADS_PREFIX, "SN:" + serial, "BN:" + batch]
    if gtin:
        parts.append("GTIN:" + gtin)
    if expiry:
        parts.append("EXP:" + expiry)
    if product:
        parts.append("PN:" + product)
    if manufacturer:
        parts.append("MFG:" + manufacturer)
    return "|".join(parts)
