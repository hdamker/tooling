"""
Trigger classification for CAMARA release automation.

Turns the event that started the workflow into a Trigger: which path the
workflow takes (slash command, issue event, PR merge, dispatch, push) and the
command it carries. parse_trigger() is a pure function of the event name and
the payload at GITHUB_EVENT_PATH; the one network lookup the push path needs
(the PR a commit was merged from) is done by main() through GitHubClient.

Usage (workflow step):
    python3 -m release_automation.scripts.trigger
"""

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

from .config import RELEASE_PLAN_FILE, SNAPSHOT_BRANCH_PREFIX

RELEASE_ISSUE_LABEL = "release-issue"

TRIGGER_SLASH_COMMAND = "slash_command"
TRIGGER_UNKNOWN = "unknown"

# Slash commands in match order. An argument-taking command keeps what follows
# it on the first line of the comment; the others ignore any text after them.
SLASH_COMMANDS = (
    ("create-snapshot", False),
    ("discard-snapshot", True),
    ("delete-draft", True),
    ("sync-issue", False),
    ("publish-release", True),
)


def _js_trim(text: str) -> str:
    # JavaScript String.prototype.trim() also strips U+FEFF; str.strip() does not.
    return text.strip().strip("\ufeff").strip()


@dataclass(frozen=True)
class Trigger:
    """
    Classified workflow trigger.

    Field names and string forms match the check-trigger job outputs the
    remaining jobs read (issue_number is a string, empty when absent).

    Attributes:
        trigger_type: slash_command | issue_close | issue_reopen | pr_merge |
            workflow_dispatch | release_plan_change | push | unknown; empty
            when the event concerns no Release Issue
        command: Slash command name without the slash, or sync-issue for
            dispatch and push
        command_args: Text after the command on its first line (argument-taking
            commands only)
        issue_number: Issue the event happened on
        user: Commenter, issue author, PR merger or actor, by event
        should_continue: Whether the workflow proceeds past check-trigger
        confirm_tag: Tag given with /publish-release --confirm
        head_sha: Commit a push event points at (for the merged-PR lookup)
    """
    trigger_type: str = ""
    command: str = ""
    command_args: str = ""
    issue_number: str = ""
    user: str = ""
    should_continue: bool = False
    confirm_tag: str = ""
    head_sha: str = ""


def _is_release_issue(issue: Dict[str, Any]) -> bool:
    return any(label.get("name") == RELEASE_ISSUE_LABEL for label in issue.get("labels") or [])


def _parse_comment(payload: Dict[str, Any]) -> Trigger:
    comment = payload["comment"]
    issue = payload["issue"]
    if not _is_release_issue(issue):
        return Trigger()

    user = comment["user"]["login"]
    issue_number = str(issue["number"])
    body = _js_trim(comment.get("body") or "")
    # Arguments are clamped to the first line for length and tidiness only;
    # shell metacharacters pass through, so consumers must read them via env.
    first_line = re.split(r"\r?\n", body, maxsplit=1)[0]

    for command, takes_args in SLASH_COMMANDS:
        if not re.match(rf"/{command}(?:\s|\Z)", body):
            continue
        args = _js_trim(first_line[len(command) + 1:]) if takes_args else ""
        confirm_tag = ""
        if command == "publish-release":
            confirm = re.search(r"--confirm\s+(\S+)", args)
            confirm_tag = confirm.group(1) if confirm else ""
        return Trigger(
            trigger_type=TRIGGER_SLASH_COMMAND,
            command=command,
            command_args=args,
            issue_number=issue_number,
            user=user,
            should_continue=True,
            confirm_tag=confirm_tag,
        )

    return Trigger(trigger_type=TRIGGER_UNKNOWN, issue_number=issue_number, user=user)


ISSUE_ACTIONS = {"closed": "issue_close", "reopened": "issue_reopen"}


def _parse_issue_event(payload: Dict[str, Any]) -> Trigger:
    issue = payload["issue"]
    if not _is_release_issue(issue):
        return Trigger()

    trigger_type = ISSUE_ACTIONS.get(payload.get("action"))
    return Trigger(
        trigger_type=trigger_type or TRIGGER_UNKNOWN,
        issue_number=str(issue["number"]),
        # The issue author, not the sender
        user=issue["user"]["login"],
        should_continue=trigger_type is not None,
    )


def _parse_pull_request(payload: Dict[str, Any]) -> Trigger:
    pr = payload["pull_request"]
    if (
        payload.get("action") == "closed"
        and pr.get("merged")
        and pr["base"]["ref"].startswith(SNAPSHOT_BRANCH_PREFIX)
    ):
        merger = pr.get("merged_by") or pr["user"]
        return Trigger(trigger_type="pr_merge", user=merger["login"], should_continue=True)
    return Trigger(trigger_type=TRIGGER_UNKNOWN)


def _parse_push(payload: Dict[str, Any], actor: str, sha: str) -> Trigger:
    changed = {
        path
        for commit in payload.get("commits") or []
        for key in ("added", "modified", "removed")
        for path in commit.get(key) or []
    }
    head_commit = payload.get("head_commit") or {}
    return Trigger(
        trigger_type="release_plan_change" if RELEASE_PLAN_FILE in changed else "push",
        command="sync-issue",
        user=actor,
        should_continue=True,
        head_sha=head_commit.get("id") or sha,
    )


def parse_trigger(
    event_name: str,
    payload: Dict[str, Any],
    actor: str = "",
    sha: str = "",
) -> Trigger:
    """
    Classify an event.

    Args:
        event_name: GITHUB_EVENT_NAME (the caller's event in a reusable workflow)
        payload: Parsed JSON at GITHUB_EVENT_PATH
        actor: GITHUB_ACTOR, used as user for dispatch and push
        sha: GITHUB_SHA, fallback head commit for push

    Returns:
        Trigger; should_continue is False for events the workflow ignores
    """
    if event_name == "issue_comment":
        return _parse_comment(payload)
    if event_name == "issues":
        return _parse_issue_event(payload)
    if event_name == "pull_request":
        return _parse_pull_request(payload)
    if event_name == "workflow_dispatch":
        # Dispatch only ever syncs the Release Issue; the command input is ignored.
        return Trigger(
            trigger_type="workflow_dispatch",
            command="sync-issue",
            user=actor,
            should_continue=True,
        )
    if event_name == "push":
        return _parse_push(payload, actor, sha)
    return Trigger(trigger_type=TRIGGER_UNKNOWN)


def write_outputs(path: str, outputs: Dict[str, str]) -> None:
    """Append outputs to GITHUB_OUTPUT in heredoc form (values may hold any text)."""
    with open(path, "a", encoding="utf-8") as f:
        for name, value in outputs.items():
            delimiter = f"EOF-{uuid.uuid4()}"
            f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def to_outputs(trigger: Trigger, merged_pr: Optional[Tuple[int, str]]) -> Dict[str, str]:
    """String outputs under the check-trigger job's output names, plus the Trigger as JSON."""
    outputs = asdict(trigger)
    del outputs["head_sha"]
    outputs["trigger"] = json.dumps(asdict(trigger))
    outputs["should_continue"] = "true" if trigger.should_continue else "false"
    outputs["trigger_pr_number"] = str(merged_pr[0]) if merged_pr else ""
    outputs["trigger_pr_url"] = merged_pr[1] if merged_pr else ""
    return outputs


def main(client=None) -> int:
    event_name = os.environ["GITHUB_EVENT_NAME"]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        payload = json.load(f)

    trigger = parse_trigger(
        event_name,
        payload,
        actor=os.environ.get("GITHUB_ACTOR", ""),
        sha=os.environ.get("GITHUB_SHA", ""),
    )

    merged_pr = None
    if event_name == "push":
        if client is None:
            from .github_client import GitHubClient
            client = GitHubClient(
                repo=os.environ["GITHUB_REPOSITORY"], token=os.environ.get("GITHUB_TOKEN")
            )
        merged_pr = client.find_merged_pr_for_commit(trigger.head_sha)
        if merged_pr:
            print(f"Found merged PR: #{merged_pr[0]}")

    outputs = to_outputs(trigger, merged_pr)
    print(f"Event: {event_name}")
    print(f"Action: {payload.get('action') or 'N/A'}")
    for name, value in outputs.items():
        print(f"{name}: {value}")

    write_outputs(os.environ["GITHUB_OUTPUT"], outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
