"""
Steps of the snapshot job around and including snapshot creation.

    settings       schema-validate the central validation settings before anything
                   irreversible happens
    gate           fail the job when pre-snapshot validation said it should
    bot-identity   commit identity for the create step
    create         the snapshot, release-review branch and Release PR of the
                   plan's release (snapshot_creator), from the plan document

Each prints GitHub annotations and exits non-zero on failure; gate,
bot-identity and create also write step outputs.

Usage (workflow steps):
    python3 -m release_automation.scripts.snapshot_prep <step>
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

import yaml

from .bot_identity import resolve_bot_identity
from .plan_document import PlanDocument
from .trigger import write_outputs

CREATE_OUTPUTS = (
    "success", "snapshot_id", "snapshot_branch", "release_review_branch",
    "release_pr_number", "release_pr_url", "error_message", "apis_json",
)


def validate_settings(config_path: Path, schema_path: Path) -> int:
    """Schema-validate the central validation settings; 0 when valid."""
    import yaml
    from jsonschema import Draft202012Validator

    if not config_path.exists():
        print(
            f"::error title=Validation settings missing::"
            f"{config_path} not present on tooling/main; "
            f"aborting before snapshot creation"
        )
        return 1
    if not schema_path.exists():
        print(
            f"::error title=Validation settings schema missing::"
            f"{schema_path} not present on the pinned tooling ref"
        )
        return 1

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    errors = list(Draft202012Validator(schema).iter_errors(config))
    if errors:
        for err in errors:
            loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"::error title=Validation settings invalid::{loc}: {err.message}")
        print(
            "::error::Aborting before snapshot creation — "
            "validation settings on tooling/main fail schema validation"
        )
        return 1

    print(f"Validation settings: {config_path} (main) — schema-valid")
    return 0


def gate_validation(summary: str, run_url: str, output_path: str) -> int:
    """Fail the job on a pre-snapshot validation failure, with the reason for the Release Issue."""
    print("::error::Pre-snapshot validation failed — fix issues on main before re-running /create-snapshot")
    write_outputs(output_path, {
        "success": "false",
        "error_message": f"Pre-snapshot validation failed: {summary}. [View workflow logs]({run_url})",
    })
    return 1


def _github_client(env: Mapping[str, str]):
    from .github_client import GitHubClient

    return GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN") or None)


def _create_outputs(output_path: str, **values: str) -> None:
    write_outputs(output_path, {name: values.get(name, "false" if name == "success" else "") for name in CREATE_OUTPUTS})


def create_snapshot(plan: PlanDocument, gh, tooling_root: Path, bot_name: str, bot_email: str, output_path: str,
                    dry_run: bool = False) -> int:
    """
    Create the snapshot of the plan's release: read release-plan.yaml from the
    base branch, run SnapshotCreator, write the step outputs. 0 on success.
    """
    from .mechanical_transformer import MechanicalTransformer
    from .metadata_generator import MetadataGenerator
    from .snapshot_creator import SnapshotConfig, SnapshotCreator
    from .version_calculator import VersionCalculator

    tag, base_branch = plan.release_tag, plan.base_branch
    print(f"Creating snapshot for {tag}")
    print(f"  Repository: {gh.repo}")
    print(f"  Base branch: {base_branch}")
    print(f"  Dry run: {dry_run}")

    content = gh.get_file_content("release-plan.yaml", ref=base_branch)
    if content is None:
        print(f"::error::release-plan.yaml not found on {base_branch}")
        _create_outputs(output_path, error_message="release-plan.yaml not found")
        return 1
    try:
        release_plan = yaml.safe_load(content)
    except yaml.YAMLError as e:
        print(f"::error::Failed to parse release-plan.yaml: {e}")
        _create_outputs(output_path, error_message=f"Invalid YAML: {e}")
        return 1
    if not isinstance(release_plan, dict):
        print("::error::release-plan.yaml is not a valid YAML mapping")
        _create_outputs(output_path, error_message="Invalid release-plan.yaml structure")
        return 1
    plan_tag = (release_plan.get("repository") or {}).get("target_release_tag", "")
    if plan_tag != tag:
        # The plan job read the same file moments ago; the plan's tag stays authoritative
        print(f"::warning::release-plan.yaml tag '{plan_tag}' doesn't match the plan's '{tag}'")

    creator = SnapshotCreator(
        github_client=gh,
        version_calculator=VersionCalculator(github_client=gh),
        transformer=MechanicalTransformer(config_path=str(tooling_root / "release_automation" / "config" / "transformations.yaml")),
        metadata_generator=MetadataGenerator(),
        bot_name=bot_name,
        bot_email=bot_email,
    )
    config = SnapshotConfig(
        release_tag=tag, base_branch=base_branch, dry_run=dry_run,
        release_issue_number=plan.release.release_issue_number,
    )
    print("Creating snapshot...")
    try:
        result = creator.create_snapshot(release_plan, config)
    except Exception as e:
        import traceback

        print(f"::error::Snapshot creation failed: {e}")
        traceback.print_exc()
        _create_outputs(output_path, error_message=str(e))
        return 1

    for note in result.notes:
        print(note)
    for warning in result.warnings:
        print(f"::warning::{warning}")
    if not result.success:
        error = "; ".join(result.errors) if result.errors else "Unknown error"
        print(f"::error::Snapshot creation failed: {error}")
        _create_outputs(
            output_path, success="false", snapshot_id=result.snapshot_id or "",
            snapshot_branch=result.snapshot_branch or "", error_message=error,
        )
        return 1

    print("Snapshot created successfully!")
    print(f"  Snapshot ID: {result.snapshot_id}")
    print(f"  Snapshot branch: {result.snapshot_branch}")
    print(f"  Release PR: #{result.release_pr_number}")
    print(f"  PR URL: {result.release_pr_url}")
    for api_name, version in result.api_versions.items():
        print(f"  {api_name}: {version}")
    apis: List[Dict[str, str]] = [{"api_name": n, "api_version": v} for n, v in result.api_versions.items()]
    _create_outputs(
        output_path, success="true", snapshot_id=result.snapshot_id or "",
        snapshot_branch=result.snapshot_branch or "", release_review_branch=result.release_review_branch or "",
        release_pr_number=str(result.release_pr_number) if result.release_pr_number else "",
        release_pr_url=result.release_pr_url or "", apis_json=json.dumps(apis),
    )
    return 0


def main(argv: List[str], env: Optional[Mapping[str, str]] = None) -> int:
    env = os.environ if env is None else env
    step = argv[0] if len(argv) == 1 else ""

    if step == "settings":
        return validate_settings(Path(env["SETTINGS_PATH"]), Path(env["SCHEMA_PATH"]))

    if step == "gate":
        run_url = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
        return gate_validation(env.get("VALIDATION_SUMMARY", ""), run_url, env["GITHUB_OUTPUT"])

    if step == "bot-identity":
        try:
            name, email = resolve_bot_identity(
                _github_client(env), env.get("RELEASE_APP_SLUG", ""), env.get("APP_TOKEN_USED") == "true"
            )
        except Exception as e:
            print(f"::error::Could not resolve the bot identity: {e}")
            return 1
        print(f"Committing as: {name} <{email}>")
        write_outputs(env["GITHUB_OUTPUT"], {"bot_name": name, "bot_email": email})
        return 0

    if step == "create":
        tooling_root = Path(env["TOOLING_PATH"])
        # redocly from validation/node_modules/.bin: one validation/package.json pin
        # governs PR-time bundling and snapshot bundling
        os.environ["PATH"] = str(tooling_root / "validation" / "node_modules" / ".bin") + os.pathsep + os.environ.get("PATH", "")
        return create_snapshot(
            PlanDocument.from_json(env["PLAN_JSON"]), _github_client(env), tooling_root,
            env.get("BOT_NAME") or "github-actions[bot]",
            env.get("BOT_EMAIL") or "41898282+github-actions[bot]@users.noreply.github.com",
            env["GITHUB_OUTPUT"], dry_run=env.get("DRY_RUN", "false").lower() == "true",
        )

    raise SystemExit("usage: snapshot_prep settings|gate|bot-identity|create")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
