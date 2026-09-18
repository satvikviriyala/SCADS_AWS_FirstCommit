"""Reference enrollment: measure the artwork rather than describe it.

Enrollment renders the reference pack and reads back where the words actually
landed. Hand-written anchor coordinates were the alternative, and they do not
work: the text-layout feature compares measured OCR positions against enrolled
positions, so every hand-guessed anchor carries a constant offset that swamps
the displacement the feature exists to detect. Measured across the corpus,
guessed anchors held ``text_layout`` at 0.69 for every fixture — genuine and
tampered alike — because the baseline error was larger than the signal.

This mirrors real enrollment, where a manufacturer supplies artwork and the
anchor positions are measured from it.
"""

from dataclasses import replace
from typing import Dict, List, Optional, Sequence

from ..contracts.records import BatchRecord, OcrAnchor, ReferenceProfile, SkuRecord

# Anchor name -> how to find its token in the rendered artwork.
#
# Only *stable* text is anchored. Batch and expiry are checked against the
# registry instead, because they differ legitimately between packs and anchoring
# them would flag every new batch as displaced
# (``docs/SCORING_AND_DETECTION.md`` section 6.1).
STABLE_ANCHORS = ("brand", "form", "strength", "manufacturer", "warning")

# Displacement tolerance, as a fraction of pack width. The layout score reaches
# zero at three times this, so a word must move ~18% of the pack's width to
# score nothing at all.
DEFAULT_TOLERANCE = 0.06


def _token_for(name: str, sku: SkuRecord) -> Optional[str]:
    if name == "brand":
        source = sku.generic_name or sku.product_name
        return source.split()[0].upper() if source else None
    if name == "form":
        form = (sku.form or "TABLET").upper()
        return form if form.endswith("S") else form + "S"
    if name == "strength":
        strength = (sku.strength or "").upper()
        return strength.split()[0] if strength else None
    if name == "manufacturer":
        return "DEMO"
    if name == "warning":
        return "PRESCRIPTION"
    return None


def measure_anchors(
    template: ReferenceProfile, sku: SkuRecord, batch: BatchRecord
) -> ReferenceProfile:
    """Render ``template``'s artwork and return it with measured anchors.

    The rendering does not depend on anchors, so there is no circularity: the
    artwork is drawn from the ROI layout, then the anchors are read off it.
    """
    from .render import Tamper, render_pack

    pack = render_pack(
        profile=template,
        sku=sku,
        batch=batch,
        serial=None,
        qr_payload=None,
        tamper=Tamper(),
    )

    by_text: Dict[str, List] = {}
    for word in pack.words:
        by_text.setdefault(word.text.strip().upper(), []).append(word)

    anchors: List[OcrAnchor] = []
    for name in STABLE_ANCHORS:
        token = _token_for(name, sku)
        if not token:
            continue
        candidates = by_text.get(token)
        if not candidates:
            # The token was not drawn — usually because a text block clipped it.
            # Skipping is correct: an anchor for text that is not on the pack
            # would mark every genuine pack as missing it.
            continue
        word = candidates[0]
        anchors.append(
            OcrAnchor(name=name, text=token, x=word.x, y=word.y, tolerance=DEFAULT_TOLERANCE)
        )

    return replace(template, ocr_anchors=anchors)


def enroll_all(
    templates: Sequence[ReferenceProfile],
    skus: Sequence[SkuRecord],
    batches: Sequence[BatchRecord],
) -> List[ReferenceProfile]:
    """Enroll each template against its product's first active batch."""
    sku_by_id = {s.sku_id: s for s in skus}
    enrolled: List[ReferenceProfile] = []
    for template in templates:
        sku = sku_by_id.get(template.sku_id)
        if sku is None:
            continue
        batch = next((b for b in batches if b.sku_id == template.sku_id), None)
        if batch is None:
            continue
        enrolled.append(measure_anchors(template, sku, batch))
    return enrolled
