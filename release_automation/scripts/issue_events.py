"""
Release Issue close events for CAMARA release automation.

A Release Issue closed while its release is in progress (snapshot-active or
draft-ready; the plan decides) is reopened with an issue_reopened comment.
Closes in other states and reopens need no action here; finalize syncs the issue.
"""

from dataclasses import dataclass
from typing import Any

from .bot_responder import post_comment
from .github_client import GitHubClientError

REOPEN_REASON = "Cannot close Release Issue while release is in progress"


@dataclass(frozen=True)
class IssueEventOutcome:
    success: bool
    action_taken: str = ""
    error_message: str = ""


def reopen_release_issue(gh, issue_number: int, release_tag: str, base_context: Any) -> IssueEventOutcome:
    print(f"Auto-reopening issue #{issue_number}")
    try:
        gh.reopen_issue(issue_number)
    except GitHubClientError as e:
        print(f"::error::Could not reopen #{issue_number}: {e}")
        return IssueEventOutcome(success=False, error_message=str(e))
    print("Issue reopened successfully")
    try:
        post_comment(gh, "issue_reopened", issue_number, base_context, {"reason": REOPEN_REASON}, release_tag)
    except GitHubClientError as e:
        print(f"::error::Could not post issue_reopened: {e}")
        return IssueEventOutcome(success=False, action_taken="reopened", error_message=str(e))
    return IssueEventOutcome(success=True, action_taken="reopened")
