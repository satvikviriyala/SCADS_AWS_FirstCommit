"""Image loading and the numpy primitives the pipeline needs.

Uploads are attacker-controlled, so decoding is bounded on every axis: declared
type, magic bytes, byte length and pixel count, all checked before the decoder
sees the data (``docs/SECURITY_PRIVACY.md`` section 3).

Only ``numpy`` and ``Pillow`` are used. That is a deliberate constraint, not a
limitation of convenience: it keeps the deployed Lambda a plain zip well inside
the size limit, and it guarantees the code that runs in tests is byte-for-byte
the code that runs in AWS.
"""

import io
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

# Pillow refuses images above this pixel count as a decompression-bomb guard.
# Set explicitly rather than relying on the library default.
Image.MAX_IMAGE_PIXELS = 50_000_000

ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp")

# Magic-byte signatures. Checked because a content type is a claim, not a fact.
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),
)

MAX_DIMENSION = 6000
MIN_DIMENSION = 200


class ImageRejected(ValueError):
    """The upload is not a usable image. Carries a public reason code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def sniff_content_type(data: bytes) -> Optional[str]:
    """Identify an image by its magic bytes."""
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            if content_type == "image/webp":
                # RIFF is a container; confirm the WEBP fourcc.
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return content_type
                continue
            return content_type
    return None


@dataclass(frozen=True)
class LoadedImage:
    """A decoded scan, ready for analysis."""

    gray: np.ndarray          # float32 in [0, 1], shape (H, W)
    rgb: Optional[np.ndarray]  # float32 in [0, 1], shape (H, W, 3)
    width: int
    height: int
    content_type: str
    byte_length: int

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000.0


def load_image(data: bytes, max_bytes: int, declared_type: Optional[str] = None) -> LoadedImage:
    """Decode an upload into arrays, or raise :class:`ImageRejected`.

    EXIF is dropped by converting through raw pixel arrays: orientation is
    applied first (so a phone photo is upright), then everything else is
    discarded rather than carried into storage
    (``docs/SECURITY_PRIVACY.md`` section 3).
    """
    if not data:
        raise ImageRejected("EMPTY_UPLOAD", "the uploaded object is empty")
    if len(data) > max_bytes:
        raise ImageRejected(
            "FILE_TOO_LARGE",
            "image is {} bytes; the limit is {}".format(len(data), max_bytes),
        )

    sniffed = sniff_content_type(data)
    if sniffed is None:
        raise ImageRejected(
            "UNSUPPORTED_MEDIA_TYPE", "the uploaded bytes are not a JPEG, PNG or WebP image"
        )
    if declared_type and declared_type.split(";")[0].strip() != sniffed:
        # A mismatch is not automatically an attack — some clients mislabel — so
        # the sniffed type wins and the declared one is ignored.
        pass

    try:
        with Image.open(io.BytesIO(data)) as handle:
            handle = _apply_orientation(handle)
            if handle.width > MAX_DIMENSION or handle.height > MAX_DIMENSION:
                handle = _fit_within(handle, MAX_DIMENSION)
            rgb_image = handle.convert("RGB")
            rgb = np.asarray(rgb_image, dtype=np.float32) / 255.0
    except ImageRejected:
        raise
    except Exception as exc:
        raise ImageRejected("CORRUPT_IMAGE", "the image could not be decoded: " + type(exc).__name__)

    height, width = rgb.shape[0], rgb.shape[1]
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ImageRejected(
            "IMAGE_TOO_SMALL",
            "image is {}x{}; at least {}px on each side is required".format(
                width, height, MIN_DIMENSION
            ),
        )

    return LoadedImage(
        gray=to_gray(rgb),
        rgb=rgb,
        width=width,
        height=height,
        content_type=sniffed,
        byte_length=len(data),
    )


def _apply_orientation(image: "Image.Image") -> "Image.Image":
    """Rotate per EXIF orientation so a phone photo is analysed upright."""
    try:
        from PIL import ImageOps

        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def _fit_within(image: "Image.Image", limit: int) -> "Image.Image":
    scale = limit / float(max(image.width, image.height))
    return image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.LANCZOS,
    )


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """Rec. 601 luma. Matches how Pillow converts to ``L``."""
    return (
        0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    ).astype(np.float32)


def to_pil(gray: np.ndarray) -> "Image.Image":
    return Image.fromarray(np.clip(gray * 255.0, 0, 255).astype(np.uint8))


def from_pil(image: "Image.Image") -> np.ndarray:
    return np.asarray(image, dtype=np.float32) / 255.0


def gaussian_kernel_1d(sigma: float, truncate: float = 4.0) -> np.ndarray:
    """A normalised 1-D Gaussian kernel."""
    radius = max(1, int(truncate * float(sigma) + 0.5))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(offsets * offsets) / (2.0 * float(sigma) ** 2))
    return (kernel / kernel.sum()).astype(np.float32)


def _convolve_1d(gray: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    radius = len(kernel) // 2
    padding = [(0, 0), (0, 0)]
    padding[axis] = (radius, radius)
    padded = np.pad(gray, padding, mode="edge")
    output = np.zeros_like(gray, dtype=np.float32)
    length = gray.shape[axis]
    for index, weight in enumerate(kernel):
        if weight == 0.0:
            continue
        window = [slice(None), slice(None)]
        window[axis] = slice(index, index + length)
        output += weight * padded[tuple(window)]
    return output


def gaussian_blur(gray: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur in float32.

    Implemented in numpy rather than through ``PIL.ImageFilter.GaussianBlur``
    on purpose. Pillow's filter operates on 8-bit pixels, and SSIM needs this
    function to compute local variances as ``E[x^2] - E[x]^2``. Quantising to
    8 bits puts an error of about 1/255 into each moment, and that error is the
    same order as the variance of a mildly textured region — so the difference
    of the two quantised moments is dominated by rounding noise.

    Concretely: with the 8-bit path, SSIM between a genuine rectified pack and
    its own reference came out at 0.0 instead of ~0.8, because every variance
    and covariance term was noise. Float precision is not an optimisation here,
    it is a correctness requirement.
    """
    if sigma <= 0:
        return gray
    kernel = gaussian_kernel_1d(sigma)
    return _convolve_1d(_convolve_1d(gray, kernel, 0), kernel, 1)


