"""
Release state manager for CAMARA release automation.

This module provides the core state derivation logic that determines
the current release state by examining repository artifacts.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional

import yaml

from .github_client import GitHubClient
from .release_line import line_of
from .trigger import RELEASE_TAG_MARKER_RE
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
    error_type: str  # 'missing_file', 'malformed_yaml', 'missing_field', 'release_line'
    message: str
    file_path: str
    field_path: Optional[str] = None


@dataclass
class ReleaseInfoResult:
    """
    Result of derive_state(): the release of a base branch.

    Distinguishes between:
    - Success: Valid state derived from repository artifacts
    - Error: Configuration problem that prevents state derivation

    Configuration errors are NOT a state. They are a failure mode that is
    surfaced to the user for correction.

    With a snapshot (SNAPSHOT_ACTIVE, DRAFT_READY) the snapshot fields come
    from the snapshot branch and its release-metadata.yaml; without one, apis
    and the dependency releases come from release-plan.yaml (api_version is
    then the target version).
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
    base_branch: str = ""  # Branch whose release-plan.yaml was read (set by derive_state)
    # Snapshot details (release-metadata.yaml of the snapshot branch)
    snapshot_id: str = ""
    release_review_branch: str = ""
    release_pr_number: Optional[int] = None
    src_commit_sha: str = ""
    draft_release_url: str = ""  # DRAFT_READY only
    # API and dependency details (release-metadata.yaml, else release-plan.yaml)
    apis: List[Dict[str, str]] = field(default_factory=list)
    commonalities_release: str = ""
    identity_consent_management_release: str = ""


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
        base_branch: str,
        retry_draft_release: bool = False,
    ) -> ReleaseInfoResult:
        """
        Derive the current release state and tag from repository artifacts.

        This is the single entry point for state derivation. It determines
        the release_tag from the authoritative source and derives the state:

        1. Read and validate release-plan.yaml of base_branch (config errors
           → failure); its target_release_tag must be on that line (line_of)
        2. If tag exists → PUBLISHED
        3. If snapshot branch exists:
           - Read release_tag from release-metadata.yaml on snapshot
           - If draft release exists → DRAFT_READY
           - Otherwise → SNAPSHOT_ACTIVE
        4. If release-plan.yaml target_release_type != "none" → PLANNED
        5. Otherwise → NOT_PLANNED

        Args:
            base_branch: Branch whose release-plan.yaml defines the release
            retry_draft_release: Retry draft-release detection for eventual
                consistency (useful when called right after draft creation)

        Returns:
            ReleaseInfoResult with either:
                - success=True: release_tag, state, snapshot_branch, source
                - success=False: config_error with details
        """
        # Step 1: Read and validate release-plan.yaml
        plan, config_error = self._read_release_plan_with_validation(base_branch)

        if config_error:
            return ReleaseInfoResult(success=False, config_error=config_error, base_branch=base_branch)

        plan_release_tag = plan["repository"]["target_release_tag"]
        line = line_of(self.gh, plan_release_tag)
        if line != base_branch:
            return ReleaseInfoResult(success=False, base_branch=base_branch, config_error=ConfigurationError(
                error_type="release_line",
                message=(
                    f"{config.RELEASE_PLAN_FILE} on {base_branch} targets {plan_release_tag}, "
                    f"which is released from {line}. Plan it on {line}, or plan another tag here."
                ),
                file_path=config.RELEASE_PLAN_FILE,
                field_path="repository.target_release_tag",
            ))
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
                base_branch=base_branch,
                **self._plan_details(plan),
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

            snapshot_id = snapshot_branch[len(config.SNAPSHOT_BRANCH_PREFIX):]
            review_branch = f"{config.RELEASE_REVIEW_BRANCH_PREFIX}{snapshot_id}"
            repo_section = (metadata or {}).get("repository") or {}
            deps = (metadata or {}).get("dependencies") or {}
            return ReleaseInfoResult(
                success=True,
                release_tag=effective_tag,
                state=state,
                snapshot_branch=snapshot_branch,
                source="release-metadata.yaml",
                release_issue_number=self.find_release_issue(effective_tag),
                release_type=metadata_release_type,
                meta_release=meta_release,
                base_branch=base_branch,
                snapshot_id=snapshot_id,
                release_review_branch=review_branch,
                release_pr_number=self.gh.find_pr_for_branch(review_branch),
                src_commit_sha=repo_section.get("src_commit_sha") or snapshot_branches[0].sha,
                draft_release_url=self._draft_release_url(effective_tag) if state == ReleaseState.DRAFT_READY else "",
                apis=list((metadata or {}).get("apis") or []),
                commonalities_release=deps.get("commonalities_release", "") or "",
                identity_consent_management_release=deps.get("identity_consent_management_release", "") or "",
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
            base_branch=base_branch,
            **self._plan_details(plan),
        )

    @staticmethod
    def _plan_details(plan: dict) -> Dict[str, Any]:
        """apis and dependency releases of a release-plan.yaml (no snapshot)."""
        deps = plan.get("dependencies") or {}
        return {
            "apis": [
                {"api_name": api.get("api_name", ""), "api_version": api.get("target_api_version", "")}
                for api in plan.get("apis") or []
            ],
            "commonalities_release": deps.get("commonalities_release", "") or "",
            "identity_consent_management_release": deps.get("identity_consent_management_release", "") or "",
        }

    def _draft_release_url(self, release_tag: str) -> str:
        release = self.gh.get_draft_release(release_tag)
        return release.html_url if release else ""

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

    def find_release_issue(self, release_tag: str) -> Optional[int]:
        """
        Find the Release Issue number for a given release tag.

        Searches for open issues with the 'release-issue' label that:
        1. Contain the WORKFLOW_MARKER in the body (workflow-owned)
        2. Carry exactly this tag in their release-tag marker (the title is
           for readers; "r1.1" is a substring of "Release r1.10")

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
            if WORKFLOW_MARKER not in body:
                continue
            match = RELEASE_TAG_MARKER_RE.search(body)
            if match and match.group("tag") == release_tag:
                return issue.get("number")

        return None

    def _read_release_plan_with_validation(
        self, ref: str
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


def main(client=None) -> int:
    """
    Workflow step of validation.yml (P-033): the active release state of a branch.

    Outputs state, snapshot_branch and release_issue_number; all empty on a
    configuration error, which is logged as a warning (validation decides).

    Usage:
        python3 -m release_automation.scripts.state_manager
    """
    import os

    from .trigger import write_outputs

    env = os.environ
    if client is None:
        client = GitHubClient(repo=env["GITHUB_REPOSITORY"], token=env.get("GITHUB_TOKEN"))
    base_branch = env["BASE_BRANCH"]
    info = ReleaseStateManager(client).derive_state(base_branch)
    if not info.success:
        print(f"::warning::Configuration error: {info.config_error.message}")
    else:
        print(f"Release {info.release_tag}: {info.state.value} on {base_branch}")
    write_outputs(env["GITHUB_OUTPUT"], {
        "state": info.state.value if info.state else "",
        "snapshot_branch": info.snapshot_branch or "",
        "release_issue_number": str(info.release_issue_number or ""),
    })
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
