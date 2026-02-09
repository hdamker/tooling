"""
Issue synchronization for CAMARA release automation.

This module provides functionality for creating and synchronizing
workflow-owned Release Issues based on state derivation from repository
artifacts.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .github_client import GitHubClient
from .state_manager import ReleaseState, ReleaseStateManager
from .issue_manager import IssueManager
from .bot_responder import BotResponder


# Marker to identify workflow-owned issues
WORKFLOW_MARKER = "<!-- release-automation:workflow-owned -->"

# Required labels for release automation
# Format: (name, color_hex_without_hash, description)
REQUIRED_LABELS = [
    ("release-issue", "5319E7", "Release tracking issue managed by automation"),
    ("release-state:planned", "0E8A16", "Release is planned"),
    ("release-state:snapshot-active", "FBCA04", "Release snapshot is active"),
    ("release-state:draft-ready", "1D76DB", "Draft release is ready"),
    ("release-state:published", "0E8A16", "Release has been published"),
    ("release-state:not-planned", "C2C9D1", "No release is currently planned"),
]


@dataclass
class SyncResult:
    """
    Result of a Release Issue synchronization operation.

    Attributes:
        action: Action taken ('created', 'updated', 'none')
        issue: Issue dict if an issue was created or updated
        reason: Reason when action is 'none' (e.g., 'up_to_date', 'no_planned_release')
    """
    action: str  # 'created', 'updated', 'none'
    issue: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class IssueSyncManager:
    """
    Manages synchronization of workflow-owned Release Issues.

    This class is responsible for:
    - Creating Release Issues when a PLANNED state is detected
    - Updating issue sections and labels when state changes
    - Finding existing workflow-owned issues
    - Ignoring manually-created issues

    Only issues containing the WORKFLOW_MARKER are managed by this class.
    Manually created issues are completely ignored.
    """

    # Labels used for Release Issues
    RELEASE_ISSUE_LABEL = "release-issue"
    STATE_LABEL_PREFIX = "release-state:"

    def __init__(
        self,
        github_client: GitHubClient,
        state_manager: Optional[ReleaseStateManager] = None,
        issue_manager: Optional[IssueManager] = None,
        bot_responder: Optional[BotResponder] = None
    ):
        """
        Initialize the issue sync manager.

        Args:
            github_client: GitHubClient for repository operations
            state_manager: ReleaseStateManager for state derivation (optional for close_release_issue)
            issue_manager: IssueManager for issue content management (optional for close_release_issue)
            bot_responder: BotResponder for message templates (optional for close_release_issue)
        """
        self.gh = github_client
        self.state_manager = state_manager
        self.issue_manager = issue_manager
        self.bot = bot_responder
        self._labels_ensured = False  # Track if we've already ensured labels

    def ensure_labels_exist(self) -> List[str]:
        """
        Ensure all required labels exist in the repository.

        Creates any missing labels with the correct colors and descriptions.
        This method is idempotent and caches its result within the instance.

        Returns:
            List of labels that were created (empty if all existed)
        """
        if self._labels_ensured:
            return []

        created = []
        for name, color, description in REQUIRED_LABELS:
            existing = self.gh.get_label(name)
            if existing is None:
                self.gh.create_label(name, color, description)
                created.append(name)

        self._labels_ensured = True
        return created

    def sync_release_issue(
        self,
        release_plan: Dict[str, Any],
        trigger_pr: Optional[int] = None
    ) -> SyncResult:
        """
        Ensure Release Issue exists and reflects current state.

        This method:
        1. Derives the current release state from repository artifacts
        2. Finds any existing workflow-owned issue for this release
        3. Creates a new issue if PLANNED and no issue exists
        4. Updates the issue if state or content has changed

        Args:
            release_plan: Parsed release-plan.yaml content
            trigger_pr: Optional PR number that triggered the sync

        Returns:
            SyncResult with action taken and issue details
        """
        release_tag = release_plan.get("repository", {}).get("target_release_tag", "")
        if not release_tag:
            return SyncResult(action="none", reason="missing_release_tag")

        # Ensure required labels exist before any label operations
        self.ensure_labels_exist()

        # Derive current state
        state = self.state_manager.derive_state(release_tag)

        # Find existing workflow-owned issue
        issue = self.find_workflow_owned_issue(release_tag)

        if issue is None:
            # No workflow-owned issue exists
            if state == ReleaseState.PLANNED:
                # Create new Release Issue
                new_issue = self.create_release_issue(release_plan, trigger_pr)
                # Populate sections with initial content and refetch.
                # Wrapped in retry_on_not_found because GitHub API may
                # return 404 for a freshly created issue (eventual consistency).
                def _post_create():
                    self._update_release_issue(new_issue, state, release_plan)
                    return self.gh.get_issue(new_issue["number"])
                updated_issue = self.gh.retry_on_not_found(_post_create)
                return SyncResult(action="created", issue=updated_issue)
            else:
                return SyncResult(action="none", reason="no_planned_release")

        # Issue exists - check if update needed
        if self._needs_update(issue, state, release_plan):
            self._update_release_issue(issue, state, release_plan)
            # Refetch issue after update
            updated_issue = self.gh.get_issue(issue["number"])
            return SyncResult(action="updated", issue=updated_issue)

        return SyncResult(action="none", reason="up_to_date")

    def find_workflow_owned_issue(self, release_tag: str) -> Optional[Dict[str, Any]]:
        """
        Find an existing workflow-owned issue for the given release.

        Searches for open issues with the 'release-issue' label, then
        filters to find one that:
        1. Contains the WORKFLOW_MARKER in its body
        2. Has the release_tag in its title

        Args:
            release_tag: Release tag to search for (e.g., "r4.1")

        Returns:
            Issue dict if found, None otherwise
        """
        issues = self.gh.search_issues(
            labels=[self.RELEASE_ISSUE_LABEL],
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
                return issue

        return None

    def create_release_issue(
        self,
        release_plan: Dict[str, Any],
        trigger_pr: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a new workflow-owned Release Issue.

        Args:
            release_plan: Parsed release-plan.yaml content
            trigger_pr: Optional PR number that triggered creation

        Returns:
            Dict with created issue details
        """
        repo_config = release_plan.get("repository", {})
        release_tag = repo_config.get("target_release_tag", "")
        release_type = repo_config.get("target_release_type", "")
        meta_release = repo_config.get("meta_release")

        # Generate title
        title = self.issue_manager.generate_title(
            release_tag=release_tag,
            release_type=release_type,
            meta_release=meta_release
        )

        # Generate body using the template
        body = self.issue_manager.generate_issue_body_template(
            release_tag=release_tag,
            release_type=release_type,
            meta_release=meta_release
        )

        # Ensure the workflow marker is in the body
        if WORKFLOW_MARKER not in body:
            # Insert marker after first heading
            lines = body.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('##') or line.startswith('#'):
                    lines.insert(i + 1, f"\n{WORKFLOW_MARKER}\n")
                    break
            else:
                # No heading found, prepend
                lines.insert(0, f"{WORKFLOW_MARKER}\n")
            body = '\n'.join(lines)

        # Create labels
        labels = [
            self.RELEASE_ISSUE_LABEL,
            f"{self.STATE_LABEL_PREFIX}planned"
        ]

        # Create the issue
        return self.gh.create_issue(
            title=title,
            body=body,
            labels=labels
        )

    def _needs_update(
        self,
        issue: Dict[str, Any],
        state: ReleaseState,
        release_plan: Dict[str, Any]
    ) -> bool:
        """
        Check if an issue needs updating based on state or plan changes.

        Args:
            issue: Current issue dict
            state: Current derived state
            release_plan: Current release plan

        Returns:
            True if issue needs updating
        """
        # Check if state label matches
        current_labels = [
            label.get("name", "") if isinstance(label, dict) else label
            for label in issue.get("labels", [])
        ]

        expected_state_label = self.get_state_label(state)

        # Check if the expected state label is present
        state_labels = [l for l in current_labels if l.startswith(self.STATE_LABEL_PREFIX)]
        if expected_state_label not in current_labels:
            return True

        # Check if title needs updating
        current_title = issue.get("title", "")
        if self.issue_manager.should_update_title(current_title, release_plan):
            return True

        return False

    def _update_release_issue(
        self,
        issue: Dict[str, Any],
        state: ReleaseState,
        release_plan: Dict[str, Any]
    ) -> None:
        """
        Update an existing Release Issue to match current state.

        Updates:
        - State label (removes old, adds new)
        - STATE section content (with artifact links)
        - CONFIG section content (API versions, dependencies)
        - ACTIONS section content (valid commands)
        - Title if needed

        Args:
            issue: Issue dict to update
            state: Current derived state
            release_plan: Current release plan
        """
        issue_number = issue["number"]
        release_tag = release_plan.get("repository", {}).get("target_release_tag", "")

        # Update state label
        current_labels = [
            label.get("name", "") if isinstance(label, dict) else label
            for label in issue.get("labels", [])
        ]

        # Remove old state labels
        old_state_labels = [
            l for l in current_labels
            if l.startswith(self.STATE_LABEL_PREFIX)
        ]
        if old_state_labels:
            self.gh.remove_labels(issue_number, old_state_labels)

        # Add new state label
        new_state_label = self.get_state_label(state)
        self.gh.add_labels(issue_number, [new_state_label])

        # Get snapshot info and artifact URLs
        snapshot = self.state_manager.get_current_snapshot(release_tag)
        snapshot_id = snapshot.snapshot_id if snapshot else ""
        snapshot_branch = snapshot.snapshot_branch if snapshot else ""
        release_pr_url = ""
        draft_release_url = ""
        snapshot_branch_url = ""

        if snapshot and snapshot.release_pr_number:
            # Construct PR URL
            release_pr_url = f"https://github.com/{self.gh.repo}/pull/{snapshot.release_pr_number}"

        if snapshot_branch:
            # Construct snapshot branch tree URL
            snapshot_branch_url = f"https://github.com/{self.gh.repo}/tree/{snapshot_branch}"

        # Get draft release URL if in draft-ready state
        if state == ReleaseState.DRAFT_READY:
            draft_release_url = self._get_draft_release_url(release_tag)

        # Update STATE section with artifact links
        new_state_content = self.issue_manager.generate_state_section(
            state=state.value,
            snapshot_id=snapshot_id,
            release_pr_url=release_pr_url,
            draft_release_url=draft_release_url,
            snapshot_branch_url=snapshot_branch_url
        )
        current_body = issue.get("body", "")
        updated_body = self.issue_manager.update_section(
            current_body, "STATE", new_state_content
        )

        # Update CONFIG section with API versions and dependencies
        api_versions = {}
        commonalities_release = ""
        icm_release = ""
        if snapshot:
            # Extract calculated versions from snapshot APIs
            for api in snapshot.apis:
                api_name = api.get("api_name", "")
                api_version = api.get("api_version", "")
                if api_name and api_version:
                    api_versions[api_name] = api_version
            commonalities_release = snapshot.commonalities_release
            icm_release = snapshot.identity_consent_management_release
        else:
            # No snapshot - get dependencies from release_plan
            deps = release_plan.get("dependencies", {})
            commonalities_release = deps.get("commonalities_release", "")
            icm_release = deps.get("identity_consent_management_release", "")

        new_config_content = self.issue_manager.generate_config_section(
            release_plan=release_plan,
            api_versions=api_versions,
            commonalities_release=commonalities_release,
            icm_release=icm_release
        )
        updated_body = self.issue_manager.update_section(
            updated_body, "CONFIG", new_config_content
        )

        # Update ACTIONS section with valid commands
        new_actions_content = self.issue_manager.generate_actions_section(
            state=state.value,
            release_pr_url=release_pr_url,
            release_tag=release_tag
        )
        updated_body = self.issue_manager.update_section(
            updated_body, "ACTIONS", new_actions_content
        )

        # Check if title needs updating
        new_title = None
        if self.issue_manager.should_update_title(issue.get("title", ""), release_plan):
            repo_config = release_plan.get("repository", {})
            new_title = self.issue_manager.generate_title(
                release_tag=repo_config.get("target_release_tag", ""),
                release_type=repo_config.get("target_release_type", ""),
                meta_release=repo_config.get("meta_release")
            )

        # Update issue
        self.gh.update_issue(
            issue_number=issue_number,
            title=new_title,
            body=updated_body if updated_body != current_body else None
        )

    def _get_draft_release_url(self, release_tag: str) -> str:
        """
        Get the URL of the draft release for a given tag.

        Args:
            release_tag: Release tag to search for

        Returns:
            Draft release URL if found, empty string otherwise
        """
        try:
            releases = self.gh.get_releases(include_drafts=True)
            for release in releases:
                if release.draft and release.tag_name == release_tag:
                    return release.html_url
        except Exception:
            pass
        return ""

    def get_state_label(self, state: ReleaseState) -> str:
        """
        Get the label name for a given state.

        Args:
            state: The release state

        Returns:
            Label name (e.g., "release-state:planned")
        """
        return f"{self.STATE_LABEL_PREFIX}{state.value.replace('_', '-')}"

    def close_release_issue(
        self,
        issue_number: int,
        release_tag: str,
        release_url: str,
        reference_tag: str,
        sync_pr_url: str = ""
    ) -> bool:
        """
        Update and close Release Issue after publication.

        Steps:
        1. Update STATE section with publication info
        2. Update ACTIONS section (no actions available)
        3. Change label to release-state:published
        4. Close issue with reason "completed"

        Args:
            issue_number: Issue number to close
            release_tag: Release tag (e.g., "r4.1")
            release_url: URL to the published release
            reference_tag: Reference tag (e.g., "src/r4.1")
            sync_pr_url: Optional URL to the post-release sync PR

        Returns:
            True if successful, False on error
        """
        try:
            # Get current issue
            issue = self.gh.get_issue(issue_number)
            current_body = issue.get("body", "")

            # Update STATE section
            new_state_content = self.issue_manager.generate_published_state_section(
                release_tag=release_tag,
                release_url=release_url,
                reference_tag=reference_tag,
                sync_pr_url=sync_pr_url or None
            )
            updated_body = self.issue_manager.update_section(
                current_body, "STATE", new_state_content
            )

            # Update ACTIONS section
            new_actions_content = self.issue_manager.generate_published_actions_section()
            updated_body = self.issue_manager.update_section(
                updated_body, "ACTIONS", new_actions_content
            )

            # Update issue body if changed
            if updated_body != current_body:
                self.gh.update_issue(issue_number, body=updated_body)

            # Update labels: remove old state labels, add published
            current_labels = [
                label.get("name", "") if isinstance(label, dict) else label
                for label in issue.get("labels", [])
            ]
            old_state_labels = [
                l for l in current_labels
                if l.startswith(self.STATE_LABEL_PREFIX)
            ]
            if old_state_labels:
                self.gh.remove_labels(issue_number, old_state_labels)

            new_state_label = f"{self.STATE_LABEL_PREFIX}published"
            self.gh.add_labels(issue_number, [new_state_label])

            # Close the issue
            self.gh.close_issue(issue_number, state_reason="completed")

            return True

        except Exception as e:
            # Log error but don't raise - issue closure is non-critical
            import logging
            logging.getLogger(__name__).error(
                f"Failed to close release issue #{issue_number}: {e}"
            )
            return False
