"""Tests for trigger.py: event payload → Trigger.

One payload fixture per event. Expected values reproduce the former inline
`Detect Trigger Type` github-script step of release-automation-reusable.yml.
"""

import json

import pytest

from release_automation.scripts import trigger as trigger_mod
from release_automation.scripts.trigger import Trigger, parse_trigger


RELEASE_ISSUE_LABELS = [{"name": "release-issue"}, {"name": "release-state: planned"}]


def issue_comment_payload(body, labels=RELEASE_ISSUE_LABELS, commenter="alice"):
    return {
        "action": "created",
        "comment": {"id": 101, "body": body, "user": {"login": commenter}},
        "issue": {"number": 42, "labels": labels, "user": {"login": "release-bot[bot]"}},
    }


def parse(event_name, payload, actor="dispatcher", sha="f" * 40):
    return parse_trigger(event_name, payload, actor=actor, sha=sha)


# ── issue_comment ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,command,args",
    [
        ("/create-snapshot", "create-snapshot", ""),
        ("/create-snapshot please", "create-snapshot", ""),
        ("/discard-snapshot wrong API version", "discard-snapshot", "wrong API version"),
        ("/discard-snapshot", "discard-snapshot", ""),
        ("/delete-draft   needs rework  ", "delete-draft", "needs rework"),
        ("/sync-issue extra", "sync-issue", ""),
        ("/publish-release", "publish-release", ""),
        ("  /create-snapshot\n", "create-snapshot", ""),
    ],
)
def test_slash_command_on_release_issue(body, command, args):
    t = parse("issue_comment", issue_comment_payload(body))

    assert t == Trigger(
        trigger_type="slash_command",
        command=command,
        command_args=args,
        issue_number="42",
        user="alice",
        should_continue=True,
    )


def test_command_args_clamped_to_first_line():
    t = parse(
        "issue_comment",
        issue_comment_payload("/discard-snapshot bad tag\r\nmore context\nand more"),
    )

    assert t.command_args == "bad tag"


def test_command_args_keep_shell_metacharacters_verbatim():
    t = parse("issue_comment", issue_comment_payload("/delete-draft `rm -rf` $(id)"))

    assert t.command_args == "`rm -rf` $(id)"


@pytest.mark.parametrize(
    "body,confirm_tag,args",
    [
        ("/publish-release --confirm r1.2", "r1.2", "--confirm r1.2"),
        ("/publish-release   --confirm   r1.2 now", "r1.2", "--confirm   r1.2 now"),
        ("/publish-release --confirm", "", "--confirm"),
        ("/publish-release r1.2", "", "r1.2"),
    ],
)
def test_publish_release_confirm_tag(body, confirm_tag, args):
    t = parse("issue_comment", issue_comment_payload(body))

    assert t.command == "publish-release"
    assert t.command_args == args
    assert t.confirm_tag == confirm_tag


@pytest.mark.parametrize(
    "body",
    [
        "/create-snapshotextra",
        "/create-snapshot-now",
        "please /create-snapshot",
        "/unknown-command",
        "",
        "looks good to me",
    ],
)
def test_unrecognised_comment_on_release_issue(body):
    t = parse("issue_comment", issue_comment_payload(body))

    assert t == Trigger(
        trigger_type="unknown",
        issue_number="42",
        user="alice",
        should_continue=False,
    )


def test_comment_with_null_body():
    payload = issue_comment_payload("")
    payload["comment"]["body"] = None

    assert parse("issue_comment", payload).should_continue is False


def test_comment_on_other_issue_is_skipped():
    t = parse("issue_comment", issue_comment_payload("/create-snapshot", labels=[{"name": "bug"}]))

    assert t == Trigger(should_continue=False)


# ── issues ───────────────────────────────────────────────────────────────────


def issues_payload(action, labels=RELEASE_ISSUE_LABELS):
    return {
        "action": action,
        "issue": {"number": 42, "labels": labels, "user": {"login": "release-bot[bot]"}},
        "sender": {"login": "alice"},
    }


