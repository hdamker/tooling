"""
Command policy for CAMARA release automation.

Decides what the workflow does with a classified trigger in the current
release state: a Plan to execute, or a Rejection to answer. Slash commands are
checked in a fixed order — state table, common-cache gate, permission,
publisher authorization, confirm tag — and the first failing check names the
rejection. Other triggers are not validated.

Policy values that are expected to change (RM#675) are the publish_mode and
publishers of config.RELEASE_TYPES.

A Plan names the action the snapshot or act job executes (action_for).

main() is the plan job's plan step: it derives the release state of the base
branch (state_manager), checks the common-file cache (common_sync), applies
the policy, posts the one response comment, writes the step summary and the
typed plan document (plan_document.PlanDocument) the later jobs read.

Usage (workflow step):
    python3 -m release_automation.scripts.command_policy
"""

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional, Union

from . import config
from .commands import ALLOWED_COMMANDS, COMMANDS
from .github_client import GitHubClient, GitHubClientError
from .maintenance_branch import BranchPlan
from .maintenance_branch import check as check_maintenance_branch
from .plan_document import CommonCache, PlanDocument  # noqa: F401  (CommonCache re-exported)
from .config import MAIN_BRANCH, PUBLISH_MODE_DRAFT, PUBLISH_MODE_ON_MERGE, PUBLISHERS_CODEOWNERS  # noqa: F401
from .state_manager import ConfigurationError, ReleaseInfoResult, ReleaseStateManager
from .trigger import DISPATCH_CREATE_MAINTENANCE_BRANCH, TRIGGER_SLASH_COMMAND, Trigger

WRITE_PERMISSIONS = ("admin", "maintain", "write")

# A Release Issue closed in these states is reopened
BLOCK_CLOSURE_STATES = (config.STATE_SNAPSHOT_ACTIVE, config.STATE_DRAFT_READY)

# Actions of the snapshot job (create-snapshot) and the act job (all others)
ACTION_CREATE_SNAPSHOT = "create-snapshot"
ACTION_CREATE_DRAFT = "create-draft"
ACTION_PUBLISH_ON_MERGE = "publish-on-merge"
ACTION_REOPEN_ISSUE = "reopen-issue"
ACTION_CREATE_MAINTENANCE_BRANCH = "create-maintenance-branch"
# Slash commands that are actions of their own (the others: finalize alone)
COMMAND_ACTIONS = tuple(c.name for c in COMMANDS if c.job)

# App bots don't register as collaborators, so the permission API returns
# 'none' for them; the write intent is established by the App installation on
# the target repo. Used by the Release Automation Regression canary in
# camaraproject/tooling, which posts slash commands as camara-validation[bot].
TRUSTED_BOT_USERS = {"camara-validation[bot]"}

# Bot comment templates the plan job posts
RESPONSE_INTERIM = "interim_processing"
RESPONSE_PUBLISH_CONFIRMATION = "publish_confirmation"
RESPONSE_REJECTED = "command_rejected"
RESPONSE_CONFIG_ERROR = "config_error"


@dataclass(frozen=True)
class Plan:
    """
    What the workflow executes.

    Attributes:
        response: Template the plan job posts ("" for non-slash triggers)
        base_branch: Branch the release is cut from: the line of the release
            tag (release_line.line_of), whose release-plan.yaml was read
        publish_mode: draft | on_merge, per release type (PUBLISH_MODES)
        action: What the snapshot/act job executes ("" for none; action_for)
        branch_plan: What create-maintenance-branch creates (that action only)
    """
    trigger_type: str
    command: str
    release_tag: str
    state: str
    release_type: str
    base_branch: str
    confirm_tag: str = ""
    publish_mode: str = PUBLISH_MODE_DRAFT
    response: str = ""
    action: str = ""
    branch_plan: Optional[BranchPlan] = None

    allowed = True

    def to_json(self) -> str:
        return json.dumps({"allowed": True, **asdict(self)})


@dataclass(frozen=True)
class Rejection:
    """
    Why the workflow stops.

    Attributes:
        response: command_rejected | config_error for slash commands; "" when
            there is no comment to update (the workflow fails instead)
        error_type: Configuration error category (config errors only)
    """
    error_message: str
    response: str
    error_type: str = ""

    allowed = False

    def to_json(self) -> str:
        return json.dumps({"allowed": False, **asdict(self)})


