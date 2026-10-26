"""
Issue synchronization for CAMARA release automation.

Creates and synchronizes the workflow-owned Release Issue of a release line
with the release as the plan derived it and the run's action changed it
(ReleaseView): the finalize job never derives state again.
"""

from dataclasses import dataclass, field
import json
import re
import traceback
from typing import Any, Dict, List, Optional

import yaml

from .github_client import GitHubClient
from .release_line import line_of
from .state_manager import ReleaseState
from .issue_manager import IssueManager
from .labels import RELEASE_ISSUE_LABELS, ensure_labels
from .plan_document import PlanDocument


# Marker to identify workflow-owned issues
WORKFLOW_MARKER = "<!-- release-automation:workflow-owned -->"
RELEASE_TAG_MARKER_RE = re.compile(
    r"<!--\s*release-automation:release-tag:(?P<tag>.*?)\s*-->"
)

# Triggers that only refresh the issue on a state change; everything else
# (commands, syncs) rewrites the managed sections
ISSUE_EVENTS = ("issue_close", "issue_reopen")


@dataclass(frozen=True)
class ReleaseView:
    """
    The release as the Release Issue must show it: the state after the run's
    action, the issue to write, and the artifacts the plan knew or the action
    produced. Built by finalize from the plan document and the outcome
    (release_view).

    Attributes:
        state: Release state to show (ReleaseState value)
        issue_number: The Release Issue, "" when none exists yet
        snapshot_id, snapshot_branch, release_pr_number, draft_release_url:
            Artifacts of the state ("" when the state has none)
        api_versions: Calculated version per api_name (a snapshot's
            release-metadata.yaml), {} before a snapshot exists
        commonalities_release, identity_consent_management_release: From the
            snapshot's metadata; "" to take the release plan's
        common_cache_status, common_cache_details, common_sync_pr_url: Cache
            detection and sync PR, shown in the CONFIG section
        refresh: Rewrite the managed sections even when the state label
            already matches (commands and syncs; issue events only on a change)
    """
    state: str
    issue_number: str = ""
    snapshot_id: str = ""
    snapshot_branch: str = ""
    release_pr_number: str = ""
    draft_release_url: str = ""
    api_versions: Dict[str, str] = field(default_factory=dict)
    commonalities_release: str = ""
    identity_consent_management_release: str = ""
    common_cache_status: str = ""
    common_cache_details: str = ""
    common_sync_pr_url: str = ""
    refresh: bool = True


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
    - Closing superseded workflow-owned issues of the same line
    - Ignoring manually-created issues

    Only issues containing the WORKFLOW_MARKER are managed by this class.
    """

    # Labels used for Release Issues
    RELEASE_ISSUE_LABEL = "release-issue"
    STATE_LABEL_PREFIX = "release-state:"

    def __init__(
        self,
        github_client: GitHubClient,
        issue_manager: Optional[IssueManager],
        base_branch: str,
    ):
        """
        Initialize the issue sync manager.

        Args:
            github_client: GitHubClient for repository operations
            issue_manager: IssueManager for issue content management
            base_branch: Line the Release Issue belongs to (release_line.line_of)
        """
        self.gh = github_client
        self.issue_manager = issue_manager
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

    def sync_release_issue(self, release_plan: Dict[str, Any], view: ReleaseView) -> SyncResult:
        """
        Ensure the Release Issue exists and reflects the release view.

        1. Read the issue the view names (never searched: the plan found it)
        2. Create a new issue if PLANNED and none exists
        3. Update the issue when the view asks for a refresh or its state,
           title or plan content changed

        Args:
            release_plan: Parsed release-plan.yaml content of the base branch
            view: The release as the issue must show it

        Returns:
            SyncResult with action taken and issue details
        """
        release_tag = release_plan.get("repository", {}).get("target_release_tag", "")
        if not release_tag:
            return SyncResult(action="none", reason="missing_release_tag")

        # Ensure required labels exist before any label operations
        self.ensure_labels_exist()

        state = ReleaseState(view.state)
        print(
            f"Issue sync: state={state.value}, issue=#{view.issue_number or '(none)'}, "
            f"snapshot_branch={view.snapshot_branch or '(none)'}, "
            f"release_pr_number={view.release_pr_number or '(none)'}, "
            f"draft_release_url={'yes' if view.draft_release_url else 'no'}, refresh={view.refresh}"
        )

        issue = self.gh.get_issue(int(view.issue_number)) if view.issue_number else None

        if issue is None:
            # No workflow-owned issue exists
            if state == ReleaseState.PLANNED:
                # Create new Release Issue
                new_issue = self.create_release_issue(release_plan)
                # Populate sections with initial content and refetch.
                # Wrapped in retry_on_not_found because GitHub API may
                # return 404 for a freshly created issue (eventual consistency).
                def _post_create():
                    self._update_release_issue(new_issue, state, release_plan, view)
                    return self.gh.get_issue(new_issue["number"])
                updated_issue = self.gh.retry_on_not_found(_post_create)
                self.cleanup_stale_workflow_owned_issues(release_tag, updated_issue)
                return SyncResult(action="created", issue=updated_issue)
            else:
                return SyncResult(action="none", reason="no_planned_release")

        # Issue exists - check if update needed
        if view.refresh or self._needs_update(issue, state, release_plan):
            self._update_release_issue(issue, state, release_plan, view)
            # Refetch issue after update
            updated_issue = self.gh.get_issue(issue["number"])
            self.cleanup_stale_workflow_owned_issues(release_tag, updated_issue)
            return SyncResult(action="updated", issue=updated_issue)

        self.cleanup_stale_workflow_owned_issues(release_tag, issue)
        return SyncResult(action="none", reason="up_to_date")

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

    def create_release_issue(self, release_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new workflow-owned Release Issue.

        Args:
            release_plan: Parsed release-plan.yaml content

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
        view: ReleaseView,
    ) -> None:
        """
        Update an existing Release Issue to match the release view.

        Updates:
        - State label (removes old, adds new)
        - STATE section content (with artifact links)
        - CONFIG section content (API versions, dependencies)
        - ACTIONS section content (valid commands)
        - Title if needed

        Args:
            issue: Issue dict to update
            state: State to show
            release_plan: Current release plan
            view: Artifacts and cache state to show
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

        # Artifact URLs of the view
        snapshot_id = view.snapshot_id
        if view.snapshot_branch and not snapshot_id:
            snapshot_id = view.snapshot_branch.replace("release-snapshot/", "")
        release_pr_url = f"https://github.com/{self.gh.repo}/pull/{view.release_pr_number}" if view.release_pr_number else ""
        snapshot_branch_url = f"https://github.com/{self.gh.repo}/tree/{view.snapshot_branch}" if view.snapshot_branch else ""
        draft_release_url = view.draft_release_url if state == ReleaseState.DRAFT_READY else ""

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

        # Update CONFIG section: calculated versions and dependencies from the
        # snapshot when there is one, dependencies from release_plan otherwise
        deps = release_plan.get("dependencies", {})
        new_config_content = self.issue_manager.generate_config_section(
            release_plan=release_plan,
            api_versions=dict(view.api_versions),
            commonalities_release=view.commonalities_release or deps.get("commonalities_release", ""),
            icm_release=view.identity_consent_management_release or deps.get("identity_consent_management_release", ""),
            common_cache_status=view.common_cache_status,
            common_cache_details=view.common_cache_details,
            common_sync_pr_url=view.common_sync_pr_url,
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
        main_sync_pr_url: str = "",
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
            main_sync_pr_url: Case B: URL of the sync PR into main

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
                    main_sync_pr_url=main_sync_pr_url,
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


def _summary(path: str, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def release_view(plan: PlanDocument, state: str, outcome: Dict[str, str], issue_number: str,
                 common_sync_pr_url: str = "") -> ReleaseView:
    """
    The release as finalize shows it on the Release Issue: the state after the
    run's action, the artifacts of that state from the action's outcome or,
    when the plan already knew them, from the plan.
    """
    release = plan.release
    with_snapshot = state in (ReleaseState.SNAPSHOT_ACTIVE.value, ReleaseState.DRAFT_READY.value)
    api_versions: Dict[str, str] = {}
    if with_snapshot:
        apis = json.loads(outcome["apis_json"]) if outcome.get("apis_json") else release.apis
        api_versions = {a["api_name"]: a["api_version"] for a in apis if a.get("api_name") and a.get("api_version")}
    return ReleaseView(
        state=state,
        issue_number=issue_number,
        snapshot_id=(outcome.get("snapshot_id") or release.snapshot_id) if with_snapshot else "",
        snapshot_branch=(outcome.get("snapshot_branch") or plan.snapshot_branch) if with_snapshot else "",
        release_pr_number=(outcome.get("release_pr_number") or plan.release_pr_number) if with_snapshot else "",
        draft_release_url=(outcome.get("draft_release_url") or release.draft_release_url) if with_snapshot else "",
        api_versions=api_versions,
        commonalities_release=release.commonalities_release if with_snapshot else "",
        identity_consent_management_release=release.identity_consent_management_release if with_snapshot else "",
        common_cache_status=plan.cache.status,
        common_cache_details=plan.cache.details,
        common_sync_pr_url=common_sync_pr_url or plan.cache.sync_pr_url,
        refresh=plan.trigger.trigger_type not in ISSUE_EVENTS,
    )


def sync_for_workflow(gh: GitHubClient, plan: PlanDocument, view: ReleaseView, summary_path: str = "") -> WorkflowSync:
    """
    Sync the Release Issue for a workflow run (create, update, or leave it).

    Args:
        gh: GitHub client of the API repository (the issue client)
        plan: The plan document; its base branch's release-plan.yaml is read
        view: The release as the issue must show it (release_view)
        summary_path: GITHUB_STEP_SUMMARY ("" to skip)

    Returns:
        WorkflowSync; issue_action "error" when the sync failed (logged)
    """
    release_tag, base_branch = plan.release_tag, plan.base_branch
    print("Issue sync context:")
    print(f"  State: {view.state or '(none)'}")
    print(f"  Issue: #{view.issue_number or '(none)'}")
    print(f"  Snapshot branch: {view.snapshot_branch or '(none)'}")
    print(f"  Release PR: {view.release_pr_number or '(none)'}")
    print(f"  Draft release URL present: {'yes' if view.draft_release_url else 'no'}")
    print(f"  Refresh: {view.refresh}")

    if not release_tag:
        print("No release tag provided - skipping issue sync")
        return WorkflowSync()

    if view.state in (ReleaseState.PUBLISHED.value, ""):
        print(f"State '{view.state}' does not require issue sync - skipping")
        if view.state == ReleaseState.PUBLISHED.value:
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

    sync_manager = IssueSyncManager(github_client=gh, issue_manager=IssueManager(), base_branch=base_branch)
    print(f"Syncing Release Issue for {release_tag} (state: {view.state})")
    try:
        result = sync_manager.sync_release_issue(release_plan_data, view)
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
