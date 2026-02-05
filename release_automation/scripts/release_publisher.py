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
            "draft": release.draft
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

        # Set release_date in UTC
        release_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        try:
            updated = self.gh.update_release(release_id, draft=False)
            return PublishResult(
                success=True,
                release_url=updated.get("html_url"),
                release_id=release_id
            )
        except GitHubClientError as e:
            return PublishResult(
                success=False,
                error_message=f"Failed to publish release: {e}"
            )
