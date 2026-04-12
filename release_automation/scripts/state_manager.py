"""
Release state manager for CAMARA release automation.

This module provides the core state derivation logic that determines
the current release state by examining repository artifacts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import time
from typing import Any, Dict, List, Optional

import yaml

from .github_client import GitHubClient
from . import config


# Constants for release issue identification (duplicated from issue_sync to avoid circular imports)
WORKFLOW_MARKER = "<!-- release-automation:workflow-owned -->"
RELEASE_ISSUE_LABEL = "release-issue"


class ReleaseState(Enum):
    """
    Possible states for a CAMARA release.

    State Transition Flow:
        PLANNED → SNAPSHOT_ACTIVE → DRAFT_READY → PUBLISHED
                                 ↘ (discard)
        Any state can transition to NOT_PLANNED via release-plan.yaml changes
    """
    PLANNED = config.STATE_PLANNED                # release-plan.yaml defines intent
    SNAPSHOT_ACTIVE = config.STATE_SNAPSHOT_ACTIVE  # Snapshot branch exists
    DRAFT_READY = config.STATE_DRAFT_READY        # Draft release created
    PUBLISHED = config.STATE_PUBLISHED            # Tag exists (final state)
    NOT_PLANNED = config.STATE_NOT_PLANNED        # target_release_type set to "none"


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
        src_commit_sha: The commit SHA the snapshot was created from
        created_at: When the snapshot was created
        release_pr_number: PR number if Release PR exists
        release_type: Release type from release-metadata.yaml
        apis: API metadata from release-metadata.yaml
        commonalities_release: From release-metadata.yaml dependencies
        identity_consent_management_release: From release-metadata.yaml dependencies
    """
    snapshot_id: str
    snapshot_branch: str
    release_review_branch: str
    src_commit_sha: str
    created_at: datetime
    release_pr_number: Optional[int] = None
    release_type: str = ""
    apis: List[Dict[str, str]] = field(default_factory=list)
    commonalities_release: str = ""
    identity_consent_management_release: str = ""


@dataclass
class ConfigurationError:
    """
    Details about a configuration error that prevents state derivation.

    Configuration errors are distinct from the NOT_PLANNED state - they indicate
    the repository configuration is broken, not that no release is planned.

    Attributes:
        error_type: Category of error ('missing_file', 'malformed_yaml', 'missing_field')
        message: Human-readable error description
        file_path: Which file has the problem
        field_path: Dot-separated path to problematic field (e.g., "repository.target_release_tag")
    """
    error_type: str  # 'missing_file', 'malformed_yaml', 'missing_field'
    message: str
    file_path: str
    field_path: Optional[str] = None


