"""
Unit tests for issue_sync.py

Tests the IssueSyncManager class which synchronizes the Release Issue with
the release view the finalize job builds from the plan document (107 D3).
"""

import pytest
from unittest.mock import MagicMock

from release_automation.scripts.github_client import GitHubClientError
from release_automation.scripts.issue_manager import IssueManager
from release_automation.scripts.labels import RELEASE_ISSUE_LABELS
from release_automation.scripts.issue_sync import (
    IssueSyncManager,
    ReleaseView,
    SyncResult,
    WORKFLOW_MARKER,
    post_publish_warnings,
)
from release_automation.scripts.state_manager import ReleaseState
from release_automation.tests.plans import make_plan


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_created_result(self):
        """Test creating a 'created' result."""
        issue = {"number": 1, "title": "Release r4.1"}
        result = SyncResult(action="created", issue=issue)

        assert result.action == "created"
        assert result.issue == issue
        assert result.reason is None

    def test_none_result_with_reason(self):
        """Test creating a 'none' result with reason."""
        result = SyncResult(action="none", reason="up_to_date")

        assert result.action == "none"
        assert result.issue is None
        assert result.reason == "up_to_date"


class TestIssueSyncManagerInit:
    """Tests for IssueSyncManager initialization."""

    def test_init_with_dependencies(self):
        gh = MagicMock()
        issue_manager = MagicMock()

        manager = IssueSyncManager(gh, issue_manager, "maintenance/r1")

        assert manager.gh == gh
        assert manager.issue_manager == issue_manager
        assert manager.base_branch == "maintenance/r1"

    def test_base_branch_is_required(self):
        # F12: no silent main
        with pytest.raises(TypeError):
            IssueSyncManager(MagicMock(), MagicMock())


