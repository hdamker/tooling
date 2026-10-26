"""Tests for release_line.py: the line a release tag belongs to, and the base branch per trigger (spec 1.1-1.4)."""

import json

import pytest

from release_automation.scripts import release_line
from release_automation.scripts.release_line import base_branch_for, line_of, maintenance_branch
from release_automation.scripts.trigger import Trigger
from release_automation.tests.fake_github import FakeGitHub

MB = "maintenance/r1"


def repo(*branches):
    return FakeGitHub(branches={"main": "m1", **{b: "x" for b in branches}})


@pytest.mark.parametrize(
    "tag,branch",
    [("r1.8", "maintenance/r1"), ("r12.3", "maintenance/r12"), ("", ""), ("v1.0", "")],
)
def test_maintenance_branch(tag, branch):
    assert maintenance_branch(tag) == branch


def test_line_is_main_without_maintenance_branch():
    assert line_of(repo(), "r1.7") == "main"


def test_line_is_the_maintenance_branch_when_it_exists():
    gh = repo(MB)

    assert line_of(gh, "r1.8") == MB
    assert line_of(gh, "r2.2") == "main"


def test_line_of_an_unparsable_tag_is_main():
    assert line_of(repo(MB), "") == "main"


# ── base branch per trigger ─────────────────────────────────────────────────


@pytest.mark.parametrize("trigger_type", ["push", "workflow_dispatch"])
@pytest.mark.parametrize(
    "ref,base",
    [
        ("main", "main"),
        (MB, MB),  # spec 1.2
        ("feature/x", "main"),  # dispatch from another branch syncs main, as before
        ("maintenance-r1", "main"),  # pre-automation hyphenated branch is not a line
        ("", "main"),
    ],
)
def test_push_and_dispatch_use_the_ref_branch(trigger_type, ref, base):
    trigger = Trigger(trigger_type=trigger_type, command="sync-issue", should_continue=True, ref=ref)

    assert base_branch_for(trigger, repo(MB)) == base


@pytest.mark.parametrize("trigger_type", ["slash_command", "issue_close", "issue_reopen", "pr_merge"])
def test_tag_triggers_use_the_line_of_the_tag(trigger_type):
    # spec 1.3 (slash command, issue events) and 1.4 (pr_merge)
    trigger = Trigger(trigger_type=trigger_type, should_continue=True, release_tag="r1.8")

    assert base_branch_for(trigger, repo(MB)) == MB
    assert base_branch_for(trigger, repo()) == "main"


def test_tag_trigger_without_tag_uses_main():
    trigger = Trigger(trigger_type="slash_command", command="sync-issue", should_continue=True)

    assert base_branch_for(trigger, repo(MB)) == "main"


@pytest.mark.parametrize(
    "tag,version",
    [("r1.8", (1, 8)), ("r1.10", (1, 10)), ("r12.3", (12, 3)), ("", None), ("r1", None), ("v1.0", None)],
)
def test_tag_version(tag, version):
    assert release_line.tag_version(tag) == version


# ── main(): the plan job's resolve step (trigger + line → GITHUB_OUTPUT) ─────

from release_automation.tests.test_trigger import issue_comment_payload, push_payload, read_outputs  # noqa: E402


def run_resolve(tmp_path, monkeypatch, event_name, payload, client=None):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payload))
    output_path = tmp_path / "output"
    output_path.write_text("")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", "erin")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    assert release_line.main(client=client or repo()) == 0
    return read_outputs(output_path)


def test_resolve_writes_the_trigger_and_the_base_branch(tmp_path, monkeypatch):
    payload = issue_comment_payload("/publish-release --confirm r1.8", issue_body=(
        "<!-- release-automation:workflow-owned -->\n<!-- release-automation:release-tag:r1.8 -->\n"
    ))

    out = run_resolve(tmp_path, monkeypatch, "issue_comment", payload, client=repo(MB))

    assert set(out) == {"trigger", "should_continue", "base_branch"}
    assert Trigger(**json.loads(out["trigger"])) == Trigger(
        trigger_type="slash_command", command="publish-release", command_args="--confirm r1.8",
        issue_number="42", user="alice", should_continue=True, confirm_tag="r1.8", release_tag="r1.8",
    )
    assert (out["should_continue"], out["base_branch"]) == ("true", MB)


def test_resolve_push_uses_the_pushed_branch(tmp_path, monkeypatch):
    out = run_resolve(tmp_path, monkeypatch, "push", push_payload())

    trigger = json.loads(out["trigger"])
    assert (trigger["trigger_type"], trigger["command"], trigger["user"]) == ("push", "sync-issue", "erin")
    assert out["base_branch"] == "main"


def test_resolve_skipped_event_resolves_no_branch(tmp_path, monkeypatch):
    class NoCalls:
        def get_branch_sha(self, name):
            raise AssertionError("no lookup for a skipped event")

    out = run_resolve(tmp_path, monkeypatch, "issue_comment", issue_comment_payload("/create-snapshot", labels=[]), NoCalls())

    assert (out["should_continue"], out["base_branch"]) == ("false", "")
    assert json.loads(out["trigger"])["trigger_type"] == ""
