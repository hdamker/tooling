"""Release review PR checks.

Validates that release review PRs (targeting release-snapshot branches)
only modify allowed files (CHANGELOG.md, CHANGELOG/, README.md).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional

from validation.context import ValidationContext

from ._types import make_finding

logger = logging.getLogger(__name__)

# Files and directories allowed to change on release review PRs.
_ALLOWED_PATHS = frozenset({"CHANGELOG.md", "README.md"})
_ALLOWED_PREFIXES = ("CHANGELOG/",)


def _get_changed_files(
    repo_path: Path, base_ref: Optional[str] = None
) -> List[str]:
    """Get files changed in the current PR via git diff.

    Uses three-dot diff against ``origin/{base_ref}`` when available
    (merge-base comparison — works regardless of checkout merge strategy).
    Falls back to ``HEAD~1`` when base_ref is not provided.
    """
    # Primary: merge-base diff against the target branch
    if base_ref:
        try:
            result = subprocess.run(
                [
                    "git", "diff", "--name-only", "--diff-filter=ACMR",
                    f"origin/{base_ref}...HEAD",
                ],
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
            logger.warning(
                "Merge-base diff failed (rc=%d), falling back to HEAD~1",
                result.returncode,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Merge-base diff error: %s, falling back to HEAD~1", exc)

    # Fallback: diff against first parent (assumes merge commit)
    try:
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

    changed_files = _get_changed_files(repo_path, context.base_ref)
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
