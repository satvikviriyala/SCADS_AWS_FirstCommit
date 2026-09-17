"""Versioned identifiers stamped onto every scan result.

Every decision SCADS emits records which code and which policy produced it, so
a result can be re-evaluated later (``docs/EVALUATION.md``) and so a threshold
change is never silently retroactive.

Bump rules:

``PIPELINE_VERSION``
    Any change to quality, registration or physical feature extraction that can
    move a feature value for unchanged input.
``FUSION_POLICY_VERSION``
    Any change to weights, caps, thresholds or gate ordering in
    :mod:`scads.decision`.
``CONTRACT_VERSION``
    Any change to the wire shape or the reason-code registry.
"""

PIPELINE_VERSION = "cv_0.1.0"
FUSION_POLICY_VERSION = "fusion_0.1.0"
CONTRACT_VERSION = "api_0.1.0"
SERVICE_VERSION = "0.1.0"
SERVICE_NAME = "scads-api"