class TestSyncReleaseIssue:
    """Tests for sync_release_issue method: the issue follows the release view, nothing is derived."""

    PLAN = {"repository": {"target_release_tag": "r4.1", "target_release_type": "pre-release-rc", "meta_release": "Sync26"}}

    def _create_manager(self):
        """Helper to create a manager with mocked dependencies."""
        gh = MagicMock()
        issue_manager = MagicMock()
        gh.get_branch_sha.return_value = None  # no maintenance branch
        gh.search_issues.return_value = []  # no other workflow-owned issues
        # Make retry_on_not_found call the function directly (no actual retry in tests)
        gh.retry_on_not_found.side_effect = lambda fn, **kwargs: fn()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "**State**: x"
        issue_manager.update_section.return_value = "updated body"

        manager = IssueSyncManager(gh, issue_manager, "main")
        return manager, gh, issue_manager

    @staticmethod
    def issue(number=1, label="release-state:planned", body=f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.1 -->"):
        return {"number": number, "title": "Release r4.1 (RC)", "body": body, "labels": [{"name": label}],
                "html_url": f"https://github.com/test/repo/issues/{number}"}

    def test_creates_issue_when_planned_and_no_issue(self):
        manager, gh, issue_manager = self._create_manager()
        gh.create_issue.return_value = {"number": 1, "title": "Release r4.1 (RC)"}
        gh.get_issue.return_value = self.issue()
        issue_manager.generate_title.return_value = "Release r4.1 (RC) — Sync26"
        issue_manager.generate_issue_body_template.return_value = f"## Release\n{WORKFLOW_MARKER}"

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="planned"))

        assert result.action == "created"
        assert result.issue is not None
        gh.create_issue.assert_called_once()

    def test_reads_the_issue_the_view_names_not_a_search(self):
        # 107 D3: GitHub objects by the plan's reference, never by search
        manager, gh, _ = self._create_manager()
        gh.get_issue.return_value = self.issue(7)

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="planned", issue_number="7"))

        assert result.action == "updated"
        gh.get_issue.assert_any_call(7)
        gh.create_issue.assert_not_called()

    def test_always_updates_issue_in_planned_state(self):
        """PLANNED always refreshes CONFIG from release-plan.yaml, also without a refresh."""
        manager, gh, _ = self._create_manager()
        gh.get_issue.return_value = self.issue()

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="planned", issue_number="1", refresh=False))

        assert result.action == "updated"

    def test_updates_issue_when_state_changes(self):
        manager, gh, _ = self._create_manager()
        gh.get_issue.return_value = self.issue(label="release-state:planned")

        result = manager.sync_release_issue(
            self.PLAN, ReleaseView(state="snapshot-active", issue_number="1", snapshot_branch="release-snapshot/r4.1-abc",
                                   release_pr_number="12", refresh=False),
        )

        assert result.action == "updated"
        gh.remove_labels.assert_called_with(1, ["release-state:planned"])
        gh.add_labels.assert_called_with(1, ["release-state:snapshot-active"])

    def test_issue_event_without_a_change_is_up_to_date(self):
        # An issue close or reopen refreshes only on a state change (refresh=False)
        manager, gh, _ = self._create_manager()
        gh.get_issue.return_value = self.issue(label="release-state:snapshot-active")

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="snapshot-active", issue_number="1", refresh=False))

        assert (result.action, result.reason) == ("none", "up_to_date")
        gh.update_issue.assert_not_called()

    def test_refresh_rewrites_the_issue_when_state_matches(self):
        # Commands and syncs rewrite the managed sections
        manager, gh, _ = self._create_manager()
        gh.get_issue.return_value = self.issue(label="release-state:snapshot-active")

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="snapshot-active", issue_number="1", refresh=True))

        assert result.action == "updated"

    def test_closes_stale_workflow_owned_issue_after_current_issue_exists(self):
        """Stale workflow-owned issues for old tags are de-stated and closed."""
        manager, gh, _ = self._create_manager()
        current = self.issue(2)
        stale = {
            "number": 1, "title": "Release r4.0 (RC)",
            "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.0 -->",
            "labels": [{"name": "release-issue"}, {"name": "release-state:planned"}],
            "html_url": "https://github.com/test/repo/issues/1",
        }
        gh.search_issues.return_value = [stale, current]
        gh.get_issue.return_value = current

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="planned", issue_number="2"))

        assert result.action == "updated"
        gh.remove_labels.assert_any_call(1, ["release-state:planned"])
        gh.add_issue_comment.assert_called_once()
        comment_args = gh.add_issue_comment.call_args.args
        assert comment_args[0] == 1
        assert "#2" in comment_args[1]
        assert "`r4.1`" in comment_args[1]
        gh.close_issue.assert_called_once_with(1, state_reason="not_planned")

    def test_no_action_when_not_planned_and_no_issue(self):
        manager, gh, _ = self._create_manager()

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="not-planned"))

        assert (result.action, result.reason) == ("none", "no_planned_release")
        gh.create_issue.assert_not_called()

    def test_returns_none_action_when_missing_release_tag(self):
        manager, _, _ = self._create_manager()

        result = manager.sync_release_issue({"repository": {}}, ReleaseView(state="planned"))

        assert (result.action, result.reason) == ("none", "missing_release_tag")

    def test_draft_ready_shows_the_views_draft_url(self):
        manager, gh, issue_manager = self._create_manager()
        gh.get_issue.return_value = self.issue(label="release-state:snapshot-active")
        url = "https://github.com/org/repo/releases/tag/untagged-123"

        result = manager.sync_release_issue(self.PLAN, ReleaseView(state="draft-ready", issue_number="1", draft_release_url=url))

        assert result.action == "updated"
        issue_manager.generate_state_section.assert_called_once_with(
            state="draft-ready", snapshot_id="", release_pr_url="", draft_release_url=url, snapshot_branch_url="",
        )

    def test_snapshot_artifacts_reach_the_sections(self):
        manager, gh, issue_manager = self._create_manager()
        gh.repo = "org/repo"
        gh.get_issue.return_value = self.issue(label="release-state:planned")
        plan = {**self.PLAN, "apis": [{"api_name": "qod", "target_api_version": "1.0.0"}],
                "dependencies": {"commonalities_release": "r4.3"}}

        manager.sync_release_issue(plan, ReleaseView(
            state="snapshot-active", issue_number="1", snapshot_branch="release-snapshot/r4.1-abc", release_pr_number="12",
            api_versions={"qod": "1.0.0-rc.1"}, commonalities_release="r4.4",
            common_cache_status="stale", common_cache_details="d", common_sync_pr_url="u",
        ))

        issue_manager.generate_state_section.assert_called_once_with(
            state="snapshot-active", snapshot_id="r4.1-abc", release_pr_url="https://github.com/org/repo/pull/12",
            draft_release_url="", snapshot_branch_url="https://github.com/org/repo/tree/release-snapshot/r4.1-abc",
        )
        issue_manager.generate_config_section.assert_called_once_with(
            release_plan=plan, api_versions={"qod": "1.0.0-rc.1"}, commonalities_release="r4.4", icm_release="",
            common_cache_status="stale", common_cache_details="d", common_sync_pr_url="u",
        )
        issue_manager.generate_actions_section.assert_called_once_with(
            state="snapshot-active", release_pr_url="https://github.com/org/repo/pull/12", release_tag="r4.1",
        )

    def test_without_a_snapshot_the_dependencies_come_from_the_plan(self):
        manager, gh, issue_manager = self._create_manager()
        gh.get_issue.return_value = self.issue()
        plan = {**self.PLAN, "dependencies": {"commonalities_release": "r4.3", "identity_consent_management_release": "r4.2"}}

        manager.sync_release_issue(plan, ReleaseView(state="planned", issue_number="1"))

        kwargs = issue_manager.generate_config_section.call_args.kwargs
        assert (kwargs["api_versions"], kwargs["commonalities_release"], kwargs["icm_release"]) == ({}, "r4.3", "r4.2")


