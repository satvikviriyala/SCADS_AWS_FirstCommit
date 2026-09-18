"""Synthetic medicine-pack rendering and capture simulation.

Used to build the evaluation corpus and the demo fixtures. Two stages, kept
separate because they model different things:

``render_pack``
    Draws a carton front at canonical resolution — the artwork itself. This is
    what gets enrolled as a reference, and what a tamper perturbs.
``simulate_capture``
    Projects a carton into a photograph: perspective, rotation, background,
    lighting, sensor noise, JPEG compression. This is what a phone would send.

Keeping them apart is what makes the corpus meaningful. A tamper is applied to
the *artwork*, then photographed, so the pipeline faces the same problem it
faces in reality: recover the artwork through an unknown camera transform, then
decide whether it matches.

**What this corpus can and cannot support.** Synthetic tampering is a
controlled proxy for measuring sensitivity — it shows which feature responds to
which kind of change. It is not a counterfeit benchmark, and no accuracy claim
about real counterfeits can be derived from it. ``docs/EVALUATION.md`` section 1
and ``docs/RESEARCH_NOTES.md`` state this; fixtures produced here are labelled
``synthetic_tamper``, never "counterfeit".
"""

import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..contracts.records import BatchRecord, ReferenceProfile, SerialRecord, SkuRecord
from ..physical.registration import apply_homography, compute_homography

# Ink and card tones. Not pure black on pure white: real cartons are not, and a
# perfect binary image would make the print-sharpness feature meaningless.
CARD = 246
INK = 28
ACCENT = 96


@dataclass(frozen=True)
class WordBox:
    """A rendered word and where it ended up, in normalised coordinates."""

    text: str
    x: float
    y: float
    width: float
    height: float

    def to_payload(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "x": round(self.x, 5),
            "y": round(self.y, 5),
            "width": round(self.width, 5),
            "height": round(self.height, 5),
            "confidence": 99.0,
        }


@dataclass
class RenderedPack:
    image: "Image.Image"
    words: List[WordBox] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)

    @property
    def size(self) -> Tuple[int, int]:
        return self.image.size


@dataclass(frozen=True)
class Tamper:
    """One controlled perturbation of the artwork.

    ``kind`` names the mechanism; ``strength`` scales it in [0, 1] so a slider
    can sweep sensitivity (``docs/EVALUATION.md`` section 3).
    """

    kind: str = "none"
    strength: float = 0.0
    target: str = ""

    @property
    def is_none(self) -> bool:
        return self.kind == "none" or self.strength <= 0.0


def _font(size: int) -> "ImageFont.FreeTypeFont":
    """A scalable font with no external file dependency.

    Pillow's bundled default is used deliberately: fixture rendering must be
    byte-reproducible on any machine, and reaching for a system font would make
    the corpus depend on the operating system it was generated on.
    """
    return ImageFont.load_default(size=size)


def _draw_text_block(
    draw: "ImageDraw.ImageDraw",
    text: str,
    box: Tuple[int, int, int, int],
    size: int,
    frame: Tuple[int, int],
    fill: int = INK,
    offset: Tuple[int, int] = (0, 0),
) -> List[WordBox]:
    """Draw one line of text inside ``box`` and return its word geometry."""
    left, top, right, bottom = box
    font = _font(size)
    words: List[WordBox] = []

    cursor_x = left + offset[0]
    baseline_y = top + offset[1]
    frame_w, frame_h = frame

    space = draw.textlength(" ", font=font)
    for token in text.split():
        length = draw.textlength(token, font=font)
        if cursor_x + length > right and cursor_x > left:
            break
        draw.text((cursor_x, baseline_y), token, font=font, fill=fill)
        bbox = font.getbbox(token)
        height = max(1, bbox[3] - bbox[1])
        words.append(
            WordBox(
                text=token,
                x=(cursor_x + length / 2.0) / frame_w,
                y=(baseline_y + bbox[1] + height / 2.0) / frame_h,
                width=length / frame_w,
                height=height / frame_h,
            )
        )
        cursor_x += length + space
    return words


def _qr_image(payload: str, size: int) -> Optional["Image.Image"]:
    """Render a QR code, or ``None`` if the generator is unavailable.

    ``segno`` is a pure-Python development dependency used only for fixtures; it
    is not part of the deployed package.
    """
    try:
        import segno
    except ImportError:
        return None
    code = segno.make(payload, error="m")
    buffer = io.BytesIO()
    code.save(buffer, kind="png", scale=6, border=2)
    buffer.seek(0)
    with Image.open(buffer) as handle:
        return handle.convert("L").resize((size, size), Image.NEAREST)


def render_pack(
    profile: ReferenceProfile,
    sku: SkuRecord,
    batch: BatchRecord,
    serial: Optional[SerialRecord],
    qr_payload: Optional[str] = None,
    tamper: Optional[Tamper] = None,
    printed_batch_code: Optional[str] = None,
    printed_serial_code: Optional[str] = None,
) -> RenderedPack:
    """Render a carton front matching ``profile``'s enrolled ROI layout.

    ``printed_batch_code`` / ``printed_serial_code`` override what is *printed*
    without changing what the QR encodes, which is how a QR-versus-print
    conflict fixture is built.
    """
    tamper = tamper or Tamper()
    width, height = profile.canonical_width, profile.canonical_height
    frame = (width, height)

    image = Image.new("L", frame, CARD)
    draw = ImageDraw.Draw(image)
    words: List[WordBox] = []
    lines: List[str] = []

    rois = {roi.name: roi for roi in profile.stable_rois}

    def box_of(name: str) -> Tuple[int, int, int, int]:
        return rois[name].pixel_box(width, height)

    # --- outer card edge, so the pack detector has a boundary to find --------
    draw.rectangle([2, 2, width - 3, height - 3], outline=ACCENT, width=3)

    # --- brand block --------------------------------------------------------
    brand_offset = (0, 0)
    if tamper.kind == "text_shift" and tamper.target in ("", "brand_block"):
        brand_offset = (int(round(26 * tamper.strength)), int(round(10 * tamper.strength)))
    left, top, right, bottom = box_of("brand_block")
    brand = sku.generic_name.upper() if sku.generic_name else sku.product_name.upper()
    words += _draw_text_block(
        draw, brand, (left + 6, top + 8, right, bottom), 56, frame, INK, brand_offset
    )
    lines.append(brand)
    draw.line([left + 6, bottom - 6, right - 10, bottom - 6], fill=ACCENT, width=3)

    # --- generic / form line ------------------------------------------------
    left, top, right, bottom = box_of("generic_line")
    form_line = (sku.form or "TABLETS").upper()
    if not form_line.endswith("S"):
        form_line += "S"
    words += _draw_text_block(draw, form_line, (left + 6, top + 4, right, bottom), 34, frame)
    lines.append(form_line)

    # --- strength -----------------------------------------------------------
    left, top, right, bottom = box_of("strength_block")
    strength = (sku.strength or "500 mg").upper()
    words += _draw_text_block(draw, strength, (left + 6, top + 4, right, bottom), 40, frame)
    lines.append(strength)

    # --- warning strip ------------------------------------------------------
    left, top, right, bottom = box_of("warning_strip")
    # Inset inside the ROI. Drawing a 2 px line exactly on a region boundary is
    # an artefact of the fixture, not of real packaging: the crop would bisect
    # the line, so any sub-pixel misalignment moves it in and out of the
    # compared window and dominates that region's score.
    draw.rectangle([left + 5, top + 4, right - 5, bottom - 4], outline=INK, width=2)
    words += _draw_text_block(
        draw, "PRESCRIPTION ONLY KEEP AWAY FROM CHILDREN", (left + 8, top + 6, right - 4, bottom), 22, frame
    )
    lines.append("PRESCRIPTION ONLY KEEP AWAY FROM CHILDREN")

    # --- manufacturer block -------------------------------------------------
    left, top, right, bottom = box_of("manufacturer_block")
    words += _draw_text_block(draw, "DEMO PHARMA LTD", (left + 6, top + 4, right, bottom), 26, frame)
    words += _draw_text_block(
        draw, "MFG LIC DEMO-MFG-0001", (left + 6, top + 36, right, bottom), 20, frame
    )
    words += _draw_text_block(
        draw, "MADE IN INDIA", (left + 6, top + 62, right, bottom), 20, frame
    )
    lines += ["DEMO PHARMA LTD", "MFG LIC DEMO-MFG-0001", "MADE IN INDIA"]

    # --- logo mark ----------------------------------------------------------
    logo_offset = (0, 0)
    if tamper.kind == "logo_shift":
        logo_offset = (int(round(30 * tamper.strength)), int(round(18 * tamper.strength)))
    left, top, right, bottom = box_of("logo_mark")
    _draw_logo(draw, (left + logo_offset[0], top + logo_offset[1], right + logo_offset[0], bottom + logo_offset[1]))

    # --- QR zone (dynamic) --------------------------------------------------
    left, top, right, bottom = box_of("qr_zone")
    if qr_payload:
        side = min(right - left, bottom - top) - 6
        qr = _qr_image(qr_payload, max(24, side))
        if qr is not None:
            image.paste(qr, (left + 4, top + 4))

    # --- batch overprint (dynamic) -----------------------------------------
    left, top, right, bottom = box_of("batch_overprint")
    batch_code = printed_batch_code or batch.batch_code
    serial_code = printed_serial_code or (serial.serial_code if serial else "")
    expiry_text = (batch.expiry_date or "")[:7].replace("-", "/")

    words += _draw_text_block(draw, "B.NO " + batch_code, (left, top, right, bottom), 20, frame)
    words += _draw_text_block(draw, "EXP " + expiry_text, (left, top + 26, right, bottom), 20, frame)
    if serial_code:
        words += _draw_text_block(draw, "SN " + serial_code, (left, top + 52, right, bottom), 20, frame)
    lines += ["B.NO " + batch_code, "EXP " + expiry_text]
    if serial_code:
        lines.append("SN " + serial_code)

    # --- artwork-level tampers ---------------------------------------------
    image = _apply_artwork_tamper(image, profile, tamper)

    return RenderedPack(image=image, words=words, lines=lines)


def _draw_logo(draw: "ImageDraw.ImageDraw", box: Tuple[int, int, int, int]) -> None:
    """A deterministic geometric mark: concentric frame plus a cross and chord."""
    left, top, right, bottom = box
    draw.rectangle([left, top, right - 4, bottom - 4], outline=INK, width=4)
    inset = 14
    draw.ellipse([left + inset, top + inset, right - 4 - inset, bottom - 4 - inset], outline=INK, width=5)
    cx = (left + right - 4) // 2
    cy = (top + bottom - 4) // 2
    draw.line([cx, top + inset + 6, cx, bottom - 4 - inset - 6], fill=INK, width=5)
    draw.line([left + inset + 6, cy, right - 4 - inset - 6, cy], fill=INK, width=5)
    draw.line([left + inset, bottom - 4 - inset, right - 4 - inset, top + inset], fill=ACCENT, width=3)


def _apply_artwork_tamper(
    image: "Image.Image", profile: ReferenceProfile, tamper: Tamper
) -> "Image.Image":
    """Apply a perturbation to the rendered artwork."""
    if tamper.is_none:
        return image

    width, height = image.size

    if tamper.kind == "reprint":
        # Photocopy proxy: softened ink with reduced contrast, applied to the
        # printed interior only.
        #
        # The carton's outer border is deliberately left crisp. A counterfeit
        # carton is physically cut and folded, so its edges are as sharp as a
        # genuine one however badly the artwork is printed. Blurring the border
        # too — as an earlier version of this did — makes the whole photograph
        # look out of focus, which the quality gate then (correctly) rejects as
        # a bad capture. That confounds the two things this fixture is meant to
        # separate: a soft *photograph* and soft *printing*. Keeping the border
        # sharp gives the print-sharpness feature a signal that capture quality
        # cannot explain away.
        radius = 0.6 + 2.6 * tamper.strength
        blurred = image.filter(ImageFilter.GaussianBlur(radius=radius))
        array = np.asarray(blurred, dtype=np.float32)
        midpoint = float(array.mean())
        contrast = 1.0 - 0.45 * tamper.strength
        array = midpoint + (array - midpoint) * contrast
        softened = np.clip(array, 0, 255).astype(np.uint8)

        # Degrade the printed regions only. A photocopy or low-grade reprint
        # loses fine detail — small text, thin rules, halftone — while large
        # shapes and the carton's physical edge stay crisp. Softening the entire
        # image instead makes the whole photograph look out of focus, which the
        # quality gate then rejects as a bad capture, and the fixture stops
        # testing anything about printing.
        combined = np.asarray(image, dtype=np.uint8).copy()
        for roi in profile.stable_rois:
            if roi.dynamic:
                continue
            left, top, right, bottom = roi.pixel_box(width, height)
            combined[top:bottom, left:right] = softened[top:bottom, left:right]
        return Image.fromarray(combined)

    if tamper.kind == "patch":
        # Structural replacement: overwrite a stable region with flat card plus a
        # crude re-draw. Targets the structural feature.
        target = tamper.target or "warning_strip"
        roi = next((r for r in profile.stable_rois if r.name == target), None)
        if roi is None:
            return image
        left, top, right, bottom = roi.pixel_box(width, height)
        shrink = 1.0 - tamper.strength
        keep = int((bottom - top) * shrink)
        draw = ImageDraw.Draw(image)
        draw.rectangle([left, top + keep, right, bottom], fill=CARD)
        if tamper.strength > 0.4:
            draw.rectangle([left + 4, top + keep + 4, right - 4, bottom - 4], outline=ACCENT, width=2)
        return image

    if tamper.kind == "color_cast":
        rgb = image.convert("RGB")
        array = np.asarray(rgb, dtype=np.float32)
        array[:, :, 0] *= 1.0 + 0.30 * tamper.strength
        array[:, :, 2] *= 1.0 - 0.30 * tamper.strength
        return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).convert("L")

    if tamper.kind == "resample":
        # Local resampling artefact: downscale and upscale, losing fine detail.
        factor = max(0.25, 1.0 - 0.7 * tamper.strength)
        small = image.resize(
            (max(8, int(width * factor)), max(8, int(height * factor))), Image.BILINEAR
        )
        return small.resize((width, height), Image.BILINEAR)

    # text_shift and logo_shift are applied during drawing.
    return image


