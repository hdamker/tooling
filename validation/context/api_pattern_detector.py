"""API pattern detection from OpenAPI spec content.

Classifies a CAMARA API as request-response, implicit-subscription,
or explicit-subscription by inspecting the OpenAPI paths and operations.

Design doc references:
  - Section 1.4: api_pattern detection logic
  - Section 8.3: api_pattern field in context object
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATTERN_REQUEST_RESPONSE = "request-response"
PATTERN_IMPLICIT_SUBSCRIPTION = "implicit-subscription"
PATTERN_EXPLICIT_SUBSCRIPTION = "explicit-subscription"

# ---------------------------------------------------------------------------
# Pure detection
# ---------------------------------------------------------------------------


def detect_api_pattern(spec: dict) -> str:
    """Detect the API pattern from a parsed OpenAPI spec.

    Three-tier heuristic:
    1. Any path containing ``/subscriptions`` → explicit-subscription
    2. Any operation with a ``callbacks`` key → implicit-subscription
    3. Default → request-response

    Args:
        spec: Parsed OpenAPI spec dict (from yaml.safe_load).

    Returns:
        One of PATTERN_REQUEST_RESPONSE, PATTERN_IMPLICIT_SUBSCRIPTION,
        or PATTERN_EXPLICIT_SUBSCRIPTION.
    """
    paths = spec.get("paths") or {}

    # Check 1: explicit subscription endpoints
    for path_key in paths:
        if "/subscriptions" in path_key:
            return PATTERN_EXPLICIT_SUBSCRIPTION

    # Check 2: implicit subscription via callbacks
    for path_key, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if isinstance(operation, dict) and "callbacks" in operation:
                return PATTERN_IMPLICIT_SUBSCRIPTION

    return PATTERN_REQUEST_RESPONSE


# ---------------------------------------------------------------------------
# I/O wrapper
# ---------------------------------------------------------------------------


def detect_api_pattern_from_file(spec_path: Path) -> str:
    """Load an OpenAPI spec and detect its API pattern.

    Returns ``"request-response"`` if the file is missing or unparseable.
    """
    if not spec_path.is_file():
        logger.debug("Spec file not found: %s", spec_path)
        return PATTERN_REQUEST_RESPONSE

    try:
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logger.warning("Failed to parse spec file %s", spec_path)
        return PATTERN_REQUEST_RESPONSE

    if not isinstance(data, dict):
        return PATTERN_REQUEST_RESPONSE

    return detect_api_pattern(data)