def publish_mode_for(release_type: Optional[str]) -> str:
    known = config.release_type(release_type)
    return known.publish_mode if known else PUBLISH_MODE_DRAFT


def _state_value(release_info: ReleaseInfoResult) -> str:
    return release_info.state.value if release_info.state else ""


def _check_state(command: str, state: str) -> Optional[str]:
    allowed = ALLOWED_COMMANDS.get(state, [])
    if command in allowed:
        return None
    valid = (
        f"Valid commands: {', '.join('/' + c for c in allowed)}"
        if allowed
        else "No commands available in this state"
    )
    return f"Command /{command} is not allowed in state '{state}'. {valid}"


def _check_cache(command: str, cache: CommonCache) -> Optional[str]:
    if command != "create-snapshot" or cache.status != "stale":
        return None
    hint = (
        f" Merge the sync PR: {cache.sync_pr_url}"
        if cache.sync_pr_url
        else " Run /sync-issue to trigger the sync, or close and reopen the Release Issue."
    )
    return f"Common file cache is stale: {cache.details}.{hint}"


def parse_codeowners(content: str) -> list:
    """Lower-cased owners on the first "*" line (applies to all files)."""
    for line in content.split("\n"):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        if trimmed.startswith("* ") or trimmed == "*":
            return [owner.lower() for owner in re.findall(r"@(\S+)", trimmed)]
    return []


def _check_publisher(user: str, permission: str, release_type: str, client) -> Optional[str]:
    """Publisher authorization for /publish-release (config.RELEASE_TYPES[...].publishers)."""
    known = config.release_type(release_type)
    rule = known.publishers if known else PUBLISHERS_CODEOWNERS
    if rule == PUBLISHERS_CODEOWNERS:
        # Break glass: maintain and admin bypass the CODEOWNERS list.
        if permission != "write":
            return None
        try:
            content = client.get_file_content("CODEOWNERS", ref="main", strict=True)
        except GitHubClientError as e:
            return f"Failed to verify codeowner status: {e}"
        owners = parse_codeowners(content) if content else []
        if owners and user.lower() not in owners:
            return (
                f"Only codeowners or admins can publish releases. "
                f"@{user} is not listed in CODEOWNERS."
            )
        return None
    raise ValueError(f"unknown publisher rule: {rule}")


def action_for(plan: Plan) -> str:
    """The action a plan executes, or "" when finalize alone follows."""
    match plan.trigger_type:
        case "slash_command":
            if plan.response == RESPONSE_INTERIM and plan.command in COMMAND_ACTIONS:
                return plan.command
            return ""
        case "pr_merge":
            return ACTION_PUBLISH_ON_MERGE if plan.publish_mode == PUBLISH_MODE_ON_MERGE else ACTION_CREATE_DRAFT
        case "issue_close":
            return ACTION_REOPEN_ISSUE if plan.state in BLOCK_CLOSURE_STATES else ""
        case "workflow_dispatch":
            return ACTION_CREATE_MAINTENANCE_BRANCH if plan.branch_plan else ""
        case _:
            return ""


def evaluate(
    trigger: Trigger,
    release_info: ReleaseInfoResult,
    cache: CommonCache = CommonCache(),
    client=None,
) -> Union[Plan, Rejection]:
    """
    Decide what to do with a trigger in the derived release state.

    Args:
        trigger: Classified trigger (should_continue is True)
        release_info: Result of ReleaseStateManager.derive_state()
        cache: Common-file cache detection result
        client: GitHubClient (permission and CODEOWNERS reads; slash commands only)

    Returns:
        Plan to execute, or Rejection to answer
    """
    result = _evaluate(trigger, release_info, cache, client)
    return replace(result, action=action_for(result)) if result.allowed else result


