"""
Maintenance branch creation for CAMARA release automation.

A codeowner dispatches create-maintenance-branch with a cycle rX once main
has moved on to a later cycle. check() decides in the plan job whether the
branch may be created and from which release; create() runs in the act job
with the App token, which bypasses the maintenance-branch-protection ruleset:

1. maintenance/rX at the src_commit_sha of the patched release (the newest
   public or maintenance release of the cycle), from its release-metadata.yaml
2. one direct commit onto it: main's caller workflows, the cycle's CHANGELOG
   from the patched release's tag (the source commit lacks that release's own
   section) and release-plan.yaml parked at rX.(N+1) with
   target_release_type none, API entries as in the patched release

No plan PR: the codeowner's first PR into the branch plans the release, as
on main, and its merge creates the line's Release Issue.
"""

import re
from dataclasses import dataclass
from typing import Union

import yaml

from . import config
from .github_client import GitHubClientError
from .release_line import MAINTENANCE_BRANCH_PREFIX, tag_version

CALLER_WORKFLOWS = (
    ".github/workflows/release-automation.yml",
    ".github/workflows/camara-validation.yml",
)
CYCLE_RE = re.compile(r"^r([1-9]\d*)$")


@dataclass(frozen=True)
class BranchPlan:
    """What create() does: the branch, the release it starts from, the tag it plans."""
    cycle: str
    branch: str
    patched_release: str
    patched_sha: str
    next_tag: str


@dataclass(frozen=True)
class CreateResult:
    """Outcome of create(); branch and setup_commit_sha are set once the branch exists."""
    success: bool
    branch: str = ""
    setup_commit_sha: str = ""
    warning: str = ""
    error_message: str = ""


def check(gh, cycle: str, main_release_tag: str) -> Union[BranchPlan, str]:
    """
    The branch plan for a cycle, or why the branch is not created.

    Args:
        gh: GitHub client of the API repository
        cycle: The dispatch input, e.g. "r1"
        main_release_tag: target_release_tag of main's release-plan.yaml

    Returns:
        BranchPlan, or the refusal message
    """
    match = CYCLE_RE.match(cycle or "")
    if not match:
        return f"The cycle must name a release cycle, e.g. r1 (got '{cycle}')."
    number = int(match.group(1))
    branch = f"{MAINTENANCE_BRANCH_PREFIX}{cycle}"

    releases = sorted(
        (r for r in gh.get_releases(include_drafts=False) if (tag_version(r.tag_name) or (0,))[0] == number),
        key=lambda r: tag_version(r.tag_name),
        reverse=True,
    )
    if not any(not r.prerelease for r in releases):
        return f"Cycle {cycle} has no public release to maintain."
    if gh.get_branch_sha(branch):
        return f"{branch} already exists."
    main_version = tag_version(main_release_tag)
    if not main_version or main_version[0] <= number:
        return (
            f"main has not left cycle {cycle}: {config.RELEASE_PLAN_FILE} on main targets "
            f"{main_release_tag or 'no tag'}. Plan a tag of a later cycle on main first "
            f"(any release type, none included)."
        )
    newest = releases[0]
    if newest.prerelease:
        return (
            f"{newest.tag_name}, the newest release of cycle {cycle}, is a pre-release. "
            f"Finish it from main first, with a maintenance release of cycle {cycle}."
        )

    metadata = gh.get_release_metadata(newest.tag_name) or {}
    sha = (metadata.get("repository") or {}).get("src_commit_sha") or ""
    if not sha:
        return (
            f"{newest.tag_name} has no src_commit_sha in {config.RELEASE_METADATA_FILE}; "
            f"only releases created by release automation can be maintained on a branch."
        )
    return BranchPlan(
        cycle=cycle,
        branch=branch,
        patched_release=newest.tag_name,
        patched_sha=sha,
        next_tag=f"{cycle}.{tag_version(newest.tag_name)[1] + 1}",
    )


def _set_value(text: str, key: str, value: str) -> str:
    """Replace the value of a `key:` line, keeping comments and layout."""
    pattern = re.compile(rf"^(?P<key>[ \t]*{key}:[ \t]*)(?:\"[^\"]*\"|'[^']*'|[^\s#]+)", re.M)
    updated, count = pattern.subn(lambda m: m.group("key") + value, text)
    if count != 1:
        raise ValueError(f"{key} not found once in {config.RELEASE_PLAN_FILE}")
    return updated


