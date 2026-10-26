"""
Common-file sync for CAMARA release automation.

Detection: compare an API repository's code/common/ cache with the
Commonalities release it declares (tooling_lib.cache_sync). The plan job uses
the result to block /create-snapshot on a stale cache and to show the cache
state on the Release Issue.

Sync: copy artifacts/common/*.yaml of that release into code/common/, write
the sync manifest, rebuild the sync branch from the base branch and open (or
reuse) its PR into it. Each release line syncs on its own: main uses
sync-common/<release>, a maintenance branch sync-common/<base_branch>/<release>.

The interface takes a git client and a GitHub client and no release-automation
types, so the module can move to a repository-reconcile workflow; the
release-state gate stays with the caller.

Usage (workflow step, detection):
    python3 -m release_automation.scripts.common_sync
"""

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from release_automation.scripts.git_operations import GitOperationsError
from release_automation.scripts.labels import add_pr_labels
from tooling_lib.cache_sync import (
    COMMON_DIR,
    MANIFEST_FILENAME,
    SyncStatus,
    check_sync_status,
    git_blob_sha,
)

# Releases before r4.2 have no sync manifest to check against.
FIRST_CHECKED_RELEASE = (4, 2)

COMMONALITIES = "Commonalities"
ICM = "IdentityAndConsentManagement"
SYNC_BRANCH_PREFIX = "sync-common/"
MAIN_BRANCH = "main"
PR_LABELS = ["common-sync", "automated"]


@dataclass(frozen=True)
class CacheCheck:
    """Detection result; status is in_sync, stale, or "" when not checked."""
    status: str = ""
    details: str = ""


def describe(status: SyncStatus) -> str:
    """One-line description of a stale cache."""
    parts = []
    if status.no_common_dir:
        parts.append("code/common/ directory is missing")
    elif status.no_manifest:
        parts.append("code/common/.sync-manifest.yaml is missing")
    else:
        for src in status.sources:
            if src.tag_mismatch:
                expected_tag, actual_tag = src.tag_mismatch
                parts.append(f"{src.repository}: expected {expected_tag}, manifest has {actual_tag}")
            for fname in src.missing_files:
                parts.append(f"{fname} missing from code/common/")
            for fname in src.modified_files:
                parts.append(f"{fname} modified since last sync")
    return "; ".join(parts) if parts else "cache mismatch detected"


