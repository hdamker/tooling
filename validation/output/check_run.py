"""Check Run payload generation for the GitHub Checks API.

Produces a structured payload that the workflow step uses to create a
Check Run with inline annotations.  Unlike workflow commands (which
have a ~10-per-level display cap), Check Run annotations are all
visible in the PR Files tab.

The workflow handles batching (50 annotations per API call) and token
resolution.  This module produces the full payload without truncation.

Design doc references:
  - Section 9.2: check annotations (Checks API migration)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import List

from validation.context import ValidationContext
from validation.postfilter.engine import PostFilterResult

from .formatting import count_findings, format_rule_label, sort_findings_by_priority

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Checks API annotation levels (different from workflow command levels)
_LEVEL_TO_ANNOTATION = {
    "error": "failure",
    "warn": "warning",
    "hint": "notice",
}

_RESULT_TO_CONCLUSION = {
    "pass": "success",
    "fail": "failure",
    "error": "failure",
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckRunPayload:
    """Structured payload for creating a GitHub Check Run.

    Attributes:
        conclusion: Check Run conclusion (success, failure, neutral).
        title: Short summary for the Check Run header.
        summary: Brief markdown for the Check Run output.
        annotations: All findings as Checks API annotation dicts.
    """

    conclusion: str
    title: str
    summary: str
    annotations: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_annotation(finding: dict) -> dict:
    """Convert a single finding to a Checks API annotation dict."""
    level = finding.get("level", "hint")
    annotation_level = _LEVEL_TO_ANNOTATION.get(level, "notice")

    path = finding.get("path", "")
    line = finding.get("line", 1)
    title = format_rule_label(finding)

    message = finding.get("message", "")
    hint = finding.get("hint")
    if hint:
        message = f"{message}\n\nHint: {hint}"

    return {
        "path": path,
        "start_line": line,
        "end_line": line,
        "annotation_level": annotation_level,
        "title": title,
        "message": message,
    }


def _resolve_conclusion(
    result: str,
    profile: str,
    has_findings: bool,
) -> str:
    """Map validation result to Checks API conclusion.

    - pass → success
    - fail → failure
    - error → failure
    - advisory override: pass + advisory profile + findings → neutral
    """
    if result == "pass" and profile == "advisory" and has_findings:
        return "neutral"
    return _RESULT_TO_CONCLUSION.get(result, "failure")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_check_run_payload(
    post_filter_result: PostFilterResult,
    context: ValidationContext,
) -> CheckRunPayload:
    """Generate the full Check Run payload from validation results.

    All findings are included as annotations (no truncation).
    The workflow step handles batching (50 per API call).

    Args:
        post_filter_result: Output of the post-filter engine.
        context: Unified validation context.

    Returns:
        :class:`CheckRunPayload` ready for JSON serialization.
    """
    findings = post_filter_result.findings
    counts = count_findings(findings)

    conclusion = _resolve_conclusion(
        post_filter_result.result,
        context.profile,
        bool(findings),
    )

    title = (
        f"{counts.errors} error{'s' if counts.errors != 1 else ''}, "
        f"{counts.warnings} warning{'s' if counts.warnings != 1 else ''}, "
        f"{counts.hints} hint{'s' if counts.hints != 1 else ''}"
    )

    summary = (
        f"Profile: {context.profile} | "
        f"Branch: {context.branch_type} | "
        f"Trigger: {context.trigger_type}"
    )

    sorted_findings = sort_findings_by_priority(findings)
    annotations = [_build_annotation(f) for f in sorted_findings]

    logger.info(
        "Check Run payload: conclusion=%s, %d annotations",
        conclusion,
        len(annotations),
    )

    return CheckRunPayload(
        conclusion=conclusion,
        title=title,
        summary=summary,
        annotations=annotations,
    )