def parked_plan(text: str, next_tag: str) -> str:
    """The patched release's release-plan.yaml, parked at the next tag of the line with type none."""
    updated = _set_value(text, "target_release_tag", next_tag)
    updated = _set_value(updated, "target_release_type", "none")
    repository = (yaml.safe_load(updated) or {}).get("repository") or {}
    if (repository.get("target_release_tag"), repository.get("target_release_type")) != (next_tag, "none"):
        raise ValueError(f"could not park {config.RELEASE_PLAN_FILE} at {next_tag}")
    return updated


def create(gh, plan: BranchPlan) -> CreateResult:
    """
    Create the branch and commit onto it.

    Never raises for GitHub errors; a failure after the branch exists names
    what was left behind (a re-run is refused while the branch exists).
    """
    warnings = []
    source_tag = f"source/{plan.patched_release}"
    source_sha = gh.get_tag_sha(source_tag)
    if not source_sha:
        warnings.append(
            f"{source_tag} not found; the branch starts at src_commit_sha {plan.patched_sha[:7]} "
            f"of {plan.patched_release} ({config.RELEASE_METADATA_FILE})"
        )
    elif source_sha != plan.patched_sha:
        warnings.append(
            f"{source_tag} points to {source_sha[:7]}, not to src_commit_sha {plan.patched_sha[:7]} "
            f"of {plan.patched_release}; the branch starts at src_commit_sha"
        )

    files = {}
    try:
        for path in CALLER_WORKFLOWS:
            content = gh.get_file_content(path, ref="main", strict=True)
            if content is None:
                warnings.append(f"{path} not found on main")
            else:
                files[path] = content
        changelog = f"CHANGELOG/CHANGELOG-{plan.cycle}.md"
        content = gh.get_file_content(changelog, ref=plan.patched_release, strict=True)
        if content is None:
            warnings.append(f"{changelog} not found on tag {plan.patched_release}")
        else:
            files[changelog] = content
        plan_text = gh.get_file_content(config.RELEASE_PLAN_FILE, ref=plan.patched_sha, strict=True)
        if plan_text is None:
            raise ValueError(f"{config.RELEASE_PLAN_FILE} not found at {plan.patched_sha[:7]}")
        files[config.RELEASE_PLAN_FILE] = parked_plan(plan_text, plan.next_tag)
    except (GitHubClientError, ValueError) as e:
        return CreateResult(success=False, warning="; ".join(warnings), error_message=f"Nothing created: {e}")
    if CALLER_WORKFLOWS[0] not in files:
        return CreateResult(
            success=False, warning="; ".join(warnings),
            error_message=f"Nothing created: {CALLER_WORKFLOWS[0]} not found on main",
        )
    for warning in warnings:
        print(f"::warning::{warning}")

    try:
        if not gh.create_branch_at_sha(plan.branch, plan.patched_sha):
            return CreateResult(success=False, warning="; ".join(warnings),
                                error_message=f"{plan.branch} already exists; nothing created.")
    except GitHubClientError as e:
        return CreateResult(success=False, warning="; ".join(warnings),
                            error_message=f"Could not create {plan.branch}: {e}")
    print(f"Created {plan.branch} at {plan.patched_sha}")

    left_behind = f"{plan.branch} was created at {plan.patched_sha[:7]}"
    try:
        setup_sha = gh.commit_files(
            plan.branch, files, f"chore: set up {plan.branch} from {plan.patched_release}"
        )
    except GitHubClientError as e:
        message = f"Direct commit onto {plan.branch} failed: {e}. {left_behind}, without the commit."
        print(f"::error::{message}")
        return CreateResult(success=False, branch=plan.branch, warning="; ".join(warnings), error_message=message)
    print(f"Committed {', '.join(sorted(files))} onto {plan.branch}: {setup_sha}")
    return CreateResult(success=True, branch=plan.branch, setup_commit_sha=setup_sha, warning="; ".join(warnings))
