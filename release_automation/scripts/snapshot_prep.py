"""
Glue steps of the snapshot job around pre-snapshot validation.

    settings       schema-validate the central validation settings before anything
                   irreversible happens
    gate           fail the job when pre-snapshot validation said it should
    bot-identity   commit identity for the Create Snapshot step

Each prints GitHub annotations and exits non-zero on failure; gate and
bot-identity also write step outputs.

Usage (workflow steps):
    python3 -m release_automation.scripts.snapshot_prep <step>
"""

import os
import sys
from pathlib import Path
from typing import List, Mapping, Optional

from .bot_identity import resolve_bot_identity
from .trigger import write_outputs


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

    raise SystemExit("usage: snapshot_prep settings|gate|bot-identity")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
