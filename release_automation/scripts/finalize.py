"""
Finalize phase of CAMARA release automation.

Runs after the action jobs, also when one of them failed, and is the only job
after plan for push, workflow_dispatch and /sync-issue. In order:

1. post-release sync PR, after a publication (sync_pr)
2. common sync when the cache is stale, then the Release Issue sync and its
   notifications (common_sync, issue_sync)
3. the result comment on a slash command, updating its acknowledgment
4. after a publication: the published Release Issue — STATE/ACTIONS, label,
   closed only when the sync PR was created (issue_sync)

What ran before comes from toJSON(needs): the plan job's outputs and each
action job's result and outputs.

Usage (workflow step):
    python3 -m release_automation.scripts.finalize
"""

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common_sync import CommonSyncOutcome
from .issue_sync import WorkflowSync, post_publish_warnings
from .sync_pr import SyncPrOutcome

COMMONALITIES_REPO = "camaraproject/Commonalities"

# A job whose success counts only together with its "success" output
COMMAND_JOBS = ("create-snapshot", "discard-snapshot", "delete-draft", "handle-pr-merge")

# Template of the result comment per command; the second is the failure template
RESULT_TEMPLATES = {
    "create-snapshot": ("create-snapshot", "snapshot_created", "snapshot_failed"),
    "discard-snapshot": ("discard-snapshot", "snapshot_discarded", "snapshot_failed"),
    "delete-draft": ("delete-draft", "draft_revoked", "snapshot_failed"),
    "publish-release": ("publish-release", "release_published", "publish_failed"),
}


@dataclass
class Run:
    """What finalize knows about the run: needs, the event payload, repository."""
    needs: Dict[str, Any]
    event: Dict[str, Any] = field(default_factory=dict)
    server_url: str = "https://github.com"
    repository: str = ""
    run_id: str = ""

    def out(self, job: str, name: str) -> str:
        return str((self.needs.get(job) or {}).get("outputs", {}).get(name, "") or "")

    def result(self, job: str) -> str:
        return (self.needs.get(job) or {}).get("result", "")

    def plan(self, name: str) -> str:
        return self.out("plan", name)

    def succeeded(self, job: str) -> bool:
        """Job concluded success and reported success (a command job)."""
        return self.result(job) == "success" and self.out(job, "success") == "true"

    def tree_url(self, ref: str) -> str:
        return f"{self.server_url}/{self.repository}/tree/{ref}"

    @property
    def published(self) -> bool:
        return self.out("publish-release", "success") == "true"


# ── when each part runs ──────────────────────────────────────────────────────


def issue_sync_due(run: Run) -> bool:
    """Release Issue sync (and common sync): a successful command, an issue event, or a sync."""
    if run.plan("config_error") or not run.plan("state"):
        return False
    return (
        any(run.succeeded(job) for job in COMMAND_JOBS)
        or run.result("handle-issue-event") == "success"
        or run.plan("command") == "sync-issue"
    )


def result_due(run: Run) -> bool:
    """Result comment: an allowed slash command whose acknowledgment was updated by plan."""
    return (
        run.plan("trigger_type") == "slash_command"
        and run.plan("allowed") == "true"
        and run.plan("interim_posted") == "true"
    )


# ── Release Issue sync ───────────────────────────────────────────────────────


def sync_overrides(run: Run) -> Dict[str, Any]:
    """State and artifacts the run's command produced, which the issue sync must not re-derive."""
    overrides = {
        "state_override": "",
        "snapshot_branch_override": "",
        "release_pr_number_override": "",
        "draft_release_url_override": "",
        "force_update": False,
    }
    if run.succeeded("create-snapshot"):
        overrides.update(
            state_override="snapshot-active",
            snapshot_branch_override=run.out("create-snapshot", "snapshot_branch"),
            release_pr_number_override=run.out("create-snapshot", "release_pr_number"),
            force_update=True,
        )
    elif run.succeeded("handle-pr-merge"):
        pr_number = (run.event.get("pull_request") or {}).get("number", "")
        overrides.update(
            state_override="draft-ready",
            snapshot_branch_override=run.plan("snapshot_branch"),
            release_pr_number_override=str(pr_number),
            draft_release_url_override=run.out("handle-pr-merge", "draft_release_url"),
            force_update=True,
        )
    elif run.succeeded("discard-snapshot") or run.succeeded("delete-draft"):
        overrides.update(state_override="planned", force_update=True)
    elif run.plan("command") == "sync-issue":
        overrides.update(force_update=True)
    return overrides


Notification = Tuple[str, str, Dict[str, str]]


def notifications(run: Run, sync: WorkflowSync, common: Optional[CommonSyncOutcome]) -> List[Notification]:
    """Comments after the issue sync, as (template, issue number, context delta)."""
    posts = []
    if sync.issue_action == "updated" and run.plan("state") == "not-planned" and sync.issue_number:
        posts.append(("state_not_planned", sync.issue_number, {"state": "not-planned"}))
    if sync.issue_action == "created" and sync.issue_number:
        closed = run.event.get("issue") or {}
        posts.append(("issue_created", sync.issue_number, {
            "state": "planned",
            "trigger_type": run.plan("trigger_type"),
            "release_plan_url": f"{run.server_url}/{run.repository}/blob/main/release-plan.yaml",
            "closed_issue_number": str(closed.get("number", "")),
            "closed_issue_url": closed.get("html_url", ""),
        }))
    issue = run.plan("release_issue_number") or sync.issue_number
    if common and issue:
        if common.status == "created":
            posts.append(("common_sync_pr_created", issue, {
                "common_cache_details": run.plan("common_cache_details"),
                "common_sync_pr_url": common.pr_url,
            }))
        elif common.status == "failed":
            posts.append(("common_sync_failed", issue, {}))
    return posts


# ── result comment ───────────────────────────────────────────────────────────


def result_template(run: Run) -> str:
    command = run.plan("command")
    if command == "sync-issue":
        return "interim_processing"
    if command not in RESULT_TEMPLATES:
        # No handler matched: a workflow bug
        return "internal_error"
    job, success, failure = RESULT_TEMPLATES[command]
    return success if run.out(job, "success") == "true" else failure


def result_context(run: Run, sync: Optional[SyncPrOutcome]) -> Dict[str, str]:
    """Context delta of the result comment over the plan's base context."""
    command = run.plan("command")
    reason = run.plan("command_args")
    if not reason and command in ("discard-snapshot", "delete-draft"):
        reason = "No reason provided"
    context = {"reason": reason}

    for job in ("discard-snapshot", "delete-draft"):
        renamed = run.out(job, "renamed_review_branch")
        if run.out(job, "success") == "true" and renamed:
            context.update(release_review_branch=renamed, release_review_branch_url=run.tree_url(renamed))

    if run.out("create-snapshot", "success") == "true":
        snapshot_branch = run.out("create-snapshot", "snapshot_branch")
        review_branch = run.out("create-snapshot", "release_review_branch")
        context.update(
            snapshot_id=run.out("create-snapshot", "snapshot_id"),
            snapshot_branch=snapshot_branch,
            snapshot_branch_url=run.tree_url(snapshot_branch),
            release_review_branch=review_branch,
            release_review_branch_url=run.tree_url(review_branch),
            release_pr_number=run.out("create-snapshot", "release_pr_number"),
            release_pr_url=run.out("create-snapshot", "release_pr_url"),
            apis_json=run.out("create-snapshot", "apis_json"),
        )

    if run.published:
        reference_tag = run.out("publish-release", "reference_tag")
        context.update(
            release_url=run.out("publish-release", "release_url"),
            reference_tag=reference_tag,
            reference_tag_url=run.tree_url(reference_tag) if reference_tag else "",
            sync_pr_url=sync.pr_url if sync else "",
            sync_pr_number=sync.pr_number if sync else "",
            src_commit_sha_short=run.plan("src_commit_sha")[:7],
        )
        warnings = post_publish_warnings(
            run.out("publish-release", "error_message"), sync.status if sync else ""
        )
        if warnings:
            context["publish_warnings"] = warnings

    for job in ("create-snapshot", "discard-snapshot", "delete-draft", "publish-release"):
        if run.out(job, "success") == "false":
            context["error_message"] = run.out(job, "error_message")
            break
    return context


# ── orchestration ────────────────────────────────────────────────────────────


@dataclass
class Clients:
    """Network-facing collaborators; tests replace them."""
    gh: Any
    git_factory: Any  # (repo, work_dir, token) -> git client
    token: str = ""
    app_slug: str = ""
    app_token_used: bool = False
    work_root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp()))
    _bot: Optional[Tuple[str, str]] = None

    def git(self, repo: str, name: str, token: Optional[str] = None):
        return self.git_factory(repo, str(self.work_root / name), token)

    def bot_identity(self) -> Tuple[str, str]:
        """Commit identity: the App bot when an App token is in use, else github-actions[bot]."""
        if self._bot is None:
            login = f"{self.app_slug}[bot]" if self.app_slug and self.app_token_used else "github-actions[bot]"
            user = self.gh.get_user(login)
            name = user["login"]
            self._bot = (name, f"{user['id']}+{name}@users.noreply.github.com")
        return self._bot


@dataclass
class Report:
    """What finalize did, for the log, the step summary and the exit code."""
    sync_pr: Optional[SyncPrOutcome] = None
    common_sync: Optional[CommonSyncOutcome] = None
    issue_sync: Optional[WorkflowSync] = None
    result_template: str = ""
    issue_finalized: Optional[bool] = None
    errors: List[str] = field(default_factory=list)


def post_comment(clients: Clients, run: Run, template: str, issue: str, delta: Dict[str, Any], comment_id: str = "") -> None:
    from .bot_responder import post_comment as post

    try:
        base_context = json.loads(run.plan("base_context") or "{}")
    except json.JSONDecodeError:
        print("::warning::Invalid base_context JSON, ignoring")
        base_context = {}
    post(clients.gh, template, issue, base_context, delta, run.plan("release_tag"), comment_id=comment_id)


def run_sync_pr(run: Run, clients: Clients) -> SyncPrOutcome:
    from .sync_pr import create_sync_pr

    try:
        bot_name, bot_email = clients.bot_identity()
    except Exception as e:
        print(f"::error::Could not resolve the bot identity: {e}")
        return SyncPrOutcome(status="failed")
    git = clients.git(run.repository, "api-repo", clients.token)
    return create_sync_pr(clients.gh, git, run.plan("release_tag"), bot_name, bot_email)


def run_common_sync(run: Run, clients: Clients) -> CommonSyncOutcome:
    from .common_sync import sync_common

    try:
        bot_name, bot_email = clients.bot_identity()
    except Exception as e:
        print(f"::error::Could not resolve the bot identity: {e}")
        return CommonSyncOutcome(status="failed")
    return sync_common(
        clients.git(run.repository, "common-sync-api", clients.token),
        # Public repository; the App token is scoped to the API repository
        clients.git(COMMONALITIES_REPO, "commonalities"),
        clients.gh,
        run.plan("commonalities_release"),
        bot_name,
        bot_email,
    )


def run_issue_sync(run: Run, clients: Clients, report: Report, summary_path: str) -> None:
    from .issue_sync import sync_for_workflow

    if run.plan("common_cache_status") == "stale":
        report.common_sync = run_common_sync(run, clients)
        print(f"Common sync: {report.common_sync.status}")

    sync = sync_for_workflow(
        clients.gh,
        release_tag=run.plan("release_tag"),
        state=run.plan("state"),
        common_cache_status=run.plan("common_cache_status"),
        common_cache_details=run.plan("common_cache_details"),
        common_sync_pr_url=(report.common_sync.pr_url if report.common_sync else "") or run.plan("common_sync_pr_url"),
        summary_path=summary_path,
        **sync_overrides(run),
    )
    report.issue_sync = sync
    print("Issue sync result:")
    print(f"  Action: {sync.issue_action}")
    print(f"  Issue: #{sync.issue_number}")
    print(f"  URL: {sync.issue_url}")
    if sync.issue_action == "error":
        # As before: a failed issue sync posts no notifications and fails the job.
        report.errors.append("Release Issue sync failed")
        return

    for template, issue, delta in notifications(run, sync, report.common_sync):
        try:
            post_comment(clients, run, template, issue, delta)
        except Exception as e:
            print(f"::error::Could not post {template}: {e}")
            report.errors.append(f"{template} comment failed")
            return


def run_result(run: Run, clients: Clients, report: Report) -> None:
    from .issue_manager import IssueManager
    from .issue_sync import IssueSyncManager

    report.result_template = result_template(run)
    try:
        post_comment(
            clients, run, report.result_template, run.plan("issue_number"),
            result_context(run, report.sync_pr), comment_id=run.plan("comment_id"),
        )
    except Exception as e:
        # As before: without the result comment the issue is not finalised.
        print(f"::error::Could not post the result comment: {e}")
        report.errors.append("result comment failed")
        return

    if run.published and run.plan("release_issue_number"):
        sync = report.sync_pr or SyncPrOutcome(status="")
        print(f"Updating release issue #{run.plan('release_issue_number')} after publish (sync status: {sync.status})")
        report.issue_finalized = IssueSyncManager(clients.gh, issue_manager=IssueManager()).finalize_published_issue(
            issue_number=int(run.plan("release_issue_number")),
            release_tag=run.plan("release_tag"),
            release_url=run.out("publish-release", "release_url"),
            reference_tag=run.out("publish-release", "reference_tag"),
            sync_pr_url=sync.pr_url,
            sync_status=sync.status,
            publish_warnings=run.out("publish-release", "error_message"),
        )


def finalize(run: Run, clients: Clients, summary_path: str = "") -> Report:
    report = Report()
    if run.published:
        report.sync_pr = run_sync_pr(run, clients)
        print(f"Post-release sync PR: {report.sync_pr.status} {report.sync_pr.pr_url}")
    if issue_sync_due(run):
        run_issue_sync(run, clients, report, summary_path)
    if result_due(run):
        run_result(run, clients, report)
    write_summary(run, report, summary_path)
    return report


def write_summary(run: Run, report: Report, summary_path: str) -> None:
    """Step summary of the finalize job: what it changed and where."""
    if not summary_path:
        return
    rows = [
        ("Trigger", f"{run.plan('trigger_type')} {run.plan('command')}".strip()),
        ("Release", f"{run.plan('release_tag')} ({run.plan('state') or 'no state'})"),
    ]
    if report.sync_pr:
        rows.append(("Post-release sync PR", f"{report.sync_pr.status} {report.sync_pr.pr_url}".strip()))
    if report.common_sync:
        rows.append(("Common sync", f"{report.common_sync.status} {report.common_sync.pr_url}".strip()))
    if report.issue_sync:
        rows.append(("Release Issue", f"{report.issue_sync.issue_action} {report.issue_sync.issue_url}".strip()))
    if report.result_template:
        rows.append(("Result comment", report.result_template))
    if report.issue_finalized is not None:
        rows.append(("Published issue", "updated" if report.issue_finalized else "update failed (see log)"))
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("## Release Automation: finalize\n\n| | |\n|---|---|\n")
        for name, value in rows:
            f.write(f"| {name} | {value} |\n")
        if report.errors:
            f.write(f"\nErrors: {'; '.join(report.errors)}\n")


def main(clients: Optional[Clients] = None) -> int:
    env = os.environ
    with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    run = Run(
        needs=json.loads(env["NEEDS_JSON"]),
        event=event,
        server_url=env.get("GITHUB_SERVER_URL", "https://github.com"),
        repository=env["GITHUB_REPOSITORY"],
        run_id=env.get("GITHUB_RUN_ID", ""),
    )
    if clients is None:
        from .git_operations import GitOperations
        from .github_client import GitHubClient

        token = env.get("GITHUB_TOKEN", "")
        clients = Clients(
            gh=GitHubClient(repo=run.repository, token=token or None),
            git_factory=lambda repo, work_dir, tok: GitOperations(repo=repo, work_dir=work_dir, token=tok),
            token=token,
            app_slug=env.get("RELEASE_APP_SLUG", ""),
            app_token_used=env.get("APP_TOKEN_USED") == "true",
            work_root=Path(env.get("RUNNER_TEMP") or tempfile.mkdtemp()),
        )

    report = finalize(run, clients, env.get("GITHUB_STEP_SUMMARY", ""))
    for error in report.errors:
        print(f"::error::{error}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