def resize_gray(gray: np.ndarray, width: int, height: int) -> np.ndarray:
    return from_pil(to_pil(gray).resize((int(width), int(height)), Image.LANCZOS))


# 3x3 Sobel kernels.
_SOBEL_X = np.array([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]], dtype=np.float32)
_SOBEL_Y = _SOBEL_X.T
# 4-neighbour Laplacian, used as the blur metric.
_LAPLACIAN = np.array([[0.0, 1.0, 0.0], [1.0, -4.0, 1.0], [0.0, 1.0, 0.0]], dtype=np.float32)


def convolve3(gray: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Vectorised 3x3 convolution with edge replication.

    Nine shifted views summed with weights. Faster than a Python loop and
    avoids pulling in scipy for one operation.
    """
    padded = np.pad(gray, 1, mode="edge")
    output = np.zeros_like(gray, dtype=np.float32)
    height, width = gray.shape
    for dy in range(3):
        for dx in range(3):
            weight = kernel[dy, dx]
            if weight != 0.0:
                output += weight * padded[dy : dy + height, dx : dx + width]
    return output


def laplacian(gray: np.ndarray) -> np.ndarray:
    return convolve3(gray, _LAPLACIAN)


def gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    gx = convolve3(gray, _SOBEL_X)
    gy = convolve3(gray, _SOBEL_Y)
    return np.sqrt(gx * gx + gy * gy)


def box_filter(gray: np.ndarray, size: int) -> np.ndarray:
    """Mean filter via a summed-area table: O(1) per pixel regardless of size."""
    if size <= 1:
        return gray
    radius = size // 2
    padded = np.pad(gray, radius + 1, mode="edge").astype(np.float64)
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    height, width = gray.shape
    y0 = np.arange(height)
    x0 = np.arange(width)
    top = y0[:, None]
    left = x0[None, :]
    bottom = top + size
    right = left + size
    total = (
        integral[bottom, right]
        - integral[top, right]
        - integral[bottom, left]
        + integral[top, left]
    )
    return (total / float(size * size)).astype(np.float32)


def normalized_cross_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Zero-mean normalised cross-correlation of two equally shaped arrays.

    Returns a value in [-1, 1]. Invariant to brightness and contrast, which
    matters because a phone photo and an enrolled reference never share
    exposure.
    """
    if a.shape != b.shape:
        raise ValueError("shape mismatch: {} vs {}".format(a.shape, b.shape))
    av = a.astype(np.float64).ravel()
    bv = b.astype(np.float64).ravel()
    av -= av.mean()
    bv -= bv.mean()
    denominator = float(np.sqrt((av * av).sum() * (bv * bv).sum()))
    if denominator < 1e-12:
        return 0.0
    return float((av * bv).sum() / denominator)