class TestReleaseIssuesPerLine:
    """Spec 5.1-5.4: one open Release Issue per line; sync and cleanup stay on their line."""

    MB = "maintenance/r1"

    @staticmethod
    def issue(number, tag):
        return {
            "number": number,
            "title": f"Release {tag}",
            "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:{tag} -->",
            "labels": [{"name": "release-issue"}, {"name": "release-state:planned"}],
            "html_url": f"https://github.com/test/repo/issues/{number}",
        }

    def manager(self, base_branch, current_tag, open_issues):
        gh = MagicMock()
        gh.retry_on_not_found.side_effect = lambda fn, **kwargs: fn()
        gh.get_branch_sha.side_effect = lambda name: "b1" if name == self.MB else None
        gh.search_issues.return_value = open_issues
        current = next(i for i in open_issues if current_tag in i["body"])
        gh.get_issue.return_value = current
        manager = IssueSyncManager(gh, IssueManager(), base_branch)
        return manager, gh, ReleaseView(state="planned", issue_number=str(current["number"]))

    @staticmethod
    def plan(tag):
        return {"repository": {"target_release_tag": tag, "target_release_type": "pre-release-alpha"}}

    def test_sync_on_main_leaves_the_maintenance_issue_open(self):
        # spec 5.1
        manager, gh, view = self.manager("main", "r2.2", [self.issue(1, "r2.2"), self.issue(2, "r1.9")])

        manager.sync_release_issue(self.plan("r2.2"), view)

        gh.close_issue.assert_not_called()

    def test_sync_on_the_maintenance_line_leaves_mains_issue_open(self):
        # spec 5.2
        manager, gh, view = self.manager(self.MB, "r1.9", [self.issue(1, "r2.2"), self.issue(2, "r1.9")])

        manager.sync_release_issue(self.plan("r1.9"), view)

        gh.close_issue.assert_not_called()

    def test_superseded_issue_on_the_same_line_is_closed(self):
        # spec 5.3: main moves r2.2 -> r2.3
        manager, gh, view = self.manager(
            "main", "r2.3", [self.issue(1, "r2.2"), self.issue(2, "r1.9"), self.issue(3, "r2.3")]
        )

        manager.sync_release_issue(self.plan("r2.3"), view)

        gh.close_issue.assert_called_once_with(1, state_reason="not_planned")

    def test_case_b_issue_title_names_the_line(self):
        # spec 5.4
        gh = MagicMock()
        manager = IssueSyncManager(gh, IssueManager(), self.MB)

        manager.create_release_issue(
            {"repository": {"target_release_tag": "r1.9", "target_release_type": "maintenance-release"}}
        )

        assert gh.create_issue.call_args.kwargs["title"] == "Release r1.9 (maintenance) (maintenance/r1)"


