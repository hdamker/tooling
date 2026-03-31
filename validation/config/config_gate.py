"""Central config gate for the CAMARA validation framework.

Reads validation-config.yaml, validates it against its JSON Schema,
and resolves the effective rollout stage for a given repository.

Design doc references:
  - Section 6.2: central config schema
  - Section 8.1 steps 1-7: config gate logic
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml
from jsonschema import Draft202012Validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Upstream GitHub org names.  Repos owned by these orgs are "upstream";
# all others are forks.
UPSTREAM_ORGS = frozenset({"camaraproject", "GSMA-Open-Gateway"})

STAGE_DISABLED = "disabled"
STAGE_ADVISORY = "advisory"
STAGE_ENABLED = "enabled"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Raised when validation-config.yaml fails schema validation."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        summary = "; ".join(errors[:3])
        if len(errors) > 3:
            summary += f" (and {len(errors) - 3} more)"
        super().__init__(f"Invalid validation config: {summary}")


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageGateResult:
    """Result of stage gate resolution.

    Attributes:
        stage: The resolved stage (disabled, advisory, standard).
        should_continue: Whether the validation pipeline should proceed.
        reason: Human-readable explanation when should_continue is False.
        is_fork: Whether the workflow is running in a fork.
        fork_override_applied: Whether the fork owner override changed the stage.
    """

    stage: str
    should_continue: bool
    reason: str = ""
    is_fork: bool = False
    fork_override_applied: bool = False
    pr_profile: str = "standard"
    release_profile: str = "standard"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_and_validate_config(
    config_path: Path, schema_path: Path
) -> dict:
    """Load validation-config.yaml and validate against its JSON Schema.

    Args:
        config_path: Path to validation-config.yaml.
        schema_path: Path to validation-config-schema.yaml.

    Returns:
        Parsed and validated config dict.

    Raises:
        ConfigValidationError: If the config fails schema validation.
        FileNotFoundError: If either file does not exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config_data is None:
        raise ConfigValidationError(["Config file is empty"])

    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = []
    for error in validator.iter_errors(config_data):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")

    if errors:
        raise ConfigValidationError(errors)

    return config_data


# ---------------------------------------------------------------------------
# Stage resolution
# ---------------------------------------------------------------------------


def resolve_stage(
    config: dict,
    repo_full_name: str,
    repo_owner: str,
    trigger_type: str,
) -> StageGateResult:
    """Resolve the effective rollout stage for a repository.

    Pure function — no I/O.  Implements design doc section 8.1, steps 2-7.

    Args:
        config: Validated config dict (output of load_and_validate_config).
        repo_full_name: Full GitHub repository name (e.g. "camaraproject/QoD").
        repo_owner: GitHub repository owner (e.g. "camaraproject").
        trigger_type: Raw GitHub event name (e.g. "pull_request",
            "workflow_dispatch").

    Returns:
        StageGateResult with the resolved stage and gate decision.
    """
    # Step 2: extract repo name (strip owner prefix)
    repo_name = repo_full_name.split("/", 1)[-1]

    # Step 3: look up stage (fall back to defaults.stage)
    repositories = config.get("repositories") or {}
    repo_entry = repositories.get(repo_name)
    stage = repo_entry["stage"] if repo_entry else config["defaults"]["stage"]

    # Step 4: fork override
    is_fork = repo_owner not in UPSTREAM_ORGS
    fork_override_applied = False

    if is_fork:
        fork_owners = config.get("fork_owners") or []
        if repo_owner in fork_owners:
            stage = STAGE_ENABLED
            fork_override_applied = True

    # Resolve profiles from config
    defaults = config.get("defaults") or {}
    if fork_override_applied:
        pr_profile = "standard"
        release_profile = "standard"
    else:
        pr_profile = (
            (repo_entry or {}).get("pr_profile")
            or defaults.get("pr_profile")
            or "standard"
        )
        release_profile = (
            (repo_entry or {}).get("release_profile")
            or defaults.get("release_profile")
            or "standard"
        )

    # Steps 5-7: gate decisions
    if stage == STAGE_DISABLED:
        return StageGateResult(
            stage=stage,
            should_continue=False,
            reason="Validation is not enabled for this repository",
            is_fork=is_fork,
            fork_override_applied=fork_override_applied,
            pr_profile=pr_profile,
            release_profile=release_profile,
        )

    if stage == STAGE_ADVISORY and trigger_type == "pull_request":
        return StageGateResult(
            stage=stage,
            should_continue=False,
            reason=(
                "Validation is in advisory mode "
                "\u2014 use workflow_dispatch to run"
            ),
            is_fork=is_fork,
            fork_override_applied=fork_override_applied,
            pr_profile=pr_profile,
            release_profile=release_profile,
        )

    return StageGateResult(
        stage=stage,
        should_continue=True,
        is_fork=is_fork,
        fork_override_applied=fork_override_applied,
        pr_profile=pr_profile,
        release_profile=release_profile,
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def resolve_stage_from_files(
    config_path: Path,
    schema_path: Path,
    repo_full_name: str,
    repo_owner: str,
    trigger_type: str,
) -> StageGateResult:
    """Load config, validate, and resolve stage in one call.

    Composes load_and_validate_config() + resolve_stage().
    """
    config = load_and_validate_config(config_path, schema_path)
    return resolve_stage(config, repo_full_name, repo_owner, trigger_type)
