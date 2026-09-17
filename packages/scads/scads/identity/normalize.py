"""Deterministic normalisation of identity fields.

OCR and QR payloads disagree about punctuation, spacing and date formats, so
comparison happens on normalised values. Every rule here is a pure string
function with a test — no model inference. ``AGENTS.md`` section 6.1 is explicit
that an unknown serial cannot be turned into a valid one by inference, and the
cheapest way to guarantee that is for normalisation to be incapable of it.
"""

import re
from typing import Optional

from ..util.clock import parse_date

_WHITESPACE = re.compile(r"\s+")
_NON_CODE = re.compile(r"[^A-Z0-9-]")

# Characters OCR confuses on printed packaging. Applied only when generating an
# *additional* candidate spelling for lookup, never to rewrite the value that
# gets reported, so a lookup can recover from O/0 confusion without the result
# claiming the pack said something it did not.
_OCR_CONFUSIONS = (("O", "0"), ("I", "1"), ("L", "1"), ("S", "5"), ("B", "8"), ("Z", "2"))


def normalize_code(value: Optional[str]) -> Optional[str]:
    """Upper-case, strip, and remove characters that cannot appear in a code."""
    if not value:
        return None
    text = _WHITESPACE.sub("", str(value).strip().upper())
    text = _NON_CODE.sub("", text)
    return text or None


def normalize_serial_code(value: Optional[str]) -> Optional[str]:
    code = normalize_code(value)
    if not code or len(code) < 4 or len(code) > 48:
        return None
    return code


def normalize_batch_code(value: Optional[str]) -> Optional[str]:
    code = normalize_code(value)
    if not code or len(code) < 3 or len(code) > 32:
        return None
    return code


def ocr_variants(code: Optional[str]) -> list:
    """Alternative spellings to try when a code is not found as printed.

    Two shapes of misread, because real OCR produces both:

    * **Systematic** — every instance of one glyph is confused the same way,
      since it is the same glyph in the same font under the same lighting.
      ``SER-A-001`` read as ``SER-A-OO1`` is one error, not two.
    * **Isolated** — a single character is misread, typically where the
      overprint is smudged.

    Bounded to one confusion pair at a time and capped, so the candidate set
    stays small and a lookup cannot wander to an unrelated serial.

    Caveat worth recording: if two issued serials differ *only* by a confusable
    pair, this could resolve the wrong unit. Production serial issuance should
    exclude confusable glyphs — or carry a check digit — rather than rely on
    this being unlikely. When a variant is what matched, the identity evidence
    records that fact instead of presenting it as an exact read.
    """
    if not code:
        return []
    variants = []
    for source, target in _OCR_CONFUSIONS:
        for a, b in ((source, target), (target, source)):
            if a in code:
                # Systematic: replace every occurrence.
                variants.append(code.replace(a, b))
                # Isolated: replace one occurrence at a time.
                for index, char in enumerate(code):
                    if char == a:
                        variants.append(code[:index] + b + code[index + 1 :])
    seen = set()
    unique = []
    for variant in variants:
        if variant != code and variant not in seen:
            seen.add(variant)
            unique.append(variant)
    return unique[:48]


_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def normalize_expiry(value: Optional[str]) -> Optional[str]:
    """Normalise an expiry to ``YYYY-MM-DD``.

    Packs print expiry many ways: ``08/2027``, ``AUG 2027``, ``270831``,
    ``2027-08-31``. A month-only expiry is resolved to the **last day of that
    month**, which is the pharmaceutical convention — a pack marked ``08/2027``
    is usable through 31 August 2027, and choosing the first of the month would
    expire genuine stock a month early.
    """
    if not value:
        return None
    text = _WHITESPACE.sub(" ", str(value).strip().upper())
    if not text:
        return None

    iso = parse_date(text)
    if iso:
        return iso.isoformat()

    # YYMMDD (GS1 AI 17). A 00 day means "end of month" in GS1.
    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", text)
    if match:
        year = 2000 + int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        if 1 <= month <= 12:
            if day == 0:
                return _end_of_month(year, month)
            try:
                import datetime

                return datetime.date(year, month, day).isoformat()
            except ValueError:
                return _end_of_month(year, month)

    # MM/YYYY, MM-YYYY, MM.YYYY
    match = re.fullmatch(r"(\d{1,2})[/\-. ](\d{4})", text)
    if match and 1 <= int(match.group(1)) <= 12:
        return _end_of_month(int(match.group(2)), int(match.group(1)))

    # MM/YY
    match = re.fullmatch(r"(\d{1,2})[/\-. ](\d{2})", text)
    if match and 1 <= int(match.group(1)) <= 12:
        return _end_of_month(2000 + int(match.group(2)), int(match.group(1)))

    # MON YYYY / MONYYYY / MON-YY
    match = re.fullmatch(r"([A-Z]{3,4})[\-/. ]?(\d{2,4})", text)
    if match and match.group(1) in _MONTHS:
        year = int(match.group(2))
        if year < 100:
            year += 2000
        return _end_of_month(year, _MONTHS[match.group(1)])

    # YYYY-MM
    match = re.fullmatch(r"(\d{4})[\-/. ](\d{1,2})", text)
    if match and 1 <= int(match.group(2)) <= 12:
        return _end_of_month(int(match.group(1)), int(match.group(2)))

    return None


def _end_of_month(year: int, month: int) -> str:
    import calendar
    import datetime

    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last).isoformat()


def normalize_manufacturer(value: Optional[str]) -> Optional[str]:
    """Normalise a manufacturer name for comparison.

    Company suffixes are dropped because packs and registries disagree about
    them ("Demo Pharma Ltd" vs "DEMO PHARMA LIMITED").
    """
    if not value:
        return None
    text = _WHITESPACE.sub(" ", str(value).strip().upper())
    text = re.sub(r"[.,]", "", text)
    for suffix in (
        " PRIVATE LIMITED", " PVT LTD", " PVT LIMITED", " LIMITED", " LTD",
        " INCORPORATED", " INC", " LLP", " LLC", " GMBH", " PLC", " CO",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return _WHITESPACE.sub(" ", text).strip() or None


def codes_agree(left: Optional[str], right: Optional[str]) -> bool:
    """Whether two codes refer to the same thing.

    ``None`` on either side is *not* disagreement — it means one source did not
    report the field. Treating a missing OCR read as a conflict would flag
    genuine packs whose batch overprint happened to be unreadable.
    """
    if not left or not right:
        return True
    if left == right:
        return True
    return right in ocr_variants(left)
