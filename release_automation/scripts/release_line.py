"""
Release line of a CAMARA release tag.

A release cycle X with a public release is maintained on `maintenance/rX`
once that branch exists, otherwise on `main` (line_of). The base branch of a
workflow run is the ref's branch for push and dispatch, and the line of the
tag the event names for slash commands, issue events and Release PR merges.

main() is the plan job's resolve step: it classifies the event (trigger) and
resolves its base branch; outputs trigger (JSON), should_continue and
base_branch.

Usage (workflow step):
    python3 -m release_automation.scripts.release_line
"""

import json
import os
import re
import sys
from dataclasses import asdict
from typing import Optional, Tuple

from .config import MAIN_BRANCH  # noqa: F401  (re-exported)
from .github_client import GitHubClient
from .trigger import Trigger, parse_trigger, write_outputs

MAINTENANCE_BRANCH_PREFIX = "maintenance/"
MAINTENANCE_BRANCH_RE = re.compile(r"^maintenance/r[1-9]\d*$")

# Triggers whose branch is the ref they ran on; all others name a tag
REF_TRIGGERS = ("push", "workflow_dispatch")


def tag_version(release_tag: str) -> Optional[Tuple[int, int]]:
    """(X, Y) of a tag rX.Y, the order of release tags; None for anything else."""
    match = re.match(r"^r([1-9]\d*)\.(\d+)$", release_tag or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def maintenance_branch(release_tag: str) -> str:
    """maintenance/rX for a tag rX.Y, "" for anything else."""
    version = tag_version(release_tag)
    return f"{MAINTENANCE_BRANCH_PREFIX}r{version[0]}" if version else ""


def line_of(gh, release_tag: str) -> str:
    """maintenance/rX if that branch exists, else main."""
    branch = maintenance_branch(release_tag)
    if branch and gh.get_branch_sha(branch):
        return branch
    return MAIN_BRANCH


def base_branch_for(trigger: Trigger, gh) -> str:
    """The branch whose release-plan.yaml the run works on."""
    if trigger.trigger_type in REF_TRIGGERS:
        return trigger.ref if MAINTENANCE_BRANCH_RE.match(trigger.ref) else MAIN_BRANCH
    return line_of(gh, trigger.release_tag)


def main(client=None) -> int:
    env = os.environ
    event_name = env["GITHUB_EVENT_NAME"]
    with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        payload = json.load(f)
    trigger = parse_trigger(event_name, payload, actor=env.get("GITHUB_ACTOR", ""))
    print(f"Event: {event_name} ({payload.get('action') or 'no action'})")
    for name, value in asdict(trigger).items():
        print(f"  {name}: {value}")

    base_branch = ""
    if trigger.should_continue:
        if client is None:
            client = GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN"))
        base_branch = base_branch_for(trigger, client)
        print(f"Base branch: {base_branch}")
    write_outputs(env["GITHUB_OUTPUT"], {
        "trigger": json.dumps(asdict(trigger)),
        "should_continue": "true" if trigger.should_continue else "false",
        "base_branch": base_branch,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