@pytest.mark.parametrize(
    "action,trigger_type",
    [("closed", "issue_close"), ("reopened", "issue_reopen")],
)
def test_issue_close_and_reopen(action, trigger_type):
    t = parse("issues", issues_payload(action))

    # user is the issue author, not the sender (as the JS step had it)
    assert t == Trigger(
        trigger_type=trigger_type,
        issue_number="42",
        user="release-bot[bot]",
        should_continue=True,
    )


def test_other_issue_action_is_ignored():
    t = parse("issues", issues_payload("labeled"))

    assert t == Trigger(
        trigger_type="unknown", issue_number="42", user="release-bot[bot]", should_continue=False
    )


def test_issue_event_on_other_issue_is_skipped():
    assert parse("issues", issues_payload("closed", labels=[])) == Trigger(should_continue=False)


# ── pull_request ─────────────────────────────────────────────────────────────


def pr_payload(action="closed", merged=True, base="release-snapshot/r1.2-abc1234", merged_by="carol"):
    return {
        "action": action,
        "pull_request": {
            "number": 7,
            "merged": merged,
            "base": {"ref": base},
            "user": {"login": "release-bot[bot]"},
            "merged_by": {"login": merged_by} if merged_by else None,
        },
    }


def test_merged_pr_into_snapshot_branch():
    t = parse("pull_request", pr_payload())

    assert t == Trigger(trigger_type="pr_merge", user="carol", should_continue=True)


def test_merged_pr_without_merged_by_falls_back_to_author():
    assert parse("pull_request", pr_payload(merged_by=None)).user == "release-bot[bot]"


@pytest.mark.parametrize(
    "payload",
    [
        pr_payload(merged=False),
        pr_payload(action="opened", merged=False),
        pr_payload(base="main"),
        pr_payload(base="release-review/r1.2-abc1234"),
    ],
)
def test_other_pull_request_events_are_ignored(payload):
    assert parse("pull_request", payload) == Trigger(trigger_type="unknown")


# ── workflow_dispatch ────────────────────────────────────────────────────────


def test_workflow_dispatch_is_sync_issue():
    payload = {"inputs": {"command": "create-snapshot"}, "ref": "refs/heads/main"}

    t = parse("workflow_dispatch", payload, actor="dave")

    # The dispatch input is ignored: dispatch only ever syncs the issue.
    assert t == Trigger(
        trigger_type="workflow_dispatch", command="sync-issue", user="dave", should_continue=True
    )


# ── push ─────────────────────────────────────────────────────────────────────


def push_payload(*commits, head="a" * 40):
    return {
        "ref": "refs/heads/main",
        "head_commit": {"id": head} if head else None,
        "commits": list(commits),
    }


def test_push_changing_release_plan():
    payload = push_payload(
        {"added": [], "modified": ["README.md"], "removed": []},
        {"added": [], "modified": ["release-plan.yaml"], "removed": []},
    )

    t = parse("push", payload, actor="erin")

    assert t == Trigger(
        trigger_type="release_plan_change",
        command="sync-issue",
        user="erin",
        should_continue=True,
        head_sha="a" * 40,
    )


@pytest.mark.parametrize(
    "commits",
    [
        [{"added": ["code/common/CAMARA_common.yaml"], "modified": [], "removed": []}],
        [{"modified": [".github/workflows/release-automation.yml"]}],
        [{"added": ["docs/release-plan.yaml"]}],
        [],
    ],
)
def test_push_without_release_plan_change(commits):
    t = parse("push", push_payload(*commits), actor="erin")

    assert t.trigger_type == "push"
    assert t.command == "sync-issue"
    assert t.should_continue is True


def test_push_release_plan_removed_counts_as_change():
    t = parse("push", push_payload({"removed": ["release-plan.yaml"]}))

    assert t.trigger_type == "release_plan_change"


