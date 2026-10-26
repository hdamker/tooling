"""
Issue synchronization for CAMARA release automation.

This module provides functionality for creating and synchronizing
workflow-owned Release Issues based on state derivation from repository
artifacts.
"""

from dataclasses import dataclass
import re
import traceback
from typing import Any, Dict, List, Optional

import yaml

from .github_client import GitHubClient
from .release_line import MAIN_BRANCH, line_of
from .state_manager import ReleaseState, ReleaseStateManager
from .issue_manager import IssueManager
from .bot_responder import BotResponder
from .labels import RELEASE_ISSUE_LABELS, ensure_labels


# Marker to identify workflow-owned issues
WORKFLOW_MARKER = "<!-- release-automation:workflow-owned -->"
RELEASE_TAG_MARKER_RE = re.compile(
    r"<!--\s*release-automation:release-tag:(?P<tag>.*?)\s*-->"
)

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
        bot_responder: Optional[BotResponder] = None,
        base_branch: str = MAIN_BRANCH,
    ):
        """
        Initialize the issue sync manager.

        Args:
            github_client: GitHubClient for repository operations
            state_manager: ReleaseStateManager for state derivation (optional for finalize_published_issue)
            issue_manager: IssueManager for issue content management
            bot_responder: BotResponder for message templates (optional for finalize_published_issue)
            base_branch: Line the Release Issue belongs to (release_line.line_of)
        """
        self.gh = github_client
        self.state_manager = state_manager
        self.issue_manager = issue_manager
        self.bot = bot_responder
        self.base_branch = base_branch
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

        created = ensure_labels(self.gh, RELEASE_ISSUE_LABELS)
        self._labels_ensured = True
        return created

    def sync_release_issue(
        self,
        release_plan: Dict[str, Any],
        trigger_pr: Optional[int] = None,
        state_override: Optional[ReleaseState] = None,
        snapshot_branch_override: Optional[str] = None,
        release_pr_number_override: Optional[str] = None,
        draft_release_url_override: Optional[str] = None,
        force_update: bool = False,
        common_cache_status: str = "",
        common_cache_details: str = "",
        common_sync_pr_url: str = "",
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
            state_override: Authoritative state for same-run workflow transitions
            snapshot_branch_override: Authoritative snapshot branch for same-run updates
            release_pr_number_override: Authoritative release PR number for same-run updates
            draft_release_url_override: Authoritative draft release URL for same-run updates
            force_update: Force a refresh even if state appears unchanged

        Returns:
            SyncResult with action taken and issue details
        """
        release_tag = release_plan.get("repository", {}).get("target_release_tag", "")
        if not release_tag:
            return SyncResult(action="none", reason="missing_release_tag")

        # Ensure required labels exist before any label operations
        self.ensure_labels_exist()

        # Derive current state
        if state_override:
            state = state_override
            context_source = "override"
        else:
            release_info = self.state_manager.derive_state(
                retry_draft_release=True,
                base_branch=self.base_branch,
            )
            if not release_info.success:
                return SyncResult(
                    action="none",
                    reason=f"config_error: {release_info.config_error.message}",
                )
            state = release_info.state
            context_source = "re-derived"
        print(
            f"Issue sync effective context: source={context_source}, "
            f"state={state.value}, "
            f"snapshot_branch={snapshot_branch_override or '(auto)'}, "
            f"release_pr_number={release_pr_number_override or '(auto)'}, "
            f"draft_release_url={'yes' if draft_release_url_override else 'auto'}, "
            f"force_update={force_update}"
        )

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
                    self._update_release_issue(
                        new_issue,
                        state,
                        release_plan,
                        snapshot_branch_override=snapshot_branch_override,
                        release_pr_number_override=release_pr_number_override,
                        draft_release_url_override=draft_release_url_override,
                        common_cache_status=common_cache_status,
                        common_cache_details=common_cache_details,
                        common_sync_pr_url=common_sync_pr_url,
                    )
                    return self.gh.get_issue(new_issue["number"])
                updated_issue = self.gh.retry_on_not_found(_post_create)
                self.cleanup_stale_workflow_owned_issues(release_tag, updated_issue)
                return SyncResult(action="created", issue=updated_issue)
            else:
                return SyncResult(action="none", reason="no_planned_release")

        # Issue exists - check if update needed
        if force_update or self._needs_update(issue, state, release_plan):
            self._update_release_issue(
                issue,
                state,
                release_plan,
                snapshot_branch_override=snapshot_branch_override,
                release_pr_number_override=release_pr_number_override,
                draft_release_url_override=draft_release_url_override,
                common_cache_status=common_cache_status,
                common_cache_details=common_cache_details,
                common_sync_pr_url=common_sync_pr_url,
            )
            # Refetch issue after update
            updated_issue = self.gh.get_issue(issue["number"])
            self.cleanup_stale_workflow_owned_issues(release_tag, updated_issue)
            return SyncResult(action="updated", issue=updated_issue)

        self.cleanup_stale_workflow_owned_issues(release_tag, issue)
        return SyncResult(action="none", reason="up_to_date")

    def find_workflow_owned_issue(self, release_tag: str) -> Optional[Dict[str, Any]]:
        """
        Find an existing workflow-owned issue for the given release.

        Searches for open issues with the 'release-issue' label, then
        filters to find one that:
        1. Contains the WORKFLOW_MARKER in its body
        2. Contains the release-tag marker in its body

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

            # Check for workflow marker
            if WORKFLOW_MARKER not in body:
                continue

            # Check for release tag marker in body (hidden HTML comment)
            release_tag_marker = f"<!-- release-automation:release-tag:{release_tag} -->"
            if release_tag_marker in body:
                return issue

        return None

    def cleanup_stale_workflow_owned_issues(
        self,
        release_tag: str,
        current_issue: Dict[str, Any],
    ) -> None:
        """
        Close older workflow-owned Release Issues for superseded release tags.

        There is one active Release Issue per line (main, maintenance/rX).
        When the target release tag changes, the old issue keeps its workflow
        and release-tag markers but no longer matches the current tag lookup.
        Issues of other lines are left alone.
        """
        current_issue_number = current_issue["number"]
        current_issue_url = current_issue.get("html_url", "")
        issues = self.gh.search_issues(
            labels=[self.RELEASE_ISSUE_LABEL],
            state="open"
        )

        for issue in issues:
            issue_number = issue.get("number")
            if issue_number == current_issue_number:
                continue

            body = issue.get("body", "") or ""
            if WORKFLOW_MARKER not in body:
                continue

            match = RELEASE_TAG_MARKER_RE.search(body)
            if not match or match.group("tag") == release_tag:
                continue
            if line_of(self.gh, match.group("tag")) != self.base_branch:
                continue

            current_labels = [
                label.get("name", "") if isinstance(label, dict) else label
                for label in issue.get("labels", [])
            ]
            state_labels = [
                label for label in current_labels
                if isinstance(label, str) and label.startswith(self.STATE_LABEL_PREFIX)
            ]
            if state_labels:
                self.gh.remove_labels(issue_number, state_labels)

            self.gh.add_issue_comment(
                issue_number,
                self._stale_issue_comment(
                    release_tag,
                    current_issue_number,
                    current_issue_url,
                )
            )
            self.gh.close_issue(issue_number, state_reason="not_planned")

    def _stale_issue_comment(
        self,
        release_tag: str,
        current_issue_number: int,
        current_issue_url: str,
    ) -> str:
        """Build the comment posted before closing a superseded Release Issue."""
        current_issue_ref = (
            f"#{current_issue_number}"
            if not current_issue_url
            else f"#{current_issue_number} ({current_issue_url})"
        )
        return (
            "This workflow-owned Release Issue has been superseded by "
            f"{current_issue_ref} for release tag `{release_tag}`.\n\n"
            "Removing the release-state label and closing this stale issue."
        )

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
            meta_release=meta_release,
            base_branch=self.base_branch,
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
        if expected_state_label not in current_labels:
            return True

        # Check if title needs updating
        current_title = issue.get("title", "")
        if self.issue_manager.should_update_title(current_title, release_plan, self.base_branch):
            return True

        # In PLANNED state, always refresh the issue body. This is the state
        # where release-plan.yaml is actively edited (APIs added/renamed,
        # dependencies changed, release type updated). The update is idempotent.
        if state == ReleaseState.PLANNED:
            return True

        return False

    def _update_release_issue(
        self,
        issue: Dict[str, Any],
        state: ReleaseState,
        release_plan: Dict[str, Any],
        snapshot_branch_override: Optional[str] = None,
        release_pr_number_override: Optional[str] = None,
        draft_release_url_override: Optional[str] = None,
        common_cache_status: str = "",
        common_cache_details: str = "",
        common_sync_pr_url: str = "",
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
            snapshot_branch_override: Authoritative snapshot branch for same-run updates
            release_pr_number_override: Authoritative release PR number for same-run updates
            draft_release_url_override: Authoritative draft release URL for same-run updates
        """
        issue_number = issue["number"]
        release_tag = release_plan.get("repository", {}).get("target_release_tag", "")

        # Update state label
        current_labels = [
            label.get("name", "") if isinstance(label, dict) else label
            for label in issue.get("labels", [])
        ]

        # Update state label only if needed
        new_state_label = self.get_state_label(state)
        if new_state_label in current_labels:
            # Correct label already present (e.g., freshly created issue) —
            # remove any extra state labels only
            extra_state_labels = [
                l for l in current_labels
                if l.startswith(self.STATE_LABEL_PREFIX) and l != new_state_label
            ]
            if extra_state_labels:
                self.gh.remove_labels(issue_number, extra_state_labels)
        else:
            # Remove old state labels, add new one
            old_state_labels = [
                l for l in current_labels
                if l.startswith(self.STATE_LABEL_PREFIX)
            ]
            if old_state_labels:
                self.gh.remove_labels(issue_number, old_state_labels)
            self.gh.add_labels(issue_number, [new_state_label])

        # Get snapshot info and artifact URLs
        snapshot = self.state_manager.get_current_snapshot(release_tag)
        snapshot_id = snapshot.snapshot_id if snapshot else ""
        snapshot_branch = snapshot_branch_override or (snapshot.snapshot_branch if snapshot else "")
        release_pr_url = ""
        draft_release_url = ""
        snapshot_branch_url = ""
        release_pr_number = release_pr_number_override or (
            str(snapshot.release_pr_number) if snapshot and snapshot.release_pr_number else ""
        )

        if snapshot_branch and not snapshot_id:
            snapshot_id = snapshot_branch.replace("release-snapshot/", "")

        if release_pr_number:
            # Construct PR URL
            release_pr_url = f"https://github.com/{self.gh.repo}/pull/{release_pr_number}"

        if snapshot_branch:
            # Construct snapshot branch tree URL
            snapshot_branch_url = f"https://github.com/{self.gh.repo}/tree/{snapshot_branch}"

        # Get draft release URL if in draft-ready state
        if state == ReleaseState.DRAFT_READY:
            draft_release_url = draft_release_url_override or self._get_draft_release_url(release_tag)

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
            icm_release=icm_release,
            common_cache_status=common_cache_status,
            common_cache_details=common_cache_details,
            common_sync_pr_url=common_sync_pr_url,
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
        if self.issue_manager.should_update_title(issue.get("title", ""), release_plan, self.base_branch):
            repo_config = release_plan.get("repository", {})
            new_title = self.issue_manager.generate_title(
                release_tag=repo_config.get("target_release_tag", ""),
                release_type=repo_config.get("target_release_type", ""),
                meta_release=repo_config.get("meta_release"),
                base_branch=self.base_branch,
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

    def finalize_published_issue(
        self,
        issue_number: int,
        release_tag: str,
        release_url: str,
        reference_tag: str,
        sync_pr_url: str,
        sync_status: str,
        publish_warnings: str = "",
    ) -> bool:
        """
        Mark the Release Issue published; close it only if the sync PR was created.

        Steps:
        1. STATE section: release, reference tag, sync PR, post-publish warnings
        2. ACTIONS section: no actions when sync_status is "created", the
           manual follow-up for that status otherwise
        3. State label to release-state:published
        4. Close with reason "completed" only when sync_status is "created"

        Args:
            issue_number: Release Issue number
            release_tag: Release tag (e.g., "r4.1")
            release_url: URL to the published release
            reference_tag: Reference tag (e.g., "src/r4.1"), "" if its creation failed
            sync_pr_url: URL of the post-release sync PR, "" if none
            sync_status: Post-release sync status (created | failed | no_changes | other)
            publish_warnings: Warnings of the non-critical publish steps

        Returns:
            True if every step succeeded, False on an API error (logged, never
            raised: the release is already published)
        """
        try:
            issue = self.gh.get_issue(issue_number)
            body = issue.get("body", "") or ""
            body = self.issue_manager.update_section(
                body,
                "STATE",
                self.issue_manager.generate_published_state_section(
                    release_tag=release_tag,
                    release_url=release_url,
                    reference_tag=reference_tag,
                    repo=self.gh.repo,
                    sync_pr_url=sync_pr_url,
                    warnings=post_publish_warnings(publish_warnings, sync_status),
                ),
            )
            body = self.issue_manager.update_section(
                body, "ACTIONS", self.issue_manager.generate_published_actions_section(sync_status)
            )
            self.gh.update_issue(issue_number, body=body)

            current_labels = [
                label.get("name", "") if isinstance(label, dict) else label
                for label in issue.get("labels", [])
            ]
            old_state_labels = [l for l in current_labels if l.startswith(self.STATE_LABEL_PREFIX)]
            if old_state_labels:
                self.gh.remove_labels(issue_number, old_state_labels)
            self.gh.add_labels(issue_number, [f"{self.STATE_LABEL_PREFIX}published"])

            if sync_status == "created":
                self.gh.close_issue(issue_number, state_reason="completed")
                print(f"Issue #{issue_number} closed successfully")
            else:
                print(f"Issue #{issue_number} left open — sync status: {sync_status}")
            return True
        except Exception as e:
            print(f"::warning::Failed to close issue: {e}")
            return False


def post_publish_warnings(publish_warnings: str, sync_status: str) -> str:
    """
    Warnings of a publication: the non-critical publish steps, then the sync PR status.

    Returns:
        "; "-joined text, "" when there is nothing to warn about
    """
    warnings = [publish_warnings] if publish_warnings else []
    if sync_status == "failed":
        warnings.append("Post-release sync PR creation failed — create manually")
    elif sync_status == "no_changes":
        warnings.append("Post-release sync skipped (no changes detected) — verify README/CHANGELOG")
    elif sync_status != "created":
        warnings.append("Post-release sync status unknown — verify README/CHANGELOG")
    return "; ".join(warnings)


@dataclass(frozen=True)
class WorkflowSync:
    """Release Issue sync as the workflow sees it; issue_action is
    created | updated | unchanged | skipped | error."""
    issue_number: str = ""
    issue_action: str = "skipped"
    issue_url: str = ""


def parse_state(value: str) -> Optional[ReleaseState]:
    """ReleaseState for a value or name in any case, - or _; None for ""."""
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return None
    for state in ReleaseState:
        if normalized in {state.value.lower().replace("-", "_"), state.name.lower()}:
            return state
    raise ValueError(f"Unknown release state override: {value}")


def _summary(path: str, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def sync_for_workflow(
    gh: GitHubClient,
    release_tag: str,
    state: str,
    state_override: str = "",
    snapshot_branch_override: str = "",
    release_pr_number_override: str = "",
    draft_release_url_override: str = "",
    force_update: bool = False,
    common_cache_status: str = "",
    common_cache_details: str = "",
    common_sync_pr_url: str = "",
    summary_path: str = "",
    base_branch: str = MAIN_BRANCH,
) -> WorkflowSync:
    """
    Sync the Release Issue for a workflow run (create, update, or leave it).

    Args:
        gh: GitHub client of the API repository
        release_tag: Release tag from the plan
        state: State derived by the plan job
        state_override: State the run's command moved the release to ("" for none)
        snapshot_branch_override, release_pr_number_override,
        draft_release_url_override: Artifacts the run's command created
        force_update: Refresh the issue even if its state label matches
        common_cache_status, common_cache_details, common_sync_pr_url: Cache
            detection and common sync PR, shown in the CONFIG section
        summary_path: GITHUB_STEP_SUMMARY ("" to skip)
        base_branch: Line of the release (Plan.base_branch); its
            release-plan.yaml is read

    Returns:
        WorkflowSync; issue_action "error" when the sync failed (logged)
    """
    try:
        override = parse_state(state_override)
    except ValueError as e:
        print(f"::error::{e}")
        return WorkflowSync(issue_action="error")

    requested_state = state_override or state
    print("Effective sync context:")
    print(f"  Source: {'override' if override else 're-derived'}")
    print(f"  Requested state: {requested_state or '(none)'}")
    print(f"  Snapshot branch override: {snapshot_branch_override or '(none)'}")
    print(f"  Release PR override: {release_pr_number_override or '(none)'}")
    print(f"  Draft release URL override present: {'yes' if draft_release_url_override else 'no'}")
    print(f"  Force update: {force_update}")

    if not release_tag:
        print("No release tag provided - skipping issue sync")
        return WorkflowSync()

    if requested_state.lower() in ("published", ""):
        print(f"State '{requested_state}' does not require issue sync - skipping")
        if requested_state.lower() == "published":
            _summary(summary_path, (
                "## Release Status: Published\n\n"
                f"Release `{release_tag}` has already been published. No further actions needed.\n"
            ))
        else:
            _summary(summary_path, (
                "## Release Status\n\n"
                f"No release state detected for `{release_tag}`. Check release-plan.yaml configuration.\n"
            ))
        return WorkflowSync()

    print(f"Reading release-plan.yaml for {release_tag} from {base_branch}")
    release_plan = gh.get_file_content("release-plan.yaml", ref=base_branch)
    if release_plan is None:
        print("::warning::Could not read release-plan.yaml - skipping issue sync")
        return WorkflowSync()
    try:
        release_plan_data = yaml.safe_load(release_plan)
    except yaml.YAMLError as e:
        print(f"::warning::Could not parse release-plan.yaml: {e}")
        return WorkflowSync()
    if not isinstance(release_plan_data, dict):
        print("::warning::release-plan.yaml is not a valid YAML mapping")
        return WorkflowSync()

    plan_tag = (release_plan_data.get("repository") or {}).get("target_release_tag", "")
    if plan_tag != release_tag:
        print(f"::warning::release-plan.yaml tag '{plan_tag}' doesn't match input '{release_tag}'")

    sync_manager = IssueSyncManager(
        github_client=gh,
        state_manager=ReleaseStateManager(github_client=gh),
        issue_manager=IssueManager(),
        bot_responder=BotResponder(),
        base_branch=base_branch,
    )
    print(f"Syncing Release Issue for {release_tag} (state: {requested_state})")
    try:
        result = sync_manager.sync_release_issue(
            release_plan_data,
            state_override=override,
            snapshot_branch_override=snapshot_branch_override or None,
            release_pr_number_override=release_pr_number_override or None,
            draft_release_url_override=draft_release_url_override or None,
            force_update=force_update,
            common_cache_status=common_cache_status,
            common_cache_details=common_cache_details,
            common_sync_pr_url=common_sync_pr_url,
        )
    except Exception as e:
        print(f"::error::Issue sync failed: {e}")
        traceback.print_exc()
        return WorkflowSync(issue_action="error")

    if result.action == "none":
        print(f"No action taken: {result.reason}")
        if result.reason == "no_planned_release":
            _summary(summary_path, (
                "## Release Status: Not Planned\n\n"
                f"No release is currently planned for `{release_tag}` (`target_release_type: none`).\n"
                "No open Release Issue exists.\n"
            ))
        return WorkflowSync(issue_action="unchanged")
    if result.issue:
        number = result.issue.get("number", "")
        url = result.issue.get("html_url", "")
        print(f"Issue {result.action}: #{number}")
        print(f"  URL: {url}")
        return WorkflowSync(issue_number=str(number), issue_action=result.action, issue_url=url)
    print(f"Action {result.action} but no issue returned")
    return WorkflowSync(issue_action=result.action)
