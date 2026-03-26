"""Workflow summary generation for ``$GITHUB_STEP_SUMMARY``.

Produces a Markdown string with header, per-API summary table, findings
tables grouped by severity level, engine status table, and footer.
Implements 900 KB truncation with priority ordering (errors are never
truncated).

Design doc references:
  - Section 9.3: workflow summary structure and truncation strategy
  - Section 9.4: 1 MB GitHub limit (900 KB safety margin)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from validation.context import ValidationContext
from validation.postfilter.engine import PostFilterResult

from .formatting import (
    REPO_LEVEL_LABEL,
    count_findings,
    count_findings_by_api,
    format_rule_label,
    sort_findings_by_priority,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUMMARY_SIZE_LIMIT = 900 * 1024  # 900 KB (GitHub limit is 1 MB)

_RESULT_LABEL = {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryResult:
    """Result of workflow summary generation.

    Attributes:
        markdown: Complete Markdown string for ``$GITHUB_STEP_SUMMARY``.
        truncated: Whether any findings sections were truncated.
        truncation_note: Human-readable note about what was truncated,
            or empty string if nothing was truncated.
    """

    markdown: str
    truncated: bool
    truncation_note: str


# ---------------------------------------------------------------------------
# Internal section renderers
# ---------------------------------------------------------------------------


def _render_header(
    result: str,
    context: ValidationContext,
) -> str:
    """Render the summary header with result and metadata."""
    label = _RESULT_LABEL.get(result, result.upper())
    return (
        f"## CAMARA Validation — {label}\n\n"
        f"**Profile**: {context.profile} | "
        f"**Branch**: {context.branch_type} | "
        f"**Trigger**: {context.trigger_type}\n"
    )


def _render_api_table(findings: List[dict]) -> str:
    """Render the per-API summary table."""
    by_api = count_findings_by_api(findings)
    if not by_api:
        return ""

    lines = [
        "\n### Summary\n",
        "| API | Errors | Warnings | Hints |",
        "|-----|--------|----------|-------|",
    ]
    for api_name, counts in by_api.items():
        lines.append(
            f"| {api_name} | {counts.errors} | {counts.warnings} | {counts.hints} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_findings_table(
    findings: List[dict],
    level_label: str,
) -> str:
    """Render a findings table for a single severity level.

    Returns an empty string if there are no findings at this level.
    """
    if not findings:
        return ""

    lines = [
        f"\n### {level_label}\n",
        "| Rule | File | Line | Message | Hint |",
        "|------|------|------|---------|------|",
    ]
    for f in findings:
        rule = format_rule_label(f)
        path = f.get("path", "")
        line = f.get("line", 0)
        message = f.get("message", "").replace("|", "\\|")
        hint = (f.get("hint") or "").replace("|", "\\|")
        lines.append(f"| {rule} | {path} | {line} | {message} | {hint} |")
    lines.append("")
    return "\n".join(lines)


def _render_engine_table(
    engine_statuses: Optional[Dict[str, str]],
) -> str:
    """Render the engine status table."""
    if not engine_statuses:
        return ""

    lines = [
        "\n### Engine Status\n",
        "| Engine | Status |",
        "|--------|--------|",
    ]
    for engine, status in engine_statuses.items():
        lines.append(f"| {engine} | {status} |")
    lines.append("")
    return "\n".join(lines)


def _render_footer(
    context: ValidationContext,
    commit_sha: str,
) -> str:
    """Render the footer with commit info and workflow link."""
    parts = []
    if commit_sha:
        parts.append(f"Commit: {commit_sha[:7]}")
    if context.tooling_ref:
        parts.append(f"Tooling: {context.tooling_ref[:7]}")
    if context.workflow_run_url:
        parts.append(f"[Full workflow run]({context.workflow_run_url})")
    if not parts:
        return ""
    return "\n---\n" + " | ".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def _byte_size(text: str) -> int:
    """Return the UTF-8 byte size of *text*."""
    return len(text.encode("utf-8"))


def _truncation_notice(shown: int, total: int, level_label: str) -> str:
    """Build a truncation notice for a findings section."""
    return (
        f"> Showing {shown} of {total} {level_label.lower()} findings. "
        f"Full results available in workflow artifacts.\n"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_workflow_summary(
    post_filter_result: PostFilterResult,
    context: ValidationContext,
    engine_statuses: Optional[Dict[str, str]] = None,
    commit_sha: str = "",
) -> SummaryResult:
    """Generate the full workflow summary Markdown.

    Implements truncation: errors are never truncated; warnings and then
    hints are truncated if the cumulative size exceeds
    :data:`SUMMARY_SIZE_LIMIT`.

    Args:
        post_filter_result: Output of the post-filter engine.
        context: Unified validation context.
        engine_statuses: Optional mapping of engine name to status string.
        commit_sha: Full commit SHA (first 7 chars shown in footer).

    Returns:
        :class:`SummaryResult` with the complete Markdown and truncation info.
    """
    findings = post_filter_result.findings
    sorted_all = sort_findings_by_priority(findings)

    # Partition by level
    errors = [f for f in sorted_all if f.get("level") == "error"]
    warnings = [f for f in sorted_all if f.get("level") == "warn"]
    hints = [f for f in sorted_all if f.get("level") == "hint"]

    # Fixed sections (always rendered)
    header = _render_header(post_filter_result.result, context)
    api_table = _render_api_table(findings)
    engine_table = _render_engine_table(engine_statuses)
    footer = _render_footer(context, commit_sha)

    fixed_size = sum(
        _byte_size(s) for s in (header, api_table, engine_table, footer)
    )

    # Budget for findings sections
    budget = SUMMARY_SIZE_LIMIT - fixed_size
    truncated = False
    truncation_note = ""

    # Errors section — never truncated
    errors_section = _render_findings_table(errors, "Errors")
    budget -= _byte_size(errors_section)

    # Warnings section — truncated if over budget
    warnings_section = _render_findings_table(warnings, "Warnings")
    if budget - _byte_size(warnings_section) < 0 and warnings:
        # Find how many warnings fit
        shown = _fit_count(warnings, "Warnings", budget)
        if shown > 0:
            warnings_section = _render_findings_table(warnings[:shown], "Warnings")
            warnings_section += _truncation_notice(
                shown, len(warnings), "Warnings"
            )
        else:
            warnings_section = _truncation_notice(0, len(warnings), "Warnings")
        truncated = True
        truncation_note = f"{len(warnings) - shown} warning(s) truncated"
    budget -= _byte_size(warnings_section)

    # Hints section — truncated if over budget
    hints_section = _render_findings_table(hints, "Hints")
    if budget - _byte_size(hints_section) < 0 and hints:
        shown = _fit_count(hints, "Hints", budget)
        if shown > 0:
            hints_section = _render_findings_table(hints[:shown], "Hints")
            hints_section += _truncation_notice(shown, len(hints), "Hints")
        else:
            hints_section = _truncation_notice(0, len(hints), "Hints")
        truncated = True
        note = f"{len(hints) - shown} hint(s) truncated"
        truncation_note = (
            f"{truncation_note}; {note}" if truncation_note else note
        )

    # Assemble
    markdown = (
        header
        + api_table
        + errors_section
        + warnings_section
        + hints_section
        + engine_table
        + footer
    )

    return SummaryResult(
        markdown=markdown,
        truncated=truncated,
        truncation_note=truncation_note,
    )


def _fit_count(
    findings: List[dict],
    level_label: str,
    budget: int,
) -> int:
    """Binary-search for how many findings fit within *budget* bytes.

    Accounts for the truncation notice size that will be appended.
    """
    if budget <= 0:
        return 0

    # Quick check: does the full section fit?
    full = _render_findings_table(findings, level_label)
    if _byte_size(full) <= budget:
        return len(findings)

    # Binary search
    lo, hi = 0, len(findings)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        section = _render_findings_table(findings[:mid], level_label)
        notice = _truncation_notice(mid, len(findings), level_label)
        if _byte_size(section) + _byte_size(notice) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo
