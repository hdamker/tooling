"""
Trigger classification for CAMARA release automation.

Turns the event that started the workflow into a Trigger: which path the
workflow takes (slash command, issue event, PR merge, dispatch, push) and the
command it carries. parse_trigger() is a pure function of the event name and
the payload at GITHUB_EVENT_PATH.

Usage (workflow step):
    python3 -m release_automation.scripts.trigger
"""

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict

from .config import SNAPSHOT_BRANCH_PREFIX

RELEASE_ISSUE_LABEL = "release-issue"
RELEASE_TAG_MARKER_RE = re.compile(r"<!--\s*release-automation:release-tag:(?P<tag>.*?)\s*-->")

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
            workflow_dispatch | push | unknown; empty
            when the event concerns no Release Issue
        command: Slash command name without the slash, or sync-issue for
            dispatch and push
        command_args: Text after the command on its first line (argument-taking
            commands only)
        issue_number: Issue the event happened on
        user: Commenter, issue author, PR merger or actor, by event
        should_continue: Whether the workflow proceeds past check-trigger
        confirm_tag: Tag given with /publish-release --confirm
        ref: Branch of a dispatch or push ("" for other events)
        release_tag: Tag the event names — the Release Issue's release-tag
            marker, or the snapshot branch of a merged Release PR
    """
    trigger_type: str = ""
    command: str = ""
    command_args: str = ""
    issue_number: str = ""
    user: str = ""
    should_continue: bool = False
    confirm_tag: str = ""
    ref: str = ""
    release_tag: str = ""


def _issue_release_tag(issue: Dict[str, Any]) -> str:
    match = RELEASE_TAG_MARKER_RE.search(issue.get("body") or "")
    return match.group("tag") if match else ""


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
            release_tag=_issue_release_tag(issue),
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
        release_tag=_issue_release_tag(issue) if trigger_type else "",
    )


def _parse_pull_request(payload: Dict[str, Any]) -> Trigger:
    pr = payload["pull_request"]
    if (
        payload.get("action") == "closed"
        and pr.get("merged")
        and pr["base"]["ref"].startswith(SNAPSHOT_BRANCH_PREFIX)
    ):
        merger = pr.get("merged_by") or pr["user"]
        snapshot_id = pr["base"]["ref"][len(SNAPSHOT_BRANCH_PREFIX):]
        return Trigger(
            trigger_type="pr_merge",
            user=merger["login"],
            should_continue=True,
            release_tag=snapshot_id.split("-")[0],
        )
    return Trigger(trigger_type=TRIGGER_UNKNOWN)


def parse_trigger(
    event_name: str,
    payload: Dict[str, Any],
    actor: str = "",
) -> Trigger:
    """
    Classify an event.

    Args:
        event_name: GITHUB_EVENT_NAME (the caller's event in a reusable workflow)
        payload: Parsed JSON at GITHUB_EVENT_PATH
        actor: GITHUB_ACTOR, used as user for dispatch and push

    Returns:
        Trigger; should_continue is False for events the workflow ignores
    """
    if event_name == "issue_comment":
        return _parse_comment(payload)
    if event_name == "issues":
        return _parse_issue_event(payload)
    if event_name == "pull_request":
        return _parse_pull_request(payload)
    if event_name in ("workflow_dispatch", "push"):
        # Both only ever sync the Release Issue; the dispatch command input is ignored.
        ref = payload.get("ref") or ""
        return Trigger(
            trigger_type=event_name,
            command="sync-issue",
            user=actor,
            should_continue=True,
            ref=ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else "",
        )
    return Trigger(trigger_type=TRIGGER_UNKNOWN)


def write_outputs(path: str, outputs: Dict[str, str]) -> None:
    """Append outputs to GITHUB_OUTPUT in heredoc form (values may hold any text)."""
    with open(path, "a", encoding="utf-8") as f:
        for name, value in outputs.items():
            delimiter = f"EOF-{uuid.uuid4()}"
            f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def to_outputs(trigger: Trigger) -> Dict[str, str]:
    """String outputs under the check-trigger job's output names, plus the Trigger as JSON."""
    outputs = asdict(trigger)
    outputs["trigger"] = json.dumps(asdict(trigger))
    outputs["should_continue"] = "true" if trigger.should_continue else "false"
    return outputs


def main() -> int:
    event_name = os.environ["GITHUB_EVENT_NAME"]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        payload = json.load(f)

    trigger = parse_trigger(
        event_name,
        payload,
        actor=os.environ.get("GITHUB_ACTOR", ""),
    )

    outputs = to_outputs(trigger)
    print(f"Event: {event_name}")
    print(f"Action: {payload.get('action') or 'N/A'}")
    for name, value in outputs.items():
        print(f"{name}: {value}")

    write_outputs(os.environ["GITHUB_OUTPUT"], outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
