"""
Maintenance branch creation for CAMARA release automation.

A codeowner dispatches create-maintenance-branch with a cycle rX once main
has moved on to a later cycle. check() decides in the plan job whether the
branch may be created and from which release; create() runs in the act job
with the App token, which bypasses the maintenance-branch-protection ruleset:

1. maintenance/rX at the src_commit_sha of the patched release (the newest
   public or maintenance release of the cycle), from its release-metadata.yaml
2. one direct commit onto it: main's caller workflows and the cycle's
   CHANGELOG from the patched release's tag (the source commit lacks that
   release's own section)
3. a plan PR into it for rX.(N+1) maintenance-release, API versions unchanged
"""

import re
from dataclasses import dataclass
from typing import Union

import yaml

from . import config
from .github_client import GitHubClientError
from .labels import add_pr_labels
from .release_line import MAINTENANCE_BRANCH_PREFIX, tag_version

CALLER_WORKFLOWS = (
    ".github/workflows/release-automation.yml",
    ".github/workflows/camara-validation.yml",
)
PLAN_BRANCH_PREFIX = "release-plan/"
PR_LABELS = ["automated"]

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
    plan_pr_number: str = ""
    plan_pr_url: str = ""
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


def next_plan(text: str, next_tag: str) -> str:
    """The patched release's release-plan.yaml, retargeted to the next maintenance release."""
    updated = _set_value(text, "target_release_tag", next_tag)
    updated = _set_value(updated, "target_release_type", "maintenance-release")
    repository = (yaml.safe_load(updated) or {}).get("repository") or {}
    if (repository.get("target_release_tag"), repository.get("target_release_type")) != (
        next_tag, "maintenance-release"
    ):
        raise ValueError(f"could not retarget {config.RELEASE_PLAN_FILE} to {next_tag}")
    return updated


def pr_body(plan: BranchPlan) -> str:
    changelog = f"CHANGELOG/CHANGELOG-{plan.cycle}.md"
    return (
        f"Plan for the next maintenance release of cycle {plan.cycle}, opened when `{plan.branch}` was created.\n"
        "\n"
        f"- `target_release_tag`: {plan.next_tag}\n"
        "- `target_release_type`: maintenance-release\n"
        f"- API versions: unchanged from {plan.patched_release}\n"
        "\n"
        "**Before merging:** set the patch version (`target_api_version`) of each API this maintenance "
        "release fixes, on this PR's branch. Until one API version changes, CAMARA Validation reports "
        "\"no new content\" (P-035) on this PR.\n"
        "\n"
        f"The fixes reach `{plan.branch}` through their own PRs (e.g. a cherry-pick of the fix on main). "
        f"Merging this plan creates the Release Issue for {plan.next_tag}.\n"
        "\n"
        f"`{plan.branch}` starts at the source commit of {plan.patched_release} (`{plan.patched_sha[:7]}`), "
        f"plus one commit with main's caller workflows and `{changelog}` from tag {plan.patched_release}.\n"
        "\n"
        "Created by release automation (create-maintenance-branch)."
    )


def create(gh, plan: BranchPlan) -> CreateResult:
    """
    Create the branch, commit onto it and open the plan PR.

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
        retargeted = next_plan(plan_text, plan.next_tag)
    except (GitHubClientError, ValueError) as e:
        return CreateResult(success=False, warning="; ".join(warnings), error_message=f"Nothing created: {e}")
    if CALLER_WORKFLOWS[0] not in files:
        return CreateResult(
            success=False, warning="; ".join(warnings),
            error_message=f"Nothing created: {CALLER_WORKFLOWS[0]} not found on main",
        )
    for warning in warnings:
        print(f"::warning::{warning}")

    def failed(message: str, **kwargs) -> CreateResult:
        print(f"::error::{message}")
        return CreateResult(success=False, branch=plan.branch, warning="; ".join(warnings),
                            error_message=message, **kwargs)

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
        return failed(f"Direct commit onto {plan.branch} failed: {e}. {left_behind}, without the commit.")
    print(f"Committed {', '.join(sorted(files))} onto {plan.branch}: {setup_sha}")

    plan_branch = f"{PLAN_BRANCH_PREFIX}{plan.next_tag}"
    try:
        if not gh.create_branch_at_sha(plan_branch, setup_sha):
            raise GitHubClientError(f"{plan_branch} already exists")
        gh.update_file(
            config.RELEASE_PLAN_FILE, retargeted, f"chore: plan {plan.next_tag} on {plan.branch}", plan_branch
        )
        number, url = gh.create_pr(
            title=f"Release Automation: plan {plan.next_tag} on {plan.branch}",
            body=pr_body(plan),
            head=plan_branch,
            base=plan.branch,
        )
    except GitHubClientError as e:
        return failed(
            f"The plan PR for {plan.next_tag} could not be opened: {e}. {left_behind} and set up "
            f"({setup_sha[:7]}); open the plan PR by hand.",
            setup_commit_sha=setup_sha,
        )
    add_pr_labels(gh, number, PR_LABELS)
    print(f"Plan PR: {url}")
    return CreateResult(
        success=True,
        branch=plan.branch,
        setup_commit_sha=setup_sha,
        plan_pr_number=str(number),
        plan_pr_url=url,
        warning="; ".join(warnings),
    )
