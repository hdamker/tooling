"""Static checks for release automation workflow wiring."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from release_automation.scripts.trigger import SLASH_COMMANDS


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "release-automation-reusable.yml"
)


def _create_snapshot_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["create-snapshot"]["steps"]


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step not found: {name}")


def test_create_snapshot_passes_release_history_to_pre_snapshot_validation():
    steps = _create_snapshot_steps()
    names = [step.get("name") for step in steps]

    assert "Resolve published release history" in names
    assert names.index("Resolve published release history") < names.index(
        "Run pre-snapshot validation"
    )

    resolver = _step_by_name(steps, "Resolve published release history")
    assert resolver["id"] == "release-history"
    assert "GH_TOKEN" in resolver["env"]
    assert "_tooling/validation/scripts/resolve-release-history.py" in resolver["run"]
    assert '--repo "${{ github.repository }}"' in resolver["run"]
    assert '--output "${RUNNER_TEMP}/release-history.json"' in resolver["run"]

    validation = _step_by_name(steps, "Run pre-snapshot validation")
    assert validation["with"]["release_history_path"] == (
        "${{ steps.release-history.outputs.release_history_path || '' }}"
    )


def _all_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]


def test_tooling_checkouts_resolve_through_job_context():
    checkouts = [
        step
        for step in _all_steps()
        if str(step.get("uses", "")).startswith("actions/checkout")
        and step.get("with", {}).get("path") == "_tooling"
    ]

    assert len(checkouts) == 6
    for step in checkouts:
        assert step["with"]["repository"] == "${{ job.workflow_repository }}"
        assert step["with"]["ref"] == "${{ job.workflow_sha }}"
    assert len({step["with"]["sparse-checkout"] for step in checkouts}) == 1


def test_no_oidc_tooling_ref_resolution_or_override():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    for token in (
        "getIDToken",
        "tooling_ref_override",
        "ALLOWED_TOOLING_REFS",
        "needs.check-trigger.outputs.tooling_",
    ):
        assert token not in text
    assert "id-token" not in workflow["permissions"]


def _job_steps(job: str) -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"][job]["steps"]


def test_plan_acks_before_checkout_then_runs_trigger_module():
    steps = _job_steps("plan")
    names = [step.get("name") for step in steps]

    assert names.index("Post Acknowledgment") < names.index("Checkout tooling")
    assert names.index("Checkout tooling") < names.index("Detect Trigger Type")

    detect = _step_by_name(steps, "Detect Trigger Type")
    assert detect["id"] == "detect"
    assert detect["working-directory"] == "_tooling"
    assert detect["run"].strip() == "python -m release_automation.scripts.trigger"
    assert "uses" not in detect


def test_ack_command_list_matches_trigger_module():
    ack = _step_by_name(_job_steps("plan"), "Post Acknowledgment")
    script = ack["with"]["script"]

    match = re.search(r"body\.match\(/\^\\/\(([a-z|-]+)\)", script)
    assert match, "ack command regex not found"
    assert match.group(1).split("|") == [name for name, _ in SLASH_COMMANDS]
    # The ack reads the payload directly; it must not depend on later steps.
    assert "steps." not in script


def test_plan_runs_policy_then_one_response():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan = workflow["jobs"]["plan"]
    names = [step.get("name") for step in plan["steps"]]

    order = [
        "Detect Trigger Type",
        "Derive Release State",
        "Check common cache sync",
        "Apply Command Policy",
        "Assemble Context",
        "Post Response",
    ]
    assert [n for n in names if n in order] == order

    policy = _step_by_name(plan["steps"], "Apply Command Policy")
    assert policy["run"].strip() == "python -m release_automation.scripts.command_policy"
    assert policy["env"]["TRIGGER_JSON"] == "${{ steps.detect.outputs.trigger }}"
    cache = _step_by_name(plan["steps"], "Check common cache sync")
    assert cache["run"].strip() == "python -m release_automation.scripts.common_sync"
    # The existing-PR lookup is part of common_sync (exact sync-common/<release> head).
    assert policy["env"]["COMMON_SYNC_PR_URL"] == "${{ steps.cache-sync.outputs.common_sync_pr_url }}"
    assert cache["env"]["ICM_RELEASE"] == "${{ steps.state.outputs.identity_consent_management_release }}"

    respond = _step_by_name(plan["steps"], "Post Response")
    assert respond["uses"] == "./_tooling/shared-actions/post-bot-comment"
    assert respond["with"]["template"] == "${{ steps.policy.outputs.response }}"
    assert respond["with"]["context"] == "${{ steps.policy.outputs.response_context }}"
    assert plan["outputs"]["plan"] == "${{ steps.policy.outputs.plan }}"

    # The ack is the only inline script left in plan.
    scripts = [s for s in plan["steps"] if str(s.get("uses", "")).startswith("actions/github-script")]
    assert [s["name"] for s in scripts] == ["Post Acknowledgment"]


def test_folded_jobs_are_gone_and_compat_outputs_cover_every_reader():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]

    for gone in ("check-trigger", "derive-state", "handle-config-error",
                 "post-interim", "post-rejection", "publish-confirmation"):
        assert gone not in jobs
        assert f"needs.{gone}." not in text

    read = set(re.findall(r"needs\.plan\.outputs\.([a-z_]+)", text))
    assert read <= set(jobs["plan"]["outputs"])
    for name, job in jobs.items():
        if name != "plan":
            needs = job.get("needs", [])
            assert "plan" in ([needs] if isinstance(needs, str) else needs), name


def test_finalize_replaces_the_tail_jobs():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = yaml.safe_load(text)["jobs"]

    for gone in ("update-issue", "post-result", "create-sync-pr"):
        assert gone not in jobs
        assert f"needs.{gone}." not in text

    finalize = jobs["finalize"]
    assert finalize["if"] == "always() && needs.plan.outputs.finalize == 'true'"
    assert set(finalize["needs"]) == set(jobs) - {"finalize"}
    step = _step_by_name(finalize["steps"], "Finalize")
    assert step["run"].strip() == "python -m release_automation.scripts.finalize"
    assert step["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"


def test_finalize_reads_only_defined_outputs():
    """finalize.py reads plan and command-job outputs from toJSON(needs), not expressions."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    source = (WORKFLOW.parents[2] / "release_automation" / "scripts" / "finalize.py").read_text(encoding="utf-8")

    plan_reads = set(re.findall(r'\.plan\("([a-z_]+)"\)', source))
    assert plan_reads and plan_reads <= set(jobs["plan"]["outputs"])
    for job, name in re.findall(r'\.out\("([a-z-]+)", "([a-z_]+)"\)', source):
        assert name in jobs[job]["outputs"], (job, name)
