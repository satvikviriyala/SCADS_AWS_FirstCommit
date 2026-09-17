"""Identity extraction and registry evaluation."""

from .evaluator import evaluate_identity, extract_claim  # noqa: F401
from .ocr import OcrResult, OcrWord  # noqa: F401
from .qr import build_demo_payload, parse_qr_payload  # noqa: F401