@dataclass
class ReleaseInfoResult:
    """
    Result of derive_state() call.

    Distinguishes between:
    - Success: Valid state derived from repository artifacts
    - Error: Configuration problem that prevents state derivation

    The key insight: configuration errors are NOT a state. They are a
    failure mode that should be surfaced to the user for correction.
    """
    success: bool
    release_tag: Optional[str] = None
    state: Optional[ReleaseState] = None
    snapshot_branch: Optional[str] = None
    source: Optional[str] = None  # 'release-plan.yaml' | 'release-metadata.yaml' | 'tag'
    config_error: Optional[ConfigurationError] = None
    release_issue_number: Optional[int] = None  # GitHub issue number if found
    release_type: Optional[str] = None  # Release type if available
    meta_release: Optional[str] = None  # Meta-release name (e.g., "Sync26")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dict for backward compatibility and workflow outputs.

        Returns:
            Dict with release info or error details
        """
        if self.success:
            return {
                "release_tag": self.release_tag,
                "state": self.state,
                "snapshot_branch": self.snapshot_branch,
                "source": self.source,
                "config_error": None,
                "config_error_type": None,
                "release_issue_number": self.release_issue_number,
                "release_type": self.release_type,
                "meta_release": self.meta_release,
            }
        else:
            return {
                "release_tag": None,
                "state": None,  # NOT NOT_PLANNED - this is an error, not a state
                "snapshot_branch": None,
                "source": None,
                "config_error": self.config_error.message if self.config_error else "Unknown error",
                "config_error_type": self.config_error.error_type if self.config_error else "unknown",
                "release_issue_number": None,
                "release_type": None,
                "meta_release": None,
            }


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

    def derive_state(
        self,
        retry_draft_release: bool = False
    ) -> ReleaseInfoResult:
        """
        Derive the current release state and tag from repository artifacts.

        This is the single entry point for state derivation. It determines
        the release_tag from the authoritative source and derives the state:

        1. Read and validate release-plan.yaml (config errors → failure)
        2. If tag exists → PUBLISHED
        3. If snapshot branch exists:
           - Read release_tag from release-metadata.yaml on snapshot
           - If draft release exists → DRAFT_READY
           - Otherwise → SNAPSHOT_ACTIVE
        4. If release-plan.yaml target_release_type != "none" → PLANNED
        5. Otherwise → NOT_PLANNED

        Args:
            retry_draft_release: Retry draft-release detection for eventual
                consistency (useful when called right after draft creation)

        Returns:
            ReleaseInfoResult with either:
                - success=True: release_tag, state, snapshot_branch, source
                - success=False: config_error with details
        """
        # Step 1: Read and validate release-plan.yaml
        plan, config_error = self._read_release_plan_with_validation()

        if config_error:
            return ReleaseInfoResult(success=False, config_error=config_error)

        plan_release_tag = plan["repository"]["target_release_tag"]
        plan_release_type = plan["repository"].get("target_release_type")
        meta_release = plan["repository"].get("meta_release")

        # Step 2: Check if tag exists → PUBLISHED
        if self.gh.tag_exists(plan_release_tag):
            return ReleaseInfoResult(
                success=True,
                release_tag=plan_release_tag,
                state=ReleaseState.PUBLISHED,
                snapshot_branch=None,
                source="tag",
                release_issue_number=self.find_release_issue(plan_release_tag),
                release_type=plan_release_type,
                meta_release=meta_release,
            )

        # Step 3: Check for snapshot branches
        snapshot_branches = self.gh.list_branches(
            f"{config.SNAPSHOT_BRANCH_PREFIX}{plan_release_tag}-*"
        )

        if snapshot_branches:
            snapshot_branch = snapshot_branches[0].name
            metadata = self._read_release_metadata(snapshot_branch)

            if metadata:
                metadata_release_tag = metadata.get(
                    "repository", {}
                ).get("release_tag")
                metadata_release_type = metadata.get(
                    "repository", {}
                ).get("release_type")
            else:
                # Fall back to extracting from branch name
                snapshot_id = snapshot_branch.replace(
                    config.SNAPSHOT_BRANCH_PREFIX, ""
                )
                metadata_release_tag = (
                    snapshot_id.split("-")[0] if "-" in snapshot_id
                    else snapshot_id
                )
                metadata_release_type = None

            effective_tag = metadata_release_tag or plan_release_tag

            # Check for draft release
            if self._draft_release_exists(
                effective_tag, retry=retry_draft_release
            ):
                state = ReleaseState.DRAFT_READY
            else:
                state = ReleaseState.SNAPSHOT_ACTIVE

            return ReleaseInfoResult(
                success=True,
                release_tag=effective_tag,
                state=state,
                snapshot_branch=snapshot_branch,
                source="release-metadata.yaml",
                release_issue_number=self.find_release_issue(effective_tag),
                release_type=metadata_release_type,
                meta_release=meta_release,
            )

        # Step 4: No snapshot — use release-plan.yaml state
        if plan_release_type and plan_release_type.lower() != "none":
            state = ReleaseState.PLANNED
        else:
            state = ReleaseState.NOT_PLANNED

        return ReleaseInfoResult(
            success=True,
            release_tag=plan_release_tag,
            state=state,
            snapshot_branch=None,
            source="release-plan.yaml",
            release_issue_number=self.find_release_issue(plan_release_tag),
            release_type=plan_release_type,
            meta_release=meta_release,
        )

    def _draft_release_exists(self, release_tag: str, retry: bool = False) -> bool:
        """
        Check if a draft release exists, optionally retrying for eventual consistency.

        Args:
            release_tag: Release tag to check (e.g., "r4.1")
            retry: Whether to retry draft-release detection

        Returns:
            True if a draft release exists, False otherwise
        """
        attempts = 3 if retry else 1

        for attempt in range(attempts):
            if self.gh.draft_release_exists(release_tag):
                return True

            if attempt < attempts - 1:
                time.sleep(5)

        return False

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
        branches = self.gh.list_branches(f"{config.SNAPSHOT_BRANCH_PREFIX}{release_tag}-*")

        if not branches:
            return None

        # Use the first (or only) matching branch
        # In practice, there should only be one active snapshot per release
        branch = branches[0]
        branch_name = branch.name

        # Derive snapshot_id from branch name
        # release-snapshot/r4.1-abc1234 → r4.1-abc1234
        snapshot_id = branch_name.replace(config.SNAPSHOT_BRANCH_PREFIX, "")

        # Read release-metadata.yaml from the snapshot branch
        metadata = self._read_release_metadata(branch_name)

        # Extract data from metadata (or use defaults)
        if metadata:
            repo_section = metadata.get("repository", {})
            src_commit_sha = repo_section.get("src_commit_sha", branch.sha)
            release_type = repo_section.get("release_type", "")
            apis = metadata.get("apis", [])
            deps = metadata.get("dependencies", {})
            commonalities_release = deps.get("commonalities_release", "")
            identity_consent_management_release = deps.get(
                "identity_consent_management_release", ""
            )
        else:
            src_commit_sha = branch.sha
            release_type = ""
            apis = []
            commonalities_release = ""
            identity_consent_management_release = ""

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
        release_review_branch = f"{config.RELEASE_REVIEW_BRANCH_PREFIX}{snapshot_id}"
        release_pr_number = self.gh.find_pr_for_branch(release_review_branch)

        return SnapshotInfo(
            snapshot_id=snapshot_id,
            snapshot_branch=branch_name,
            release_review_branch=release_review_branch,
            src_commit_sha=src_commit_sha,
            created_at=created_at,
            release_pr_number=release_pr_number,
            release_type=release_type,
            apis=apis,
            commonalities_release=commonalities_release,
            identity_consent_management_release=identity_consent_management_release,
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

    def find_release_issue(self, release_tag: str) -> Optional[int]:
        """
        Find the Release Issue number for a given release tag.

        Searches for open issues with the 'release-issue' label that:
        1. Contain the WORKFLOW_MARKER in the body (workflow-owned)
        2. Have the release_tag in the title

        Args:
            release_tag: Release tag to search for (e.g., "r4.1")

        Returns:
            Issue number if found, None otherwise
        """
        issues = self.gh.search_issues(
            labels=[RELEASE_ISSUE_LABEL],
            state="open"
        )

        for issue in issues:
            body = issue.get("body", "") or ""
            title = issue.get("title", "") or ""

            # Check for workflow marker
            if WORKFLOW_MARKER not in body:
                continue

            # Check for release tag in title
            if release_tag in title:
                return issue.get("number")

        return None

    def _read_release_plan_with_validation(
        self, ref: str = "main"
    ) -> tuple[Optional[dict], Optional[ConfigurationError]]:
        """
        Read and validate release-plan.yaml from the repository.

        This method distinguishes between different error conditions:
        - File not found
        - YAML parse error
        - Missing required fields

        Args:
            ref: Branch, tag, or commit to read from

        Returns:
            Tuple of (parsed_content, error):
                - (dict, None) if successful
                - (None, ConfigurationError) if error
        """
        content = self.gh.get_file_content(config.RELEASE_PLAN_FILE, ref)

        if content is None:
            return None, ConfigurationError(
                error_type="missing_file",
                message=f"No {config.RELEASE_PLAN_FILE} found on {ref} branch",
                file_path=config.RELEASE_PLAN_FILE
            )

        # Try to parse YAML
        try:
            plan = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return None, ConfigurationError(
                error_type="malformed_yaml",
                message=f"Invalid YAML syntax in {config.RELEASE_PLAN_FILE}: {e}",
                file_path=config.RELEASE_PLAN_FILE
            )

        # Validate plan is a dict (not null or other type)
        if not isinstance(plan, dict):
            return None, ConfigurationError(
                error_type="malformed_yaml",
                message=f"{config.RELEASE_PLAN_FILE} must contain a YAML mapping (not empty or scalar)",
                file_path=config.RELEASE_PLAN_FILE
            )

        # Validate required fields
        repository = plan.get("repository")
        if not repository or not isinstance(repository, dict):
            return None, ConfigurationError(
                error_type="missing_field",
                message=f"Missing 'repository' section in {config.RELEASE_PLAN_FILE}",
                file_path=config.RELEASE_PLAN_FILE,
                field_path="repository"
            )

        target_release_tag = repository.get("target_release_tag")
        if not target_release_tag:
            return None, ConfigurationError(
                error_type="missing_field",
                message=f"Missing 'target_release_tag' in {config.RELEASE_PLAN_FILE} repository section",
                file_path=config.RELEASE_PLAN_FILE,
                field_path="repository.target_release_tag"
            )

        return plan, None

    def _read_release_metadata(self, ref: str) -> Optional[dict]:
        """
        Read and parse release-metadata.yaml from a branch.

        Args:
            ref: Branch, tag, or commit to read from

        Returns:
            Parsed YAML content as dict, or None if file doesn't exist or is invalid
        """
        content = self.gh.get_file_content(config.RELEASE_METADATA_FILE, ref)
        if not content:
            return None

        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse {config.RELEASE_METADATA_FILE} from {ref}: {e}")
            return None
