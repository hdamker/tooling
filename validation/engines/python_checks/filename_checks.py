"""Filename convention checks.

Validates that API names (from release-plan.yaml) follow kebab-case
naming and that the corresponding spec files exist on disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding

# Kebab-case: lowercase letters/digits, separated by single hyphens.
_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def check_filename_kebab_case(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate that the API name uses kebab-case.

    Since the spec filename is derived from ``api_name`` in
    release-plan.yaml (``code/API_definitions/{api_name}.yaml``),
    this effectively validates that the release-plan entry follows
    the CAMARA naming convention.
    """
    api = context.apis[0]
    if _KEBAB_CASE_RE.match(api.api_name):
        return []

    return [
        make_finding(
            engine_rule="check-filename-kebab-case",
            level="error",
            message=(
                f"API name '{api.api_name}' does not follow kebab-case "
                f"convention (expected pattern: lowercase-with-hyphens)"
            ),
            path=api.spec_file,
            line=1,
            api_name=api.api_name,
        )
    ]


def check_filename_matches_api_name(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify the spec file exists at the expected path.

    The expected path is ``code/API_definitions/{api_name}.yaml``,
    derived from the ``api_name`` in release-plan.yaml.  If the file
    does not exist, the api_name likely doesn't match the actual
    filename on disk.
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file

    if spec_path.is_file():
        return []

    return [
        make_finding(
            engine_rule="check-filename-matches-api-name",
            level="error",
            message=(
                f"Expected spec file '{api.spec_file}' not found — "
                f"check that api_name '{api.api_name}' in release-plan.yaml "
                f"matches the actual filename"
            ),
            path=api.spec_file,
            line=1,
            api_name=api.api_name,
        )
    ]
