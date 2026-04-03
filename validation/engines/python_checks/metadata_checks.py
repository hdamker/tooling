"""Commonalities version check.

Validates that ``info.x-camara-commonalities`` is present and contains
a valid version value appropriate for the branch type.

Design Guide section 5.3.7: "The API SHALL specify the Commonalities
release version they are compliant to, by including the
x-camara-commonalities extension field."
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import load_yaml_safe, make_finding

_ENGINE_RULE = "check-commonalities-version"

# Full semver: 0.7.0, 0.7.0-rc.1, 1.0.0-alpha.2
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*))?$"
)

# Short form: 0.7, 4.1 (allowed on main/feature only)
_SHORT_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)$"
)

# Placeholder values allowed on main/feature branches
_PLACEHOLDERS = frozenset({"wip", "tbd"})


def _is_valid_format(value: str, branch_type: str) -> bool:
    """Check if the value is a valid x-camara-commonalities format.

    Main/feature: wip, tbd, X.Y, or X.Y.Z[-pre] are all valid.
    Release/maintenance: only X.Y.Z[-pre] is valid.
    """
    if branch_type in ("main", "feature"):
        if value in _PLACEHOLDERS:
            return True
        if _SHORT_VERSION_RE.match(value):
            return True
        if _SEMVER_RE.match(value):
            return True
        return False

    # release / maintenance — must be full semver
    return _SEMVER_RE.match(value) is not None


def _is_concrete_version(value: str) -> bool:
    """True if the value is a concrete version (not a placeholder)."""
    return value not in _PLACEHOLDERS and (
        _SEMVER_RE.match(value) is not None
        or _SHORT_VERSION_RE.match(value) is not None
    )


def check_commonalities_version(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate info.x-camara-commonalities presence and value.

    Per-API check (runs once per API in context.apis).

    Checks:
    1. Field must be present in info object.
    2. Value must be a valid format for the branch type.
    3. If a concrete version and context.commonalities_version is set,
       the values must match.
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file
    spec = load_yaml_safe(spec_path)

    if spec is None:
        # Missing file — filename check reports this.
        return []

    info = spec.get("info", {})
    raw_value = info.get("x-camara-commonalities")

    # Check 1: presence
    if raw_value is None:
        return [
            make_finding(
                engine_rule=_ENGINE_RULE,
                level="error",
                message=(
                    f"info.x-camara-commonalities is missing in "
                    f"{api.spec_file}"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        ]

    value = str(raw_value).strip()

    # Check 2: format validation
    if not _is_valid_format(value, context.branch_type):
        if context.branch_type in ("release", "maintenance"):
            detail = (
                f"must be a full version (X.Y.Z or X.Y.Z-pre) on "
                f"{context.branch_type} branch"
            )
        else:
            detail = (
                "must be 'wip', 'tbd', or a valid version "
                "(X.Y, X.Y.Z, X.Y.Z-pre)"
            )
        return [
            make_finding(
                engine_rule=_ENGINE_RULE,
                level="error",
                message=(
                    f"info.x-camara-commonalities '{value}' has invalid "
                    f"format — {detail}"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        ]

    # Check 3: version mismatch against resolved commonalities_version
    if (
        context.commonalities_version
        and _is_concrete_version(value)
    ):
        # Normalize short form for comparison: "0.7" matches "0.7.0"
        expected = context.commonalities_version
        actual = value
        if _SHORT_VERSION_RE.match(actual):
            actual = f"{actual}.0"

        # Strip pre-release for prefix comparison if short form was used
        expected_base = expected.split("-")[0]
        actual_base = actual.split("-")[0]

        if actual_base != expected_base and actual != expected:
            return [
                make_finding(
                    engine_rule=_ENGINE_RULE,
                    level="warn",
                    message=(
                        f"info.x-camara-commonalities '{value}' does not "
                        f"match the declared Commonalities version "
                        f"'{context.commonalities_version}' from "
                        f"release-plan.yaml"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            ]

    return []
