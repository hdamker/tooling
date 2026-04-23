#!/usr/bin/env python3
"""
CAMARA Validation Framework — Release-Plan Dependency Resolver

Diffs release-plan.yaml between the PR base ref and the checked-out head,
detects which declared dependency tags changed, and probes the source repo
for tag existence.  Emits GitHub Actions step outputs consumed by the
run-validation shared action.

Outputs (written to the file at $GITHUB_OUTPUT, or --github-output):

    commonalities_release_changed   'true' | 'false'
    icm_release_changed             'true' | 'false'
    commonalities_tag_exists        'true' | 'false' | ''   (empty = skipped / lookup failed)
    icm_tag_exists                  'true' | 'false' | ''
    release_plan_check_only         'true' | 'false'

`release_plan_check_only` is 'true' only when commonalities_release advanced:
that is the dependency whose cached content (code/common/*) is stale under
the new ruleset, so the orchestrator suppresses the Spectral + gherkin
engines.  ICM has no common files to sync.

External commands: `git show origin/<base_ref>:<path>` and `gh api
/repos/<owner>/<repo>/git/ref/tags/<tag>`.  `gh` inherits GH_TOKEN /
GITHUB_TOKEN from the calling workflow.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "Error: pyyaml package is required. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Dependency table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dependency:
    field: str
    source_repo: str  # "owner/repo"
    changed_output: str
    tag_exists_output: str


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        field="commonalities_release",
        source_repo="camaraproject/Commonalities",
        changed_output="commonalities_release_changed",
        tag_exists_output="commonalities_tag_exists",
    ),
    Dependency(
        field="identity_consent_management_release",
        source_repo="camaraproject/IdentityAndConsentManagement",
        changed_output="icm_release_changed",
        tag_exists_output="icm_tag_exists",
    ),
)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _parse_plan(raw: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def read_plan_at_ref(base_ref: str, plan_path: str, *, git_bin: str = "git") -> dict[str, Any]:
    """Load release-plan.yaml at `origin/<base_ref>`; return {} when missing."""
    try:
        result = subprocess.run(
            [git_bin, "show", f"origin/{base_ref}:{plan_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {}
    if result.returncode != 0:
        return {}
    return _parse_plan(result.stdout)


def read_plan_at_path(plan_path: Path) -> dict[str, Any]:
    """Load release-plan.yaml from the workspace; return {} when missing."""
    try:
        raw = plan_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return _parse_plan(raw)


def get_dep(plan: dict[str, Any], field: str) -> str | None:
    deps = plan.get("dependencies") if isinstance(plan, dict) else None
    if not isinstance(deps, dict):
        return None
    value = deps.get(field)
    return value if isinstance(value, str) and value else None


# ---------------------------------------------------------------------------
# Tag lookup via gh
# ---------------------------------------------------------------------------


def tag_exists(owner: str, repo: str, tag: str, *, gh_bin: str = "gh") -> str:
    """Return 'true' / 'false' / '' — tri-state existence flag.

    'false' is only returned when the `gh` error is an authoritative 404.
    Any other failure (5xx, rate limit, auth, network) returns '' so P-023
    surfaces a warn-level finding rather than blocking validation.
    """
    try:
        result = subprocess.run(
            [
                gh_bin,
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"/repos/{owner}/{repo}/git/ref/tags/{tag}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        emit_warning(f"Tag lookup for {owner}/{repo}@{tag} skipped: gh not found")
        return ""

    if result.returncode == 0:
        return "true"

    combined = f"{result.stdout}\n{result.stderr}"
    if "HTTP 404" in combined or "Not Found" in combined:
        return "false"

    message = (result.stderr or result.stdout or "").strip().splitlines()
    detail = message[-1] if message else f"exit code {result.returncode}"
    emit_warning(f"Tag lookup for {owner}/{repo}@{tag} failed: {detail}")
    return ""


# ---------------------------------------------------------------------------
# GitHub Actions output + warning helpers
# ---------------------------------------------------------------------------


def write_outputs(outputs: dict[str, str], target: Path | None) -> None:
    if target is None:
        for key, value in outputs.items():
            print(f"{key}={value}")
        return
    with target.open("a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def emit_warning(message: str) -> None:
    print(f"::warning::{message}")


# ---------------------------------------------------------------------------
# Main resolution
# ---------------------------------------------------------------------------


def resolve(
    *,
    base_ref: str,
    plan_path: str,
    workspace_plan: Path,
    gh_bin: str = "gh",
    git_bin: str = "git",
) -> dict[str, str]:
    base_plan = read_plan_at_ref(base_ref, plan_path, git_bin=git_bin)
    head_plan = read_plan_at_path(workspace_plan)

    outputs: dict[str, str] = {}
    commonalities_changed = False

    for dep in DEPENDENCIES:
        base_tag = get_dep(base_plan, dep.field)
        head_tag = get_dep(head_plan, dep.field)
        changed = base_tag != head_tag
        outputs[dep.changed_output] = "true" if changed else "false"

        if changed and dep.field == "commonalities_release":
            commonalities_changed = True

        if changed and head_tag:
            owner, repo = dep.source_repo.split("/", 1)
            outputs[dep.tag_exists_output] = tag_exists(owner, repo, head_tag, gh_bin=gh_bin)
        else:
            outputs[dep.tag_exists_output] = ""

    outputs["release_plan_check_only"] = "true" if commonalities_changed else "false"
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="PR base ref (e.g. 'main').")
    parser.add_argument(
        "--plan-path",
        default="release-plan.yaml",
        help="Path to release-plan.yaml relative to the repo root.",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("GITHUB_WORKSPACE", "."),
        help="Path to the checked-out head workspace (default: $GITHUB_WORKSPACE).",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="Path to the GITHUB_OUTPUT file (default: $GITHUB_OUTPUT).",
    )
    parser.add_argument("--gh-bin", default="gh", help=argparse.SUPPRESS)
    parser.add_argument("--git-bin", default="git", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    outputs = resolve(
        base_ref=args.base_ref,
        plan_path=args.plan_path,
        workspace_plan=Path(args.workspace) / args.plan_path,
        gh_bin=args.gh_bin,
        git_bin=args.git_bin,
    )

    target = Path(args.github_output) if args.github_output else None
    write_outputs(outputs, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
