"""
Act phase of CAMARA release automation.

Executes the action the plan names and writes one JSON outcome for finalize.
The plan decides (command_policy); this module dispatches:

    discard-snapshot   draft_release.discard_snapshot
    delete-draft       draft_release.delete_draft
    publish-release    release_publisher.publish_draft
    create-draft       draft_release.create_draft, then the draft_created comment
    publish-on-merge   draft_release.publish_on_merge
    reopen-issue       issue_events.reopen_release_issue
    create-maintenance-branch  maintenance_branch.create

create-snapshot runs in the snapshot job (it needs the validation toolchain);
snapshot_outcome() turns that job's step outputs into the same outcome form.

Two clients: the repository client (App token: branches, commits, PRs,
releases) and the issue client (GITHUB_TOKEN) for every Release Issue write,
so no write to the issue triggers a caller run.

Outcome values are strings, under the output names of the former command jobs.

Usage (workflow steps):
    python3 -m release_automation.scripts.act            # act job
    python3 -m release_automation.scripts.act snapshot   # last step of the snapshot job
"""

import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Tuple

from .bot_context import bot_context
from .bot_responder import post_comment
from .config import STATE_DRAFT_READY
from .github_client import GitHubClientError
from .plan_document import PlanDocument

SNAPSHOT_FIELDS = (
    "success", "snapshot_id", "snapshot_branch", "release_review_branch",
    "release_pr_number", "release_pr_url", "error_message", "apis_json",
)


def _outcome(action: str, result) -> Dict[str, str]:
    values = {}
    for name, value in asdict(result).items():
        if name == "success":
            values[name] = "true" if value else "false"
        elif isinstance(value, bool):
            values[name] = "true" if value else ""
        else:
            values[name] = str(value)
    return {"action": action, **values}


def act(plan: PlanDocument, gh, event: Dict[str, Any], issues=None) -> Dict[str, str]:
    from .draft_release import create_draft, delete_draft, discard_snapshot, publish_on_merge
    from .issue_events import reopen_release_issue
    from .maintenance_branch import create
    from .release_publisher import publish_draft

    issues = issues or gh
    action = plan.action
    tag = plan.release_tag
    snapshot = plan.snapshot_branch
    review = plan.release_review_branch
    if action == "create-maintenance-branch":
        print(f"Action: {action} ({plan.branch_plan.branch} from {plan.branch_plan.patched_release})")
    else:
        print(f"Action: {action} ({tag})")

    match action:
        case "discard-snapshot":
            return _outcome(action, discard_snapshot(gh, plan.release_pr_number, snapshot, review))
        case "delete-draft":
            return _outcome(action, delete_draft(gh, tag, snapshot, review))
        case "publish-release":
            return _outcome(action, publish_draft(gh, tag, snapshot, review, plan.src_commit_sha))
        case "create-draft":
            result = create_draft(gh, tag, snapshot, plan.release_type)
            outcome = _outcome(action, result)
            # The merged Release PR, for the comment and the issue sync
            pr = event.get("pull_request") or {}
            outcome["release_pr_number"] = str(pr.get("number", ""))
            outcome["release_pr_url"] = pr.get("html_url", "")
            if result.success and plan.release_issue_number:
                try:
                    post_comment(issues, "draft_created", plan.release_issue_number, bot_context(plan), {
                        "state": STATE_DRAFT_READY,
                        "draft_release_url": result.draft_release_url,
                        "release_pr_number": outcome["release_pr_number"],
                        "release_pr_url": outcome["release_pr_url"],
                        "candidate_block_stripped": outcome["candidate_block_stripped"],
                    }, tag)
                except GitHubClientError as e:
                    print(f"::error::Could not post draft_created: {e}")
                    outcome["comment_failed"] = "true"
            return outcome
        case "publish-on-merge":
            return _outcome(action, publish_on_merge(
                gh, tag, snapshot, review, plan.release_type, plan.src_commit_sha
            ))
        case "reopen-issue":
            return _outcome(action, reopen_release_issue(issues, int(plan.trigger.issue_number), tag, bot_context(plan)))
        case "create-maintenance-branch":
            return _outcome(action, create(gh, plan.branch_plan))
        case _:
            raise ValueError(f"unknown action: {action}")


def maintenance_branch_summary(plan: PlanDocument, outcome: Dict[str, str]) -> str:
    """
    Step summary of create-maintenance-branch: the branch, its parked plan and
    the next step, or what failed. The summary is the only feedback: no Release
    Issue exists yet for the line, and finalize does not run.
    """
    bp = plan.branch_plan
    if outcome.get("success") == "true":
        branch = outcome.get("branch", "")
        rows = [
            ("Maintenance branch", (
                f"{branch} created at {bp.patched_sha[:7]}, the source commit of "
                f"{bp.patched_release}; set-up commit {outcome.get('setup_commit_sha', '')[:7]}"
            )),
            ("Release plan", f"parked at {bp.next_tag}, target_release_type: none"),
            ("Next step", (
                f"Open a PR into {branch} that sets target_release_type: maintenance-release and raises the "
                f"patch version of each API the release fixes; its merge creates the Release Issue for {bp.next_tag}."
            )),
        ]
    else:
        rows = [("Maintenance branch", f"failed: {outcome.get('error_message') or 'no outcome'}")]
    if outcome.get("warning"):
        rows.append(("Warning", outcome["warning"]))
    lines = ["## Release Automation: create-maintenance-branch", "", "| | |", "|---|---|"]
    lines += [f"| {name} | {value.replace('|', chr(92) + '|').replace(chr(10), ' ')} |" for name, value in rows]
    return "\n".join(lines) + "\n"


def snapshot_outcome(create: Dict[str, str], gate: Dict[str, str]) -> Dict[str, str]:
    """Outcome of the snapshot job from the Create Snapshot and validation-gate step outputs."""
    outcome = {"action": "create-snapshot"}
    for name in SNAPSHOT_FIELDS:
        outcome[name] = create.get(name, "") or (gate.get(name, "") if name in ("success", "error_message") else "")
    return outcome


def clients_from_env() -> Tuple[Any, Any]:
    """The repository client (GITHUB_TOKEN) and the issue client (ISSUE_TOKEN, else the same token)."""
    from .github_client import GitHubClient

    env = os.environ
    token = env.get("GITHUB_TOKEN") or None
    return (
        GitHubClient(repo=env["GITHUB_REPOSITORY"], token=token),
        GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("ISSUE_TOKEN") or token),
    )


def main(argv: List[str], gh=None, issues=None) -> int:
    from .trigger import write_outputs

    env = os.environ
    if argv == ["snapshot"]:
        outcome = snapshot_outcome(json.loads(env.get("CREATE_JSON") or "{}"), json.loads(env.get("GATE_JSON") or "{}"))
        print(f"Pre-snapshot validation: {env.get('VALIDATION_RESULT') or 'skipped'}")
        for name in ("success", "snapshot_id", "snapshot_branch", "release_pr_number", "error_message"):
            print(f"  {name}: {outcome[name]}")
        write_outputs(env["GITHUB_OUTPUT"], {"outcome": json.dumps(outcome)})
        return 0

    plan = PlanDocument.from_json(env["PLAN_JSON"])
    with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    if gh is None:
        gh, issues = clients_from_env()

    outcome = act(plan, gh, event, issues)
    write_outputs(env["GITHUB_OUTPUT"], {"outcome": json.dumps(outcome)})
    print(f"Outcome: {json.dumps(outcome)}")
    if plan.action == "create-maintenance-branch" and env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(maintenance_branch_summary(plan, outcome))
    # A failed action fails the job; finalize runs regardless and reports it.
    return 0 if outcome["success"] == "true" and not outcome.get("comment_failed") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
