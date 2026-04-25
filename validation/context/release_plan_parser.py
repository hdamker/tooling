"""Release-plan.yaml parser for the CAMARA validation framework.

Loads and extracts fields from the repository's release-plan.yaml file.
Returns None when the file is absent — the context builder treats this
as "no release context" (null fields, empty APIs list).

Design doc references:
  - Section 8.3: release context fields in the validation context object
  - release-plan-schema.yaml: authoritative schema (Draft 7)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import yaml
from jsonschema import Draft7Validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tag-format validation
# ---------------------------------------------------------------------------

# CAMARA release tag format: r<major>.<minor>, both positive integers.
# Excludes r0.x and components with leading zeros.
_VALID_RELEASE_TAG_RE = re.compile(r"^r[1-9]\d*\.[1-9]\d*$")


def is_valid_release_tag(tag: str) -> bool:
    """Check whether a string is a valid CAMARA release tag.

    Valid format: ``r<major>.<minor>`` with positive integer components
    (e.g. ``r1.1``, ``r4.2``, ``r10.20``). Excludes ``r0.x`` and tags
    with leading-zero components.

    Used as a precheck for dependency tags (commonalities_release,
    icm_release) before lookup/existence checks — distinguishes
    "tag is malformed" from "tag does not exist".
    """
    if not tag:
        return False
    return bool(_VALID_RELEASE_TAG_RE.fullmatch(tag))

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleasePlanApi:
    """Single API entry from release-plan.yaml."""

    api_name: str
    target_api_version: str
    target_api_status: str


@dataclass(frozen=True)
class ReleasePlanData:
    """Parsed release-plan.yaml content."""

    target_release_type: str
    commonalities_release: Optional[str]
    icm_release: Optional[str]
    apis: Tuple[ReleasePlanApi, ...]


# ---------------------------------------------------------------------------
# Pure parsing
# ---------------------------------------------------------------------------


def parse_release_plan(data: dict) -> ReleasePlanData:
    """Extract validation-relevant fields from a parsed release-plan dict.

    This is a pure function — no I/O.  Expects a dict that has already
    been loaded from YAML (optionally schema-validated).
    """
    repo = data.get("repository", {})
    deps = data.get("dependencies") or {}

    apis_raw = data.get("apis") or []
    apis = tuple(
        ReleasePlanApi(
            api_name=a["api_name"],
            target_api_version=a["target_api_version"],
            target_api_status=a["target_api_status"],
        )
        for a in apis_raw
    )

    return ReleasePlanData(
        target_release_type=repo.get("target_release_type", "none"),
        commonalities_release=deps.get("commonalities_release"),
        icm_release=deps.get("identity_consent_management_release"),
        apis=apis,
    )


# ---------------------------------------------------------------------------
# I/O wrapper
# ---------------------------------------------------------------------------


def load_release_plan(
    plan_path: Path, schema_path: Path
) -> Optional[ReleasePlanData]:
    """Load release-plan.yaml, validate, and extract fields.

    Returns None if the file is missing or empty.  If schema validation
    fails, logs a warning and returns what can be parsed (graceful
    degradation).

    Args:
        plan_path: Path to release-plan.yaml in the repo checkout.
        schema_path: Path to release-plan-schema.yaml.
    """
    if not plan_path.is_file():
        logger.debug("release-plan.yaml not found at %s", plan_path)
        return None

    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logger.warning("Failed to parse %s as YAML", plan_path)
        return None

    if not data:
        logger.debug("release-plan.yaml is empty at %s", plan_path)
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
                    "release-plan.yaml validation: %s: %s", path, err.message
                )
    except Exception:
        logger.warning("Could not validate release-plan.yaml against schema")

    return parse_release_plan(data)
