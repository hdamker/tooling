"""Post-release sync PR creator for CAMARA release automation.

This module creates a sync PR to main after release publication,
containing CHANGELOG updates from the release.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .github_client import GitHubClient, GitHubClientError
from .template_loader import render_template

logger = logging.getLogger(__name__)


@dataclass
class SyncPRResult:
    """Result of a sync PR creation operation."""
    success: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    error_message: Optional[str] = None


class PostReleaseSyncer:
    """Creates post-release sync PRs to main branch.

    After a release is published, this class creates a PR that:
    1. Syncs CHANGELOG/CHANGELOG-rX.md from the release tag (X = cycle number)
    2. Creates a PR with appropriate labels for human review

    Note: README update is handled by the create-sync-pr workflow job
    using the ReadmeUpdater class and update-readme-release-info composite action.
    """

    # Labels to apply to sync PRs
    SYNC_PR_LABELS = ["post-release", "automated"]

    def __init__(self, gh: GitHubClient):
        """Initialize with GitHub client.

        Args:
            gh: Configured GitHubClient instance
        """
        self.gh = gh

    def create_sync_pr(
        self,
        release_tag: str,
        source_ref: str,
    ) -> SyncPRResult:
        """Create post-release sync PR to main.

        Creates a PR that syncs CHANGELOG from the release tag back to
        main. README update is handled separately by the workflow job.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            source_ref: Git ref to read CHANGELOG from (release tag or branch)

        Returns:
            SyncPRResult with PR details or error
        """
        sync_branch = f"post-release/{release_tag}"

        try:
            # Step 1: Create sync branch from main
            main_sha = self._get_main_sha()
            if not main_sha:
                return SyncPRResult(
                    success=False,
                    error_message="Failed to get main branch SHA"
                )

            branch_created = self._create_branch(sync_branch, main_sha)
            if not branch_created:
                # Branch might already exist from previous attempt
                logger.warning(f"Branch {sync_branch} may already exist, continuing")

            # Step 2: Sync CHANGELOG from source ref
            changelog_synced = self._sync_changelog(source_ref, sync_branch, release_tag)
            if not changelog_synced:
                return SyncPRResult(
                    success=False,
                    error_message="CHANGELOG sync failed - no content to sync"
                )

            # Step 3: Create PR
            pr_result = self._create_pr(release_tag, sync_branch)
            if not pr_result:
                return SyncPRResult(
                    success=False,
                    error_message="Failed to create sync PR"
                )

            # Step 4: Add labels
            self._add_labels_to_pr(pr_result["number"])

            return SyncPRResult(
                success=True,
                pr_number=pr_result["number"],
                pr_url=pr_result["url"]
            )

        except GitHubClientError as e:
            logger.error(f"GitHub API error during sync PR creation: {e}")
            return SyncPRResult(
                success=False,
                error_message=f"GitHub API error: {e}"
            )
        except Exception as e:
            logger.error(f"Unexpected error during sync PR creation: {e}")
            return SyncPRResult(
                success=False,
                error_message=f"Unexpected error: {e}"
            )

    def _get_main_sha(self) -> Optional[str]:
        """Get the current SHA of the main branch."""
        try:
            branches = self.gh.list_branches(pattern="main")
            for branch in branches:
                if branch.name == "main":
                    return branch.sha
        except GitHubClientError:
            pass
        return None

    def _create_branch(self, branch_name: str, sha: str) -> bool:
        """Create a new branch at the given SHA."""
        try:
            self.gh._run_gh([
                "api",
                f"repos/{self.gh.repo}/git/refs",
                "-X", "POST",
                "-f", f"ref=refs/heads/{branch_name}",
                "-f", f"sha={sha}"
            ])
            return True
        except GitHubClientError as e:
            error_msg = str(e).lower()
            if "422" in error_msg or "reference already exists" in error_msg:
                return True  # Already exists, that's fine
            raise

    def _sync_changelog(
        self,
        snapshot_branch: str,
        target_branch: str,
        release_tag: str
    ) -> bool:
        """Copy release-specific CHANGELOG from snapshot branch to target branch.

        Copies CHANGELOG/CHANGELOG-rX.md where X is the release cycle number
        extracted from the release tag (e.g., r4.1 → CHANGELOG/CHANGELOG-r4.md).

        Args:
            snapshot_branch: Source branch with release CHANGELOG
            target_branch: Branch to update
            release_tag: Release tag (e.g., "r4.1") to extract cycle number

        Returns:
            True if successful, False otherwise
        """
        # Extract cycle number from release tag (r4.1 → 4)
        import re
        match = re.match(r"r(\d+)\.\d+", release_tag)
        if not match:
            logger.warning(f"Cannot extract cycle from release tag: {release_tag}")
            return False

        cycle = match.group(1)
        changelog_path = f"CHANGELOG/CHANGELOG-r{cycle}.md"

        # Get CHANGELOG from snapshot branch
        changelog_content = self.gh.get_file_content(changelog_path, ref=snapshot_branch)
        if not changelog_content:
            logger.warning(f"No {changelog_path} found on {snapshot_branch}")
            return False

        # Write to target branch
        try:
            self.gh.update_file(
                path=changelog_path,
                content=changelog_content,
                message=f"chore: sync {changelog_path} from release {release_tag}",
                branch=target_branch
            )
            return True
        except GitHubClientError as e:
            logger.error(f"Failed to update {changelog_path}: {e}")
            return False

    def _create_pr(self, release_tag: str, head_branch: str) -> Optional[Dict[str, Any]]:
        """Create the sync PR.

        Args:
            release_tag: Release tag for title
            head_branch: Source branch for PR

        Returns:
            Dict with 'number' and 'url', or None on error
        """
        title = f"Release Automation: Post-release sync ({release_tag})"
        body = render_template("sync_pr", {"release_tag": release_tag})

        try:
            # Use gh pr create
            output = self.gh._run_gh([
                "pr", "create",
                "--repo", self.gh.repo,
                "--title", title,
                "--body", body,
                "--head", head_branch,
                "--base", "main"
            ])

            # Parse PR URL from output
            pr_url = output.strip()
            try:
                pr_number = int(pr_url.rstrip("/").split("/")[-1])
                return {"number": pr_number, "url": pr_url}
            except (ValueError, IndexError):
                logger.error(f"Failed to parse PR number from: {pr_url}")
                return None

        except GitHubClientError as e:
            # Check if PR already exists
            error_msg = str(e).lower()
            if "already exists" in error_msg:
                logger.warning(f"PR already exists for {head_branch}")
                # Try to find existing PR
                existing_pr = self.gh.find_pr_for_branch(head_branch)
                if existing_pr:
                    return {
                        "number": existing_pr,
                        "url": f"https://github.com/{self.gh.repo}/pull/{existing_pr}"
                    }
            raise

    def _add_labels_to_pr(self, pr_number: int) -> None:
        """Add standard labels to the sync PR."""
        try:
            # Ensure labels exist first
            for label_name in self.SYNC_PR_LABELS:
                existing = self.gh.get_label(label_name)
                if not existing:
                    # Create with default color
                    color = "0E8A16" if label_name == "post-release" else "FBCA04"
                    self.gh.create_label(
                        label_name,
                        color,
                        f"Label for {label_name} PRs"
                    )

            self.gh.add_labels(pr_number, self.SYNC_PR_LABELS)
        except GitHubClientError as e:
            # Non-critical failure
            logger.warning(f"Failed to add labels to PR #{pr_number}: {e}")