def _evaluate(
    trigger: Trigger,
    release_info: ReleaseInfoResult,
    cache: CommonCache = CommonCache(),
    client=None,
) -> Union[Plan, Rejection]:
    is_slash = trigger.trigger_type == TRIGGER_SLASH_COMMAND

    if not release_info.success:
        error = release_info.config_error or ConfigurationError("unknown", "Unknown error", "")
        return Rejection(
            error_message=error.message,
            response=RESPONSE_CONFIG_ERROR if is_slash else "",
            error_type=error.error_type,
        )

    state = _state_value(release_info)
    release_type = release_info.release_type or ""
    plan = Plan(
        trigger_type=trigger.trigger_type,
        command=trigger.command,
        release_tag=release_info.release_tag or "",
        state=state,
        release_type=release_type,
        confirm_tag=trigger.confirm_tag,
        base_branch=release_info.base_branch,
        publish_mode=publish_mode_for(release_type),
    )
    if trigger.command == DISPATCH_CREATE_MAINTENANCE_BRANCH:
        return _evaluate_create_maintenance_branch(trigger, plan, client)
    if not is_slash:
        return plan

    command = trigger.command
    user = trigger.user

    def reject(message: str) -> Rejection:
        return Rejection(error_message=message, response=RESPONSE_REJECTED)

    message = _check_state(command, state) or _check_cache(command, cache)
    if message:
        return reject(message)

    message, permission = _check_permission(user, client)
    if message:
        return reject(message)

    if command == "publish-release":
        message = _check_publisher(user, permission, release_type, client)
        if message:
            return reject(message)
        if trigger.confirm_tag and trigger.confirm_tag != plan.release_tag:
            return reject(
                f"Confirm tag `{trigger.confirm_tag}` does not match expected release tag "
                f"`{plan.release_tag}`. Use: /publish-release --confirm {plan.release_tag}"
            )
        if not trigger.confirm_tag:
            return replace(plan, response=RESPONSE_PUBLISH_CONFIRMATION)

    return replace(plan, response=RESPONSE_INTERIM)


def _check_permission(user: str, client) -> tuple:
    """(rejection message or None, permission): write access or higher."""
    if user in TRUSTED_BOT_USERS:
        permission = "write"
        print(f"User {user} is a trusted CI bot; treating as write")
    else:
        try:
            permission = client.get_collaborator_permission(user)
        except GitHubClientError as e:
            return f"Failed to verify permissions: {e}", ""
    print(f"User permission: {permission}")

    if permission not in WRITE_PERMISSIONS:
        return (
            "You must have write access or higher to run release commands. "
            f"Your current permission: {permission}"
        ), permission
    return None, permission


def _evaluate_create_maintenance_branch(trigger: Trigger, plan: Plan, client) -> Union[Plan, Rejection]:
    """The dispatch action create-maintenance-branch: a Plan with its branch plan, or why not."""
    def refuse(message: str) -> Rejection:
        # No comment to update: the plan job's step summary and failure report it
        return Rejection(error_message=message, response="")

    message, _ = _check_permission(trigger.user, client)
    if message:
        return refuse(message)
    if plan.base_branch != MAIN_BRANCH:
        return refuse(f"Dispatch create-maintenance-branch from main, not from {plan.base_branch}.")
    try:
        branch_plan = check_maintenance_branch(client, trigger.command_args, plan.release_tag)
    except GitHubClientError as e:
        return refuse(f"Failed to check the release history: {e}")
    if isinstance(branch_plan, str):
        return refuse(branch_plan)
    return replace(plan, branch_plan=branch_plan)


def finalize_due(result: Union[Plan, Rejection]) -> bool:
    """
    Whether the finalize job runs: a Plan whose command runs, not a rejection
    or confirmation request. create-maintenance-branch has nothing to finalize
    (no Release Issue of the new line exists yet); act writes its summary.
    """
    return (
        result.allowed
        and result.response != RESPONSE_PUBLISH_CONFIRMATION
        and result.action != ACTION_CREATE_MAINTENANCE_BRANCH
    )


def plan_document(
    result: Union[Plan, Rejection],
    trigger: Trigger,
    release_info: ReleaseInfoResult,
    cache: CommonCache,
    base_branch: str,
    repo_url: str = "",
    run_url: str = "",
    result_comment_id: str = "",
) -> PlanDocument:
    """The plan job's one output: the decision plus everything the later jobs read."""
    if result.allowed:
        return PlanDocument(
            trigger=trigger, release=release_info, cache=cache, base_branch=base_branch,
            allowed=True, publish_mode=result.publish_mode, response=result.response, action=result.action,
            branch_plan=result.branch_plan, repo_url=repo_url, run_url=run_url,
            result_comment_id=result_comment_id,
        )
    return PlanDocument(
        trigger=trigger, release=release_info, cache=cache, base_branch=base_branch,
        allowed=False, response=result.response, error_message=result.error_message,
        error_type=result.error_type, repo_url=repo_url, run_url=run_url,
    )


def response_delta(plan: PlanDocument) -> dict:
    """Template variables of the plan job's response comment beyond the base context."""
    if plan.response == RESPONSE_CONFIG_ERROR:
        return {"error_type": plan.error_type, "error_message": plan.error_message}
    if plan.response == RESPONSE_REJECTED:
        return {"error_message": plan.error_message}
    if plan.response == RESPONSE_PUBLISH_CONFIRMATION:
        # Draft releases have no direct URL
        return {"draft_release_url": f"{plan.repo_url}/releases"}
    return {}


def _describe_trigger(trigger: Trigger) -> str:
    text = trigger.trigger_type
    if trigger.trigger_type == TRIGGER_SLASH_COMMAND:
        text += f" `/{trigger.command}`"
    elif trigger.trigger_type == "workflow_dispatch":
        text += f" `{' '.join(filter(None, (trigger.command, trigger.command_args)))}`"
    text += f" by @{trigger.user}"
    if trigger.ref:
        text += f", ref {trigger.ref}"
    if trigger.issue_number:
        text += f" on #{trigger.issue_number}"
    if trigger.trigger_type == "pr_merge":
        text += f" (Release PR of {trigger.release_tag})"
    return text


def _describe_plan(result: Union[Plan, Rejection]) -> str:
    if not result.allowed:
        if result.error_type:
            return f"configuration error ({result.error_type}): {result.error_message}"
        return f"{'rejected' if result.response else 'refused'}: {result.error_message}"
    if result.response == RESPONSE_PUBLISH_CONFIRMATION:
        return f"confirmation requested: /publish-release --confirm {result.release_tag}"
    jobs = []
    if result.action:
        jobs.append("snapshot" if result.action == ACTION_CREATE_SNAPSHOT else "act")
    if finalize_due(result):
        jobs.append("finalize")
    runs = f"runs {', '.join(jobs)}" if jobs else "nothing else runs"
    if result.action == ACTION_CREATE_MAINTENANCE_BRANCH:
        bp = result.branch_plan
        return (
            f"{result.action}: {bp.branch} at {bp.patched_release} ({bp.patched_sha[:7]}), "
            f"plan parked at {bp.next_tag}; {runs}"
        )
    if result.action:
        return f"{result.action}, publish mode {result.publish_mode}; {runs}"
    return f"no action; {runs}"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def plan_summary(result: Union[Plan, Rejection], trigger: Trigger, release_info: ReleaseInfoResult,
                 cache: CommonCache) -> str:
    """Step summary of the plan job: the trigger, the context it derived, the plan (tooling#154)."""
    rows = [("Trigger", _describe_trigger(trigger))]
    if release_info.success:
        release = release_info.release_tag or "no tag"
        if release_info.release_type:
            release += f" ({release_info.release_type})"
        rows.append(("Release", f"{release}, state {_state_value(release_info) or 'unknown'}"))
        rows.append(("Base branch", release_info.base_branch))
        cache_text = cache.status or "not checked"
        if cache.status == "stale" and cache.details:
            cache_text += f": {cache.details}"
        rows.append(("Common cache", cache_text))
    rows.append(("Plan", _describe_plan(result)))
    lines = ["## Release Automation: plan", "", "| | |", "|---|---|"]
    lines += [f"| {name} | {_cell(value)} |" for name, value in rows]
    return "\n".join(lines) + "\n"


