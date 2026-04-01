"""Check annotation generation via GitHub Actions workflow commands.

Produces ``::error``, ``::warning``, and ``::notice`` command strings
that GitHub Actions renders as file-pinned annotations in the PR diff.

Design doc references:
  - Section 9.3: check run annotations (50 per step limit, priority ordering)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from validation.postfilter.engine import PostFilterResult

from .formatting import deduplicate_findings, format_rule_label, sort_findings_by_priority

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANNOTATION_LIMIT = 50

_LEVEL_TO_COMMAND = {
    "error": "error",
    "warn": "warning",
    "hint": "notice",
}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnotationResult:
    """Result of annotation generation.

    Attributes:
        commands: Workflow command strings ready to print to stdout.
        total_findings: Total number of findings before truncation.
        annotations_emitted: Number of annotations actually emitted.
        truncated: Whether findings were truncated to the limit.
    """

    commands: List[str]
    total_findings: int
    annotations_emitted: int
    truncated: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize_message(text: str) -> str:
    """Sanitize a message for use in a workflow command.

    Workflow commands use ``::`` as delimiters and newlines as
    terminators.  Both must be escaped in the message body.
    """
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Percent-encode the characters that GitHub Actions interprets specially
    # in workflow command data: %, \r, \n, and :
    # Using the documented encoding: https://github.com/actions/toolkit
    text = text.replace("%", "%25")
    text = text.replace(":", "%3A")
    return text


def _build_command(finding: dict) -> str:
    """Build a single ``::error``/``::warning``/``::notice`` command."""
    level = finding.get("level", "hint")
    command = _LEVEL_TO_COMMAND.get(level, "notice")

    # Location parameters
    path = finding.get("path", "")
    line = finding.get("line", 1)
    col = finding.get("column")

    rule_label = format_rule_label(finding)

    # Title: human-readable message.  Rule ID in message body.
    title = finding.get("message", "")
    message = f"[{rule_label}] {title}"
    hint = finding.get("hint")
    if hint:
        message = f"{message} | Hint: {hint}"

    # Build parameter string
    params = f"file={path},line={line}"
    if col is not None:
        params += f",col={col}"
    params += f",title={_sanitize_message(title)}"

    return f"::{command} {params}::{_sanitize_message(message)}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_annotations(
    post_filter_result: PostFilterResult,
) -> AnnotationResult:
    """Generate workflow command annotation strings from findings.

    Findings are sorted by priority (errors first, then warnings, then
    hints) and truncated to :data:`ANNOTATION_LIMIT`.

    Args:
        post_filter_result: Output of the post-filter engine.

    Returns:
        :class:`AnnotationResult` with workflow command strings.
    """
    deduped = deduplicate_findings(post_filter_result.findings)
    sorted_findings = sort_findings_by_priority(deduped)
    total = len(sorted_findings)

    selected = sorted_findings[:ANNOTATION_LIMIT]
    commands = [_build_command(f) for f in selected]
    emitted = len(commands)
    truncated = total > ANNOTATION_LIMIT

    if truncated:
        logger.info(
            "Annotation limit reached: showing %d of %d findings",
            emitted,
            total,
        )

    return AnnotationResult(
        commands=commands,
        total_findings=total,
        annotations_emitted=emitted,
        truncated=truncated,
    )
