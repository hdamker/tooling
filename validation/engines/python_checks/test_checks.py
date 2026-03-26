"""Test file checks.

Validates that test files exist for each API, are located in
``code/Test_definitions/``, and have version-aligned filenames.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding
from .version_checks import build_version_segment

_TEST_DIR = "code/Test_definitions"


def _stem_matches_api(stem: str, api_name: str) -> bool:
    """Check if a test file stem matches an API name.

    Matches:
    - Exact: ``{api-name}``
    - With version: ``{api-name}.{version}``
    - With suffix: ``{api-name}-{suffix}``
    - With suffix + version: ``{api-name}-{suffix}.{version}``
    """
    if stem == api_name:
        return True
    if stem.startswith(f"{api_name}."):
        return True
    if stem.startswith(f"{api_name}-"):
        return True
    return False


def check_test_directory_exists(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify ``code/Test_definitions/`` exists when APIs are present.

    Repo-level check — runs once, not per-API.
    """
    if not context.apis:
        return []

    test_dir = repo_path / _TEST_DIR
    if test_dir.is_dir():
        return []

    return [
        make_finding(
            engine_rule="check-test-directory-exists",
            level="error",
            message=(
                f"Directory '{_TEST_DIR}/' is missing — "
                f"test definitions are required when API specs are present"
            ),
            path=_TEST_DIR,
            line=1,
        )
    ]


def check_test_files_exist(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify at least one ``.feature`` file exists for the API.

    Per-API check.  Looks for files matching the api-name prefix in
    ``code/Test_definitions/``.
    """
    api = context.apis[0]
    test_dir = repo_path / _TEST_DIR

    if not test_dir.is_dir():
        # Directory-level check reports this; avoid duplicate findings.
        return []

    # Match files starting with the api-name.
    # Patterns: {api-name}.feature, {api-name}.{version}.feature,
    #           {api-name}-{suffix}.feature, {api-name}-{suffix}.{version}.feature
    matching = [
        f for f in test_dir.iterdir()
        if f.is_file()
        and f.suffix == ".feature"
        and _stem_matches_api(f.stem, api.api_name)
    ]

    if matching:
        return []

    return [
        make_finding(
            engine_rule="check-test-files-exist",
            level="error",
            message=(
                f"No .feature test file found for API '{api.api_name}' "
                f"in {_TEST_DIR}/"
            ),
            path=_TEST_DIR,
            line=1,
            api_name=api.api_name,
        )
    ]


def check_test_file_version(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate test file version suffix matches API version.

    Per-API check.  Uses CAMARA version-to-URL mapping rules to derive
    the expected version suffix.  Test files should be named like:
    ``{api-name}.{version-suffix}.feature`` or
    ``{api-name}-{operationId}.{version-suffix}.feature``.

    Example: ``quality-on-demand.v0.2alpha2.feature``
    """
    api = context.apis[0]
    test_dir = repo_path / _TEST_DIR

    if not test_dir.is_dir():
        return []

    expected_segment = build_version_segment(api.target_api_version)
    if expected_segment is None:
        return []

    # Find all .feature files matching this API.
    matching = [
        f for f in test_dir.iterdir()
        if f.is_file()
        and f.suffix == ".feature"
        and (f.stem == api.api_name or f.stem.startswith(f"{api.api_name}-")
             or f.stem.startswith(f"{api.api_name}."))
    ]

    if not matching:
        # No test files found — check_test_files_exist reports this.
        return []

    findings: List[dict] = []
    for test_file in matching:
        # Extract version suffix: everything after the first dot in the stem.
        # e.g. "quality-on-demand.v1" -> "v1"
        # e.g. "quality-on-demand-createSession.v0.3" -> "v0.3"
        stem = test_file.stem
        dot_idx = stem.find(".")
        if dot_idx == -1:
            # No version suffix in filename — report as finding.
            findings.append(
                make_finding(
                    engine_rule="check-test-file-version",
                    level="error",
                    message=(
                        f"Test file '{test_file.name}' has no version suffix "
                        f"(expected '.{expected_segment}' before .feature)"
                    ),
                    path=f"{_TEST_DIR}/{test_file.name}",
                    line=1,
                    api_name=api.api_name,
                )
            )
            continue

        actual_suffix = stem[dot_idx + 1:]
        if actual_suffix.lower() != expected_segment.lower():
            findings.append(
                make_finding(
                    engine_rule="check-test-file-version",
                    level="error",
                    message=(
                        f"Test file '{test_file.name}' has version suffix "
                        f"'{actual_suffix}' but expected '{expected_segment}' "
                        f"(from API version '{api.target_api_version}')"
                    ),
                    path=f"{_TEST_DIR}/{test_file.name}",
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings
