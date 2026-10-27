"""
Finalize phase of CAMARA release automation.

Runs after the action jobs, also when one of them failed, and is the only job
after plan for push, workflow_dispatch and /sync-issue. In order:

1. post-release sync PR, after a publication (sync_pr): into main for a
   release from main, into the maintenance branch and main for a release
   from maintenance/rX
2. common sync of the base branch when its cache is stale, then the Release
   Issue sync and its notifications (common_sync, issue_sync)
3. the result comment on a slash command, updating its acknowledgment; after
   a publication on the Release PR merge (publish_mode on_merge), a new
   comment on the Release Issue
4. after a publication: the published Release Issue — STATE/ACTIONS, label,
   closed only when the sync PR was created (issue_sync)

What ran before comes from toJSON(needs): the plan job's plan document, and
the result and JSON outcome of the snapshot or act job that executed its
action (Run.from_needs).

Sync PRs and common sync use the repository client (App token: commits and
PRs); every Release Issue write uses the issue client (GITHUB_TOKEN), so no
write to the issue triggers a caller run.

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

from . import config
from .bot_context import bot_context
from .bot_identity import resolve_bot_identity
from .commands import COMMANDS, command
from .common_sync import CommonSyncOutcome
from .issue_sync import ReleaseView, WorkflowSync, post_publish_warnings
from .issue_sync import release_view as build_release_view
from .plan_document import PlanDocument
from .sync_pr import SyncPrOutcome

COMMONALITIES_REPO = "camaraproject/Commonalities"

PUBLISH_ACTIONS = ("publish-release", "publish-on-merge")
ACTION_CREATE_DRAFT = "create-draft"

# Actions after which the Release Issue is synced (when they succeeded); a
# publication updates the issue in finalize_published instead
STATE_CHANGING_ACTIONS = tuple(
    c.name for c in COMMANDS if c.job and c.state_after and c.name not in PUBLISH_ACTIONS
) + (ACTION_CREATE_DRAFT,)


@dataclass
class Run:
    """
    What finalize knows about the run: the plan, the outcome and result of the
    job that executed its action, the event payload, the repository.
    """
    plan: PlanDocument
    outcome: Dict[str, str] = field(default_factory=dict)
    result: str = ""  # conclusion of the job that executed the action ("" without one)
    event: Dict[str, Any] = field(default_factory=dict)
    server_url: str = "https://github.com"
    repository: str = ""
    run_id: str = ""

    @classmethod
    def from_needs(cls, needs: Dict[str, Any], event: Dict[str, Any], server_url: str, repository: str,
                   run_id: str = "") -> "Run":
        """Build the run from toJSON(needs) of the finalize job."""
        def outputs(job: str) -> Dict[str, Any]:
            return (needs.get(job) or {}).get("outputs") or {}

        plan = PlanDocument.from_json(outputs("plan")["plan"])
        outcome: Dict[str, str] = {}
        result = ""
        if plan.action:
            job = "snapshot" if plan.action == "create-snapshot" else "act"
            outcome = json.loads(outputs(job).get("outcome") or "{}")
            result = (needs.get(job) or {}).get("result", "")
        return cls(plan=plan, outcome=outcome, result=result, event=event, server_url=server_url,
                   repository=repository, run_id=run_id)

    @property
    def base_context(self) -> Dict[str, Any]:
        return bot_context(self.plan)

    @property
    def result_comment_id(self) -> str:
        """The acknowledgment the plan job updated with interim_processing, "" if none."""
        return self.plan.result_comment_id

    @property
    def action(self) -> str:
        return self.plan.action

    def out(self, name: str) -> str:
        """A value of the action's outcome ("" without an action or outcome)."""
        return str(self.outcome.get(name, "") or "")

    def succeeded(self, action: str) -> bool:
        """The action ran, its job concluded success and it reported success."""
        return self.action == action and self.result == "success" and self.out("success") == "true"

    def tree_url(self, ref: str) -> str:
        return f"{self.server_url}/{self.repository}/tree/{ref}"

    @property
    def published(self) -> bool:
        return self.action in PUBLISH_ACTIONS and self.out("success") == "true"


# ── when each part runs ──────────────────────────────────────────────────────


def issue_sync_due(run: Run) -> bool:
    """Release Issue sync (and common sync): a successful command, an issue event, or a sync."""
    if not run.plan.state:
        return False
    issue_event = run.plan.trigger.trigger_type in ("issue_close", "issue_reopen") and (
        not run.action or run.succeeded("reopen-issue")
    )
    return (
        any(run.succeeded(action) for action in STATE_CHANGING_ACTIONS)
        or issue_event
        or run.plan.trigger.command == "sync-issue"
    )


def result_due(run: Run) -> bool:
    """Result comment: an allowed slash command whose acknowledgment was updated by plan."""
    return run.plan.trigger.trigger_type == "slash_command" and run.result_comment_id != ""


# ── Release Issue sync ───────────────────────────────────────────────────────


def synced_state(run: Run) -> str:
    """The state the Release Issue shows after the run: a successful action's state_after, else the plan's."""
    if run.succeeded(ACTION_CREATE_DRAFT):
        return config.STATE_DRAFT_READY
    cmd = command(run.action)
    if cmd and cmd.state_after and run.succeeded(cmd.name):
        return cmd.state_after
    return run.plan.state


def synced_issue(run: Run) -> str:
    """The Release Issue the sync writes: the plan's, or the one the run just reopened ("" for none)."""
    if run.plan.release_issue_number:
        return run.plan.release_issue_number
    return run.plan.trigger.issue_number if run.succeeded("reopen-issue") else ""


def release_view(run: Run, common_sync_pr_url: str = "") -> ReleaseView:
    """What the issue sync shows (issue_sync.release_view): the state after the action and its artifacts."""
    return build_release_view(run.plan, synced_state(run), run.outcome, synced_issue(run), common_sync_pr_url)


Notification = Tuple[str, str, Dict[str, str]]


def notifications(run: Run, sync: WorkflowSync, common: Optional[CommonSyncOutcome]) -> List[Notification]:
    """Comments after the issue sync, as (template, issue number, context delta)."""
    posts = []
    if sync.issue_action == "updated" and run.plan.state == "not-planned" and sync.issue_number:
        posts.append(("state_not_planned", sync.issue_number, {"state": "not-planned"}))
    if sync.issue_action == "created" and sync.issue_number:
        closed = run.event.get("issue") or {}
        posts.append(("issue_created", sync.issue_number, {
            "state": "planned",
            "trigger_type": run.plan.trigger.trigger_type,
            "release_plan_url": run.plan.release_plan_url,
            "closed_issue_number": str(closed.get("number", "")),
            "closed_issue_url": closed.get("html_url", ""),
        }))
    issue = run.plan.release_issue_number or sync.issue_number
    if common and issue:
        if common.status == "created":
            posts.append(("common_sync_pr_created", issue, {
                "common_cache_details": run.plan.cache.details,
                "common_sync_pr_url": common.pr_url,
            }))
        elif common.status == "failed":
            posts.append(("common_sync_failed", issue, {}))
    return posts


# ── result comment ───────────────────────────────────────────────────────────


def result_template(run: Run, sync: Optional[WorkflowSync] = None) -> str:
    cmd = command(run.plan.trigger.command)
    if cmd is None:
        # No handler matched: a workflow bug
        return "internal_error"
    if not cmd.job:
        # Finalize alone (/sync-issue): the result is the issue sync's
        return cmd.ok if sync and sync.issue_action != "error" else cmd.failed
    return cmd.ok if run.action == cmd.name and run.out("success") == "true" else cmd.failed


def reported_state(run: Run) -> str:
    """The release state a result comment reports: after a successful command, its state_after."""
    cmd = command(run.plan.trigger.command)
    if cmd and cmd.state_after and run.succeeded(cmd.name):
        return cmd.state_after
    if run.published:
        return config.STATE_PUBLISHED
    return run.plan.state


def result_context(run: Run, sync: Optional[SyncPrOutcome]) -> Dict[str, str]:
    """Context delta of the result comment over the plan's base context."""
    command = run.plan.trigger.command
    reason = run.plan.trigger.command_args
    if not reason and command in ("discard-snapshot", "delete-draft"):
        reason = "No reason provided"
    context = {"reason": reason}

    ok = run.out("success") == "true"
    renamed = run.out("renamed_review_branch")
    if run.action in ("discard-snapshot", "delete-draft") and ok and renamed:
        context.update(release_review_branch=renamed, release_review_branch_url=run.tree_url(renamed))

    if run.action == "create-snapshot" and ok:
        snapshot_branch = run.out("snapshot_branch")
        review_branch = run.out("release_review_branch")
        context.update(
            snapshot_id=run.out("snapshot_id"),
            snapshot_branch=snapshot_branch,
            snapshot_branch_url=run.tree_url(snapshot_branch),
            release_review_branch=review_branch,
            release_review_branch_url=run.tree_url(review_branch),
            release_pr_number=run.out("release_pr_number"),
            release_pr_url=run.out("release_pr_url"),
            apis_json=run.out("apis_json"),
        )

    if run.published:
        reference_tag = run.out("reference_tag")
        context.update(
            release_url=run.out("release_url"),
            reference_tag=reference_tag,
            reference_tag_url=run.tree_url(reference_tag) if reference_tag else "",
            sync_pr_url=sync.pr_url if sync else "",
            sync_pr_number=sync.pr_number if sync else "",
            main_sync_pr_url=sync.main_pr_url if sync else "",
            main_sync_pr_number=sync.main_pr_number if sync else "",
            src_commit_sha_short=run.plan.src_commit_sha[:7],
        )
        warnings = post_publish_warnings(run.out("error_message"), sync.status if sync else "")
        if warnings:
            context["publish_warnings"] = warnings

    if run.out("success") == "false":
        context["error_message"] = run.out("error_message")
    return context


# ── orchestration ────────────────────────────────────────────────────────────


@dataclass
class Clients:
    """Network-facing collaborators; tests replace them."""
    gh: Any  # repository client
    git_factory: Any  # (repo, work_dir, token) -> git client
    issue_gh: Any = None  # Release Issue client; the repository client if unset
    token: str = ""
    app_slug: str = ""
    app_token_used: bool = False
    work_root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp()))
    _bot: Optional[Tuple[str, str]] = None

    @property
    def issues(self):
        return self.issue_gh or self.gh

    def git(self, repo: str, name: str, token: Optional[str] = None):
        return self.git_factory(repo, str(self.work_root / name), token)

    def bot_identity(self) -> Tuple[str, str]:
        """Commit identity: the App bot when an App token is in use, else github-actions[bot]."""
        if self._bot is None:
            self._bot = resolve_bot_identity(self.gh, self.app_slug, self.app_token_used)
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

    post(clients.issues, template, issue, run.base_context, delta, run.plan.release_tag, comment_id=comment_id)


def run_sync_pr(run: Run, clients: Clients) -> SyncPrOutcome:
    from .sync_pr import combine_case_b, create_sync_pr

    try:
        bot_name, bot_email = clients.bot_identity()
    except Exception as e:
        print(f"::error::Could not resolve the bot identity: {e}")
        return SyncPrOutcome(status="failed")
    tag = run.plan.release_tag
    base_branch = run.plan.base_branch
    if base_branch == "main":
        git = clients.git(run.repository, "api-repo", clients.token)
        return create_sync_pr(clients.gh, git, tag, bot_name, bot_email, base_branch=base_branch)
    # Case B: the cycle CHANGELOG into the line and into main, no README
    line_git = clients.git(run.repository, f"api-repo-{base_branch.replace('/', '-')}", clients.token)
    line = create_sync_pr(clients.gh, line_git, tag, bot_name, bot_email, base_branch=base_branch, readme=False)
    main_git = clients.git(run.repository, "api-repo", clients.token)
    main = create_sync_pr(clients.gh, main_git, tag, bot_name, bot_email, base_branch="main", readme=False)
    return combine_case_b(line, main)


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
        run.plan.release.commonalities_release,
        bot_name,
        bot_email,
        base_branch=run.plan.base_branch,
    )


def run_issue_sync(run: Run, clients: Clients, report: Report, summary_path: str) -> None:
    from .issue_sync import sync_for_workflow

    if run.plan.cache.status == "stale":
        report.common_sync = run_common_sync(run, clients)
        print(f"Common sync: {report.common_sync.status}")

    sync = sync_for_workflow(
        clients.issues, run.plan,
        release_view(run, report.common_sync.pr_url if report.common_sync else ""),
        summary_path=summary_path,
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
    report.result_template = result_template(run, report.issue_sync)
    try:
        post_comment(
            clients, run, report.result_template, run.plan.trigger.issue_number,
            {**result_context(run, report.sync_pr), "state": reported_state(run)}, comment_id=run.result_comment_id,
        )
    except Exception as e:
        # As before: without the result comment the issue is not finalised.
        print(f"::error::Could not post the result comment: {e}")
        report.errors.append("result comment failed")
        return
    finalize_published(run, clients, report)


def run_merge_publication(run: Run, clients: Clients, report: Report) -> None:
    """publish_mode on_merge: the result goes to the Release Issue as a new comment."""
    report.result_template = "release_published" if run.published else "publish_failed"
    issue = run.plan.release_issue_number
    if not issue:
        print("::warning::No Release Issue to report the publication on")
        return
    try:
        post_comment(clients, run, report.result_template, issue,
                     {**result_context(run, report.sync_pr), "state": reported_state(run)})
    except Exception as e:
        print(f"::error::Could not post the result comment: {e}")
        report.errors.append("result comment failed")
        return
    finalize_published(run, clients, report)


def finalize_published(run: Run, clients: Clients, report: Report) -> None:
    """After a publication: STATE/ACTIONS, label, and the close when the sync PR was created."""
    from .issue_manager import IssueManager
    from .issue_sync import IssueSyncManager

    if run.published and run.plan.release_issue_number:
        sync = report.sync_pr or SyncPrOutcome(status="")
        print(f"Updating release issue #{run.plan.release_issue_number} after publish (sync status: {sync.status})")
        report.issue_finalized = IssueSyncManager(
            clients.issues, issue_manager=IssueManager(), base_branch=run.plan.base_branch,
        ).finalize_published_issue(
            issue_number=int(run.plan.release_issue_number),
            release_tag=run.plan.release_tag,
            release_url=run.out("release_url"),
            reference_tag=run.out("reference_tag"),
            sync_pr_url=sync.pr_url,
            main_sync_pr_url=sync.main_pr_url,
            sync_status=sync.status,
            publish_warnings=run.out("error_message"),
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
    elif run.action == "publish-on-merge":
        run_merge_publication(run, clients, report)
    write_summary(run, report, summary_path)
    return report


def write_summary(run: Run, report: Report, summary_path: str) -> None:
    """Step summary of the finalize job: what it changed and where."""
    if not summary_path:
        return
    rows = [
        ("Trigger", f"{run.plan.trigger.trigger_type} {run.plan.trigger.command}".strip()),
        ("Release", f"{run.plan.release_tag} ({run.plan.state or 'no state'})"),
    ]
    if report.sync_pr:
        sync_text = f"{report.sync_pr.status} {report.sync_pr.pr_url}".strip()
        if report.sync_pr.main_pr_url:
            sync_text += f", into main {report.sync_pr.main_pr_url}"
        rows.append(("Post-release sync PR", sync_text))
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
    run = Run.from_needs(
        json.loads(env["NEEDS_JSON"]),
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
            issue_gh=GitHubClient(repo=run.repository, token=env.get("ISSUE_TOKEN") or token or None),
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
