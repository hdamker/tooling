"""
Release state manager for CAMARA release automation.

This module provides the core state derivation logic that determines
the current release state by examining repository artifacts.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

import yaml

from .github_client import GitHubClient


class ReleaseState(Enum):
    """
    Possible states for a CAMARA release.

    State Transition Flow:
        PLANNED → SNAPSHOT_ACTIVE → DRAFT_READY → PUBLISHED
                                 ↘ (discard)
        Any state can transition to CANCELLED via release-plan.yaml changes
    """
    PLANNED = "planned"                # release-plan.yaml defines intent
    SNAPSHOT_ACTIVE = "snapshot-active"  # Snapshot branch exists
    DRAFT_READY = "draft-ready"        # Draft release created
    PUBLISHED = "published"            # Tag exists (final state)
    CANCELLED = "cancelled"            # target_release_type set to "none"


@dataclass
class SnapshotInfo:
    """
    Information about an active release snapshot.

    The snapshot_id is derived from the branch name:
        release-snapshot/r4.1-abc1234 → r4.1-abc1234

    Attributes:
        snapshot_id: Unique identifier (e.g., "r4.1-abc1234")
        snapshot_branch: Full branch name (e.g., "release-snapshot/r4.1-abc1234")
        release_review_branch: Review branch name (e.g., "release-review/r4.1-abc1234")
        base_commit_sha: The commit SHA the snapshot was created from
        created_at: When the snapshot was created
        release_pr_number: PR number if Release PR exists
    """
    snapshot_id: str
    snapshot_branch: str
    release_review_branch: str
    base_commit_sha: str
    created_at: datetime
    release_pr_number: Optional[int] = None


class ReleaseStateManager:
    """
    Manages release state derivation from repository artifacts.

    This class examines repository artifacts (tags, branches, releases,
    release-plan.yaml) to determine the current state of a release.
    All operations are read-only.
    """

    def __init__(self, github_client: GitHubClient):
        """
        Initialize the state manager.

        Args:
            github_client: GitHubClient instance for repository operations
        """
        self.gh = github_client

    def derive_state(self, release_tag: str) -> ReleaseState:
        """
        Derive the current release state from repository artifacts.

        The derivation follows this priority order:
        1. If tag exists → PUBLISHED
        2. If snapshot branch exists:
           - If draft release exists → DRAFT_READY
           - Otherwise → SNAPSHOT_ACTIVE
        3. If release-plan.yaml defines this release:
           - If target_release_type is "none" → CANCELLED
           - Otherwise → PLANNED
        4. Default → CANCELLED

        Args:
            release_tag: Release tag to check (e.g., "r4.1")

        Returns:
            Current ReleaseState for the given release tag
        """
        # Step 1: Check if tag exists → PUBLISHED
        if self.gh.tag_exists(release_tag):
            return ReleaseState.PUBLISHED

        # Step 2: Check for snapshot branch
        snapshot_branches = self.gh.list_branches(f"release-snapshot/{release_tag}-*")

        if snapshot_branches:
            # Step 3: Check for draft release
            if self.gh.draft_release_exists(release_tag):
                return ReleaseState.DRAFT_READY
            return ReleaseState.SNAPSHOT_ACTIVE

        # Step 4: No snapshot - check release-plan.yaml for PLANNED state
        plan = self._read_release_plan()
        if plan:
            target_tag = plan.get("repository", {}).get("target_release_tag")
            release_type = plan.get("repository", {}).get("target_release_type")

            if target_tag == release_tag:
                if release_type and release_type.lower() != "none":
                    return ReleaseState.PLANNED
                elif release_type and release_type.lower() == "none":
                    return ReleaseState.CANCELLED

        return ReleaseState.CANCELLED

    def get_current_snapshot(self, release_tag: str) -> Optional[SnapshotInfo]:
        """
        Get information about the current active snapshot for a release.

        If multiple snapshot branches exist for the same release tag,
        returns the most recent one (by branch creation time).

        Args:
            release_tag: Release tag to check (e.g., "r4.1")

        Returns:
            SnapshotInfo if a snapshot exists, None otherwise
        """
        branches = self.gh.list_branches(f"release-snapshot/{release_tag}-*")

        if not branches:
            return None

        # Use the first (or only) matching branch
        # In practice, there should only be one active snapshot per release
        branch = branches[0]
        branch_name = branch.name

        # Derive snapshot_id from branch name
        # release-snapshot/r4.1-abc1234 → r4.1-abc1234
        snapshot_id = branch_name.replace("release-snapshot/", "")

        # Read release-metadata.yaml from the snapshot branch
        metadata = self._read_release_metadata(branch_name)

        # Get the base commit SHA from metadata or branch
        if metadata:
            base_commit_sha = metadata.get("repository", {}).get("src_commit_sha", branch.sha)
        else:
            base_commit_sha = branch.sha

        # Get branch creation time (approximated)
        created_at_str = self.gh.get_branch_creation_time(branch_name)
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now()
        else:
            created_at = datetime.now()

        # Find the Release PR for this snapshot branch
        release_review_branch = f"release-review/{snapshot_id}"
        release_pr_number = self.gh.find_pr_for_branch(release_review_branch)

        return SnapshotInfo(
            snapshot_id=snapshot_id,
            snapshot_branch=branch_name,
            release_review_branch=release_review_branch,
            base_commit_sha=base_commit_sha,
            created_at=created_at,
            release_pr_number=release_pr_number
        )

    def get_snapshot_history(self, release_tag: str) -> List[SnapshotInfo]:
        """
        Get history of all snapshots for a release.

        This includes both active and discarded snapshots. Discarded
        snapshots may have their branches deleted but can be identified
        from release-review branches or issue history.

        Args:
            release_tag: Release tag to check (e.g., "r4.1")

        Returns:
            List of SnapshotInfo objects, ordered by creation time (newest first)
        """
        # For now, just return the current snapshot if it exists
        # Full history tracking will be implemented with issue_sync.py
        current = self.get_current_snapshot(release_tag)
        if current:
            return [current]
        return []

    def _read_release_plan(self, ref: str = "main") -> Optional[dict]:
        """
        Read and parse release-plan.yaml from the repository.

        Args:
            ref: Branch, tag, or commit to read from

        Returns:
            Parsed YAML content as dict, or None if file doesn't exist
        """
        content = self.gh.get_file_content("release-plan.yaml", ref)
        if not content:
            return None

        try:
            return yaml.safe_load(content)
        except yaml.YAMLError:
            return None

    def _read_release_metadata(self, ref: str) -> Optional[dict]:
        """
        Read and parse release-metadata.yaml from a branch.

        Args:
            ref: Branch, tag, or commit to read from

        Returns:
            Parsed YAML content as dict, or None if file doesn't exist
        """
        content = self.gh.get_file_content("release-metadata.yaml", ref)
        if not content:
            return None

        try:
            return yaml.safe_load(content)
        except yaml.YAMLError:
            return None