class TestCreateReleaseIssue:
    """Tests for create_release_issue method."""

    def test_creates_issue_with_correct_labels(self):
        """Test issue is created with correct labels."""
        gh = MagicMock()
        issue_manager = MagicMock()
        gh.create_issue.return_value = {"number": 1}
        issue_manager.generate_title.return_value = "Release r4.1 (RC)"
        issue_manager.generate_issue_body_template.return_value = f"Body\n{WORKFLOW_MARKER}"

        manager = IssueSyncManager(gh, issue_manager, "main")

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        manager.create_release_issue(release_plan)

        gh.create_issue.assert_called_once()
        call_args = gh.create_issue.call_args
        assert "release-issue" in call_args.kwargs["labels"]
        assert "release-state:planned" in call_args.kwargs["labels"]

    def test_includes_workflow_marker_in_body(self):
        """Test workflow marker is included in body."""
        gh = MagicMock()
        issue_manager = MagicMock()
        gh.create_issue.return_value = {"number": 1}
        issue_manager.generate_title.return_value = "Release r4.1"
        # Body without marker - should be added
        issue_manager.generate_issue_body_template.return_value = "### Release Highlights\nContent"

        manager = IssueSyncManager(gh, issue_manager, "main")

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        manager.create_release_issue(release_plan)

        call_args = gh.create_issue.call_args
        assert WORKFLOW_MARKER in call_args.kwargs["body"]


class TestNeedsUpdate:
    """Tests for _needs_update method."""

    def test_needs_update_when_state_label_wrong(self):
        """Test returns True when state label doesn't match."""
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False

        manager = IssueSyncManager(MagicMock(), issue_manager, "main")

        issue = {
            "labels": [{"name": "release-state:planned"}]
        }

        result = manager._needs_update(issue, ReleaseState.SNAPSHOT_ACTIVE, {})
        assert result is True

    def test_no_update_when_non_planned_state_matches(self):
        """Test returns False when non-PLANNED state label matches and title unchanged."""
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False

        manager = IssueSyncManager(MagicMock(), issue_manager, "main")

        issue = {
            "labels": [{"name": "release-state:snapshot-active"}]
        }

        result = manager._needs_update(issue, ReleaseState.SNAPSHOT_ACTIVE, {})
        assert result is False

    def test_always_needs_update_in_planned_state(self):
        """Test returns True in PLANNED state even when label and title match.

        PLANNED is the state where release-plan.yaml is actively edited,
        so the issue body should always be refreshed to reflect changes
        in APIs, dependencies, or release type.
        """
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False

        manager = IssueSyncManager(MagicMock(), issue_manager, "main")

        issue = {
            "labels": [{"name": "release-state:planned"}]
        }

        result = manager._needs_update(issue, ReleaseState.PLANNED, {})
        assert result is True

    def test_needs_update_when_title_changed(self):
        """Test returns True when title needs updating."""
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = True

        manager = IssueSyncManager(MagicMock(), issue_manager, "main")

        issue = {
            "title": "Old title",
            "labels": [{"name": "release-state:snapshot-active"}]
        }

        result = manager._needs_update(issue, ReleaseState.SNAPSHOT_ACTIVE, {"repository": {}})
        assert result is True


class TestUpdateReleaseIssue:
    """Tests for _update_release_issue method."""

    def test_updates_state_label(self):
        """Test state label is updated correctly."""
        gh = MagicMock()
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "new state"
        issue_manager.update_section.return_value = "same body"

        manager = IssueSyncManager(gh, issue_manager, "main")

        issue = {
            "number": 1,
            "body": "body",
            "labels": [{"name": "release-state:planned"}]
        }

        manager._update_release_issue(issue, ReleaseState.SNAPSHOT_ACTIVE, {}, ReleaseView(state="snapshot-active"))

        gh.remove_labels.assert_called_with(1, ["release-state:planned"])
        gh.add_labels.assert_called_with(1, ["release-state:snapshot-active"])

    def test_skips_label_update_when_correct_label_already_present(self):
        """Test that no label API calls are made when the correct state label is already set."""
        gh = MagicMock()
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "new state"
        issue_manager.update_section.return_value = "same body"

        manager = IssueSyncManager(gh, issue_manager, "main")

        issue = {
            "number": 1,
            "body": "body",
            "labels": [{"name": "release-issue"}, {"name": "release-state:planned"}]
        }

        manager._update_release_issue(issue, ReleaseState.PLANNED, {}, ReleaseView(state="planned"))

        gh.remove_labels.assert_not_called()
        gh.add_labels.assert_not_called()

    def test_removes_extra_state_labels_when_correct_present(self):
        """Test that extra state labels are removed when the correct one is already present."""
        gh = MagicMock()
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "new state"
        issue_manager.update_section.return_value = "same body"

        manager = IssueSyncManager(gh, issue_manager, "main")

        issue = {
            "number": 1,
            "body": "body",
            "labels": [
                {"name": "release-state:planned"},
                {"name": "release-state:snapshot-active"}
            ]
        }

        manager._update_release_issue(issue, ReleaseState.PLANNED, {}, ReleaseView(state="planned"))

        gh.remove_labels.assert_called_with(1, ["release-state:snapshot-active"])
        gh.add_labels.assert_not_called()

    def test_updates_issue_body(self):
        """Test issue body is updated when changed."""
        gh = MagicMock()
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "new state"
        issue_manager.update_section.return_value = "new body"  # Different from current

        manager = IssueSyncManager(gh, issue_manager, "main")

        issue = {
            "number": 1,
            "body": "old body",
            "labels": []
        }

        manager._update_release_issue(issue, ReleaseState.PLANNED, {}, ReleaseView(state="planned"))

        gh.update_issue.assert_called()
        call_args = gh.update_issue.call_args
        assert call_args.kwargs.get("body") == "new body"


class TestGetStateLabel:
    """Tests for get_state_label method."""

    def test_returns_correct_label_for_each_state(self):
        """Test correct label returned for each state."""
        manager = IssueSyncManager(MagicMock(), MagicMock(), "main")

        assert manager.get_state_label(ReleaseState.PLANNED) == "release-state:planned"
        assert manager.get_state_label(ReleaseState.SNAPSHOT_ACTIVE) == "release-state:snapshot-active"
        assert manager.get_state_label(ReleaseState.DRAFT_READY) == "release-state:draft-ready"
        assert manager.get_state_label(ReleaseState.PUBLISHED) == "release-state:published"
        assert manager.get_state_label(ReleaseState.NOT_PLANNED) == "release-state:not-planned"


class TestWorkflowMarkerConstant:
    """Tests for WORKFLOW_MARKER constant."""

    def test_marker_format(self):
        """Test marker has expected format."""
        assert "release-automation" in WORKFLOW_MARKER
        assert "workflow-owned" in WORKFLOW_MARKER
        assert WORKFLOW_MARKER.startswith("<!--")
        assert WORKFLOW_MARKER.endswith("-->")


