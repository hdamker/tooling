"""Tests for finalize.py (the finalize job: sync PRs, Release Issue, result comment).

Expected values reproduce the former update-issue, post-result and
create-sync-pr jobs of release-automation-reusable.yml: their job and step
conditions, "Resolve Sync Context", "Determine Result Template", "Resolve
Reason" and "Build Result Context". The plan arrives as the typed plan
document (Run.from_needs).
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
    reported_state,
    result_template,
    release_view,
)
from release_automation.scripts.issue_sync import ReleaseView, WorkflowSync
from release_automation.scripts.sync_pr import SyncPrOutcome
from release_automation.tests.plans import make_plan

PLAN = {
    "trigger_type": "slash_command",
    "command": "create-snapshot",
    "command_args": "",
    "issue_number": "42",
    "user": "alice",
    "action": "",
    "state": "planned",
    "release_tag": "r4.1",
    "release_issue_number": "42",
    "snapshot_branch": "release-snapshot/r4.1-abc1234",
    "src_commit_sha": "abc1234def5678",
    "commonalities_release": "r4.3",
    "base_branch": "main",
    "result_comment_id": "555",
}


def make_needs(plan=None, jobs=None):
    """toJSON(needs) of the finalize job; jobs: {action: (job result, outcome)} — at most one action per run."""
    plan = {**PLAN, **(plan or {})}
    needs = {
        "snapshot": {"result": "skipped", "outputs": {}},
        "act": {"result": "skipped", "outputs": {}},
    }
    for action, (result, outcome) in (jobs or {}).items():
        plan["action"] = action
        job = "snapshot" if action == "create-snapshot" else "act"
        needs[job] = {"result": result, "outputs": {"outcome": json.dumps({"action": action, **outcome})} if outcome else {}}
    document = make_plan(**plan)
    needs["plan"] = {"result": "success", "outputs": {
        "plan": document.to_json(), "action": document.action, "finalize": "true",
        "result_comment_id": document.result_comment_id,
    }}
    return needs


def make_run(plan=None, jobs=None, event=None):
    return Run.from_needs(
        make_needs(plan, jobs),
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
        ({"trigger_type": "pr_merge"}, {"create-draft": ok()}, True),
        ({"trigger_type": "issue_close", "command": ""}, {"reopen-issue": ok(action_taken="reopened")}, True),
        ({"trigger_type": "issue_close", "command": ""}, {}, True),
        ({"trigger_type": "issue_reopen", "command": ""}, {}, True),
        ({"command": "sync-issue"}, {}, True),
        ({"trigger_type": "push", "command": "sync-issue"}, {}, True),
        ({}, {"create-snapshot": failed()}, False),
        ({}, {"create-snapshot": ("failure", {"success": "true"})}, False),
        ({"trigger_type": "pr_merge"}, {"create-draft": ("failure", {})}, False),
        ({"trigger_type": "issue_close", "command": ""}, {"reopen-issue": ("failure", {"success": "false"})}, False),
        # A publication never syncs the issue here; the published finalisation does.
        ({"command": "publish-release"}, {"publish-release": ok()}, False),
        ({"trigger_type": "pr_merge"}, {"publish-on-merge": ok()}, False),
        ({"command": "sync-issue", "state": ""}, {}, False),
    ],
)
def test_issue_sync_due(plan, jobs, due):
    assert issue_sync_due(make_run(plan, jobs)) is due


@pytest.mark.parametrize(
    "plan,due",
    [
        ({}, True),
        ({"trigger_type": "push"}, False),
        ({"result_comment_id": ""}, False),
    ],
)
def test_result_due(plan, due):
    assert result_due(make_run(plan)) is due


# ── the release view the issue sync shows (107 D3: no re-derivation in finalize) ──


def test_view_after_create_snapshot():
    apis = json.dumps([{"api_name": "qod", "api_version": "1.0.0-rc.1"}])
    run = make_run(jobs={"create-snapshot": ok(
        snapshot_id="r4.1-new", snapshot_branch="release-snapshot/r4.1-new", release_pr_number="12", apis_json=apis,
    )})

    assert release_view(run) == ReleaseView(
        state="snapshot-active", issue_number="42", snapshot_id="r4.1-new",
        snapshot_branch="release-snapshot/r4.1-new", release_pr_number="12",
        api_versions={"qod": "1.0.0-rc.1"}, commonalities_release="r4.3", refresh=True,
    )


def test_view_after_draft_creation():
    run = make_run(
        {"trigger_type": "pr_merge", "state": "snapshot-active", "snapshot_id": "r4.1-abc1234",
         "release_pr_number": "13", "apis": [{"api_name": "qod", "api_version": "1.0.0-rc.1"}]},
        {"create-draft": ok(draft_release_url="https://github.com/camaraproject/Example/releases/tag/untagged-1",
                            release_pr_number="14")},
    )

    view = release_view(run)

    assert (view.state, view.issue_number, view.refresh) == ("draft-ready", "42", True)
    # The plan's snapshot, the merged PR of the outcome
    assert (view.snapshot_id, view.snapshot_branch, view.release_pr_number) == ("r4.1-abc1234", "release-snapshot/r4.1-abc1234", "14")
    assert view.draft_release_url == "https://github.com/camaraproject/Example/releases/tag/untagged-1"
    assert view.api_versions == {"qod": "1.0.0-rc.1"}


@pytest.mark.parametrize("job", ["discard-snapshot", "delete-draft"])
def test_view_after_discard_or_delete_has_no_artifacts(job):
    run = make_run({"state": "snapshot-active", "snapshot_id": "r4.1-abc1234", "release_pr_number": "13",
                    "apis": [{"api_name": "qod", "api_version": "1.0.0-rc.1"}]}, jobs={job: ok()})

    view = release_view(run)

    assert (view.state, view.refresh) == ("planned", True)
    assert (view.snapshot_id, view.snapshot_branch, view.release_pr_number, view.draft_release_url) == ("", "", "", "")
    assert view.api_versions == {} and view.commonalities_release == ""


def test_view_of_a_failed_command_keeps_the_plans_state():
    run = make_run({"state": "planned"}, jobs={"create-snapshot": failed(error_message="boom")})

    assert release_view(run).state == "planned"


@pytest.mark.parametrize("plan,refresh", [
    ({"command": "sync-issue"}, True),
    ({"trigger_type": "push", "command": "sync-issue"}, True),
    ({"trigger_type": "issue_close", "command": ""}, False),
    ({"trigger_type": "issue_reopen", "command": ""}, False),
])
def test_view_refreshes_except_on_issue_events(plan, refresh):
    assert release_view(make_run(plan)).refresh is refresh


def test_view_of_a_sync_in_snapshot_active_takes_the_plans_artifacts():
    run = make_run({"command": "sync-issue", "state": "snapshot-active", "snapshot_id": "r4.1-abc1234",
                    "release_pr_number": "13", "apis": [{"api_name": "qod", "api_version": "1.0.0-rc.1"}],
                    "common_cache_status": "stale", "common_cache_details": "d", "common_sync_pr_url": "u"})

    view = release_view(run, "https://x/pull/40")

    assert (view.snapshot_id, view.release_pr_number, view.api_versions) == ("r4.1-abc1234", "13", {"qod": "1.0.0-rc.1"})
    assert (view.common_cache_status, view.common_cache_details, view.common_sync_pr_url) == ("stale", "d", "https://x/pull/40")


def test_view_after_reopen_names_the_reopened_issue():
    # The plan found no open issue (it was closed); the sync writes the one act reopened
    run = make_run({"trigger_type": "issue_close", "command": "", "state": "snapshot-active",
                    "release_issue_number": "", "issue_number": "42"},
                   {"reopen-issue": ok(action_taken="reopened")})

    assert release_view(run).issue_number == "42"


def test_view_after_a_close_in_planned_names_no_issue():
    # A new Release Issue gets created; the closed one stays closed
    run = make_run({"trigger_type": "issue_close", "command": "", "state": "planned", "release_issue_number": "", "issue_number": "42"})

    assert release_view(run).issue_number == ""


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


@pytest.mark.parametrize("state", ["planned", "snapshot-active"])
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
        ("publish-release", {"publish-release": ok()}, "release_published"),
        ("publish-release", {"publish-release": failed()}, "publish_failed"),
        ("unknown-cmd", {}, "internal_error"),
    ],
)
def test_result_template(command, jobs, template):
    assert result_template(make_run({"command": command}, jobs)) == template


@pytest.mark.parametrize("issue_action,template", [
    ("updated", "issue_synced"), ("unchanged", "issue_synced"), ("error", "issue_sync_failed"),
])
def test_sync_issue_result_follows_the_issue_sync(issue_action, template):
    # F7 (#499): /sync-issue reports a result instead of staying at "Processing";
    # a failed sync is not a workflow bug, so it gets its own template, not internal_error
    sync = WorkflowSync(issue_number="42", issue_action=issue_action)

    assert result_template(make_run({"command": "sync-issue"}), sync) == template


@pytest.mark.parametrize(
    "command,jobs,state",
    [
        ("create-snapshot", {"create-snapshot": ok()}, "snapshot-active"),
        ("create-snapshot", {"create-snapshot": failed()}, "planned"),
        ("discard-snapshot", {"discard-snapshot": ok()}, "planned"),
        ("discard-snapshot", {"discard-snapshot": failed()}, "snapshot-active"),
        ("publish-release", {"publish-release": ok()}, "published"),
        ("publish-release", {"publish-release": ("failure", {})}, "snapshot-active"),
        ("sync-issue", {}, "snapshot-active"),
    ],
)
def test_reported_state_is_the_state_after_the_action(command, jobs, state):
    # The valid actions of a result comment follow the state after the action
    assert reported_state(make_run({"command": command, "state": "snapshot-active" if command != "create-snapshot" else "planned"}, jobs)) == state


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


def publish(error_message="", reference_tag="src/r4.1", action="publish-release"):
    return {action: ok(
        release_url="https://github.com/camaraproject/Example/releases/tag/r4.1",
        reference_tag=reference_tag,
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
        "main_sync_pr_url": "",
        "main_sync_pr_number": "",
        "src_commit_sha_short": "abc1234",
    }


def test_context_after_publish_with_warnings():
    run = make_run({"command": "publish-release"}, publish("Failed to create pointer branch", reference_tag=""))

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

    def fake_sync_pr(gh, git, tag, bot_name, bot_email, base_branch, readme=True):
        calls["sync_pr"] = dict(work_dir=git.work_dir, tag=tag, bot=(bot_name, bot_email))
        calls.setdefault("sync_prs", []).append(dict(work_dir=git.work_dir, base_branch=base_branch, readme=readme))
        gh.events.append(("sync-pr", tag, base_branch))
        default = SyncPrOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/20", pr_number="20")
        return calls.get("sync_pr_outcomes", {}).get(base_branch) or calls.get("sync_pr_outcome", default)

    def fake_common(api_git, commonalities_git, gh, release, bot_name, bot_email, base_branch):
        calls["common"] = dict(api=api_git.work_dir, commonalities=(commonalities_git.repo, commonalities_git.token), release=release)
        calls["common_base_branch"] = base_branch
        gh.events.append(("common-sync", release, None))
        return calls.get("common_outcome", CommonSyncOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/40", pr_number="40"))

    def fake_issue_sync(gh, plan, view, summary_path=""):
        calls["issue_sync"] = view
        gh.events.append(("issue-sync", plan.release_tag, None))
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


def test_release_issue_writes_use_the_issue_client(stubs, tmp_path):
    # spec 5.7: sync PR and common sync on the repository client (App), the issue on GITHUB_TOKEN
    gh, issues = FakeGitHub(), FakeGitHub()
    two = Clients(gh=gh, issue_gh=issues, git_factory=FakeGit, token="app-token", app_slug="release-bot",
                  app_token_used=True, work_root=tmp_path)

    run_finalize(make_run(PUBLISH_PLAN, publish()), two)
    run_finalize(make_run({
        "trigger_type": "push", "command": "sync-issue", "result_comment_id": "",
        "common_cache_status": "stale", "common_cache_details": "stale", "common_sync_pr_url": "",
    }), two)

    assert kinds(gh) == ["sync-pr", "common-sync"]
    assert kinds(issues) == ["update", "issue-body", "remove-labels", "add-labels", "close", "issue-sync", "comment"]


def test_issue_client_defaults_to_the_repository_client(tmp_path):
    gh = FakeGitHub()

    assert Clients(gh=gh, git_factory=FakeGit).issues is gh


LINE_PR = SyncPrOutcome(status="created", pr_url="https://github.com/camaraproject/Example/pull/21", pr_number="21")


def test_case_a_publish_syncs_readme_and_changelog_into_main(stubs, tmp_path):
    run_finalize(make_run(PUBLISH_PLAN, publish()), clients(FakeGitHub(), tmp_path))

    assert stubs["sync_prs"] == [{"work_dir": str(tmp_path / "api-repo"), "base_branch": "main", "readme": True}]


def test_case_b_publish_syncs_the_changelog_into_both_lines_then_closes(stubs, tmp_path):
    # spec 7.1/7.2
    stubs["sync_pr_outcomes"] = {"maintenance/r1": LINE_PR}
    gh = FakeGitHub()
    summary = tmp_path / "summary"
    run = make_run({**PUBLISH_PLAN, "base_branch": "maintenance/r1", "release_tag": "r1.10"}, publish())

    report = run_finalize(run, clients(gh, tmp_path), str(summary))

    assert stubs["sync_prs"] == [
        {"work_dir": str(tmp_path / "api-repo-maintenance-r1"), "base_branch": "maintenance/r1", "readme": False},
        {"work_dir": str(tmp_path / "api-repo"), "base_branch": "main", "readme": False},
    ]
    assert report.sync_pr == SyncPrOutcome(
        status="created", pr_url=LINE_PR.pr_url, pr_number="21",
        main_pr_url="https://github.com/camaraproject/Example/pull/20", main_pr_number="20",
    )
    body = gh.events[2][2]
    assert "[#21](https://github.com/camaraproject/Example/pull/21)" in body
    assert "[#20](https://github.com/camaraproject/Example/pull/20) into main" in body
    issue_body = gh.events[3][2]
    assert "🔄 **Sync PR:** [View PR](https://github.com/camaraproject/Example/pull/21)" in issue_body
    assert "🔄 **Sync PR into main:** [View PR](https://github.com/camaraproject/Example/pull/20)" in issue_body
    assert ("close", 42, "completed") in gh.events
    text = summary.read_text()
    assert ("| Post-release sync PR | created https://github.com/camaraproject/Example/pull/21, "
            "into main https://github.com/camaraproject/Example/pull/20 |") in text


@pytest.mark.parametrize("failing", ["maintenance/r1", "main"])
def test_case_b_with_one_failed_sync_pr_leaves_the_issue_open(stubs, tmp_path, failing):
    # spec 7.3: the publication is not failed
    stubs["sync_pr_outcomes"] = {"maintenance/r1": LINE_PR, failing: SyncPrOutcome(status="failed")}
    gh = FakeGitHub()
    run = make_run({**PUBLISH_PLAN, "base_branch": "maintenance/r1", "release_tag": "r1.10"}, publish())

    report = run_finalize(run, clients(gh, tmp_path))

    assert report.sync_pr.status == "failed"
    assert not any(e[0] == "close" for e in gh.events)
    assert report.errors == []


@pytest.mark.parametrize("base_branch", ["main", "maintenance/r1"])
def test_common_sync_runs_on_the_base_branch(stubs, tmp_path, base_branch):
    # spec 7.4
    run = make_run({
        "trigger_type": "push", "command": "sync-issue", "result_comment_id": "", "base_branch": base_branch,
        "common_cache_status": "stale", "common_cache_details": "stale", "common_sync_pr_url": "",
    })

    run_finalize(run, clients(FakeGitHub(), tmp_path))

    assert stubs["common_base_branch"] == base_branch


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

    run_finalize(make_run({**PUBLISH_PLAN, "result_comment_id": ""}, publish()), clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr"]


def test_result_comment_failure_skips_the_published_issue(stubs, tmp_path):
    gh = FakeGitHub(fail_comments=True)

    report = run_finalize(make_run(PUBLISH_PLAN, publish()), clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr"]
    assert report.errors == ["result comment failed"]
    assert report.issue_finalized is None


def test_sync_issue_command(stubs, tmp_path):
    gh = FakeGitHub()

    report = run_finalize(make_run({"command": "sync-issue"}), clients(gh, tmp_path))

    assert kinds(gh) == ["issue-sync", "update"]
    assert stubs["issue_sync"].refresh is True
    body = gh.events[1][2]
    assert body.startswith("<!-- release-bot:r4.1 -->\n**🔄 Release Issue synced — State: `planned`**")
    assert "**Valid actions:**<br>→ **`/create-snapshot` — begin the release process**" in body
    assert report.result_template == "issue_synced"


def test_stale_cache_runs_common_sync_before_the_issue_sync(stubs, tmp_path):
    gh = FakeGitHub()
    run = make_run({
        "trigger_type": "push", "command": "sync-issue", "result_comment_id": "",
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
    assert stubs["issue_sync"].common_sync_pr_url == "https://github.com/camaraproject/Example/pull/40"
    _, issue, body = gh.events[2]
    assert issue == 42
    assert body.startswith("<!-- release-bot:r4.1 -->\n**Common file sync: [sync PR](https://github.com/camaraproject/Example/pull/40) created**")
    assert "code/common/.sync-manifest.yaml is missing" in body


def test_issue_sync_falls_back_to_the_plans_sync_pr(stubs, tmp_path):
    stubs["common_outcome"] = CommonSyncOutcome(status="no_changes")
    run = make_run({"command": "sync-issue", "common_cache_status": "stale", "common_sync_pr_url": "https://x/pull/3"})

    run_finalize(run, clients(FakeGitHub(), tmp_path))

    assert stubs["issue_sync"].common_sync_pr_url == "https://x/pull/3"


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
    monkeypatch.setenv("NEEDS_JSON", json.dumps(make_needs({"command": "sync-issue", "result_comment_id": ""})))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert finalize.main(clients(FakeGitHub(), tmp_path)) == 1


# ── publish_mode on_merge ────────────────────────────────────────────────────

MERGE_PLAN = {"trigger_type": "pr_merge", "command": "", "user": "bob", "issue_number": "", "state": "snapshot-active",
              "result_comment_id": ""}


def test_publish_on_merge_reports_on_the_release_issue_and_closes(stubs, tmp_path):
    gh = FakeGitHub()

    report = run_finalize(make_run(MERGE_PLAN, publish(action="publish-on-merge")), clients(gh, tmp_path))

    assert kinds(gh) == ["sync-pr", "comment", "issue-body", "remove-labels", "add-labels", "close"]
    _, issue, body = gh.events[1]
    assert issue == 42
    assert body.startswith("<!-- release-bot:r4.1 -->\n**🚀 Release published")
    assert report.result_template == "release_published" and report.issue_finalized is True


def test_failed_publish_on_merge_posts_publish_failed(stubs, tmp_path):
    gh = FakeGitHub()
    run = make_run(MERGE_PLAN, {"publish-on-merge": failed(error_message="Failed to publish release: 422")})

    report = run_finalize(run, clients(gh, tmp_path))

    assert kinds(gh) == ["comment"]
    assert report.result_template == "publish_failed"
    assert "Failed to publish release: 422" in gh.events[0][2]
