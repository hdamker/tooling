"""PR comment markdown generation.

Produces a concise summary comment for the pull request with a
create-or-update marker.  The actual posting is handled by the
workflow step (``actions/github-script``).

Design doc references:
  - Section 9.3: PR comment (concise, marker-based create-or-update)
"""

from __future__ import annotations

import logging

from validation.context import ValidationContext
from validation.postfilter.engine import PostFilterResult

from .formatting import count_findings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKER = "<!-- camara-validation -->"

_RESULT_LABEL = {
    "pass": "PASS",
    "fail": "FAIL",
    "error": "ERROR",
    "advisory": "ADVISORY",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_pr_comment(
    post_filter_result: PostFilterResult,
    context: ValidationContext,
) -> str:
    """Generate the PR comment markdown string.

    The returned string includes the :data:`MARKER` for idempotent
    create-or-update by the workflow step.

    Args:
        post_filter_result: Output of the post-filter engine.
        context: Unified validation context.

    Returns:
        Complete Markdown string ready to post as a PR comment.
    """
    result = post_filter_result.result
    findings = post_filter_result.findings
    # Advisory profile: show ADVISORY instead of PASS when findings exist
    if result == "pass" and context.profile == "advisory" and findings:
        result_label = _RESULT_LABEL["advisory"]
    else:
        result_label = _RESULT_LABEL.get(result, result.upper())
    counts = count_findings(findings)

    lines = [
        MARKER,
        f"### CAMARA Validation — {result_label}",
        "",
        (
            f"{counts.errors} errors, {counts.warnings} warnings, "
            f"{counts.hints} hints | Profile: {context.profile}"
        ),
        "",
    ]
    if context.workflow_run_url:
        lines.append(f"[View full results]({context.workflow_run_url})")
    else:
        lines.append("See workflow summary for full results.")

    return "\n".join(lines)