def test_push_without_head_commit_uses_github_sha():
    t = parse("push", push_payload(head=None), sha="b" * 40)

    assert t.head_sha == "b" * 40


# ── other events ─────────────────────────────────────────────────────────────


def test_unhandled_event():
    assert parse("schedule", {"schedule": "0 0 * * *"}) == Trigger(trigger_type="unknown")


# ── main(): env → GITHUB_OUTPUT ──────────────────────────────────────────────


class FakeClient:
    def __init__(self, merged_pr=None):
        self.merged_pr = merged_pr
        self.looked_up = []

    def find_merged_pr_for_commit(self, sha):
        self.looked_up.append(sha)
        return self.merged_pr


def read_outputs(path):
    """Parse GITHUB_OUTPUT heredoc entries (name<<DELIM ... DELIM)."""
    outputs = {}
    lines = path.read_text().split("\n")
    i = 0
    while i < len(lines):
        if "<<" in lines[i]:
            name, delim = lines[i].split("<<", 1)
            j = lines.index(delim, i + 1)
            outputs[name] = "\n".join(lines[i + 1:j])
            i = j
        i += 1
    return outputs


def run_main(tmp_path, monkeypatch, event_name, payload, client=None):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payload))
    output_path = tmp_path / "output"
    output_path.write_text("")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", "erin")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_REPOSITORY", "camaraproject/ReleaseTest2")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    trigger_mod.main(client=client)
    return read_outputs(output_path)


OUTPUT_NAMES = {
    "trigger_type", "command", "command_args", "issue_number", "user",
    "should_continue", "confirm_tag", "trigger_pr_number", "trigger_pr_url", "trigger",
}


def test_main_writes_check_trigger_outputs(tmp_path, monkeypatch):
    payload = issue_comment_payload("/publish-release --confirm r1.2")

    out = run_main(tmp_path, monkeypatch, "issue_comment", payload, client=FakeClient())

    assert set(out) == OUTPUT_NAMES
    assert Trigger(**json.loads(out.pop("trigger"))) == parse("issue_comment", payload)
    assert out == {
        "trigger_type": "slash_command",
        "command": "publish-release",
        "command_args": "--confirm r1.2",
        "issue_number": "42",
        "user": "alice",
        "should_continue": "true",
        "confirm_tag": "r1.2",
        "trigger_pr_number": "",
        "trigger_pr_url": "",
    }


def test_main_skipped_event(tmp_path, monkeypatch):
    payload = issue_comment_payload("/create-snapshot", labels=[])

    out = run_main(tmp_path, monkeypatch, "issue_comment", payload, client=FakeClient())

    assert out["should_continue"] == "false"
    assert out["trigger_type"] == ""


def test_main_push_looks_up_merged_pr(tmp_path, monkeypatch):
    client = FakeClient(merged_pr=(17, "https://github.com/camaraproject/ReleaseTest2/pull/17"))
    payload = push_payload({"modified": ["release-plan.yaml"]}, head="d" * 40)

    out = run_main(tmp_path, monkeypatch, "push", payload, client=client)

    assert client.looked_up == ["d" * 40]
    assert out["trigger_type"] == "release_plan_change"
    assert out["user"] == "erin"
    assert out["trigger_pr_number"] == "17"
    assert out["trigger_pr_url"] == "https://github.com/camaraproject/ReleaseTest2/pull/17"


def test_main_push_without_merged_pr(tmp_path, monkeypatch):
    out = run_main(tmp_path, monkeypatch, "push", push_payload(), client=FakeClient())

    assert out["trigger_pr_number"] == ""
    assert out["trigger_pr_url"] == ""


def test_main_non_push_does_not_look_up_pr(tmp_path, monkeypatch):
    client = FakeClient(merged_pr=(1, "u"))

    run_main(tmp_path, monkeypatch, "workflow_dispatch", {}, client=client)

    assert client.looked_up == []
