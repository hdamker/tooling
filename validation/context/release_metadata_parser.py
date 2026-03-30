"""Release-metadata.yaml parser for the CAMARA validation framework.

On snapshot branches, release-plan.yaml is removed and replaced with
release-metadata.yaml.  This module extracts the same fields needed by
the context builder, mapping the metadata schema to the existing
ReleasePlanData dataclass.

Field mapping:
  - repository.release_type          → target_release_type
  - dependencies.commonalities_release  → commonalities_release (tag only)
  - dependencies.identity_consent_management_release → icm_release (tag only)
  - apis[].api_name                  → api_name
  - apis[].api_version               → target_api_version
  - (derived from api_version)       → target_api_status

The dependencies fields in release-metadata.yaml use the enriched format
"r4.2 (1.2.0-rc.1)"; only the release tag prefix (e.g. "r4.2") is
extracted for Spectral ruleset selection.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from jsonschema import Draft7Validator

from .release_plan_parser import ReleasePlanApi, ReleasePlanData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RELEASE_TAG_RE = re.compile(r"^(r\d+\.\d+)")


def _extract_release_tag(enriched: Optional[str]) -> Optional[str]:
    """Extract the release tag from the enriched metadata format.

    "r4.2 (1.2.0-rc.1)" → "r4.2"
    "r4.2"               → "r4.2"
    None / ""             → None
    """
    if not enriched:
        return None
    m = _RELEASE_TAG_RE.match(enriched.strip())
    return m.group(1) if m else None


def _derive_api_status(api_version: str) -> str:
    """Derive target_api_status from the API version string.

    release-metadata.yaml does not carry target_api_status, so we derive
    it from the version's pre-release suffix:
      "0.5.0-alpha.1"  → "alpha"
      "1.0.0-rc.2"     → "rc"
      "1.0.0"          → "public"
    """
    if "-alpha." in api_version:
        return "alpha"
    if "-rc." in api_version:
        return "rc"
    return "public"


# ---------------------------------------------------------------------------
# Pure parsing
# ---------------------------------------------------------------------------


def parse_release_metadata(data: dict) -> ReleasePlanData:
    """Extract validation-relevant fields from a parsed release-metadata dict.

    This is a pure function — no I/O.  Expects a dict that has already
    been loaded from YAML (optionally schema-validated).
    """
    repo = data.get("repository", {})
    deps = data.get("dependencies") or {}

    apis_raw = data.get("apis") or []
    apis = tuple(
        ReleasePlanApi(
            api_name=a["api_name"],
            target_api_version=a["api_version"],
            target_api_status=_derive_api_status(a["api_version"]),
        )
        for a in apis_raw
        if "api_name" in a and "api_version" in a
    )

    return ReleasePlanData(
        target_release_type=repo.get("release_type", "none"),
        commonalities_release=_extract_release_tag(
            deps.get("commonalities_release")
        ),
        icm_release=_extract_release_tag(
            deps.get("identity_consent_management_release")
        ),
        apis=apis,
    )


# ---------------------------------------------------------------------------
# I/O wrapper
# ---------------------------------------------------------------------------


def load_release_metadata(
    metadata_path: Path, schema_path: Path
) -> Optional[ReleasePlanData]:
    """Load release-metadata.yaml, validate, and extract fields.

    Returns None if the file is missing or empty.  If schema validation
    fails, logs a warning and returns what can be parsed (graceful
    degradation).

    Args:
        metadata_path: Path to release-metadata.yaml in the repo checkout.
        schema_path: Path to release-metadata-schema.yaml.
    """
    if not metadata_path.is_file():
        logger.debug("release-metadata.yaml not found at %s", metadata_path)
        return None

    try:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logger.warning("Failed to parse %s as YAML", metadata_path)
        return None

    if not data:
        logger.debug("release-metadata.yaml is empty at %s", metadata_path)
        return None

    # Schema validation (warn on failure, continue with best-effort parse)
    try:
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(data))
        if errors:
            for err in errors[:3]:
                path = ".".join(str(p) for p in err.absolute_path) or "(root)"
                logger.warning(
                    "release-metadata.yaml validation: %s: %s",
                    path,
                    err.message,
                )
    except Exception:
        logger.warning(
            "Could not validate release-metadata.yaml against schema"
        )

    return parse_release_metadata(data)
