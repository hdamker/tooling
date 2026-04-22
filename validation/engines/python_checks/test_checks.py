"""Test file checks.

Validates that test files exist for each API, are located in
``code/Test_definitions/``, and carry version-aligned Feature lines.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from validation.context import ValidationContext

from ._types import make_finding

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


# Regex to extract version from CAMARA Feature line. Aligned with the T1b
# transformation pattern in release_automation/config/transformations.yaml
# so that any line T1b can transform is also recognized here. The leading
# ``\s`` separator accepts both the comma-and-space form ("Feature: X, vwip")
# and the space-only form ("Feature: X vwip"). The captured token is
# ``wip`` / ``vwip`` (style variation on main/maintenance) or ``v{semver}``
# (release branches).
# Examples:
#   "Feature: CAMARA QoD API, vwip - Operation deleteSession"       → "vwip"
#   "Feature: CAMARA QoD API, wip - Operation deleteSession"        → "wip"
#   "Feature: CAMARA QoD API vwip - Operation deleteSession"        → "vwip"
#   "Feature: CAMARA QoD API, v2.2.0-alpha.5 - Operation create"    → "v2.2.0-alpha.5"
#   "Feature: CAMARA QoD API, v1.0.0"                               → "v1.0.0"
_FEATURE_VERSION_RE = re.compile(r"\s(v?wip|v\S+?)(?:\s+-\s|\s*$)")


def _extract_feature_version(file_path: Path) -> Optional[str]:
    """Read the first line and extract the version segment.

    Returns the version string (e.g. ``"vwip"``, ``"v2.2.0-alpha.5"``)
    or ``None`` if no version could be parsed from the Feature line.
    """
    try:
        with open(file_path, encoding="utf-8") as fh:
            first_line = fh.readline().rstrip()
    except (OSError, UnicodeDecodeError):
        return None

    m = _FEATURE_VERSION_RE.search(first_line)
    if m:
        return m.group(1)
    return None


def check_test_file_version(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate that the version in test Feature lines matches the branch.

    Per-API check.  On main and maintenance the Feature line must carry
    ``vwip``.  On release branches it must match the version derived
    from ``target_api_version`` (sourced from release-metadata.yaml).
    Feature branches are skipped.

    This avoids cascading with P-003 (info.version format): on
    main/maintenance the expected value is hardcoded, not derived from
    the spec.

    Example Feature line::

        Feature: CAMARA Quality On Demand API, vwip - Operation deleteSession
    """
    api = context.apis[0]
    test_dir = repo_path / _TEST_DIR

    if not test_dir.is_dir():
        return []

    if context.branch_type in ("main", "maintenance"):
        expected_segment = "vwip"
    elif context.branch_type == "release":
        # Snapshot transformer T1b produces "v{api_version}" in Feature
        # lines.  api.target_api_version holds the full calculated
        # version (incl. pre-release extension) from release-metadata.
        expected_segment = f"v{api.target_api_version}"
    else:
        # Feature branches: no constraint.
        return []

    # Find all .feature files matching this API.
    matching = [
        f for f in test_dir.iterdir()
        if f.is_file()
        and f.suffix == ".feature"
        and _stem_matches_api(f.stem, api.api_name)
    ]

    if not matching:
        # No test files found — check_test_files_exist reports this.
        return []

    # Compare with leading-v stripped so bare "wip" and "vwip" are treated
    # as equivalent on main/maintenance (a style variation, parallel to
    # "0.1.0" vs "v0.1.0" in info.version). Release branches always carry
    # T1b's "v{api_version}" output, so the normalized comparison still
    # enforces an exact match there.
    expected_token = expected_segment.lower().removeprefix("v")

    findings: List[dict] = []
    for test_file in matching:
        actual_version = _extract_feature_version(test_file)

        if actual_version is None:
            # No wip/vwip/v* token on the Feature line — T1b has nothing to
            # replace and a release cut would carry the literal text into
            # the snapshot. Emitted under a distinct rule ID (P-024) so its
            # severity cannot be masked by P-007's conditional_level.
            findings.append(
                make_finding(
                    engine_rule="check-test-file-feature-line-untransformable",
                    level="error",
                    message=(
                        f"Test file '{test_file.name}' Feature line has no "
                        f"'wip', 'vwip', or 'v{{version}}' token — nothing "
                        f"for snapshot transformation to replace "
                        f"(expected '{expected_segment}')"
                    ),
                    path=f"{_TEST_DIR}/{test_file.name}",
                    line=1,
                    api_name=api.api_name,
                )
            )
            continue

        actual_token = actual_version.lower().removeprefix("v")
        if actual_token != expected_token:
            findings.append(
                make_finding(
                    engine_rule="check-test-file-version",
                    level="error",
                    message=(
                        f"Test file '{test_file.name}' has version "
                        f"'{actual_version}' in Feature line but expected "
                        f"'{expected_segment}' "
                        f"(on {context.branch_type} branch)"
                    ),
                    path=f"{_TEST_DIR}/{test_file.name}",
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings
