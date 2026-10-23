"""Tests for issue_events.py (former Handle Issue Event and Post Auto-Reopen Comment steps)."""

from release_automation.scripts.issue_events import REOPEN_REASON, IssueEventOutcome, reopen_release_issue
from release_automation.tests.fake_github import FakeGitHub, gh_error

BASE = {"release_tag": "r1.4", "state": "snapshot-active", "release_pr_number": "41",
        "release_pr_url": "https://github.com/camaraproject/Example/pull/41"}


def test_reopen_posts_issue_reopened():
    gh = FakeGitHub()

    outcome = reopen_release_issue(gh, 40, "r1.4", BASE)

    assert outcome == IssueEventOutcome(success=True, action_taken="reopened")
    assert gh.reopened == [40]
    assert gh.calls == ["reopen_issue", "create_comment"]
    body = gh.comments[0]["body"]
    assert gh.comments[0]["issue"] == 40
    assert body.startswith("<!-- release-bot:r1.4 -->\n**🔄 Issue reopened — State: `snapshot-active`**")
    assert "**Release PR:** [#41](https://github.com/camaraproject/Example/pull/41)" in body


def test_reopen_failure_posts_nothing(capsys):
    gh = FakeGitHub(fail={"reopen_issue": [gh_error("HTTP 403")]})

    outcome = reopen_release_issue(gh, 40, "r1.4", BASE)

    assert outcome == IssueEventOutcome(success=False, action_taken="", error_message="gh command failed: HTTP 403")
    assert gh.comments == []
    assert "::error::Could not reopen #40: gh command failed: HTTP 403" in capsys.readouterr().out


def test_comment_failure_fails_the_outcome():
    gh = FakeGitHub(fail={"create_comment": [gh_error("HTTP 500")]})

    outcome = reopen_release_issue(gh, 40, "r1.4", BASE)

    assert outcome == IssueEventOutcome(success=False, action_taken="reopened", error_message="gh command failed: HTTP 500")


def test_reason_text_is_unchanged():
    assert REOPEN_REASON == "Cannot close Release Issue while release is in progress"
