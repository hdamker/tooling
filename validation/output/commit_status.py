"""Commit status payload generation.

Produces a ``CommitStatusPayload`` that the workflow step sends via
``github.rest.repos.createCommitStatus()``.  The Python code does not
call the GitHub API — it only prepares the payload.

Design doc references:
  - Section 9.3: commit status (context, state mapping)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from validation.context import ValidationContext
from validation.postfilter.engine import PostFilterResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATUS_CONTEXT = "CAMARA Validation"

_DESCRIPTION_MAX_LEN = 140

_RESULT_TO_STATE = {
    "pass": "success",
    "advisory": "success",
    "fail": "failure",
    "error": "error",
}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitStatusPayload:
    """Payload for ``createCommitStatus`` GitHub API call.

    Attributes:
        state: One of ``"success"``, ``"failure"``, ``"error"``.
        description: Short summary (max 140 characters).
        context: Check context identifier.
        target_url: Link to the full workflow run.
    """

    state: str
    description: str
    context: str
    target_url: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_commit_status(
    post_filter_result: PostFilterResult,
    context: ValidationContext,
) -> CommitStatusPayload:
    """Generate the commit status payload.

    Args:
        post_filter_result: Output of the post-filter engine.
        context: Unified validation context.

    Returns:
        :class:`CommitStatusPayload` ready for the workflow step to post.
    """
    state = _RESULT_TO_STATE.get(post_filter_result.result, "error")

    description = post_filter_result.summary
    if len(description) > _DESCRIPTION_MAX_LEN:
        description = description[: _DESCRIPTION_MAX_LEN - 1] + "\u2026"

    return CommitStatusPayload(
        state=state,
        description=description,
        context=STATUS_CONTEXT,
        target_url=context.workflow_run_url,
    )
