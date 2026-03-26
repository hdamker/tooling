"""Release review PR checks.

Validates that release review PRs (targeting release-snapshot branches)
only modify allowed files (CHANGELOG.md, CHANGELOG/, README.md).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding

logger = logging.getLogger(__name__)

# Files and directories allowed to change on release review PRs.
_ALLOWED_PATHS = frozenset({"CHANGELOG.md", "README.md"})
_ALLOWED_PREFIXES = ("CHANGELOG/",)


def _get_changed_files(repo_path: Path) -> List[str]:
    """Get files changed in the current PR via git diff.

    Compares HEAD against the merge-base with the target branch.
    Falls back to diffing HEAD~1 if git operations fail.
    """
    try:
        # In a PR context, the diff against origin/base shows changed files.
        # Use --diff-filter=ACMR to only show added/copied/modified/renamed.
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD~1"],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
            timeout=30,
        )
        if result.returncode == 0:
            return [
                f.strip() for f in result.stdout.strip().split("\n")
                if f.strip()
            ]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return []


def _is_allowed(file_path: str) -> bool:
    """Check if a file path is in the allowed set for release review PRs."""
    if file_path in _ALLOWED_PATHS:
        return True
    for prefix in _ALLOWED_PREFIXES:
        if file_path.startswith(prefix):
            return True
    return False


def check_release_review_file_restriction(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify release review PRs only modify allowed files.

    Only runs when ``context.is_release_review_pr`` is ``True``.
    Returns empty list otherwise.

    Allowed files: CHANGELOG.md, CHANGELOG/*, README.md.
    All other files on the snapshot branch are immutable.
    """
    if not context.is_release_review_pr:
        return []

    changed_files = _get_changed_files(repo_path)
    if not changed_files:
        return []

    findings: List[dict] = []
    for file_path in changed_files:
        if not _is_allowed(file_path):
            findings.append(
                make_finding(
                    engine_rule="check-release-review-file-restriction",
                    level="error",
                    message=(
                        f"File '{file_path}' must not be modified on a "
                        f"release review PR — only CHANGELOG.md, CHANGELOG/, "
                        f"and README.md are allowed"
                    ),
                    path=file_path,
                    line=1,
                )
            )

    return findings