def _manifest_repositories(api_repo: Path) -> List[str]:
    try:
        manifest = yaml.safe_load((api_repo / COMMON_DIR / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        return [s.get("repository") for s in manifest["sources"] if isinstance(s, dict)]
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return []


def expected_releases(api_repo: Path, commonalities_release: str, icm_release: str = "") -> Dict[str, str]:
    """
    Source releases code/common/ must match.

    The ICM release counts only once the manifest records ICM files: ICM
    publishes no common artifacts today, so requiring it would leave every
    cache stale with no common sync able to fix it.
    """
    expected = {COMMONALITIES: commonalities_release}
    if icm_release and ICM in _manifest_repositories(api_repo):
        expected[ICM] = icm_release
    return expected


def detect(api_repo: Path, commonalities_release: str, icm_release: str = "") -> CacheCheck:
    """
    Check code/common/ against the declared Commonalities (and ICM) release.

    Args:
        api_repo: Checkout of the API repository (code/common/ is enough)
        commonalities_release: Declared release, e.g. "r4.2"
        icm_release: Declared ICM release (see expected_releases)

    Returns:
        CacheCheck; empty status when the release is unparsable or before r4.2
    """
    m = re.fullmatch(r"r(\d+)\.(\d+)", commonalities_release)
    if not m:
        print(f"Cannot parse commonalities_release '{commonalities_release}', skipping cache check")
        return CacheCheck()
    if (int(m.group(1)), int(m.group(2))) < FIRST_CHECKED_RELEASE:
        print(f"commonalities_release {commonalities_release} < r4.2, skipping cache check")
        return CacheCheck()

    status = check_sync_status(api_repo, expected_releases(api_repo, commonalities_release, icm_release))
    if status.in_sync:
        print(f"Common file cache is in sync with {commonalities_release}")
        return CacheCheck(status="in_sync")

    details = describe(status)
    print(f"Common file cache is stale: {details}")
    return CacheCheck(status="stale", details=details)


def sync_branch(release: str, base_branch: str = MAIN_BRANCH) -> str:
    """sync-common/<release> for main, sync-common/<base_branch>/<release> for other lines."""
    if not base_branch or base_branch == MAIN_BRANCH:
        return f"{SYNC_BRANCH_PREFIX}{release}"
    return f"{SYNC_BRANCH_PREFIX}{base_branch}/{release}"


def _sync_branch_line(head: str) -> str:
    """The base branch a sync branch belongs to, "" for other branches."""
    if not head.startswith(SYNC_BRANCH_PREFIX):
        return ""
    rest = head[len(SYNC_BRANCH_PREFIX):]
    parts = rest.split("/")
    if parts[0] == "maintenance" and len(parts) >= 3:
        return "/".join(parts[:2])
    return MAIN_BRANCH


def find_sync_pr(gh, release: str, base_branch: str = MAIN_BRANCH) -> str:
    """URL of the open sync PR for exactly this release's branch on this line, or ""."""
    found = gh.find_open_pr(sync_branch(release, base_branch))
    return found[1] if found else ""


@dataclass(frozen=True)
class CommonSyncOutcome:
    """
    Common sync result; status is created | updated | no_changes | failed.

    unexpected_files lists names under code/common/ the release does not
    provide (left in place, named in the PR body).
    """
    status: str
    pr_url: str = ""
    pr_number: str = ""
    unexpected_files: Tuple[str, ...] = ()


class CommonSyncError(Exception):
    """A common sync step failed; the message is the ::error:: text."""


def copy_common_files(source_dir: Path, api_repo: Path, release: str) -> Dict[str, str]:
    """
    Copy the release's *.yaml files into code/common/ and write the manifest.

    Returns:
        File name -> git blob SHA of each copied file

    Raises:
        CommonSyncError: When the release has no artifacts/common or no YAML in it
    """
    if not source_dir.is_dir():
        raise CommonSyncError(f"Commonalities artifacts/common not found at tag {release}")
    source_files = sorted(p for p in source_dir.iterdir() if p.suffix == ".yaml")
    if not source_files:
        raise CommonSyncError(f"No YAML files in Commonalities artifacts/common at {release}")

    common_dir = api_repo / COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for src in source_files:
        dest = common_dir / src.name
        shutil.copy2(src, dest)
        files[src.name] = git_blob_sha(dest.read_bytes())
        print(f"Synced: {src.name} ({files[src.name][:12]})")

    manifest = {"sources": [{"repository": COMMONALITIES, "release": release, "files": files}]}
    (common_dir / MANIFEST_FILENAME).write_text(
        yaml.dump(manifest, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )
    print(f"Wrote manifest: {common_dir / MANIFEST_FILENAME} ({len(files)} files)")
    return files


def pr_body(release: str, unexpected: Tuple[str, ...] = (), base_branch: str = MAIN_BRANCH) -> str:
    body = (
        "> [!WARNING]\n"
        f"> This branch is owned by Release Automation and is rebuilt from `{base_branch}` on every run.\n"
        "> **Do not commit fixes to this branch** — any commits here are overwritten the next time the sync runs.\n"
        "\n"
        f"Automated sync of `code/common/` files from `camaraproject/Commonalities` at release tag `{release}`.\n"
        "\n"
        "This PR was created by release automation because the cached Commonalities files were out of sync "
        "with the declared dependency in `release-plan.yaml`.\n"
        "\n"
        "**What changed:**\n"
        f"- Updated files in `code/common/` to match Commonalities {release}\n"
        "- Added/updated `.sync-manifest.yaml` with file integrity hashes\n"
        "\n"
        "**How to handle this PR:**\n"
        "- **Validation green** — review and merge.\n"
        "- **Validation red** — choose one:\n"
        f"  - *(recommended)* fix the errors on `{base_branch}`, then re-trigger the sync; this PR is rebuilt from "
        f"the new `{base_branch}` HEAD with the corrected content.\n"
        f"  - merge this PR with the errors and fix them on `{base_branch}` afterwards.\n"
        "\n"
        "To re-trigger the sync, run the **CAMARA Release Automation** workflow from the repository's "
        "**Actions** tab.\n"
        "\n"
        "`/create-snapshot` is blocked until common files are in sync."
    )
    if unexpected:
        names = ", ".join(f"`{name}`" for name in unexpected)
        body += (
            f"\n\n**Not provided by Commonalities {release}:** {names} in `code/common/` — "
            f"remove them on `{base_branch}` if they are no longer needed."
        )
    return body


def _close_superseded_prs(gh, branch: str, release: str, base_branch: str) -> None:
    """Close the open sync PRs of other releases on the same line."""
    try:
        prs = gh.list_open_prs()
    except Exception as e:
        print(f"Could not list open PRs: {e}")
        return
    for pr in prs:
        if pr["head"] != branch and _sync_branch_line(pr["head"]) == (base_branch or MAIN_BRANCH):
            print(f"Closing stale sync PR #{pr['number']}")
            try:
                gh.close_pr(pr["number"], comment=f"Superseded by sync to Commonalities {release}")
            except Exception as e:
                print(f"Could not close #{pr['number']}: {e}")


def sync_common(
    api_git, commonalities_git, gh, release: str, bot_name: str, bot_email: str,
    base_branch: str = MAIN_BRANCH,
) -> CommonSyncOutcome:
    """
    Rebuild code/common/ from the Commonalities release and open or reuse its sync PR.

    Args:
        api_git: Git client of the API repository; base_branch is cloned into its work_dir
        commonalities_git: Git client of camaraproject/Commonalities; the release
            tag is cloned into its work_dir
        gh: GitHub client of the API repository
        release: Declared Commonalities release, e.g. "r4.3"
        bot_name: Commit author and committer name
        bot_email: Commit author and committer email
        base_branch: Branch of the release line whose cache is synced; the PR targets it

    Returns:
        CommonSyncOutcome; every failed step is status "failed", nothing raises
    """
    base_branch = base_branch or MAIN_BRANCH
    branch = sync_branch(release, base_branch)
    api_repo = Path(api_git.work_dir)
    try:
        api_git.clone(base_branch, depth=1)
    except GitOperationsError as e:
        print(f"::error::Could not clone the API repository: {e}")
        return CommonSyncOutcome(status="failed")
    try:
        commonalities_git.clone(release, depth=1)
    except GitOperationsError as e:
        print(f"::error::Could not fetch Commonalities {release}: {e}")
        return CommonSyncOutcome(status="failed")

    try:
        # Reset the RA-owned branch to the base branch first, then copy onto it.
        api_git.create_branch(branch, reset=True)
        synced = copy_common_files(Path(commonalities_git.work_dir) / "artifacts" / "common", api_repo, release)
    except (GitOperationsError, CommonSyncError) as e:
        print(f"::error::{e}")
        return CommonSyncOutcome(status="failed")

    unexpected = tuple(sorted(
        p.name for p in (api_repo / COMMON_DIR).iterdir()
        if p.name != MANIFEST_FILENAME and p.name not in synced
    ))
    if unexpected:
        print(
            f"::warning::code/common/ has files not provided by Commonalities {release}: "
            f"{', '.join(unexpected)}"
        )

    _close_superseded_prs(gh, branch, release, base_branch)

    try:
        if not api_git.has_changes(COMMON_DIR):
            print(f"code/common already matches Commonalities {release}; nothing to sync")
            return CommonSyncOutcome(status="no_changes", unexpected_files=unexpected)
        api_git.configure_user(bot_name, bot_email)
        api_git.commit_all(f"chore: sync common files from Commonalities {release}")
        # Force: the branch is rebuilt from the base branch each run; RA is its only owner.
        api_git.push(branch, set_upstream=False, force=True)
    except GitOperationsError as e:
        print(f"::error::Could not push {branch}: {e}")
        return CommonSyncOutcome(status="failed", unexpected_files=unexpected)

    existing = gh.find_open_pr(branch)
    if existing:
        number, url = existing
        print(f"Reusing open sync PR: {url}")
        return CommonSyncOutcome(status="updated", pr_url=url, pr_number=str(number), unexpected_files=unexpected)

    try:
        number, url = gh.create_pr(
            title=f"Sync common files from Commonalities {release}",
            body=pr_body(release, unexpected, base_branch),
            head=branch,
            base=base_branch,
        )
    except Exception as e:
        print(f"::error::Failed to create sync PR: {e}")
        return CommonSyncOutcome(status="failed", unexpected_files=unexpected)
    add_pr_labels(gh, number, PR_LABELS)
    print(f"Sync PR created: {url}")
    return CommonSyncOutcome(status="created", pr_url=url, pr_number=str(number), unexpected_files=unexpected)


def main(client=None) -> int:
    from release_automation.scripts.trigger import write_outputs

    release = os.environ["COMMONALITIES_RELEASE"]
    check = detect(Path(os.environ["API_REPO_PATH"]), release, os.environ.get("ICM_RELEASE", ""))
    sync_pr_url = ""
    if check.status == "stale":
        if client is None:
            from .github_client import GitHubClient
            client = GitHubClient(repo=os.environ["GITHUB_REPOSITORY"], token=os.environ.get("GITHUB_TOKEN"))
        sync_pr_url = find_sync_pr(client, release, os.environ.get("BASE_BRANCH") or MAIN_BRANCH)
        print(f"Found existing sync PR: {sync_pr_url}" if sync_pr_url else "No existing sync PR found")
    write_outputs(os.environ["GITHUB_OUTPUT"], {
        "common_cache_status": check.status,
        "common_cache_details": check.details,
        "common_sync_pr_url": sync_pr_url,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
