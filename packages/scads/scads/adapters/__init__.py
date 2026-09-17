"""Adapters for storage, registry, OCR and optional explanation."""

from .base import (  # noqa: F401
    DependencyUnavailable,
    Explainer,
    ObjectStore,
    OcrProvider,
    ReferenceStore,
    Registry,
    RegistryWriter,
    ScanEventStore,
)
from .factory import Adapters, build_adapters  # noqa: F401
