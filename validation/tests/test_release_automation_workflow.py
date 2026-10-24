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
    return workflow["jobs"]["snapshot"]["steps"]


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
    assert '--repo "$GITHUB_REPOSITORY"' in resolver["run"]
    assert '--base-ref "$BASE_REF"' in resolver["run"]
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

    # One per phase job: plan, snapshot, act, finalize
    assert len(checkouts) == 4
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
        "Assemble Context",
        "Apply Command Policy",
        "Post Response",
    ]
    assert [n for n in names if n in order] == order

    policy = _step_by_name(plan["steps"], "Apply Command Policy")
    assert policy["run"].strip() == "python -m release_automation.scripts.command_policy"
    assert policy["env"]["TRIGGER_JSON"] == "${{ steps.detect.outputs.trigger }}"
    assert policy["env"]["STATE_JSON"] == "${{ toJSON(steps.state.outputs) }}"
    assert policy["env"]["BASE_CONTEXT"] == "${{ steps.assemble.outputs.base_context }}"
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


def test_four_phase_jobs_and_three_job_conditions():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = yaml.safe_load(text)["jobs"]

    assert list(jobs) == ["plan", "snapshot", "act", "finalize"]
    for gone in ("check-trigger", "derive-state", "handle-config-error", "post-interim", "post-rejection",
                 "publish-confirmation", "update-issue", "post-result", "create-sync-pr",
                 "create-snapshot", "discard-snapshot", "delete-draft", "publish-release",
                 "handle-pr-merge", "handle-issue-event"):
        assert f"needs.{gone}." not in text
    assert [name for name, job in jobs.items() if "if" in job] == ["snapshot", "act", "finalize"]
    assert jobs["snapshot"]["if"] == "needs.plan.outputs.action == 'create-snapshot'"
    assert jobs["act"]["if"] == "needs.plan.outputs.action != '' && needs.plan.outputs.action != 'create-snapshot'"
    # Job names are not evaluated for a skipped job; the action is carried in the step name.
    assert "name" not in jobs["act"]
    assert [s["name"] for s in jobs["act"]["steps"] if s.get("id") == "act"] == [
        "Act (${{ needs.plan.outputs.action }})"
    ]


def test_plan_has_one_json_plan_and_no_compatibility_outputs():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = yaml.safe_load(text)["jobs"]

    assert set(jobs["plan"]["outputs"]) == {"plan", "action", "finalize", "result_comment_id"}
    read = set(re.findall(r"needs\.plan\.outputs\.([a-z_]+)", text))
    assert read == {"plan", "action", "finalize"}
    for name in ("snapshot", "act", "finalize"):
        needs = jobs[name]["needs"]
        assert "plan" in ([needs] if isinstance(needs, str) else needs), name


def test_snapshot_and_act_emit_one_outcome():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    assert jobs["snapshot"]["outputs"] == {"outcome": "${{ steps.outcome.outputs.outcome }}"}
    outcome = _step_by_name(jobs["snapshot"]["steps"], "Outcome")
    assert outcome["if"] == "always()"
    assert outcome["run"].strip() == "python -m release_automation.scripts.act snapshot"
    assert jobs["act"]["outputs"] == {"outcome": "${{ steps.act.outputs.outcome }}"}
    step = next(s for s in jobs["act"]["steps"] if s.get("id") == "act")
    assert step["run"].strip() == "python -m release_automation.scripts.act"
    assert step["env"]["PLAN_JSON"] == "${{ needs.plan.outputs.plan }}"
    # No inline scripts in the action phase
    for name in ("snapshot", "act"):
        assert not [s for s in jobs[name]["steps"] if str(s.get("uses", "")).startswith("actions/github-script")]


def test_finalize_replaces_the_tail_jobs():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    finalize = jobs["finalize"]
    assert finalize["if"] == "always() && needs.plan.outputs.finalize == 'true'"
    assert finalize["needs"] == ["plan", "snapshot", "act"]
    step = _step_by_name(finalize["steps"], "Finalize")
    assert step["run"].strip() == "python -m release_automation.scripts.finalize"
    assert step["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"


def test_finalize_reads_only_defined_plan_outputs():
    """finalize.py reads the plan job's outputs and the action jobs' outcome from toJSON(needs)."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    source = (WORKFLOW.parents[2] / "release_automation" / "scripts" / "finalize.py").read_text(encoding="utf-8")

    for name in re.findall(r'_outputs\("plan"\)\.get\("([a-z_]+)"', source):
        assert name in jobs["plan"]["outputs"], name
    for job, name in re.findall(r'_json\("([a-z]+)", "([a-z_]+)"\)', source):
        assert name in jobs[job]["outputs"], (job, name)


def test_finalize_and_act_read_only_plan_document_keys():
    from release_automation.scripts.command_policy import CommonCache, Plan, plan_document
    from release_automation.scripts.trigger import Trigger

    document = plan_document(Plan("slash_command", "sync-issue", "r1.2", "planned", ""), Trigger(), {}, CommonCache(), {})
    scripts = WORKFLOW.parents[2] / "release_automation" / "scripts"
    finalize_reads = set(re.findall(r'\.plan\("([a-z_]+)"\)', (scripts / "finalize.py").read_text(encoding="utf-8")))
    act_reads = set(re.findall(r'plan\["([a-z_]+)"\]', (scripts / "act.py").read_text(encoding="utf-8")))

    assert finalize_reads and act_reads
    assert finalize_reads | act_reads <= set(document)


def test_snapshot_glue_runs_in_python_with_inputs_in_env():
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["snapshot"]["steps"]

    settings = _step_by_name(steps, "Validate central settings against schema")
    assert settings["run"].strip() == "python -m release_automation.scripts.snapshot_prep settings"
    gate = _step_by_name(steps, "Gate on validation result")
    assert gate["run"].strip() == "python -m release_automation.scripts.snapshot_prep gate"
    assert gate["env"]["VALIDATION_SUMMARY"] == "${{ steps.validation.outputs.summary }}"
    identity = _step_by_name(steps, "Resolve Bot Identity")
    assert identity["run"].strip() == "python -m release_automation.scripts.snapshot_prep bot-identity"
    assert identity["env"]["APP_TOKEN_USED"] == "${{ steps.app-token.outputs.token != '' }}"

    names = [step.get("name") for step in steps]
    assert names.index("Install dependencies") < names.index("Validate central settings against schema")
    assert names.index("Validate central settings against schema") < names.index("Run pre-snapshot validation")


def test_snapshot_run_bodies_hold_no_expressions():
    """Expressions are pre-expanded into a run body; the snapshot job passes them through env."""
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["snapshot"]["steps"]

    for step in steps:
        assert "${{" not in step.get("run", ""), step.get("name")