def check_cache(api_repo: Optional[Path], release_info: ReleaseInfoResult, client) -> CommonCache:
    """Common-file cache detection on the base branch's checkout; the sync PR of the line when stale."""
    from .common_sync import detect, find_sync_pr

    release = release_info.commonalities_release
    if not release_info.success or not release or api_repo is None:
        return CommonCache()
    check = detect(api_repo, release, release_info.identity_consent_management_release)
    sync_pr_url = ""
    if check.status == "stale":
        sync_pr_url = find_sync_pr(client, release, release_info.base_branch)
        print(f"Found existing sync PR: {sync_pr_url}" if sync_pr_url else "No existing sync PR found")
    return CommonCache(status=check.status, details=check.details, sync_pr_url=sync_pr_url)


def config_error_help(plan: PlanDocument) -> str:
    """The config_error template's text, for the log of a push or dispatch (no comment to post)."""
    from .bot_context import bot_context
    from .bot_responder import BotResponder

    delta = response_delta(replace(plan, response=RESPONSE_CONFIG_ERROR))
    return BotResponder().render_comment(RESPONSE_CONFIG_ERROR, bot_context(plan), delta, "unknown")


def post_response(plan: PlanDocument, client) -> str:
    """
    Post the plan job's one comment: update the acknowledgment (plan.result_comment_id)
    or create a new comment. Returns the comment id as a string, "" when the post failed.
    """
    from .bot_context import bot_context
    from .bot_responder import post_comment

    tag = "unknown" if plan.response == RESPONSE_CONFIG_ERROR else plan.release_tag
    try:
        comment_id = post_comment(
            client, plan.response, plan.trigger.issue_number, bot_context(plan), response_delta(plan),
            tag, comment_id=plan.result_comment_id,
        )
    except Exception as e:
        # A failed interim post does not stop the command; finalize then
        # posts no result comment (as before). Any other response is the
        # whole answer, so its failure fails the job.
        print(f"::{'warning' if plan.response == RESPONSE_INTERIM else 'error'}::Could not post {plan.response}: {e}")
        return ""
    return str(comment_id)


def main(client=None) -> int:
    from .trigger import write_outputs

    env = os.environ
    trigger = Trigger(**json.loads(env["TRIGGER_JSON"]))
    base_branch = env["BASE_BRANCH"]
    repo_url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY', '')}"
    run_url = f"{repo_url}/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
    if client is None:
        client = GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN"))

    print(f"Base branch: {base_branch}")
    release_info = ReleaseStateManager(client).derive_state(base_branch=base_branch)
    if release_info.success:
        print(f"Release {release_info.release_tag}: {_state_value(release_info)} (from {release_info.source})")
    else:
        print(f"::warning::Configuration error: {release_info.config_error.message}")
    api_repo = Path(env["API_REPO_PATH"]) if env.get("API_REPO_PATH") else None
    cache = check_cache(api_repo, release_info, client)
    if cache.status:
        print(f"Common cache: {cache.status}" + (f" ({cache.details})" if cache.details else ""))

    print(f"Validating command: /{trigger.command}")
    print(f"User: {trigger.user}")
    result = evaluate(trigger, release_info, cache, client=client)
    if result.allowed:
        print(f"Command validated successfully; action: {result.action or 'none'}")
    else:
        print(f"Rejected: {result.error_message}")

    plan = plan_document(
        result, trigger, release_info, cache, base_branch, repo_url=repo_url, run_url=run_url,
        result_comment_id=env.get("ACK_COMMENT_ID", ""),
    )
    exit_code = 0
    if plan.response:
        comment_id = post_response(plan, client)
        if plan.response == RESPONSE_INTERIM:
            plan = replace(plan, result_comment_id=comment_id)
        elif not comment_id:
            exit_code = 1
    if not result.allowed and not result.response:
        # No comment to update: the summary says why, the failed job shows it
        if result.error_type:
            print(f"::error::Configuration Error: {result.error_message}")
            print(config_error_help(plan))
        else:
            print(f"::error title=Refused::{result.error_message}")
        exit_code = 1

    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(plan_summary(result, trigger, release_info, cache))

    write_outputs(env["GITHUB_OUTPUT"], {
        "plan": plan.to_json(),
        "action": plan.action,
        "finalize": "true" if finalize_due(result) else "false",
        "result_comment_id": plan.result_comment_id if plan.response == RESPONSE_INTERIM else "",
    })
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
