"""
Release line of a CAMARA release tag.

A release cycle X with a public release is maintained on `maintenance/rX`
once that branch exists, otherwise on `main` (line_of). The base branch of a
workflow run is the ref's branch for push and dispatch, and the line of the
tag the event names for slash commands, issue events and Release PR merges.

Usage (workflow step):
    python3 -m release_automation.scripts.release_line
"""

import json
import os
import re
import sys

from .github_client import GitHubClient
from .trigger import Trigger, write_outputs

MAIN_BRANCH = "main"
MAINTENANCE_BRANCH_PREFIX = "maintenance/"
MAINTENANCE_BRANCH_RE = re.compile(r"^maintenance/r[1-9]\d*$")

# Triggers whose branch is the ref they ran on; all others name a tag
REF_TRIGGERS = ("push", "workflow_dispatch")


def maintenance_branch(release_tag: str) -> str:
    """maintenance/rX for a tag rX.Y, "" for anything else."""
    match = re.match(r"^r([1-9]\d*)\.\d+$", release_tag or "")
    return f"{MAINTENANCE_BRANCH_PREFIX}r{match.group(1)}" if match else ""


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
    trigger = Trigger(**json.loads(env["TRIGGER_JSON"]))
    if client is None:
        client = GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN"))
    base_branch = base_branch_for(trigger, client)
    print(f"Base branch: {base_branch}")
    write_outputs(env["GITHUB_OUTPUT"], {"base_branch": base_branch})
    return 0


if __name__ == "__main__":
    sys.exit(main())
