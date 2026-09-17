"""Content-addressed fixture OCR, for offline tests and local development.

The synthetic pack generator (``scripts/generate_fixtures.py``) knows exactly
where it drew each word, so it writes that ground truth to a sidecar file named
after the SHA-256 of the image it produced. This provider hashes the bytes it is
given and looks the sidecar up.

Content addressing is the point. The provider cannot produce word boxes for an
image it has no ground truth for — it returns a failed :class:`OcrResult`
instead — so a fixture-backed run can never silently stand in for real OCR on
a real photograph. The provider name is recorded in every scan record, and the
deployed smoke test asserts it reads ``textract``.
"""

import hashlib
import json
import os
from typing import Any, Dict, Optional

from ..identity.ocr import OcrResult, OcrWord
from .base import OcrProvider


def image_digest(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


class FixtureOcrProvider(OcrProvider):
    provider_name = "fixture"

    def __init__(self, sidecar_dir: str) -> None:
        self.sidecar_dir = sidecar_dir

    def _sidecar_path(self, digest: str) -> str:
        return os.path.join(self.sidecar_dir, digest + ".ocr.json")

    def write_sidecar(self, image_bytes: bytes, payload: Dict[str, Any]) -> str:
        """Record ground-truth word boxes for an image. Used by the generator."""
        digest = image_digest(image_bytes)
        os.makedirs(self.sidecar_dir, exist_ok=True)
        path = self._sidecar_path(digest)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return digest

    def detect_text(self, image_bytes: bytes, hint: Optional[Dict[str, Any]] = None) -> OcrResult:
        digest = image_digest(image_bytes)
        path = self._sidecar_path(digest)
        if not os.path.exists(path):
            return OcrResult.failed(
                self.provider_name,
                "no OCR ground truth for image " + digest[:12] + " (fixture provider)",
            )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            return OcrResult.failed(self.provider_name, str(exc))

        words = [
            OcrWord(
                text=w["text"],
                x=float(w["x"]),
                y=float(w["y"]),
                width=float(w.get("width", 0.0)),
                height=float(w.get("height", 0.0)),
                confidence=float(w.get("confidence", 99.0)),
            )
            for w in payload.get("words", [])
        ]
        return OcrResult(
            words=words,
            lines=list(payload.get("lines", [])),
            provider=self.provider_name,
            succeeded=True,
        )


class NullOcrProvider(OcrProvider):
    """OCR explicitly disabled.

    Returns a failed result rather than an empty successful one, so downstream
    code treats it as "text evidence unavailable" rather than "the pack has no
    text on it".
    """

    provider_name = "none"

    def detect_text(self, image_bytes: bytes, hint: Optional[Dict[str, Any]] = None) -> OcrResult:
        return OcrResult.failed(self.provider_name, "OCR provider disabled by configuration")
