"""Static checks for release automation workflow wiring."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from release_automation.scripts.commands import COMMANDS


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


def test_plan_acks_before_checkout_then_resolves_the_trigger():
    steps = _job_steps("plan")
    names = [step.get("name") for step in steps]

    assert names.index("Post Acknowledgment") < names.index("Checkout tooling")
    assert names.index("Checkout tooling") < names.index("Resolve trigger and release line")

    resolve = _step_by_name(steps, "Resolve trigger and release line")
    assert resolve["id"] == "resolve"
    assert resolve["working-directory"] == "_tooling"
    assert resolve["run"].strip() == "python -m release_automation.scripts.release_line"
    assert "uses" not in resolve


def test_ack_command_list_matches_the_commands_table():
    ack = _step_by_name(_job_steps("plan"), "Post Acknowledgment")
    script = ack["with"]["script"]

    match = re.search(r"body\.match\(/\^\\/\(([a-z|-]+)\)", script)
    assert match, "ack command regex not found"
    assert sorted(match.group(1).split("|")) == sorted(c.name for c in COMMANDS)
    # The ack reads the payload directly; it must not depend on later steps.
    assert "steps." not in script


def test_plan_is_resolve_then_plan():
    # 107 D3: state is derived once, in the Plan step, in Python; no composite actions in plan
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan = workflow["jobs"]["plan"]
    names = [step.get("name") for step in plan["steps"]]

    order = ["Resolve trigger and release line", "Checkout API repo (sparse, for cache sync check)", "Plan"]
    assert [n for n in names if n in order] == order
    assert not [s for s in plan["steps"] if str(s.get("uses", "")).startswith("./_tooling/shared-actions")]
    for gone in ("Derive Release State", "Check common cache sync", "Assemble Context", "Apply Command Policy",
                 "Post Response", "Fail workflow (dispatch action refused)",
                 "Fail workflow (config error on a non-slash-command trigger)"):
        assert gone not in names, gone

    step = _step_by_name(plan["steps"], "Plan")
    assert step["id"] == "plan"
    assert step["run"].strip() == "python -m release_automation.scripts.command_policy"
    assert step["env"]["TRIGGER_JSON"] == "${{ steps.resolve.outputs.trigger }}"
    assert step["env"]["BASE_BRANCH"] == "${{ steps.resolve.outputs.base_branch }}"
    assert step["env"]["API_REPO_PATH"] == "${{ github.workspace }}/_api_repo"
    assert step["env"]["ACK_COMMENT_ID"] == "${{ steps.ack.outputs.comment_id }}"
    assert step["if"] == "steps.resolve.outputs.should_continue == 'true'"
    assert plan["outputs"] == {
        "plan": "${{ steps.plan.outputs.plan }}",
        "action": "${{ steps.plan.outputs.action }}",
        "finalize": "${{ steps.plan.outputs.finalize }}",
        "result_comment_id": "${{ steps.plan.outputs.result_comment_id }}",
    }

    # The ack is the only inline script left in plan.
    scripts = [s for s in plan["steps"] if str(s.get("uses", "")).startswith("actions/github-script")]
    assert [s["name"] for s in scripts] == ["Post Acknowledgment"]
    # No shell logic left in plan besides the fork guard
    assert [s["name"] for s in plan["steps"] if "run" in s and "python" not in s["run"] and "pip" not in s["run"]] == [
        "Fork Guard - Check Issues Enabled"
    ]


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


def test_finalize_and_act_read_the_typed_plan_document():
    # F11: the plan travels as PlanDocument JSON; no string-key reads of it anywhere after plan
    scripts = WORKFLOW.parents[2] / "release_automation" / "scripts"
    for name in ("finalize.py", "act.py"):
        source = (scripts / name).read_text(encoding="utf-8")
        assert "PlanDocument" in source, name
        assert not re.search(r'plan\["|\.plan\("', source), name
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    # The workflow reads one field of the document (the checkout ref); the steps take the document
    text = WORKFLOW.read_text(encoding="utf-8")
    assert set(re.findall(r"fromJSON\(needs\.plan\.outputs\.plan\)\.([a-z_.]+)", text)) == {"base_branch"}
    assert jobs["act"]["steps"][-1]["env"]["PLAN_JSON"] == "${{ needs.plan.outputs.plan }}"
    create = _step_by_name(jobs["snapshot"]["steps"], "Create Snapshot")
    assert create["env"]["PLAN_JSON"] == "${{ needs.plan.outputs.plan }}"


def test_snapshot_creation_is_a_module_step_on_the_plan():
    # 107 D3: the create-snapshot composite is gone; the step takes the plan document
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["snapshot"]["steps"]
    create = _step_by_name(steps, "Create Snapshot")

    assert create["id"] == "create"
    assert create["run"].strip() == "python -m release_automation.scripts.snapshot_prep create"
    assert create["env"]["GITHUB_TOKEN"] == "${{ steps.app-token.outputs.token || github.token }}"
    assert create["env"]["TOOLING_PATH"] == "${{ github.workspace }}/_tooling"
    assert create["env"]["BOT_NAME"] == "${{ steps.bot-identity.outputs.bot_name }}"
    assert not [s for s in steps if str(s.get("uses", "")).startswith("./_tooling/shared-actions/create-snapshot")]
    assert not (ROOT / "shared-actions" / "create-snapshot").exists()


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


def test_plan_run_bodies_hold_no_expressions():
    """Expressions are pre-expanded into a run body; the plan job passes them through env."""
    for step in _job_steps("plan"):
        if step.get("name") != "Fork Guard - Check Issues Enabled":
            assert "${{" not in step.get("run", ""), step.get("name")


# ── caller templates (maintenance releases, 003 M5) ──────────────────────────

ROOT = Path(__file__).resolve().parents[2]
RA_CALLER = ROOT / "release_automation" / "workflows" / "release-automation-caller.yml"
VF_CALLER = ROOT / "validation" / "workflows" / "validation-caller.yml"
VF_WORKFLOW = ROOT / ".github" / "workflows" / "validation.yml"


def _on(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True
    return workflow.get("on", workflow.get(True))


def test_ra_caller_runs_on_pushes_to_main_and_maintenance_branches():
    on = _on(yaml.safe_load(RA_CALLER.read_text(encoding="utf-8")))

    assert on["push"]["branches"] == ["main", "maintenance/**"]
    assert ".github/workflows/release-automation.yml" in on["push"]["paths"]


def test_ra_caller_dispatch_inputs_match_the_trigger_module():
    from release_automation.scripts.trigger import DISPATCH_ACTIONS, DISPATCH_SYNC_ISSUE

    inputs = _on(yaml.safe_load(RA_CALLER.read_text(encoding="utf-8")))["workflow_dispatch"]["inputs"]

    assert inputs["action"]["type"] == "choice"
    assert tuple(inputs["action"]["options"]) == DISPATCH_ACTIONS
    assert inputs["action"]["default"] == DISPATCH_SYNC_ISSUE
    assert inputs["cycle"]["type"] == "string" and inputs["cycle"]["required"] is False


def test_callers_need_no_oidc_token_and_stay_on_v1_rc():
    ra = yaml.safe_load(RA_CALLER.read_text(encoding="utf-8"))
    vf = yaml.safe_load(VF_CALLER.read_text(encoding="utf-8"))

    for caller, workflow in ((ra, "release-automation-reusable.yml"), (vf, "validation.yml")):
        assert "id-token" not in caller["permissions"]
        (job,) = caller["jobs"].values()
        assert job["uses"] == f"camaraproject/tooling/.github/workflows/{workflow}@v1-rc"
        assert "with" not in job
    assert _on(vf)["pull_request"]["branches"] == ["main", "release-snapshot/**", "maintenance/**"]


RA_BOT = "camara-release-automation[bot]"


def test_ra_caller_command_list_matches_the_commands_table():
    condition = yaml.safe_load(RA_CALLER.read_text(encoding="utf-8"))["jobs"]["release-automation"]["if"]

    names = re.findall(r"startsWith\(github\.event\.comment\.body, '/([a-z-]+)'\)", condition)
    assert sorted(names) == sorted(c.name for c in COMMANDS)


def test_ra_caller_serializes_at_job_level():
    # spec 5.7: runs skipped by the job's if: never join the concurrency group
    ra = yaml.safe_load(RA_CALLER.read_text(encoding="utf-8"))

    assert "concurrency" not in ra
    assert ra["jobs"]["release-automation"]["concurrency"] == {
        "group": "release-automation-${{ github.repository }}",
        "cancel-in-progress": False,
    }


def test_ra_caller_skips_comments_and_issue_events_of_the_ra_bot():
    condition = yaml.safe_load(RA_CALLER.read_text(encoding="utf-8"))["jobs"]["release-automation"]["if"]

    assert f"github.event.comment.user.login != '{RA_BOT}'" in condition
    issues_clause = condition[condition.index("github.event_name == 'issues'"):]
    assert issues_clause.index(f"github.event.sender.login != '{RA_BOT}'") < issues_clause.index("pull_request")


def test_release_issue_writes_use_github_token():
    # spec 5.7: the App token stays for branches, commits, PRs and releases
    plan = _job_steps("plan")
    assert "Generate App Token" not in [s.get("name") for s in plan]
    assert _step_by_name(plan, "Plan")["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert _step_by_name(plan, "Resolve trigger and release line")["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    for job in ("act", "finalize"):
        (step,) = [s for s in _job_steps(job) if "release_automation.scripts" in s.get("run", "")]
        assert step["env"]["GITHUB_TOKEN"] == "${{ steps.app-token.outputs.token || github.token }}"
        assert step["env"]["ISSUE_TOKEN"] == "${{ github.token }}"


def test_validation_checks_tooling_out_at_its_own_commit():
    text = VF_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    steps = workflow["jobs"]["validate"]["steps"]

    checkout = _step_by_name(steps, "Checkout tooling")
    assert checkout["with"]["repository"] == "${{ job.workflow_repository }}"
    assert checkout["with"]["ref"] == "${{ job.workflow_sha }}"
    assert checkout["with"]["path"] == ".tooling"
    assert _step_by_name(steps, "Run validation")["with"]["tooling_ref"] == "${{ job.workflow_sha }}"
    for token in ("getIDToken", "tooling_ref_override", "ALLOWED_TOOLING_REFS", "resolve-ref", "v1-rc"):
        assert token not in text, token
    assert "id-token" not in workflow["permissions"]
    assert "tooling_ref_override" not in _on(workflow)["workflow_call"]["inputs"]


def test_cache_detection_uses_the_base_branch():
    # M10: detection on the base branch's checkout (in the Plan step), sync PR looked up within the line
    steps = _job_steps("plan")
    checkout = _step_by_name(steps, "Checkout API repo (sparse, for cache sync check)")

    assert checkout["with"]["ref"] == "${{ steps.resolve.outputs.base_branch }}"
    assert checkout["with"]["path"] == "_api_repo"
    assert checkout["if"] == "steps.resolve.outputs.should_continue == 'true'"


def test_validation_resolves_the_release_state_with_the_module():
    # The derive-release-state composite is gone; validation.yml (P-033) calls the module
    steps = yaml.safe_load(VF_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate"]["steps"]
    step = _step_by_name(steps, "Resolve active release state")

    assert step["id"] == "derive-release-state"
    assert step["working-directory"] == ".tooling"
    assert step["run"].strip() == "python -m release_automation.scripts.state_manager"
    assert step["env"]["BASE_BRANCH"] == "${{ startsWith(github.base_ref, 'maintenance/r') && github.base_ref || 'main' }}"
    assert not (ROOT / "shared-actions" / "derive-release-state").exists()
    assert not (ROOT / "shared-actions" / "post-bot-comment").exists()
