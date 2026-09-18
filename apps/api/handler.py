"""AWS Lambda entry point for the SCADS API.

Thin on purpose. All logic lives in :mod:`scads.api`, which is importable and
testable without Lambda, so the request path can be exercised end to end
locally by ``scripts/dev_server.py``.
"""

import os
import sys

# The deployment package places the `scads` package alongside this module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scads.api.router import handle_request  # noqa: E402


def lambda_handler(event, context):
    """API Gateway HTTP API (payload format 2.0) handler."""
    return handle_request(event, context)
