"""Metadata consistency checks.

Validates that ``info.license`` and ``info.x-camara-commonalities`` are
present in all API spec files and consistent across them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from validation.context import ValidationContext

from ._types import load_yaml_safe, make_finding


def _extract_metadata(spec: dict) -> tuple[Optional[Any], Optional[Any]]:
    """Extract license and x-camara-commonalities from a spec."""
    info = spec.get("info", {})
    license_val = info.get("license")
    commonalities_val = info.get("x-camara-commonalities")
    return license_val, commonalities_val


def check_license_commonalities_consistency(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify license and x-camara-commonalities are present and consistent.

    Repo-level check.  Loads all spec files referenced in ``context.apis``,
    checks that each has ``info.license`` and ``info.x-camara-commonalities``,
    and verifies the values are identical across all API files.
    """
    if not context.apis:
        return []

    findings: List[dict] = []
    first_license: Optional[Any] = None
    first_commonalities: Optional[Any] = None
    first_api: Optional[str] = None

    for api in context.apis:
        spec_path = repo_path / api.spec_file
        spec = load_yaml_safe(spec_path)

        if spec is None:
            # Missing file — filename check reports this.
            continue

        license_val, commonalities_val = _extract_metadata(spec)

        # Check presence.
        if license_val is None:
            findings.append(
                make_finding(
                    engine_rule="check-license-commonalities-consistency",
                    level="error",
                    message=f"info.license is missing in {api.spec_file}",
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )
        if commonalities_val is None:
            findings.append(
                make_finding(
                    engine_rule="check-license-commonalities-consistency",
                    level="error",
                    message=(
                        f"info.x-camara-commonalities is missing in "
                        f"{api.spec_file}"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )

        # Track first values for consistency check.
        if first_api is None:
            first_api = api.api_name
            first_license = license_val
            first_commonalities = commonalities_val
            continue

        # Consistency: compare against first API's values.
        if license_val is not None and first_license is not None:
            if license_val != first_license:
                findings.append(
                    make_finding(
                        engine_rule="check-license-commonalities-consistency",
                        level="error",
                        message=(
                            f"info.license in {api.spec_file} differs from "
                            f"{first_api}"
                        ),
                        path=api.spec_file,
                        line=1,
                        api_name=api.api_name,
                    )
                )

        if commonalities_val is not None and first_commonalities is not None:
            if commonalities_val != first_commonalities:
                findings.append(
                    make_finding(
                        engine_rule="check-license-commonalities-consistency",
                        level="error",
                        message=(
                            f"info.x-camara-commonalities in {api.spec_file} "
                            f"differs from {first_api}"
                        ),
                        path=api.spec_file,
                        line=1,
                        api_name=api.api_name,
                    )
                )

    return findings
