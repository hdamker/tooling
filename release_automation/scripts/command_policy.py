"""
Command policy for CAMARA release automation.

Decides what the workflow does with a classified trigger in the current
release state: a Plan to execute, or a Rejection to answer. Slash commands are
checked in a fixed order — state table, common-cache gate, permission,
publisher authorization, confirm tag — and the first failing check names the
rejection. Other triggers are not validated.

Policy values that are expected to change (RM#675) sit in PUBLISH_MODES and
PUBLISHERS; the initial values reproduce the behaviour before this module.

Usage (workflow step):
    python3 -m release_automation.scripts.command_policy
"""

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, replace
from typing import Optional, Union

from . import config
from .github_client import GitHubClient, GitHubClientError
from .state_manager import ConfigurationError, ReleaseInfoResult, ReleaseState
from .trigger import TRIGGER_SLASH_COMMAND, Trigger

# Commands a slash command may name, per release state (display order).
ALLOWED_COMMANDS = {
    config.STATE_PLANNED: ["create-snapshot", "sync-issue"],
    config.STATE_SNAPSHOT_ACTIVE: ["discard-snapshot", "sync-issue"],
    config.STATE_DRAFT_READY: ["delete-draft", "publish-release", "sync-issue"],
    config.STATE_PUBLISHED: ["sync-issue"],
    config.STATE_NOT_PLANNED: ["sync-issue"],
}

DEFAULT_BASE_BRANCH = "main"

# How a release is published once its Release PR is merged:
#   draft    — merge creates a draft release; /publish-release --confirm publishes it
#   on_merge — merge publishes directly
PUBLISH_MODE_DRAFT = "draft"
PUBLISH_MODE_ON_MERGE = "on_merge"
PUBLISH_MODES = {
    "pre-release-alpha": PUBLISH_MODE_DRAFT,
    "pre-release-rc": PUBLISH_MODE_DRAFT,
    "public-release": PUBLISH_MODE_DRAFT,
    "maintenance-release": PUBLISH_MODE_DRAFT,
}

# Who may post /publish-release, per release type:
#   codeowners — users on the first "*" line of CODEOWNERS (main); maintain
#                and admin bypass; no list means write access suffices
PUBLISHERS_CODEOWNERS = "codeowners"
PUBLISHERS = {
    "pre-release-alpha": PUBLISHERS_CODEOWNERS,
    "pre-release-rc": PUBLISHERS_CODEOWNERS,
    "public-release": PUBLISHERS_CODEOWNERS,
    "maintenance-release": PUBLISHERS_CODEOWNERS,
}

WRITE_PERMISSIONS = ("admin", "maintain", "write")

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
class CommonCache:
    """Common-file cache detection result (code/common/ against the declared release)."""
    status: str = ""  # in_sync | stale | "" (not checked)
    details: str = ""
    sync_pr_url: str = ""


@dataclass(frozen=True)
class Plan:
    """
    What the workflow executes.

    Attributes:
        response: Template the plan job posts ("" for non-slash triggers)
        base_branch: Branch the release is cut from
        publish_mode: draft | on_merge, per release type (PUBLISH_MODES)
    """
    trigger_type: str
    command: str
    release_tag: str
    state: str
    release_type: str
    confirm_tag: str = ""
    base_branch: str = DEFAULT_BASE_BRANCH
    publish_mode: str = PUBLISH_MODE_DRAFT
    response: str = ""

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
    return PUBLISH_MODES.get(release_type or "", PUBLISH_MODE_DRAFT)


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
        else " Run workflow_dispatch to trigger sync, or close and reopen the Release Issue."
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
    """Publisher authorization for /publish-release (PUBLISHERS)."""
    rule = PUBLISHERS.get(release_type, PUBLISHERS_CODEOWNERS)
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
        publish_mode=publish_mode_for(release_type),
    )
    if not is_slash:
        return plan

    command = trigger.command
    user = trigger.user

    def reject(message: str) -> Rejection:
        return Rejection(error_message=message, response=RESPONSE_REJECTED)

    message = _check_state(command, state) or _check_cache(command, cache)
    if message:
        return reject(message)

    if user in TRUSTED_BOT_USERS:
        permission = "write"
        print(f"User {user} is a trusted CI bot; treating as write")
    else:
        try:
            permission = client.get_collaborator_permission(user)
        except GitHubClientError as e:
            return reject(f"Failed to verify permissions: {e}")
    print(f"User permission: {permission}")

    if permission not in WRITE_PERMISSIONS:
        return reject(
            "You must have write access or higher to run release commands. "
            f"Your current permission: {permission}"
        )

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


def release_info_from_env(env) -> ReleaseInfoResult:
    """Rebuild a ReleaseInfoResult from the derive-release-state outputs."""
    if env.get("CONFIG_ERROR"):
        return ReleaseInfoResult(
            success=False,
            config_error=ConfigurationError(
                error_type=env.get("CONFIG_ERROR_TYPE", ""),
                message=env["CONFIG_ERROR"],
                file_path=config.RELEASE_PLAN_FILE,
            ),
        )
    state = env.get("STATE", "")
    return ReleaseInfoResult(
        success=True,
        release_tag=env.get("RELEASE_TAG", ""),
        state=ReleaseState(state) if state else None,
        release_type=env.get("RELEASE_TYPE", ""),
    )


def main(client=None) -> int:
    from .trigger import write_outputs

    env = os.environ
    trigger = Trigger(**json.loads(env["TRIGGER_JSON"]))
    release_info = release_info_from_env(env)
    cache = CommonCache(
        status=env.get("COMMON_CACHE_STATUS", ""),
        details=env.get("COMMON_CACHE_DETAILS", ""),
        sync_pr_url=env.get("COMMON_SYNC_PR_URL", ""),
    )
    if client is None:
        client = GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN"))

    print(f"Validating command: /{trigger.command}")
    print(f"Current state: {_state_value(release_info)}")
    print(f"User: {trigger.user}")

    result = evaluate(trigger, release_info, cache, client=client)
    if result.allowed:
        print("Command validated successfully")
    else:
        print(f"Rejected: {result.error_message}")

    write_outputs(env["GITHUB_OUTPUT"], {
        "allowed": "true" if result.allowed else "false",
        "error_message": "" if result.allowed else result.error_message,
        "plan": result.to_json(),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
