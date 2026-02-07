"""Release publisher module for publishing draft releases.

This module handles the publication of draft GitHub releases as part
of the CAMARA release automation workflow.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml

from .github_client import GitHubClient, GitHubClientError

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Result of a publish operation."""
    success: bool
    release_url: Optional[str] = None
    release_id: Optional[int] = None
    reference_tag: Optional[str] = None
    error_message: Optional[str] = None


class ReleasePublisher:
    """Publishes draft releases to GitHub.

    This class handles the publication flow:
    1. Find and validate the draft release
    2. Finalize release-metadata.yaml with release_date
    3. Publish the draft (set draft=false, which creates the tag)
    """

    def __init__(self, gh: GitHubClient):
        """Initialize with GitHub client.

        Args:
            gh: Configured GitHubClient instance
        """
        self.gh = gh

    def get_draft_release(self, release_tag: str) -> Optional[Dict[str, Any]]:
        """Find draft release by tag name.

        Args:
            release_tag: Release tag to search for

        Returns:
            Draft release dict if found, None otherwise.
            Dict contains: id, tag_name, name, html_url, draft
        """
        release = self.gh.get_draft_release(release_tag)
        if not release:
            return None

        # Get the release ID separately since Release dataclass doesn't have it
        release_id = self.gh.get_release_id(release_tag, draft_only=True)

        return {
            "id": release_id,
            "tag_name": release.tag_name,
            "name": release.name,
            "html_url": release.html_url,
            "draft": release.draft,
            "prerelease": release.prerelease
        }

    def finalize_metadata(
        self,
        snapshot_branch: str,
        release_tag: str
    ) -> Optional[str]:
        """Set release_date in release-metadata.yaml on snapshot branch.

        Args:
            snapshot_branch: Branch containing release-metadata.yaml
            release_tag: Release tag for logging/commit message

        Returns:
            Commit SHA of finalization commit, or None on error
        """
        # Read current metadata
        metadata_content = self.gh.get_file_content(
            "release-metadata.yaml",
            ref=snapshot_branch
        )
        if not metadata_content:
            logger.error(f"Cannot read release-metadata.yaml from {snapshot_branch}")
            return None

        try:
            metadata = yaml.safe_load(metadata_content)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse release-metadata.yaml: {e}")
            return None

        # Set release_date in UTC (ISO 8601 with time)
        release_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "repository" not in metadata:
            metadata["repository"] = {}
        metadata["repository"]["release_date"] = release_date

        # Write back with preserved formatting
        updated_content = yaml.dump(
            metadata,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True
        )

        try:
            result = self.gh.update_file(
                path="release-metadata.yaml",
                content=updated_content,
                message=f"chore: finalize release-metadata.yaml for {release_tag}",
                branch=snapshot_branch
            )
            commit_sha = result.get("commit", {}).get("sha")
            logger.info(f"Finalized metadata with commit {commit_sha}")
            return commit_sha
        except GitHubClientError as e:
            logger.error(f"Failed to update release-metadata.yaml: {e}")
            return None

    def publish_release(
        self,
        release_tag: str,
        snapshot_branch: str
    ) -> PublishResult:
        """Publish a draft release.

        Steps:
        1. Find draft release by tag
        2. Finalize release-metadata.yaml (set release_date)
        3. Update draft to published (creates tag)

        Args:
            release_tag: Release tag to publish
            snapshot_branch: Branch containing release metadata

        Returns:
            PublishResult with success status and details
        """
        # Step 1: Find draft release
        draft = self.get_draft_release(release_tag)
        if not draft:
            return PublishResult(
                success=False,
                error_message=f"No draft release found for tag `{release_tag}`"
            )

        release_id = draft.get("id")
        if not release_id:
            return PublishResult(
                success=False,
                error_message=f"Cannot determine release ID for `{release_tag}`"
            )

        # Step 2: Finalize metadata
        commit_sha = self.finalize_metadata(snapshot_branch, release_tag)
        if not commit_sha:
            return PublishResult(
                success=False,
                error_message="Failed to finalize release-metadata.yaml"
            )

        # Step 3: Publish (set draft=false)
        is_prerelease = draft.get("prerelease", False)

        try:
            updated = self.gh.update_release(
                release_id,
                draft=False,
                prerelease=is_prerelease,  # Re-enforce in case UI changed it
            )
        except GitHubClientError as e:
            return PublishResult(
                success=False,
                error_message=f"Failed to publish release: {e}"
            )

        # Step 3b: Set make_latest separately — GitHub ignores make_latest
        # while the release is still a draft (same PATCH call)
        if not is_prerelease:
            try:
                self.gh.update_release(release_id, make_latest="true")
            except GitHubClientError:
                logger.warning(f"Failed to mark {release_tag} as Latest release")

        return PublishResult(
            success=True,
            release_url=updated.get("html_url"),
            release_id=release_id
        )

    def create_reference_tag(
        self,
        release_tag: str,
        src_commit_sha: str
    ) -> Optional[str]:
        """Create src/rX.Y reference tag on main at the branch point.

        The reference tag marks the commit on main where the release
        snapshot was created, providing a stable reference point.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            src_commit_sha: SHA of the source commit on main

        Returns:
            Created tag name (e.g., "src/r4.1") or None on error
        """
        tag_name = f"src/{release_tag}"

        # Check if tag already exists
        if self.gh.tag_exists(tag_name):
            logger.warning(f"Reference tag {tag_name} already exists")
            return tag_name

        try:
            self.gh.create_tag(tag_name, src_commit_sha)
            logger.info(f"Created reference tag {tag_name} at {src_commit_sha[:8]}")
            return tag_name
        except GitHubClientError as e:
            # Handle race condition where tag was created between check and create
            error_msg = str(e).lower()
            if "422" in error_msg or "reference already exists" in error_msg:
                logger.warning(f"Reference tag {tag_name} already exists (race condition)")
                return tag_name
            logger.error(f"Failed to create reference tag {tag_name}: {e}")
            return None

    def cleanup_branches(
        self,
        snapshot_branch: str,
        release_review_branch: str
    ) -> Dict[str, str]:
        """Clean up branches after publication.

        Deletes the snapshot branch and renames the release-review branch
        to indicate it has been published.

        Args:
            snapshot_branch: e.g., "release-snapshot/r4.1-abc1234"
            release_review_branch: e.g., "release-review/r4.1-abc1234"

        Returns:
            Dict with status for each operation:
            - "snapshot_deleted": "deleted", "not_found", or "error"
            - "review_renamed": "renamed", "not_found", or "error"
        """
        result: Dict[str, str] = {}

        # Delete snapshot branch
        try:
            deleted = self.gh.delete_branch(snapshot_branch)
            result["snapshot_deleted"] = "deleted" if deleted else "not_found"
            if deleted:
                logger.info(f"Deleted branch {snapshot_branch}")
            else:
                logger.warning(f"Branch {snapshot_branch} not found (already deleted)")
        except GitHubClientError as e:
            logger.error(f"Failed to delete {snapshot_branch}: {e}")
            result["snapshot_deleted"] = "error"

        # Rename release-review branch to -published
        new_review_branch = f"{release_review_branch}-published"
        try:
            renamed = self.gh.rename_branch(release_review_branch, new_review_branch)
            result["review_renamed"] = "renamed" if renamed else "not_found"
            if renamed:
                logger.info(f"Renamed {release_review_branch} to {new_review_branch}")
            else:
                logger.warning(f"Branch {release_review_branch} not found (already renamed)")
        except GitHubClientError as e:
            logger.error(f"Failed to rename {release_review_branch}: {e}")
            result["review_renamed"] = "error"

        return result
