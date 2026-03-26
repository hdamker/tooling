"""Shared formatting utilities for the output pipeline.

Pure functions for counting, sorting, and labelling findings.  Used by
all output surface modules (workflow summary, annotations, PR comment,
commit status, diagnostics).

Design doc references:
  - Section 9.2: finding grouping and priority ordering
  - Section 9.3: per-API summary table
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority ordering for levels
# ---------------------------------------------------------------------------

_LEVEL_PRIORITY = {"error": 0, "warn": 1, "hint": 2}

# Sentinel label for repo-level findings (api_name is None)
REPO_LEVEL_LABEL = "(repository)"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FindingCounts:
    """Aggregate counts for a set of findings."""

    errors: int
    warnings: int
    hints: int
    total: int
    blocking: int


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def count_findings(findings: List[dict]) -> FindingCounts:
    """Count findings by level and blocking status."""
    errors = 0
    warnings = 0
    hints = 0
    blocking = 0
    for f in findings:
        level = f.get("level", "")
        if level == "error":
            errors += 1
        elif level == "warn":
            warnings += 1
        elif level == "hint":
            hints += 1
        if f.get("blocks"):
            blocking += 1
    return FindingCounts(
        errors=errors,
        warnings=warnings,
        hints=hints,
        total=len(findings),
        blocking=blocking,
    )


def count_findings_by_api(
    findings: List[dict],
) -> Dict[str, FindingCounts]:
    """Group findings by ``api_name`` and count each group.

    Findings with ``api_name`` of ``None`` are grouped under
    :data:`REPO_LEVEL_LABEL`.  Keys are returned in insertion order
    (first-seen API name).
    """
    groups: Dict[str, List[dict]] = {}
    for f in findings:
        key = f.get("api_name") or REPO_LEVEL_LABEL
        groups.setdefault(key, []).append(f)
    return {api: count_findings(fs) for api, fs in groups.items()}


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def sort_findings_by_priority(findings: List[dict]) -> List[dict]:
    """Sort findings: errors first, then warnings, then hints.

    Within the same level, sort by file path then line number.
    The sort is stable — equal items preserve their original order.
    """
    return sorted(
        findings,
        key=lambda f: (
            _LEVEL_PRIORITY.get(f.get("level", ""), 99),
            f.get("path", ""),
            f.get("line", 0),
        ),
    )


# ---------------------------------------------------------------------------
# Label formatting
# ---------------------------------------------------------------------------


def format_rule_label(finding: dict) -> str:
    """Return the best short label for a finding's rule.

    Uses ``rule_id`` when present (e.g. ``"S-042"``), otherwise falls
    back to ``engine_rule``.
    """
    return finding.get("rule_id") or finding.get("engine_rule", "unknown")


def format_finding_location(finding: dict) -> str:
    """Format a finding's location as ``path:line`` or ``path:line:column``."""
    path = finding.get("path", "")
    line = finding.get("line", 0)
    column = finding.get("column")
    if column is not None:
        return f"{path}:{line}:{column}"
    return f"{path}:{line}"
