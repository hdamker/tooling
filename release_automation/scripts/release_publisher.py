"""Release publisher module for publishing releases.

This module handles the publication of GitHub releases as part of the CAMARA
release automation workflow: a draft on /publish-release (publish_draft), or a
new release on the Release PR merge (draft_release.publish_on_merge). Both end
in complete_publication(): reference tag, pointer branch, branch cleanup.
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
    pointer_branch: Optional[str] = None
    is_prerelease: bool = False
    error_message: Optional[str] = None


@dataclass(frozen=True)
class PublishOutcome:
    """Result of a publication for the act outcome.

    error_message is the failure reason, or after a successful publication the
    warnings of the post-publication steps joined by '; '.
    """
    success: bool
    release_url: str = ""
    reference_tag: str = ""
    pointer_branch: str = ""
    error_message: str = ""


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
            release_id=release_id,
            is_prerelease=is_prerelease
        )

    def publish_new_release(
        self,
        release_tag: str,
        snapshot_branch: str,
        body: str,
        is_prerelease: bool
    ) -> PublishResult:
        """Publish a release without a draft (publish_mode on_merge).

        Steps:
        1. Finalize release-metadata.yaml (set release_date)
        2. Create the published release on the snapshot branch (creates tag)

        Returns:
            PublishResult with success status and details
        """
        commit_sha = self.finalize_metadata(snapshot_branch, release_tag)
        if not commit_sha:
            return PublishResult(
                success=False,
                error_message="Failed to finalize release-metadata.yaml"
            )
        try:
            created = self.gh.create_release(
                release_tag, snapshot_branch, release_tag, body,
                draft=False,
                prerelease=is_prerelease,
            )
        except GitHubClientError as e:
            return PublishResult(
                success=False,
                error_message=f"Failed to publish release: {e}"
            )

        # make_latest in its own call, as in publish_release()
        if not is_prerelease:
            try:
                self.gh.update_release(created.get("id"), make_latest="true")
            except GitHubClientError:
                logger.warning(f"Failed to mark {release_tag} as Latest release")
        return PublishResult(
            success=True,
            release_url=created.get("html_url"),
            release_id=created.get("id"),
            is_prerelease=is_prerelease
        )

    def create_reference_tag(
        self,
        release_tag: str,
        src_commit_sha: str
    ) -> Optional[str]:
        """Create source/rX.Y reference tag on main at the branch point.

        The reference tag marks the commit on main where the release
        snapshot was created, providing a stable reference point.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            src_commit_sha: SHA of the source commit on main

        Returns:
            Created tag name (e.g., "source/r4.1") or None on error
        """
        tag_name = f"source/{release_tag}"

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

    def create_pointer_branch(
        self,
        release_tag: str,
        is_prerelease: bool
    ) -> Optional[str]:
        """Create a pointer branch at the release tag commit.

        Public releases get release/rX.Y, pre-releases get pre-release/rX.Y.
        The pointer branch ensures the tag commit remains reachable from a
        branch, preventing GitHub's "commit does not belong to any branch"
        warning.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            is_prerelease: Whether this is a pre-release

        Returns:
            Created branch name or None on error
        """
        prefix = "pre-release" if is_prerelease else "release"
        branch_name = f"{prefix}/{release_tag}"

        # Resolve tag to commit SHA
        tag_sha = self.gh.get_tag_sha(release_tag)
        if not tag_sha:
            logger.error(f"Cannot resolve tag {release_tag} to SHA")
            return None

        try:
            created = self.gh.create_branch_at_sha(branch_name, tag_sha)
            if created:
                logger.info(f"Created pointer branch {branch_name} at {tag_sha[:8]}")
            else:
                logger.warning(f"Pointer branch {branch_name} already exists")
            return branch_name
        except GitHubClientError as e:
            error_msg = str(e).lower()
            if "422" in error_msg or "reference already exists" in error_msg:
                logger.warning(
                    f"Pointer branch {branch_name} already exists (race condition)"
                )
                return branch_name
            logger.error(f"Failed to create pointer branch {branch_name}: {e}")
            return None

    def cleanup_branches(
        self,
        snapshot_branch: str,
        release_review_branch: str
    ) -> Dict[str, str]:
        """Clean up branches after publication.

        Deletes both the snapshot and release-review branches. The release tag
        preserves the published commit, so the release-review branch carries
        no information not already in the tag list.

        Args:
            snapshot_branch: e.g., "release-snapshot/r4.1-abc1234"
            release_review_branch: e.g., "release-review/r4.1-abc1234"

        Returns:
            Dict with status for each operation:
            - "snapshot_deleted": "deleted", "not_found", or "error"
            - "review_deleted": "deleted", "not_found", or "error"
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

        # Delete release-review branch
        try:
            deleted = self.gh.delete_branch(release_review_branch)
            result["review_deleted"] = "deleted" if deleted else "not_found"
            if deleted:
                logger.info(f"Deleted branch {release_review_branch}")
            else:
                logger.warning(f"Branch {release_review_branch} not found (already deleted)")
        except GitHubClientError as e:
            logger.error(f"Failed to delete {release_review_branch}: {e}")
            result["review_deleted"] = "error"

        return result


def complete_publication(
    publisher: ReleasePublisher,
    result: PublishResult,
    release_tag: str,
    src_commit_sha: str,
    snapshot_branch: str,
    release_review_branch: str,
) -> PublishOutcome:
    """After the publish step: reference tag, pointer branch, branch cleanup (all non-critical)."""
    if not result.success:
        message = result.error_message or "Unknown error"
        print(f"::error::Publication failed: {message}")
        return PublishOutcome(success=False, error_message=message)

    release_url = result.release_url or ""
    print(f"Release published: {release_url}")
    warnings = []

    print("Step 2: Creating reference tag...")
    reference_tag = publisher.create_reference_tag(release_tag, src_commit_sha) or ""
    if reference_tag:
        print(f"Reference tag created: {reference_tag}")
    else:
        warnings.append("Failed to create reference tag")
        print("::warning::Failed to create reference tag")

    print("Step 3: Creating pointer branch...")
    pointer_branch = publisher.create_pointer_branch(release_tag, result.is_prerelease) or ""
    if pointer_branch:
        print(f"Pointer branch created: {pointer_branch}")
    else:
        warnings.append("Failed to create pointer branch")
        print("::warning::Failed to create pointer branch")

    print("Step 4: Cleaning up branches...")
    for op, status in publisher.cleanup_branches(snapshot_branch, release_review_branch).items():
        if status == "error":
            warnings.append(f"Branch cleanup issue: {op}")
        print(f"  {op}: {status}")

    print("Publish flow completed successfully")
    return PublishOutcome(
        success=True,
        release_url=release_url,
        reference_tag=reference_tag,
        pointer_branch=pointer_branch,
        error_message="; ".join(warnings),
    )


def publish_draft(
    gh: GitHubClient,
    release_tag: str,
    snapshot_branch: str,
    release_review_branch: str,
    src_commit_sha: str,
) -> PublishOutcome:
    """/publish-release --confirm: publish the draft, then complete the publication.

    The post-release sync PR and the Release Issue close follow in finalize.
    """
    publisher = ReleasePublisher(gh)
    print("Step 1: Publishing release...")
    result = publisher.publish_release(release_tag, snapshot_branch)
    return complete_publication(publisher, result, release_tag, src_commit_sha, snapshot_branch, release_review_branch)