class TestEnsureLabelsExist:
    """Tests for ensure_labels_exist method."""

    def test_creates_missing_labels(self):
        """Test missing labels are created."""
        gh = MagicMock()
        gh.get_label.return_value = None  # All labels missing

        manager = IssueSyncManager(gh, MagicMock(), "main")
        created = manager.ensure_labels_exist()

        assert len(created) == 6
        assert gh.create_label.call_count == 6

    def test_skips_existing_labels(self):
        """Test existing labels are not recreated."""
        gh = MagicMock()
        # Only release-issue exists
        gh.get_label.side_effect = lambda name: {"name": name} if name == "release-issue" else None

        manager = IssueSyncManager(gh, MagicMock(), "main")
        created = manager.ensure_labels_exist()

        assert len(created) == 5  # 6 - 1 = 5 created
        assert "release-issue" not in created
        assert gh.create_label.call_count == 5

    def test_is_idempotent(self):
        """Test calling multiple times only creates labels once."""
        gh = MagicMock()
        gh.get_label.return_value = None

        manager = IssueSyncManager(gh, MagicMock(), "main")

        # First call
        created1 = manager.ensure_labels_exist()
        assert len(created1) == 6

        # Second call
        created2 = manager.ensure_labels_exist()
        assert len(created2) == 0  # No new labels created

        # Only 6 create calls total
        assert gh.create_label.call_count == 6

    def test_returns_created_label_names(self):
        """Test returns list of created label names."""
        gh = MagicMock()
        gh.get_label.return_value = None

        manager = IssueSyncManager(gh, MagicMock(), "main")
        created = manager.ensure_labels_exist()

        expected_names = RELEASE_ISSUE_LABELS
        assert sorted(created) == sorted(expected_names)

    def test_passes_correct_color_and_description(self):
        """Test labels are created with correct color and description."""
        gh = MagicMock()
        gh.get_label.return_value = None

        manager = IssueSyncManager(gh, MagicMock(), "main")
        manager.ensure_labels_exist()

        # Check one specific label
        calls = gh.create_label.call_args_list
        release_issue_call = next(
            c for c in calls if c.args[0] == "release-issue"
        )
        assert release_issue_call.args[1] == "5319E7"  # Color
        assert "automation" in release_issue_call.args[2].lower()  # Description


class TestSyncReleaseIssueWithLabels:
    """Tests that sync_release_issue ensures labels exist."""

    def test_ensures_labels_before_operations(self):
        """Test ensure_labels_exist is called during sync."""
        gh = MagicMock()
        gh.get_label.return_value = None  # All labels missing
        gh.search_issues.return_value = []

        manager = IssueSyncManager(gh, MagicMock(), "main")

        manager.sync_release_issue({"repository": {"target_release_tag": "r4.1"}}, ReleaseView(state="not-planned"))

        # Labels should have been ensured
        assert gh.create_label.call_count == 6


PUBLISHED_BODY = (
    "<!-- release-automation:workflow-owned -->\n"
    "<!-- BEGIN:STATE -->\nold state\n<!-- END:STATE -->\n"
    "<!-- BEGIN:CONFIG -->\nconfig\n<!-- END:CONFIG -->\n"
    "<!-- BEGIN:ACTIONS -->\nold actions\n<!-- END:ACTIONS -->\n"
)


