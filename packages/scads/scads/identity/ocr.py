"""OCR result model.

Normalised so that Textract and the fixture provider are interchangeable to the
rest of the system, and so word positions are resolution-independent.

Word boxes are the input to the packaging *layout* comparison, which is what
catches a counterfeit that prints the right words in the wrong places. Text
alone would miss that.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OcrWord:
    """One detected word.

    ``x``/``y`` are the box centre and all four values are fractions of image
    width/height in [0, 1].
    """

    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.0

    @property
    def normalised_text(self) -> str:
        return self.text.strip().upper()

    def distance_to(self, x: float, y: float) -> float:
        """Euclidean distance from this word's centre to a normalised point."""
        return ((self.x - x) ** 2 + (self.y - y) ** 2) ** 0.5

    def to_public(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "confidence": round(self.confidence, 2),
        }


@dataclass(frozen=True)
class OcrResult:
    """Everything OCR produced for one image.

    ``provider`` is carried through to the scan record so a fixture-backed run
    is always distinguishable from a Textract-backed one.
    """

    words: List[OcrWord] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    provider: str = "none"
    succeeded: bool = True
    error: Optional[str] = None

    @property
    def full_text(self) -> str:
        if self.lines:
            return "\n".join(self.lines)
        return " ".join(w.text for w in self.words)

    @property
    def upper_text(self) -> str:
        return self.full_text.upper()

    def words_matching(self, token: str) -> List[OcrWord]:
        needle = token.strip().upper()
        return [w for w in self.words if needle and needle in w.normalised_text]

    def find_nearest(self, token: str, x: float, y: float) -> Optional[OcrWord]:
        """The occurrence of ``token`` closest to an expected position.

        A word can legitimately appear more than once on a pack; the layout
        comparison wants the instance nearest where the reference expects it,
        not an arbitrary one.
        """
        candidates = self.words_matching(token)
        if not candidates:
            return None
        return min(candidates, key=lambda w: w.distance_to(x, y))

    @staticmethod
    def failed(provider: str, error: str) -> "OcrResult":
        return OcrResult(words=[], lines=[], provider=provider, succeeded=False, error=error)

    def to_public(self, max_words: int = 60) -> Dict[str, Any]:
        """Diagnostics view.

        Truncated: raw OCR is not logged wholesale
        (``docs/AWS_DEPLOYMENT.md`` section 8).
        """
        return {
            "provider": self.provider,
            "succeeded": self.succeeded,
            "word_count": len(self.words),
            "words": [w.to_public() for w in self.words[:max_words]],
            "error": self.error,
        }
