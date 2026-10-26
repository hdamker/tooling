"""
Post-release sync PR for CAMARA release automation.

After a publication from main (case A), main receives the README
release-information block and the release-cycle CHANGELOG from the release
tag through a pr-to-main/<tag> PR. After a publication from maintenance/rX
(case B), the release-cycle CHANGELOG alone goes into both maintenance/rX
(pr-to-maintenance/rX/<tag>) and main (pr-to-main/<tag>). The outcome's status (created | failed | no_changes) is the boundary
between the published release and this follow-up: it decides whether the
Release Issue closes, and a failure here never fails the publication.

The branch is rebuilt from main on every run and an open PR for it is reused,
so a re-run after a partial failure converges instead of failing on push.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .git_operations import GitOperationsError
from .github_client import GitHubClientError
from .labels import add_pr_labels

RELEASE_INFO_START = "<!-- CAMARA:RELEASE-INFO:START -->"
RELEASE_INFO_END = "<!-- CAMARA:RELEASE-INFO:END -->"
SYNC_BRANCH_PREFIX = "pr-to-"
MAIN_BRANCH = "main"
PR_LABELS = ["post-release", "automated"]


@dataclass(frozen=True)
class SyncPrOutcome:
    """
    Result of the post-release sync; pr_url/pr_number are set when created.

    In case B, pr_url/pr_number are the PR into the maintenance branch and
    main_pr_url/main_pr_number the PR into main (combine_case_b).
    """
    status: str
    pr_url: str = ""
    pr_number: str = ""
    main_pr_url: str = ""
    main_pr_number: str = ""


def combine_case_b(line: "SyncPrOutcome", main: "SyncPrOutcome") -> "SyncPrOutcome":
    """One outcome for the two case-B PRs: created only when both were created."""
    statuses = {line.status, main.status}
    if "failed" in statuses:
        status = "failed"
    elif statuses == {"created"}:
        status = "created"
    else:
        status = "no_changes"
    return SyncPrOutcome(
        status=status, pr_url=line.pr_url, pr_number=line.pr_number,
        main_pr_url=main.pr_url, main_pr_number=main.pr_number,
    )


def _warning(message: str) -> None:
    print(f"::warning::{message}")


def _release_info_block(readme: str) -> Optional[str]:
    start = readme.find(RELEASE_INFO_START)
    end = readme.find(RELEASE_INFO_END)
    if start == -1 or end == -1 or end < start:
        return None
    return readme[start:end + len(RELEASE_INFO_END)]


def sync_readme(gh, work_dir: Path, tag: str) -> bool:
    """Copy the release-information block of README.md from the tag; True if main's README changed."""
    tag_readme = gh.get_file_content("README.md", ref=tag)
    if tag_readme is None:
        _warning(f"Could not read README.md from tag {tag}")
        return False
    tag_block = _release_info_block(tag_readme)
    if tag_block is None:
        _warning("Tag README missing release info delimiters")
        return False

    local_path = work_dir / "README.md"
    if not local_path.is_file():
        _warning("README.md not found in API repo checkout")
        return False
    local = local_path.read_text(encoding="utf-8")
    local_block = _release_info_block(local)
    if local_block is None:
        _warning("Main README missing release info delimiters")
        return False

    start = local.find(RELEASE_INFO_START)
    updated = local[:start] + tag_block + local[start + len(local_block):]
    if updated == local:
        print("README release info already up to date")
        return False
    local_path.write_text(updated, encoding="utf-8")
    print("README release info synced from tag")
    return True


def changelog_candidates(tag: str) -> List[str]:
    """The per-cycle CHANGELOG of the tag's release cycle."""
    match = re.match(r"^r(\d+)\.\d+", tag)
    return [f"CHANGELOG/CHANGELOG-r{match.group(1)}.md"] if match else []


def sync_changelog(gh, work_dir: Path, tag: str) -> str:
    """Copy the release-cycle CHANGELOG from the tag; returns its path, or "" if none was found."""
    candidates = changelog_candidates(tag)
    for path in candidates:
        content = gh.get_file_content(path, ref=tag)
        if content is None:
            continue
        local_path = work_dir / path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")
        print(f"Synced {path} from tag {tag}")
        return path
    _warning(f"No CHANGELOG found at {' or '.join(candidates)} on tag {tag}")
    return ""


def sync_branch(tag: str, base_branch: str = MAIN_BRANCH) -> str:
    """pr-to-<base_branch>/<tag>: pr-to-main/r1.3, pr-to-maintenance/r1/r1.10."""
    return f"{SYNC_BRANCH_PREFIX}{base_branch}/{tag}"


def pr_body(tag: str, readme: bool = True) -> str:
    return (
        f"Automated post-release sync PR for {tag}.\n"
        "\n"
        "This PR updates:\n"
        + ("- README.md Release Information section (copied from release tag)\n" if readme else "")
        + "- CHANGELOG for the release cycle\n"
        "\n"
        "Created by release automation workflow."
    )


def _failed() -> SyncPrOutcome:
    print("::error::Failed to create post-release sync PR")
    return SyncPrOutcome(status="failed")


def create_sync_pr(
    gh, git, tag: str, bot_name: str, bot_email: str,
    base_branch: str = MAIN_BRANCH, readme: bool = True,
) -> SyncPrOutcome:
    """
    Open the post-release sync PR of a published release into one branch.

    Args:
        gh: GitHub client of the API repository
        git: Git client whose work_dir receives a clone of base_branch
        tag: Published release tag, e.g. "r4.1"
        bot_name: Commit author and committer name
        bot_email: Commit author and committer email
        base_branch: Branch the PR targets
        readme: Also copy the README release-information block (case A only)

    Returns:
        SyncPrOutcome; never raises for git or GitHub errors
    """
    branch = sync_branch(tag, base_branch)
    work_dir = Path(git.work_dir)
    try:
        git.clone(base_branch, depth=1)
    except GitOperationsError as e:
        print(f"Clone failed: {e}")
        return _failed()

    readme_changed = sync_readme(gh, work_dir, tag) if readme else False
    changelog_path = sync_changelog(gh, work_dir, tag)
    if not readme_changed and not changelog_path:
        _warning("No content changes to sync")
        return SyncPrOutcome(status="no_changes")

    try:
        git.create_branch(branch, reset=True)
        if not git.has_changes():
            _warning("No actual file changes detected")
            return SyncPrOutcome(status="no_changes")

        existing = gh.find_open_pr(branch)
        if existing:
            number, url = existing
            print(f"Reusing open sync PR: {url}")
            return SyncPrOutcome(status="created", pr_url=url, pr_number=str(number))

        git.configure_user(bot_name, bot_email)
        git.commit_all(f"chore: post-release sync for {tag}")
        git.push(branch, set_upstream=False, force=True)
    except GitOperationsError as e:
        print(f"Git operation failed: {e}")
        return _failed()

    try:
        number, url = gh.create_pr(
            title=f"Release Automation: Post-release sync ({tag})" + ("" if readme else f" into {base_branch}"),
            body=pr_body(tag, readme),
            head=branch,
            base=base_branch,
        )
    except GitHubClientError as e:
        print(f"PR creation failed: {e}")
        return _failed()

    add_pr_labels(gh, number, PR_LABELS)
    print(f"Sync PR created: {url}")
    return SyncPrOutcome(status="created", pr_url=url, pr_number=str(number))
