"""CAMARA validation framework orchestrator.

Chains the full validation pipeline:

    config gate -> context builder -> engines -> post-filter -> output

Invoked once from the reusable workflow as ``python -m validation.orchestrator``.
All inputs arrive via ``VALIDATION_*`` environment variables set by the workflow.
Output files are written to ``$VALIDATION_OUTPUT_DIR`` for the workflow to read
and post to GitHub surfaces (annotations, PR comments, commit status, artifacts).

No GitHub API calls are made from Python — this keeps the orchestrator
independently testable.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from validation.config.config_gate import StageGateResult, resolve_stage_from_files
from validation.context import ValidationContext, build_validation_context
from validation.engines import (
    run_gherkin_engine,
    run_python_engine,
    run_spectral_engine,
    run_yamllint_engine,
)
from validation.output import (
    generate_annotations,
    generate_commit_status,
    generate_pr_comment,
    generate_workflow_summary,
    write_diagnostics,
)
from validation.postfilter.engine import PostFilterResult, run_post_filter

# ---------------------------------------------------------------------------
# Logging — structured output so workflow logs are readable
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("validation.orchestrator")

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INFRA_ERROR = 2


# ---------------------------------------------------------------------------
# Environment parsing
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OrchestratorArgs:
    """Parsed orchestrator inputs."""

    repo_path: Path
    tooling_path: Path
    output_dir: Path

    repo_name: str  # e.g. "camaraproject/QualityOnDemand"
    repo_owner: str  # e.g. "camaraproject"
    event_name: str  # e.g. "pull_request", "workflow_dispatch"
    ref_name: str  # checked-out branch
    base_ref: str  # PR target branch (empty for non-PR)

    mode: str  # "" or "pre-snapshot"
    profile: str  # "" or "advisory"/"standard"/"strict"
    pr_number: Optional[int]
    release_plan_changed: Optional[bool]

    workflow_run_url: str
    tooling_ref: str
    commit_sha: str


def _env(name: str, default: str = "") -> str:
    """Read a VALIDATION_* environment variable."""
    return os.environ.get(f"VALIDATION_{name}", default)


def _env_optional_int(name: str) -> Optional[int]:
    """Read an env var as optional int."""
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_optional_bool(name: str) -> Optional[bool]:
    """Read an env var as optional bool."""
    raw = _env(name).lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return None


def parse_args() -> OrchestratorArgs:
    """Parse all inputs from VALIDATION_* environment variables."""
    return OrchestratorArgs(
        repo_path=Path(_env("REPO_PATH", ".")),
        tooling_path=Path(_env("TOOLING_PATH", ".tooling")),
        output_dir=Path(_env("OUTPUT_DIR", "validation-output")),
        repo_name=_env("REPO_NAME"),
        repo_owner=_env("REPO_OWNER"),
        event_name=_env("EVENT_NAME"),
        ref_name=_env("REF_NAME"),
        base_ref=_env("BASE_REF"),
        mode=_env("MODE"),
        profile=_env("PROFILE"),
        pr_number=_env_optional_int("PR_NUMBER"),
        release_plan_changed=_env_optional_bool("RELEASE_PLAN_CHANGED"),
        workflow_run_url=_env("WORKFLOW_RUN_URL"),
        tooling_ref=_env("TOOLING_REF"),
        commit_sha=_env("COMMIT_SHA"),
    )


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ToolingPaths:
    """Resolved paths within the tooling checkout."""

    config_file: Path
    config_schema: Path
    release_plan_schema: Path
    linting_config_dir: Path
    rules_dir: Path


def resolve_tooling_paths(tooling_path: Path) -> ToolingPaths:
    """Build all paths relative to the tooling checkout."""
    return ToolingPaths(
        config_file=tooling_path / "validation" / "config" / "validation-config.yaml",
        config_schema=tooling_path / "validation" / "schemas" / "validation-config-schema.yaml",
        release_plan_schema=tooling_path / "validation" / "schemas" / "release-plan-schema.yaml",
        linting_config_dir=tooling_path / "linting" / "config",
        rules_dir=tooling_path / "validation" / "rules",
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_spec_files(repo_path: Path) -> List[Path]:
    """Find OpenAPI spec files under ``code/API_definitions/``."""
    return sorted(repo_path.glob("code/API_definitions/*.yaml"))


def discover_test_files(repo_path: Path) -> List[Path]:
    """Find Gherkin test files under ``code/Test_definitions/``."""
    return sorted(repo_path.glob("code/Test_definitions/**/*.feature"))


# ---------------------------------------------------------------------------
# Engine orchestration
# ---------------------------------------------------------------------------


def run_engines(
    repo_path: Path,
    paths: ToolingPaths,
    context: Any,  # ValidationContext
    test_files: List[Path],
) -> Tuple[List[dict], Dict[str, str]]:
    """Run all validation engines and collect findings.

    Returns:
        Tuple of (all_findings, engine_statuses).
    """
    all_findings: List[dict] = []
    engine_statuses: Dict[str, str] = {}
    is_release_review = getattr(context, "is_release_review_pr", False)

    # --- yamllint ---
    if is_release_review:
        engine_statuses["yamllint"] = "skipped (release review PR)"
        logger.info("yamllint: skipped (release review PR)")
    else:
        try:
            yamllint_config = paths.linting_config_dir / ".yamllint.yaml"
            findings = run_yamllint_engine(
                repo_path=repo_path,
                config_path=yamllint_config,
            )
            all_findings.extend(findings)
            engine_statuses["yamllint"] = f"{len(findings)} finding(s)"
            logger.info("yamllint: %d finding(s)", len(findings))
        except Exception as exc:
            engine_statuses["yamllint"] = f"error: {exc}"
            logger.error("yamllint failed: %s", exc)

    # --- Spectral ---
    if is_release_review:
        engine_statuses["spectral"] = "skipped (release review PR)"
        logger.info("Spectral: skipped (release review PR)")
    else:
        try:
            commonalities_release = getattr(context, "commonalities_release", None)
            findings = run_spectral_engine(
                repo_path=repo_path,
                config_dir=paths.linting_config_dir,
                commonalities_release=commonalities_release,
            )
            all_findings.extend(findings)
            engine_statuses["spectral"] = f"{len(findings)} finding(s)"
            logger.info("Spectral: %d finding(s)", len(findings))
        except Exception as exc:
            engine_statuses["spectral"] = f"error: {exc}"
            logger.error("Spectral failed: %s", exc)

    # --- Python checks ---
    try:
        findings = run_python_engine(
            repo_path=repo_path,
            context=context,
        )
        all_findings.extend(findings)
        engine_statuses["python"] = f"{len(findings)} finding(s)"
        logger.info("Python checks: %d finding(s)", len(findings))
    except Exception as exc:
        engine_statuses["python"] = f"error: {exc}"
        logger.error("Python checks failed: %s", exc)

    # --- gherkin-lint ---
    if not test_files:
        engine_statuses["gherkin"] = "skipped (no test files)"
        logger.info("gherkin-lint: skipped (no test files)")
    else:
        try:
            gherkin_config = paths.linting_config_dir / ".gherkin-lintrc"
            findings = run_gherkin_engine(
                repo_path=repo_path,
                config_path=gherkin_config,
            )
            all_findings.extend(findings)
            engine_statuses["gherkin"] = f"{len(findings)} finding(s)"
            logger.info("gherkin-lint: %d finding(s)", len(findings))
        except Exception as exc:
            engine_statuses["gherkin"] = f"error: {exc}"
            logger.error("gherkin-lint failed: %s", exc)

    # --- Bundling ---
    # Spectral resolves external $ref natively (DEC-021), so bundling is not
    # a validation prerequisite.  Bundled standalone specs are produced by a
    # separate workflow step for artifact upload and release automation handoff.
    engine_statuses["bundling"] = "separate workflow step"

    return all_findings, engine_statuses


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_result_json(output_dir: Path, result: str, summary: str) -> None:
    """Write result.json with overall verdict and should_fail flag."""
    payload = {
        "result": result,
        "summary": summary,
        "should_fail": result in ("fail", "error"),
    }
    (output_dir / "result.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )


def write_skip_output(output_dir: Path, reason: str) -> None:
    """Write minimal output files for a skipped run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # Summary
    (output_dir / "summary.md").write_text(
        f"## CAMARA Validation\n\n{reason}\n"
    )
    # Result
    write_result_json(output_dir, "skipped", reason)
    logger.info("Skipped: %s", reason)


def write_outputs(
    post_filter_result: Any,  # PostFilterResult
    context: Any,  # ValidationContext
    output_dir: Path,
    engine_statuses: Dict[str, str],
    commit_sha: str,
) -> None:
    """Write all output files for the workflow to consume."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Annotations ---
    annotation_result = generate_annotations(post_filter_result)
    if annotation_result.commands:
        (output_dir / "annotations.txt").write_text(
            "\n".join(annotation_result.commands) + "\n"
        )
    logger.info(
        "Annotations: %d emitted (of %d total, truncated=%s)",
        annotation_result.annotations_emitted,
        annotation_result.total_findings,
        annotation_result.truncated,
    )

    # --- Workflow summary ---
    summary_result = generate_workflow_summary(
        post_filter_result,
        context,
        engine_statuses=engine_statuses,
        commit_sha=commit_sha,
    )
    (output_dir / "summary.md").write_text(summary_result.markdown)
    if summary_result.truncated:
        logger.info("Summary truncated: %s", summary_result.truncation_note)

    # --- PR comment ---
    pr_comment = generate_pr_comment(post_filter_result, context)
    (output_dir / "pr-comment.md").write_text(pr_comment)

    # --- Commit status ---
    status_payload = generate_commit_status(post_filter_result, context)
    (output_dir / "commit-status.json").write_text(
        json.dumps(dataclasses.asdict(status_payload), indent=2) + "\n"
    )

    # --- Diagnostics ---
    diagnostics_dir = output_dir / "diagnostics"
    write_diagnostics(
        post_filter_result,
        context,
        diagnostics_dir,
        engine_reports=engine_statuses,
    )

    # --- Result ---
    write_result_json(
        output_dir,
        post_filter_result.result,
        post_filter_result.summary,
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the full validation pipeline.

    Returns:
        Exit code: 0 on success (even when validation fails), 2 on
        infrastructure error.
    """
    args = parse_args()
    logger.info(
        "Starting validation: repo=%s event=%s ref=%s",
        args.repo_name,
        args.event_name,
        args.ref_name,
    )

    # Resolve tooling paths
    paths = resolve_tooling_paths(args.tooling_path)

    # ------------------------------------------------------------------
    # Step 1: Config gate
    # ------------------------------------------------------------------
    stage_result = resolve_stage_from_files(
        config_path=paths.config_file,
        schema_path=paths.config_schema,
        repo_full_name=args.repo_name,
        repo_owner=args.repo_owner,
        trigger_type=args.event_name,
    )
    logger.info(
        "Config gate: stage=%s continue=%s fork=%s override=%s",
        stage_result.stage,
        stage_result.should_continue,
        stage_result.is_fork,
        stage_result.fork_override_applied,
    )
    if not stage_result.should_continue:
        write_skip_output(args.output_dir, stage_result.reason)
        return EXIT_OK

    # ------------------------------------------------------------------
    # Step 2: Build validation context
    # ------------------------------------------------------------------
    context = build_validation_context(
        repo_name=args.repo_name,
        event_name=args.event_name,
        ref_name=args.ref_name,
        base_ref=args.base_ref,
        mode=args.mode,
        profile_override=args.profile,
        stage=stage_result.stage,
        pr_number=args.pr_number,
        release_plan_changed=args.release_plan_changed,
        repo_path=args.repo_path,
        release_plan_schema_path=paths.release_plan_schema,
        workflow_run_url=args.workflow_run_url,
        tooling_ref=args.tooling_ref,
    )
    logger.info(
        "Context: branch=%s trigger=%s profile=%s release_review=%s apis=%d",
        context.branch_type,
        context.trigger_type,
        context.profile,
        context.is_release_review_pr,
        len(context.apis),
    )

    # ------------------------------------------------------------------
    # Step 3: Discover files
    # ------------------------------------------------------------------
    spec_files = discover_spec_files(args.repo_path)
    test_files = discover_test_files(args.repo_path)
    logger.info(
        "Files: %d spec(s), %d test(s)",
        len(spec_files),
        len(test_files),
    )

    # ------------------------------------------------------------------
    # Step 4: Run engines
    # ------------------------------------------------------------------
    all_findings, engine_statuses = run_engines(
        repo_path=args.repo_path,
        paths=paths,
        context=context,
        test_files=test_files,
    )
    logger.info("Total raw findings: %d", len(all_findings))

    # ------------------------------------------------------------------
    # Step 5: Post-filter
    # ------------------------------------------------------------------
    post_filter_result = run_post_filter(
        findings=all_findings,
        context=context,
        rules_dir=paths.rules_dir,
    )
    logger.info(
        "Post-filter: result=%s, %d finding(s) after filter",
        post_filter_result.result,
        len(post_filter_result.findings),
    )

    # ------------------------------------------------------------------
    # Step 6: Write outputs
    # ------------------------------------------------------------------
    write_outputs(
        post_filter_result=post_filter_result,
        context=context,
        output_dir=args.output_dir,
        engine_statuses=engine_statuses,
        commit_sha=args.commit_sha,
    )
    logger.info("Output written to %s", args.output_dir)

    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("Orchestrator infrastructure error")
        sys.exit(EXIT_INFRA_ERROR)
