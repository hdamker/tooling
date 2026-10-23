"""Tests for finalize.py (the finalize job: sync PRs, Release Issue, result comment).

Expected values reproduce the former update-issue, post-result and
create-sync-pr jobs of release-automation-reusable.yml: their job and step
conditions, "Resolve Sync Context", "Determine Result Template", "Resolve
Reason" and "Build Result Context".
"""

import json

import pytest

from release_automation.scripts import finalize
from release_automation.scripts.common_sync import CommonSyncOutcome
from release_automation.scripts.finalize import (
    Run,
    issue_sync_due,
    notifications,
    result_context,
    result_due,
    result_template,
    sync_overrides,
)
from release_automation.scripts.issue_sync import WorkflowSync
from release_automation.scripts.sync_pr import SyncPrOutcome

ACTION_JOBS = ("create-snapshot", "discard-snapshot", "delete-draft", "publish-release", "handle-pr-merge", "handle-issue-event")

PLAN = {
    "trigger_type": "slash_command",
    "command": "create-snapshot",
    "command_args": "",
    "issue_number": "42",
    "user": "alice",
    "allowed": "true",
    "interim_posted": "true",
    "config_error": "",
    "state": "planned",
    "release_tag": "r4.1",
    "release_issue_number": "42",
    "snapshot_branch": "release-snapshot/r4.1-abc1234",
    "src_commit_sha": "abc1234def5678",
    "common_cache_status": "",
    "common_cache_details": "",
    "common_sync_pr_url": "",
    "commonalities_release": "r4.3",
    "base_context": json.dumps({"release_tag": "r4.1", "state": "planned"}),
    "comment_id": "555",
}


def make_run(plan=None, jobs=None, event=None):
    needs = {"plan": {"result": "success", "outputs": {**PLAN, **(plan or {})}}}
    for name in ACTION_JOBS:
        needs[name] = {"result": "skipped", "outputs": {}}
    for name, (result, outputs) in (jobs or {}).items():
        needs[name] = {"result": result, "outputs": outputs}
    return Run(
        needs=needs,
        event=event or {},
        server_url="https://github.com",
        repository="camaraproject/Example",
        run_id="999",
    )


def ok(**outputs):
    return ("success", {"success": "true", **outputs})


def failed(**outputs):
    return ("success", {"success": "false", **outputs})


# ── when each part runs ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "plan,jobs,due",
    [
        ({}, {"create-snapshot": ok()}, True),
        ({}, {"discard-snapshot": ok()}, True),
        ({}, {"delete-draft": ok()}, True),
        ({"trigger_type": "pr_merge"}, {"handle-pr-merge": ok()}, True),
        ({"trigger_type": "issue_close"}, {"handle-issue-event": ("success", {"action_taken": "reopened"})}, True),
        ({"command": "sync-issue"}, {}, True),
        ({"trigger_type": "push", "command": "sync-issue", "allowed": ""}, {}, True),
        ({}, {"create-snapshot": failed()}, False),
        ({}, {"create-snapshot": ("failure", {"success": "true"})}, False),
        ({"trigger_type": "pr_merge"}, {"handle-pr-merge": ("failure", {})}, False),
        # A publication never syncs the issue here; the published finalisation does.
        ({"command": "publish-release"}, {"publish-release": ok()}, False),
        ({"command": "sync-issue", "state": ""}, {}, False),
        ({"command": "sync-issue", "config_error": "missing"}, {}, False),
    ],
)
def test_issue_sync_due(plan, jobs, due):
    assert issue_sync_due(make_run(plan, jobs)) is due


@pytest.mark.parametrize(
    "plan,due",
    [
        ({}, True),
        ({"trigger_type": "push"}, False),
        ({"allowed": "false"}, False),
        ({"interim_posted": "false"}, False),
    ],
)
def test_result_due(plan, due):
    assert result_due(make_run(plan)) is due


# ── Resolve Sync Context ─────────────────────────────────────────────────────


def test_overrides_after_create_snapshot():
    run = make_run(jobs={"create-snapshot": ok(snapshot_branch="release-snapshot/r4.1-new", release_pr_number="12")})

    assert sync_overrides(run) == {
        "state_override": "snapshot-active",
        "snapshot_branch_override": "release-snapshot/r4.1-new",
        "release_pr_number_override": "12",
        "draft_release_url_override": "",
        "force_update": True,
    }


def test_overrides_after_draft_creation():
    run = make_run(
        {"trigger_type": "pr_merge"},
        {"handle-pr-merge": ok(draft_release_url="https://github.com/camaraproject/Example/releases/tag/untagged-1")},
        event={"pull_request": {"number": 14}},
    )

    assert sync_overrides(run) == {
        "state_override": "draft-ready",
        "snapshot_branch_override": "release-snapshot/r4.1-abc1234",
        "release_pr_number_override": "14",
        "draft_release_url_override": "https://github.com/camaraproject/Example/releases/tag/untagged-1",
        "force_update": True,
    }


@pytest.mark.parametrize("job", ["discard-snapshot", "delete-draft"])
def test_overrides_after_discard_or_delete(job):
    assert sync_overrides(make_run(jobs={job: ok()})) == {
        "state_override": "planned",
        "snapshot_branch_override": "",
        "release_pr_number_override": "",
        "draft_release_url_override": "",
        "force_update": True,
    }


@pytest.mark.parametrize("plan,force", [({"command": "sync-issue"}, True), ({"trigger_type": "issue_close", "command": ""}, False)])
def test_overrides_without_a_state_change(plan, force):
    assert sync_overrides(make_run(plan)) == {
        "state_override": "",
        "snapshot_branch_override": "",
        "release_pr_number_override": "",
        "draft_release_url_override": "",
        "force_update": force,
    }


# ── notifications after the issue sync ───────────────────────────────────────


def test_issue_created_notification():
    run = make_run(
        {"trigger_type": "issue_close", "command": ""},
        event={"issue": {"number": 40, "html_url": "https://github.com/camaraproject/Example/issues/40"}},
    )
    sync = WorkflowSync(issue_number="43", issue_action="created", issue_url="u")

    assert notifications(run, sync, None) == [("issue_created", "43", {
        "state": "planned",
        "trigger_type": "issue_close",
        "release_plan_url": "https://github.com/camaraproject/Example/blob/main/release-plan.yaml",
        "closed_issue_number": "40",
        "closed_issue_url": "https://github.com/camaraproject/Example/issues/40",
    })]


def test_issue_created_without_issue_event():
    sync = WorkflowSync(issue_number="43", issue_action="created")

    (_, _, delta), = notifications(make_run({"trigger_type": "push"}), sync, None)

    assert delta["closed_issue_number"] == "" and delta["closed_issue_url"] == ""


def test_not_planned_notification():
    # The former workflow compared state == 'not_planned'; the state value is
    # 'not-planned', so this comment was never posted.
    run = make_run({"state": "not-planned"})

    assert notifications(run, WorkflowSync(issue_number="42", issue_action="updated"), None) == [
        ("state_not_planned", "42", {"state": "not-planned"}),
    ]


@pytest.mark.parametrize("state", ["planned", "not_planned"])
def test_no_not_planned_notification_in_other_states(state):
    assert notifications(make_run({"state": state}), WorkflowSync(issue_number="42", issue_action="updated"), None) == []


def test_common_sync_pr_created_notification():
    run = make_run({"common_cache_details": 'manifest has "r4.2"', "release_issue_number": ""})
    common = CommonSyncOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/40", pr_number="40")

    assert notifications(run, WorkflowSync(issue_number="43", issue_action="unchanged"), common) == [
        ("common_sync_pr_created", "43", {
            "common_cache_details": 'manifest has "r4.2"',
            "common_sync_pr_url": "https://github.com/camaraproject/Example/pull/40",
        }),
    ]


@pytest.mark.parametrize("status", ["updated", "no_changes"])
def test_no_common_sync_notification_without_new_pr(status):
    assert notifications(make_run(), WorkflowSync(issue_action="unchanged"), CommonSyncOutcome(status=status)) == []


def test_common_sync_failed_notification_prefers_the_plan_issue():
    run = make_run({"release_issue_number": "42"})

    assert notifications(run, WorkflowSync(issue_number="43", issue_action="updated"), CommonSyncOutcome(status="failed")) == [
        ("common_sync_failed", "42", {}),
    ]


def test_no_common_sync_notification_without_an_issue():
    run = make_run({"release_issue_number": ""})

    assert notifications(run, WorkflowSync(issue_action="skipped"), CommonSyncOutcome(status="failed")) == []


# ── Determine Result Template ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command,jobs,template",
    [
        ("create-snapshot", {"create-snapshot": ok()}, "snapshot_created"),
        ("create-snapshot", {"create-snapshot": failed()}, "snapshot_failed"),
        ("create-snapshot", {"create-snapshot": ("failure", {})}, "snapshot_failed"),
        ("discard-snapshot", {"discard-snapshot": ok()}, "snapshot_discarded"),
        ("discard-snapshot", {"discard-snapshot": failed()}, "snapshot_failed"),
        ("delete-draft", {"delete-draft": ok()}, "draft_revoked"),
        ("delete-draft", {"delete-draft": failed()}, "snapshot_failed"),
        ("sync-issue", {}, "interim_processing"),
        ("publish-release", {"publish-release": ok()}, "release_published"),
        ("publish-release", {"publish-release": failed()}, "publish_failed"),
        ("unknown-cmd", {}, "internal_error"),
    ],
)
def test_result_template(command, jobs, template):
    assert result_template(make_run({"command": command}, jobs)) == template


# ── Resolve Reason + Build Result Context ────────────────────────────────────


@pytest.mark.parametrize(
    "command,args,reason",
    [
        ("discard-snapshot", "", "No reason provided"),
        ("delete-draft", "", "No reason provided"),
        ("discard-snapshot", "wrong `api` $(x)", "wrong `api` $(x)"),
        ("create-snapshot", "", ""),
        ("publish-release", "--confirm r4.1", "--confirm r4.1"),
    ],
)
def test_reason(command, args, reason):
    assert result_context(make_run({"command": command, "command_args": args}), None) == {"reason": reason}


def test_context_after_create_snapshot():
    apis = json.dumps([{"api_name": "qod", "api_version": "1.0.0-rc.1"}])
    run = make_run(jobs={"create-snapshot": ok(
        snapshot_id="r4.1-abc1234",
        snapshot_branch="release-snapshot/r4.1-abc1234",
        release_review_branch="release-review/r4.1-abc1234",
        release_pr_number="12",
        release_pr_url="https://github.com/camaraproject/Example/pull/12",
        apis_json=apis,
    )})

    assert result_context(run, None) == {
        "reason": "",
        "snapshot_id": "r4.1-abc1234",
        "snapshot_branch": "release-snapshot/r4.1-abc1234",
        "snapshot_branch_url": "https://github.com/camaraproject/Example/tree/release-snapshot/r4.1-abc1234",
        "release_review_branch": "release-review/r4.1-abc1234",
        "release_review_branch_url": "https://github.com/camaraproject/Example/tree/release-review/r4.1-abc1234",
        "release_pr_number": "12",
        "release_pr_url": "https://github.com/camaraproject/Example/pull/12",
        "apis_json": apis,
    }


@pytest.mark.parametrize("job", ["discard-snapshot", "delete-draft"])
def test_context_after_discard_names_the_preserved_branch(job):
    run = make_run({"command": job, "command_args": "redo"}, {job: ok(renamed_review_branch="release-review/r4.1-abc-preserved")})

    assert result_context(run, None) == {
        "reason": "redo",
        "release_review_branch": "release-review/r4.1-abc-preserved",
        "release_review_branch_url": "https://github.com/camaraproject/Example/tree/release-review/r4.1-abc-preserved",
    }


def test_context_after_discard_without_rename():
    run = make_run({"command": "discard-snapshot"}, {"discard-snapshot": ok(renamed_review_branch="")})

    assert result_context(run, None) == {"reason": "No reason provided"}


def publish(error_message=""):
    return {"publish-release": ok(
        release_url="https://github.com/camaraproject/Example/releases/tag/r4.1",
        reference_tag="src/r4.1",
        error_message=error_message,
    )}


def test_context_after_publish():
    run = make_run({"command": "publish-release", "command_args": "--confirm r4.1"}, publish())
    sync = SyncPrOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/20", pr_number="20")

    assert result_context(run, sync) == {
        "reason": "--confirm r4.1",
        "release_url": "https://github.com/camaraproject/Example/releases/tag/r4.1",
        "reference_tag": "src/r4.1",
        "reference_tag_url": "https://github.com/camaraproject/Example/tree/src/r4.1",
        "sync_pr_url": "https://github.com/camaraproject/Example/pull/20",
        "sync_pr_number": "20",
        "src_commit_sha_short": "abc1234",
    }


def test_context_after_publish_with_warnings():
    run = make_run({"command": "publish-release"}, publish("Failed to create pointer branch"))
    jobs_ref = run.needs["publish-release"]["outputs"]
    jobs_ref["reference_tag"] = ""

    context = result_context(run, SyncPrOutcome(status="no_changes"))

    assert context["reference_tag_url"] == ""
    assert context["sync_pr_url"] == "" and context["sync_pr_number"] == ""
    assert context["publish_warnings"] == (
        "Failed to create pointer branch; "
        "Post-release sync skipped (no changes detected) — verify README/CHANGELOG"
    )


def test_context_after_publish_without_sync_outcome():
    context = result_context(make_run({"command": "publish-release"}, publish()), None)

    assert context["publish_warnings"] == "Post-release sync status unknown — verify README/CHANGELOG"


@pytest.mark.parametrize(
    "job",
    ["create-snapshot", "discard-snapshot", "delete-draft", "publish-release"],
)
def test_context_carries_the_failure(job):
    run = make_run({"command": job}, {job: failed(error_message="boom")})

    assert result_context(run, None)["error_message"] == "boom"


def test_skipped_job_carries_no_failure():
    assert "error_message" not in result_context(make_run(jobs={"create-snapshot": ("skipped", {})}), None)


# ── orchestration ────────────────────────────────────────────────────────────

from release_automation.scripts import common_sync as common_sync_mod  # noqa: E402
from release_automation.scripts import issue_sync as issue_sync_mod  # noqa: E402
from release_automation.scripts import sync_pr as sync_pr_mod  # noqa: E402
from release_automation.scripts.finalize import Clients, finalize as run_finalize  # noqa: E402
from release_automation.scripts.github_client import GitHubClientError  # noqa: E402

ISSUE_BODY = (
    "<!-- BEGIN:STATE -->\nx\n<!-- END:STATE -->\n"
    "<!-- BEGIN:ACTIONS -->\nx\n<!-- END:ACTIONS -->\n"
)


class FakeGitHub:
    repo = "camaraproject/Example"

    def __init__(self, fail_comments=False):
        self.events = []
        self.fail_comments = fail_comments

    def get_user(self, login):
        return {"id": 7, "login": login}

    def create_comment(self, issue_number, body):
        if self.fail_comments:
            raise GitHubClientError("gh command failed: 502")
        self.events.append(("comment", issue_number, body))
        return 1000 + len(self.events)

    def update_comment(self, comment_id, body):
        if self.fail_comments:
            raise GitHubClientError("gh command failed: 502")
        self.events.append(("update", comment_id, body))

    def get_issue(self, number):
        return {"number": number, "body": ISSUE_BODY, "labels": [{"name": "release-state:draft-ready"}]}

    def update_issue(self, number, title=None, body=None):
        self.events.append(("issue-body", number, body))

    def remove_labels(self, number, labels):
        self.events.append(("remove-labels", number, labels))

    def add_labels(self, number, labels):
        self.events.append(("add-labels", number, labels))

    def close_issue(self, number, state_reason="completed"):
        self.events.append(("close", number, state_reason))


@pytest.fixture
def stubs(monkeypatch):
    calls = {}

    def fake_sync_pr(gh, git, tag, bot_name, bot_email):
        calls["sync_pr"] = dict(work_dir=git.work_dir, tag=tag, bot=(bot_name, bot_email))
        gh.events.append(("sync-pr", tag, None))
        return calls.get("sync_pr_outcome", SyncPrOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/20", pr_number="20"))

    def fake_common(api_git, commonalities_git, gh, release, bot_name, bot_email):
        calls["common"] = dict(api=api_git.work_dir, commonalities=(commonalities_git.repo, commonalities_git.token), release=release)
        gh.events.append(("common-sync", release, None))
        return calls.get("common_outcome", CommonSyncOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/40", pr_number="40"))

    def fake_issue_sync(gh, **kwargs):
        calls["issue_sync"] = kwargs
        gh.events.append(("issue-sync", kwargs["release_tag"], None))
        return calls.get("issue_sync_outcome", WorkflowSync(issue_number="42", issue_action="updated", issue_url="u"))

    monkeypatch.setattr(sync_pr_mod, "create_sync_pr", fake_sync_pr)
    monkeypatch.setattr(common_sync_mod, "sync_common", fake_common)
    monkeypatch.setattr(issue_sync_mod, "sync_for_workflow", fake_issue_sync)
    return calls


class FakeGit:
    def __init__(self, repo, work_dir, token):
        self.repo, self.work_dir, self.token = repo, work_dir, token


def clients(gh, tmp_path, app=True):
    return Clients(gh=gh, git_factory=FakeGit, token="app-token", app_slug="release-bot", app_token_used=app, work_root=tmp_path)


def kinds(gh):
    return [e[0] for e in gh.events]


PUBLISH_PLAN = {"command": "publish-release", "command_args": "--confirm r4.1", "state": "draft-ready"}


def test_publish_runs_sync_pr_then_result_then_closes(stubs, tmp_path):
    gh = FakeGitHub()
    run = make_run(PUBLISH_PLAN, publish())

    report = run_finalize(run, clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr", "update", "issue-body", "remove-labels", "add-labels", "close"]
    assert stubs["sync_pr"] == {
        "work_dir": str(tmp_path / "api-repo"),
        "tag": "r4.1",
        "bot": ("release-bot[bot]", "7+release-bot[bot]@users.noreply.github.com"),
    }
    _, comment_id, body = gh.events[1]
    assert comment_id == 555
    assert body.startswith("<!-- release-bot:r4.1 -->\n**🚀 Release published")
    assert "[#20](https://github.com/camaraproject/Example/pull/20)" in body
    assert "🔄 **Sync PR:** [View PR](https://github.com/camaraproject/Example/pull/20)" in gh.events[2][2]
    assert gh.events[5] == ("close", 42, "completed")
    assert report.errors == [] and report.issue_finalized is True


def test_publish_with_failed_sync_pr_leaves_the_issue_open(stubs, tmp_path):
    stubs["sync_pr_outcome"] = SyncPrOutcome(status="failed")
    gh = FakeGitHub()

    run_finalize(make_run(PUBLISH_PLAN, publish()), clients(gh, tmp_path))

    assert "close" not in kinds(gh)
    body = gh.events[1][2]
    assert "This issue remains open — manual follow-up required." in body
    assert "Post-release sync PR creation failed — create manually" in body


def test_publish_without_interim_still_opens_the_sync_pr_only(stubs, tmp_path):
    gh = FakeGitHub()

    run_finalize(make_run({**PUBLISH_PLAN, "interim_posted": "false"}, publish()), clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr"]


def test_result_comment_failure_skips_the_published_issue(stubs, tmp_path):
    gh = FakeGitHub(fail_comments=True)

    report = run_finalize(make_run(PUBLISH_PLAN, publish()), clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr"]
    assert report.errors == ["result comment failed"]
    assert report.issue_finalized is None


def test_sync_issue_command(stubs, tmp_path):
    gh = FakeGitHub()

    base = json.dumps({"release_tag": "r4.1", "command": "sync-issue", "user": "alice"})
    report = run_finalize(make_run({"command": "sync-issue", "base_context": base}), clients(gh, tmp_path))

    assert kinds(gh) == ["issue-sync", "update"]
    assert stubs["issue_sync"]["force_update"] is True
    assert "**⏳ Processing: `/sync-issue`**" in gh.events[1][2]
    assert report.result_template == "interim_processing"


def test_stale_cache_runs_common_sync_before_the_issue_sync(stubs, tmp_path):
    gh = FakeGitHub()
    run = make_run({
        "trigger_type": "push", "command": "sync-issue", "allowed": "", "interim_posted": "false",
        "common_cache_status": "stale", "common_cache_details": "code/common/.sync-manifest.yaml is missing",
        "common_sync_pr_url": "",
    })

    run_finalize(run, clients(gh, tmp_path))

    assert kinds(gh) == ["common-sync", "issue-sync", "comment"]
    assert stubs["common"] == {
        "api": str(tmp_path / "common-sync-api"),
        "commonalities": ("camaraproject/Commonalities", None),
        "release": "r4.3",
    }
    assert stubs["issue_sync"]["common_sync_pr_url"] == "https://github.com/camaraproject/Example/pull/40"
    _, issue, body = gh.events[2]
    assert issue == 42
    assert body.startswith("<!-- release-bot:r4.1 -->\n**Common file sync: [sync PR](https://github.com/camaraproject/Example/pull/40) created**")
    assert "code/common/.sync-manifest.yaml is missing" in body


def test_issue_sync_falls_back_to_the_plans_sync_pr(stubs, tmp_path):
    stubs["common_outcome"] = CommonSyncOutcome(status="no_changes")
    run = make_run({"command": "sync-issue", "common_cache_status": "stale", "common_sync_pr_url": "https://x/pull/3"})

    run_finalize(run, clients(FakeGitHub(), tmp_path))

    assert stubs["issue_sync"]["common_sync_pr_url"] == "https://x/pull/3"


def test_issue_sync_error_posts_no_notifications_but_the_result(stubs, tmp_path):
    stubs["issue_sync_outcome"] = WorkflowSync(issue_action="error")
    stubs["common_outcome"] = CommonSyncOutcome(status="failed")
    gh = FakeGitHub()
    run = make_run({"command": "sync-issue", "common_cache_status": "stale"})

    report = run_finalize(run, clients(gh, tmp_path))

    assert kinds(gh) == ["common-sync", "issue-sync", "update"]
    assert report.errors == ["Release Issue sync failed"]


def test_bot_identity_without_app_token(stubs, tmp_path):
    gh = FakeGitHub()

    run_finalize(make_run(PUBLISH_PLAN, publish()), clients(gh, tmp_path, app=False))

    assert stubs["sync_pr"]["bot"] == ("github-actions[bot]", "7+github-actions[bot]@users.noreply.github.com")


def test_summary(stubs, tmp_path):
    summary = tmp_path / "summary"

    run_finalize(make_run(PUBLISH_PLAN, publish()), clients(FakeGitHub(), tmp_path), str(summary))

    text = summary.read_text()
    assert text.startswith("## Release Automation: finalize\n")
    assert "| Post-release sync PR | created https://github.com/camaraproject/Example/pull/20 |" in text
    assert "| Result comment | release_published |" in text
    assert "| Published issue | updated |" in text


def test_main_exit_code(stubs, tmp_path, monkeypatch):
    stubs["issue_sync_outcome"] = WorkflowSync(issue_action="error")
    event = tmp_path / "event.json"
    event.write_text("{}")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "camaraproject/Example")
    monkeypatch.setenv("NEEDS_JSON", json.dumps(make_run({"command": "sync-issue", "interim_posted": "false"}).needs))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert finalize.main(clients(FakeGitHub(), tmp_path)) == 1