class TestFinalizePublishedIssue:
    """Published Release Issue: STATE/ACTIONS, label swap, close only on a created sync PR.

    Reproduces the former inline "Update and Close Release Issue" step.
    """

    def finalize(self, gh, sync_status="created", publish_warnings="", sync_pr_url="https://github.com/org/repo/pull/9"):
        gh.repo = "org/repo"
        gh.get_issue.return_value = {
            "number": 42,
            "body": PUBLISHED_BODY,
            "labels": [{"name": "release-issue"}, {"name": "release-state:draft-ready"}],
        }
        manager = IssueSyncManager(gh, issue_manager=IssueManager(), base_branch="main")
        return manager.finalize_published_issue(
            issue_number=42,
            release_tag="r4.1",
            release_url="https://github.com/org/repo/releases/tag/r4.1",
            reference_tag="src/r4.1",
            sync_pr_url=sync_pr_url,
            sync_status=sync_status,
            publish_warnings=publish_warnings,
        )

    def body(self, gh):
        return gh.update_issue.call_args.kwargs["body"]

    def test_created_updates_body_swaps_labels_and_closes(self):
        gh = MagicMock()

        assert self.finalize(gh) is True

        assert self.body(gh) == (
            "<!-- release-automation:workflow-owned -->\n"
            "<!-- BEGIN:STATE -->\n"
            "**State:** `published`\n"
            "\n"
            "✅ **Release published:** [r4.1](https://github.com/org/repo/releases/tag/r4.1)\n"
            "📌 **Reference tag:** [`src/r4.1`](https://github.com/org/repo/tree/src/r4.1)\n"
            "🔄 **Sync PR:** [View PR](https://github.com/org/repo/pull/9)\n"
            "<!-- END:STATE -->\n"
            "<!-- BEGIN:CONFIG -->\nconfig\n<!-- END:CONFIG -->\n"
            "<!-- BEGIN:ACTIONS -->\n_No actions available - release is published._\n<!-- END:ACTIONS -->\n"
        )
        gh.remove_labels.assert_called_once_with(42, ["release-state:draft-ready"])
        gh.add_labels.assert_called_once_with(42, ["release-state:published"])
        gh.close_issue.assert_called_once_with(42, state_reason="completed")

    @pytest.mark.parametrize(
        "sync_status,warning,action",
        [
            ("failed", "Post-release sync PR creation failed — create manually", "Create post-release sync PR manually"),
            ("no_changes", "Post-release sync skipped (no changes detected) — verify README/CHANGELOG", "Verify README and CHANGELOG"),
            ("", "Post-release sync status unknown — verify README/CHANGELOG", "Verify post-release sync status"),
            ("unexpected", "Post-release sync status unknown — verify README/CHANGELOG", "Verify post-release sync status"),
        ],
    )
    def test_without_created_sync_pr_issue_stays_open(self, sync_status, warning, action):
        gh = MagicMock()

        assert self.finalize(gh, sync_status=sync_status, sync_pr_url="") is True

        body = self.body(gh)
        assert f"⚠️ **Warnings:** {warning}\n<!-- END:STATE -->" in body
        assert "Sync PR" not in body
        assert f"<!-- BEGIN:ACTIONS -->\n**Manual action required:** {action}" in body
        gh.add_labels.assert_called_once_with(42, ["release-state:published"])
        gh.close_issue.assert_not_called()

    def test_publish_warnings_appear_in_state(self):
        gh = MagicMock()

        self.finalize(gh, publish_warnings="Failed to create reference tag; Failed to create pointer branch")

        assert (
            "⚠️ **Warnings:** Failed to create reference tag; Failed to create pointer branch\n<!-- END:STATE -->"
        ) in self.body(gh)
        gh.close_issue.assert_called_once()

    def test_publish_and_sync_warnings_are_joined(self):
        gh = MagicMock()

        self.finalize(gh, sync_status="failed", publish_warnings="Failed to create pointer branch")

        assert (
            "⚠️ **Warnings:** Failed to create pointer branch; "
            "Post-release sync PR creation failed — create manually"
        ) in self.body(gh)

    @pytest.mark.parametrize("failing", ["get_issue", "update_issue", "add_labels", "close_issue"])
    def test_api_errors_are_logged_not_raised(self, failing, capsys):
        gh = MagicMock()
        getattr(gh, failing).side_effect = GitHubClientError("gh command failed: 502")

        assert self.finalize(gh) is False
        assert "::warning::Failed to close issue: gh command failed: 502" in capsys.readouterr().out


@pytest.mark.parametrize(
    "publish_warnings,sync_status,expected",
    [
        ("", "created", ""),
        ("a; b", "created", "a; b"),
        ("", "failed", "Post-release sync PR creation failed — create manually"),
        ("a", "no_changes", "a; Post-release sync skipped (no changes detected) — verify README/CHANGELOG"),
        ("", "", "Post-release sync status unknown — verify README/CHANGELOG"),
    ],
)
def test_post_publish_warnings(publish_warnings, sync_status, expected):
    assert post_publish_warnings(publish_warnings, sync_status) == expected



# ── sync_for_workflow: the Release Issue sync of the finalize job ────────────

from release_automation.scripts.issue_sync import WorkflowSync, sync_for_workflow  # noqa: E402

PLAN_YAML = "repository:\n  target_release_tag: r4.1\n  target_release_type: pre-release-alpha\n"


