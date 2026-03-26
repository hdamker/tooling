"""CHANGELOG format checks.

Validates that CHANGELOG.md (or CHANGELOG/ directory) exists when a
release is targeted, and that it contains version heading entries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding

# Matches a version heading in CHANGELOG.md.
# Patterns: "## v1.0.0", "## 1.0.0", "## 0.2.0-alpha.1", "## v0.3.0-rc.1"
_VERSION_HEADING_RE = re.compile(
    r"^##\s+v?(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?)", re.MULTILINE
)


def check_changelog_format(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate CHANGELOG existence and format.

    Repo-level check.  Only runs when the repository targets a release
    (``target_release_type`` is not ``None`` and not ``"none"``).
    """
    if not context.target_release_type or context.target_release_type == "none":
        return []

    findings: List[dict] = []

    changelog_file = repo_path / "CHANGELOG.md"
    changelog_dir = repo_path / "CHANGELOG"

    has_changelog = changelog_file.is_file() or changelog_dir.is_dir()
    if not has_changelog:
        findings.append(
            make_finding(
                engine_rule="check-changelog-format",
                level="error",
                message=(
                    "CHANGELOG.md or CHANGELOG/ directory is missing — "
                    "required when targeting a release"
                ),
                path="CHANGELOG.md",
                line=1,
            )
        )
        return findings

    # If CHANGELOG is a directory, check for at least one file inside.
    if changelog_dir.is_dir():
        md_files = [f for f in changelog_dir.iterdir() if f.suffix == ".md"]
        if not md_files:
            findings.append(
                make_finding(
                    engine_rule="check-changelog-format",
                    level="error",
                    message="CHANGELOG/ directory exists but contains no .md files",
                    path="CHANGELOG",
                    line=1,
                )
            )
        return findings

    # CHANGELOG.md exists — check for version headings.
    content = changelog_file.read_text(encoding="utf-8")
    if not _VERSION_HEADING_RE.search(content):
        findings.append(
            make_finding(
                engine_rule="check-changelog-format",
                level="error",
                message=(
                    "CHANGELOG.md has no version heading entries "
                    "(expected '## x.y.z' or '## vx.y.z')"
                ),
                path="CHANGELOG.md",
                line=1,
            )
        )

    return findings