# --------------------------------------------------------------------------
# Capture simulation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureSettings:
    """How a pack is photographed.

    Defaults describe a competent handheld capture: slightly off-axis, mild
    perspective, a little motion blur and sensor noise, JPEG compressed. A
    genuine pack captured this way must still pass, which is the false-positive
    side of the evaluation (``docs/EVALUATION.md`` section 2).
    """

    frame_width: int = 1280
    frame_height: int = 960
    pack_scale: float = 0.74
    rotation_deg: float = 3.0
    perspective: float = 0.035
    offset_x: float = 0.0
    offset_y: float = 0.0
    background: int = 96
    background_texture: float = 0.05
    blur_sigma: float = 0.7
    noise: float = 0.012
    brightness: float = 1.0
    contrast: float = 1.0
    glare: float = 0.0
    jpeg_quality: Optional[int] = 88
    seed: int = 12345


def _destination_quad(settings: CaptureSettings, aspect: float) -> np.ndarray:
    """Where the pack's corners land in the photograph."""
    frame_w, frame_h = settings.frame_width, settings.frame_height

    pack_w = frame_w * settings.pack_scale
    pack_h = pack_w / aspect
    if pack_h > frame_h * settings.pack_scale:
        pack_h = frame_h * settings.pack_scale
        pack_w = pack_h * aspect

    cx = frame_w / 2.0 + settings.offset_x * frame_w
    cy = frame_h / 2.0 + settings.offset_y * frame_h

    half_w, half_h = pack_w / 2.0, pack_h / 2.0
    corners = np.array(
        [[-half_w, -half_h], [half_w, -half_h], [half_w, half_h], [-half_w, half_h]],
        dtype=np.float64,
    )

    # Perspective: shrink the top edge and stretch the bottom, as when a pack is
    # photographed from slightly above.
    corners[0, 0] *= 1.0 - settings.perspective
    corners[1, 0] *= 1.0 - settings.perspective
    corners[0, 1] *= 1.0 - settings.perspective * 0.5
    corners[1, 1] *= 1.0 - settings.perspective * 0.5

    theta = np.radians(settings.rotation_deg)
    rotation = np.array(
        [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]], dtype=np.float64
    )
    corners = corners @ rotation.T
    corners += np.array([cx, cy])
    return corners


def simulate_capture(
    pack: RenderedPack, settings: Optional[CaptureSettings] = None
) -> Tuple["Image.Image", List[WordBox]]:
    """Photograph a rendered pack, returning the image and projected word boxes.

    The word boxes are mapped through the same homography as the pixels, so the
    OCR ground truth describes the *photograph*, exactly as a real OCR service
    would. Without that, the layout feature would be tested against coordinates
    no OCR engine could produce.
    """
    settings = settings or CaptureSettings()
    rng = np.random.default_rng(settings.seed)

    pack_gray = np.asarray(pack.image.convert("L"), dtype=np.float32) / 255.0
    pack_h, pack_w = pack_gray.shape
    aspect = pack_w / float(pack_h)

    destination = _destination_quad(settings, aspect)
    source = np.array(
        [[0.0, 0.0], [pack_w, 0.0], [pack_w, pack_h], [0.0, pack_h]], dtype=np.float64
    )

    canonical_to_frame = compute_homography(source, destination)
    frame_to_canonical = compute_homography(destination, source)
    if canonical_to_frame is None or frame_to_canonical is None:
        raise ValueError("capture geometry is degenerate")

    frame_w, frame_h = settings.frame_width, settings.frame_height

    # Background: flat tone plus low-frequency texture, so the pack detector has
    # a realistic surface to separate the carton from.
    background = np.full((frame_h, frame_w), settings.background / 255.0, dtype=np.float32)
    if settings.background_texture > 0:
        coarse = rng.normal(0.0, settings.background_texture, size=(frame_h // 16 + 2, frame_w // 16 + 2))
        texture = np.asarray(
            Image.fromarray(np.clip(coarse * 255 + 128, 0, 255).astype(np.uint8)).resize(
                (frame_w, frame_h), Image.BILINEAR
            ),
            dtype=np.float32,
        )
        background += (texture - 128.0) / 255.0

    # Inverse-map every frame pixel into the pack, and mask to the quad.
    ys, xs = np.mgrid[0:frame_h, 0:frame_w]
    grid = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], axis=1).astype(np.float64)
    mapped = apply_homography(frame_to_canonical, grid)
    mx = mapped[:, 0]
    my = mapped[:, 1]
    inside = (mx >= 0) & (mx < pack_w) & (my >= 0) & (my < pack_h)

    sampled = np.zeros(mx.shape, dtype=np.float32)
    if inside.any():
        sampled[inside] = _bilinear(pack_gray, mx[inside], my[inside])

    composite = background.copy()
    mask = inside.reshape(frame_h, frame_w)
    composite[mask] = sampled.reshape(frame_h, frame_w)[mask]

    # A soft shadow under the pack edge, which real photographs always have.
    shadow = np.asarray(
        Image.fromarray((mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=9)
        ),
        dtype=np.float32,
    ) / 255.0
    composite = np.where(mask, composite, composite * (1.0 - 0.35 * shadow))

    if settings.glare > 0:
        composite = _add_glare(composite, settings, rng)

    if settings.contrast != 1.0:
        composite = 0.5 + (composite - 0.5) * settings.contrast
    if settings.brightness != 1.0:
        composite = composite * settings.brightness

    if settings.blur_sigma > 0:
        composite = np.asarray(
            Image.fromarray(np.clip(composite * 255, 0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(radius=settings.blur_sigma)
            ),
            dtype=np.float32,
        ) / 255.0

    if settings.noise > 0:
        composite = composite + rng.normal(0.0, settings.noise, size=composite.shape)

    image = Image.fromarray(np.clip(composite * 255, 0, 255).astype(np.uint8)).convert("RGB")

    if settings.jpeg_quality:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=int(settings.jpeg_quality))
        buffer.seek(0)
        with Image.open(buffer) as handle:
            image = handle.convert("RGB")

    words = _project_words(pack.words, canonical_to_frame, pack_w, pack_h, frame_w, frame_h)
    return image, words


def _bilinear(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    max_x = image.shape[1] - 1
    max_y = image.shape[0] - 1
    x = np.clip(x - 0.5, 0, max_x)
    y = np.clip(y - 0.5, 0, max_y)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, max_x)
    y1 = np.minimum(y0 + 1, max_y)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    top = image[y0, x0] * (1 - fx) + image[y0, x1] * fx
    bottom = image[y1, x0] * (1 - fx) + image[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def _add_glare(
    composite: np.ndarray, settings: CaptureSettings, rng: np.random.Generator
) -> np.ndarray:
    """A broad specular reflection, as from a ceiling light on a glossy carton."""
    frame_h, frame_w = composite.shape
    ys, xs = np.mgrid[0:frame_h, 0:frame_w]
    cx = frame_w * 0.42
    cy = frame_h * 0.40
    radius = min(frame_w, frame_h) * (0.16 + 0.34 * settings.glare)
    falloff = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2.0 * radius**2)))
    return composite + settings.glare * 1.9 * falloff


def _project_words(
    words: Sequence[WordBox],
    canonical_to_frame: np.ndarray,
    pack_w: int,
    pack_h: int,
    frame_w: int,
    frame_h: int,
) -> List[WordBox]:
    """Map normalised canonical word boxes into normalised frame coordinates."""
    if not words:
        return []
    centres = np.array([[w.x * pack_w, w.y * pack_h] for w in words], dtype=np.float64)
    projected = apply_homography(canonical_to_frame, centres)

    # Scale factor for box dimensions: the average edge-length ratio, which is
    # adequate for the mild perspective these captures use.
    corners = np.array(
        [[0.0, 0.0], [pack_w, 0.0], [pack_w, pack_h], [0.0, pack_h]], dtype=np.float64
    )
    mapped_corners = apply_homography(canonical_to_frame, corners)
    scale_x = float(np.linalg.norm(mapped_corners[1] - mapped_corners[0]) / pack_w)
    scale_y = float(np.linalg.norm(mapped_corners[3] - mapped_corners[0]) / pack_h)

    out: List[WordBox] = []
    for word, (x, y) in zip(words, projected):
        out.append(
            WordBox(
                text=word.text,
                x=float(x) / frame_w,
                y=float(y) / frame_h,
                width=word.width * pack_w * scale_x / frame_w,
                height=word.height * pack_h * scale_y / frame_h,
            )
        )
    return out


def ocr_payload(words: Sequence[WordBox], lines: Sequence[str]) -> Dict[str, object]:
    """Build the OCR sidecar payload for :class:`FixtureOcrProvider`."""
    return {
        "words": [w.to_payload() for w in words],
        "lines": list(lines),
        "note": "synthetic ground truth from the fixture generator",
    }


def to_png_bytes(image: "Image.Image") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def to_jpeg_bytes(image: "Image.Image", quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()
