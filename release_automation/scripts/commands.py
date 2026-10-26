"""
Commands and valid actions of CAMARA release automation.

One source for the command vocabulary:

- COMMANDS: the slash commands, in match order, with the job that executes
  each, its result templates and the release state after its success
- DISPATCH_ACTIONS: the values of the caller's workflow_dispatch input "action"
- STATE_ACTIONS: per release state, what a codeowner can do, in display
  order; ALLOWED_COMMANDS (which slash commands a state accepts) is derived
  from it plus the hidden commands
- actions_for(): the "Valid actions" block of the Release Issue body, of the
  bot comments and of a rejection

The caller template's job if: and the acknowledgment regex in the reusable
workflow list the command names again; a pytest pins both to COMMANDS.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import config

JOB_SNAPSHOT = "snapshot"
JOB_ACT = "act"


@dataclass(frozen=True)
class Command:
    """A slash command.

    Attributes:
        name: The command without its slash
        takes_args: What follows on the first line is the command's argument
        job: The job that executes it (snapshot, act), "" for finalize alone
        ok: Result template after success
        failed: Result template after failure
        state_after: Release state after success, "" if unchanged
        hidden: Accepted in every state, never offered as an action
        usage: Argument hint shown in the actions list; {release_tag} is filled in
        purpose: One line in the actions list
    """
    name: str
    takes_args: bool
    job: str
    ok: str
    failed: str
    state_after: str = ""
    hidden: bool = False
    usage: str = ""
    purpose: str = ""


COMMANDS: Tuple[Command, ...] = (
    Command("create-snapshot", False, JOB_SNAPSHOT, "snapshot_created", "snapshot_failed",
            config.STATE_SNAPSHOT_ACTIVE, purpose="begin the release process"),
    Command("discard-snapshot", True, JOB_ACT, "snapshot_discarded", "snapshot_failed",
            config.STATE_PLANNED, usage="<reason>", purpose="discard and return to `planned`"),
    Command("delete-draft", True, JOB_ACT, "draft_revoked", "snapshot_failed",
            config.STATE_PLANNED, usage="<reason>", purpose="delete draft and return to `planned`"),
    Command("sync-issue", False, "", "issue_synced", "issue_sync_failed", hidden=True),
    Command("publish-release", True, JOB_ACT, "release_published", "publish_failed",
            config.STATE_PUBLISHED, usage="--confirm {release_tag}", purpose="publish the release"),
)

# Values of the caller's workflow_dispatch input "action"
DISPATCH_SYNC_ISSUE = "sync-issue"
DISPATCH_CREATE_MAINTENANCE_BRANCH = "create-maintenance-branch"
DISPATCH_ACTIONS = (DISPATCH_SYNC_ISSUE, DISPATCH_CREATE_MAINTENANCE_BRANCH)

# What a codeowner can do per state, in display order: a command name, or a
# prose step ({release_pr} is a link to the Release PR when known).
STATE_ACTIONS: Dict[str, Tuple[str, ...]] = {
    config.STATE_PLANNED: ("create-snapshot",),
    config.STATE_SNAPSHOT_ACTIVE: (
        "Update, review, and merge {release_pr} to create draft release",
        "discard-snapshot",
    ),
    config.STATE_DRAFT_READY: ("publish-release", "delete-draft"),
    config.STATE_PUBLISHED: (),
    config.STATE_NOT_PLANNED: (
        "Update `release-plan.yaml` with a planned release type to resume",
        "Close this issue — a new one will be created when a release is planned",
    ),
}


def command(name: str) -> Optional[Command]:
    return next((c for c in COMMANDS if c.name == name), None)


def _allowed(state: str) -> List[str]:
    listed = [row for row in STATE_ACTIONS[state] if command(row)]
    return listed + [c.name for c in COMMANDS if c.hidden]


# Slash commands each state accepts: the listed ones, then the hidden ones
ALLOWED_COMMANDS: Dict[str, List[str]] = {state: _allowed(state) for state in STATE_ACTIONS}


def _row(row: str, release_tag: str, release_pr_url: str) -> str:
    cmd = command(row)
    if cmd:
        usage = f" {cmd.usage.format(release_tag=release_tag)}" if cmd.usage else ""
        return f"`/{cmd.name}{usage}` — {cmd.purpose}"
    release_pr = f"[Release PR]({release_pr_url})" if release_pr_url else "Release PR"
    return row.format(release_pr=release_pr)


def actions_for(state: str, release_tag: str, release_pr_url: str = "") -> str:
    """The "Valid actions" block for a state, the first action bold; "" when there is none."""
    rows = [_row(row, release_tag, release_pr_url) for row in STATE_ACTIONS.get(state, ())]
    if not rows:
        return ""
    rows[0] = f"**{rows[0]}**"
    return "**Valid actions:**" + "".join(f"<br>→ {row}" for row in rows)