class TestSyncForWorkflow:
    def run(self, monkeypatch, tmp_path, result=None, plan=PLAN_YAML, raises=None, view=None, **plan_fields):
        gh = MagicMock()
        gh.get_file_content.return_value = plan
        calls = {}

        def fake_sync(self, release_plan, view):
            calls.update(release_plan=release_plan, view=view, base_branch=self.base_branch)
            if raises:
                raise raises
            return result

        monkeypatch.setattr(IssueSyncManager, "sync_release_issue", fake_sync)
        summary = tmp_path / "summary"
        document = make_plan(**{"release_tag": "r4.1", "state": "planned", "base_branch": "main", **plan_fields})
        outcome = sync_for_workflow(gh, document, view or ReleaseView(state=document.state), summary_path=str(summary))
        return outcome, calls, summary.read_text() if summary.exists() else "", gh

    def test_created(self, monkeypatch, tmp_path):
        issue = {"number": 7, "html_url": "https://github.com/o/r/issues/7"}
        view = ReleaseView(state="snapshot-active", snapshot_branch="release-snapshot/r4.1-abc", release_pr_number="12",
                           common_cache_status="stale", common_cache_details="d", common_sync_pr_url="u")

        outcome, calls, _, _ = self.run(monkeypatch, tmp_path, SyncResult(action="created", issue=issue), view=view)

        assert outcome == WorkflowSync(issue_number="7", issue_action="created", issue_url="https://github.com/o/r/issues/7")
        assert calls["release_plan"]["repository"]["target_release_tag"] == "r4.1"
        assert calls["view"] is view

    def test_reads_the_plan_of_the_base_branch(self, monkeypatch, tmp_path):
        _, calls, _, gh = self.run(monkeypatch, tmp_path, SyncResult(action="none"), base_branch="maintenance/r4")

        gh.get_file_content.assert_called_once_with("release-plan.yaml", ref="maintenance/r4")
        assert calls["base_branch"] == "maintenance/r4"

    def test_no_action_is_unchanged(self, monkeypatch, tmp_path):
        outcome, _, summary, _ = self.run(monkeypatch, tmp_path, SyncResult(action="none", reason="up_to_date"))

        assert outcome == WorkflowSync(issue_action="unchanged")
        assert summary == ""

    def test_no_planned_release_writes_summary(self, monkeypatch, tmp_path):
        outcome, _, summary, _ = self.run(monkeypatch, tmp_path, SyncResult(action="none", reason="no_planned_release"))

        assert outcome == WorkflowSync(issue_action="unchanged")
        assert summary == (
            "## Release Status: Not Planned\n\n"
            "No release is currently planned for `r4.1` (`target_release_type: none`).\n"
            "No open Release Issue exists.\n"
        )

    def test_published_is_skipped_with_summary(self, monkeypatch, tmp_path):
        outcome, calls, summary, _ = self.run(monkeypatch, tmp_path, view=ReleaseView(state="published"))

        assert outcome == WorkflowSync(issue_action="skipped")
        assert calls == {}
        assert summary == (
            "## Release Status: Published\n\n"
            "Release `r4.1` has already been published. No further actions needed.\n"
        )

    def test_without_release_tag_is_skipped(self, monkeypatch, tmp_path):
        outcome, calls, _, _ = self.run(monkeypatch, tmp_path, release_tag="")

        assert outcome == WorkflowSync(issue_action="skipped")
        assert calls == {}

    @pytest.mark.parametrize("plan", [None, "a: [", "- just a list\n"])
    def test_unreadable_release_plan_is_skipped(self, monkeypatch, tmp_path, plan):
        outcome, calls, _, _ = self.run(monkeypatch, tmp_path, plan=plan)

        assert outcome == WorkflowSync(issue_action="skipped")
        assert calls == {}

    def test_sync_exception_is_an_error(self, monkeypatch, tmp_path):
        outcome, _, _, _ = self.run(monkeypatch, tmp_path, raises=RuntimeError("boom"))

        assert outcome == WorkflowSync(issue_action="error")
