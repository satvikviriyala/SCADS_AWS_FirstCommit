"""Build the adapter set for a given configuration.

One place decides which implementation of each port is used, so the request path
never branches on backend identity and no code path can quietly pick the offline
backend in a deployed environment.
"""

import os
from dataclasses import dataclass
from typing import Optional

from ..config import (
    OCR_FIXTURE,
    OCR_NONE,
    OCR_TEXTRACT,
    REPO_LOCAL,
    STORE_LOCAL,
    Settings,
)
from .base import Explainer, ObjectStore, OcrProvider, ReferenceStore, Registry, ScanEventStore


@dataclass
class Adapters:
    """Everything the orchestrator needs from the outside world."""

    store: ObjectStore
    registry: Registry
    references: ReferenceStore
    events: ScanEventStore
    ocr: OcrProvider
    explainer: Optional[Explainer] = None

    def describe(self) -> dict:
        return {
            "store": self.store.backend_name,
            "registry": self.registry.backend_name,
            "references": self.references.backend_name,
            "events": self.events.backend_name,
            "ocr": self.ocr.provider_name,
            "explainer": self.explainer.provider_name if self.explainer else "none",
        }


def build_adapters(settings: Settings, upload_base_url: str = "http://localhost:8000") -> Adapters:
    """Construct adapters from ``settings``.

    Raises rather than falling back. A deployed stack with a missing table name
    must fail its health check, not serve results from a local JSON file.
    """
    settings.validate()

    if settings.store_backend == STORE_LOCAL:
        from .local_backend import LocalObjectStore

        store: ObjectStore = LocalObjectStore(settings.local_root, upload_base_url)
    else:
        from .aws_backend import S3ObjectStore

        store = S3ObjectStore(
            scan_bucket=settings.scan_bucket,
            reference_bucket=settings.reference_bucket,
            region=settings.region,
        )

    if settings.repo_backend == REPO_LOCAL:
        from .local_backend import LocalReferenceStore, LocalRegistry, LocalScanEventStore

        registry: Registry = LocalRegistry(settings.local_root)
        references: ReferenceStore = LocalReferenceStore(settings.local_root)
        events: ScanEventStore = LocalScanEventStore(settings.local_root)
    else:
        from .aws_backend import DynamoReferenceStore, DynamoRegistry, DynamoScanEventStore

        registry = DynamoRegistry(settings.registry_table, settings.region)
        references = DynamoReferenceStore(settings.reference_table, settings.region)
        events = DynamoScanEventStore(settings.scan_events_table, settings.region)

    if settings.ocr_provider == OCR_TEXTRACT:
        from .aws_backend import TextractOcrProvider

        ocr: OcrProvider = TextractOcrProvider(settings.region, settings.textract_max_bytes)
    elif settings.ocr_provider == OCR_FIXTURE:
        from .fixture_ocr import FixtureOcrProvider

        ocr = FixtureOcrProvider(os.path.join(settings.local_root, "ocr"))
    else:
        from .fixture_ocr import NullOcrProvider

        ocr = NullOcrProvider()

    explainer: Optional[Explainer] = None
    if settings.bedrock_enabled:
        from .aws_backend import BedrockExplainer

        explainer = BedrockExplainer(
            model_id=settings.bedrock_model_id,
            region=settings.bedrock_region or settings.region,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )

    return Adapters(
        store=store,
        registry=registry,
        references=references,
        events=events,
        ocr=ocr,
        explainer=explainer,
    )
