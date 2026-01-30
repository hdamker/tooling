"""
Unit tests for issue_sync.py

Tests the IssueSyncManager class which handles Release Issue synchronization.
"""

import pytest
from unittest.mock import MagicMock, patch

from release_automation.scripts.issue_sync import (
    IssueSyncManager,
    SyncResult,
    WORKFLOW_MARKER,
)
from release_automation.scripts.state_manager import ReleaseState


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
        """Test initialization with all dependencies."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)

        assert manager.gh == gh
        assert manager.state_manager == state_manager
        assert manager.issue_manager == issue_manager
        assert manager.bot == bot_responder


class TestFindWorkflowOwnedIssue:
    """Tests for find_workflow_owned_issue method."""

    def test_finds_issue_with_marker_and_tag(self):
        """Test finding an issue with workflow marker and release tag."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.1 (RC) — Fall26",
                "body": f"Some content\n{WORKFLOW_MARKER}\nMore content",
                "labels": [{"name": "release-issue"}]
            }
        ]

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        result = manager.find_workflow_owned_issue("r4.1")

        assert result is not None
        assert result["number"] == 1
        gh.search_issues.assert_called_once_with(labels=["release-issue"], state="open")

    def test_ignores_issue_without_marker(self):
        """Test that issues without workflow marker are ignored."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.1 (RC)",
                "body": "No marker here",
                "labels": [{"name": "release-issue"}]
            }
        ]

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        result = manager.find_workflow_owned_issue("r4.1")

        assert result is None

    def test_ignores_issue_with_wrong_tag(self):
        """Test that issues with different release tag are ignored."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.0 (RC)",  # Different tag
                "body": f"{WORKFLOW_MARKER}",
                "labels": [{"name": "release-issue"}]
            }
        ]

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        result = manager.find_workflow_owned_issue("r4.1")

        assert result is None

    def test_returns_none_when_no_issues(self):
        """Test returns None when no issues found."""
        gh = MagicMock()
        gh.search_issues.return_value = []

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        result = manager.find_workflow_owned_issue("r4.1")

        assert result is None

    def test_handles_multiple_issues_finds_correct_one(self):
        """Test finding correct issue among multiple."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.0",
                "body": f"{WORKFLOW_MARKER}",
                "labels": []
            },
            {
                "number": 2,
                "title": "Release r4.1 (RC)",
                "body": f"{WORKFLOW_MARKER}",
                "labels": []
            },
            {
                "number": 3,
                "title": "Manual release issue",
                "body": "No marker",
                "labels": []
            }
        ]

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        result = manager.find_workflow_owned_issue("r4.1")

        assert result is not None
        assert result["number"] == 2


class TestSyncReleaseIssue:
    """Tests for sync_release_issue method."""

    def _create_manager(self):
        """Helper to create a manager with mocked dependencies."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)
        return manager, gh, state_manager, issue_manager, bot_responder

    def test_creates_issue_when_planned_and_no_issue(self):
        """Test issue creation when PLANNED and no existing issue."""
        manager, gh, state_manager, issue_manager, _ = self._create_manager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Fall26"
            }
        }

        state_manager.derive_state.return_value = ReleaseState.PLANNED
        gh.search_issues.return_value = []
        gh.create_issue.return_value = {"number": 1, "title": "Release r4.1 (RC)"}
        issue_manager.generate_title.return_value = "Release r4.1 (RC) — Fall26"
        issue_manager.generate_issue_body_template.return_value = f"## Release\n{WORKFLOW_MARKER}"

        result = manager.sync_release_issue(release_plan, trigger_pr=123)

        assert result.action == "created"
        assert result.issue is not None
        gh.create_issue.assert_called_once()

    def test_no_action_when_issue_exists_and_up_to_date(self):
        """Test no action when issue exists and is up to date."""
        manager, gh, state_manager, issue_manager, _ = self._create_manager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        state_manager.derive_state.return_value = ReleaseState.PLANNED
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.1 (RC)",
                "body": f"{WORKFLOW_MARKER}",
                "labels": [{"name": "release-state:planned"}]
            }
        ]
        issue_manager.should_update_title.return_value = False

        result = manager.sync_release_issue(release_plan)

        assert result.action == "none"
        assert result.reason == "up_to_date"

    def test_updates_issue_when_state_changes(self):
        """Test issue update when state changes."""
        manager, gh, state_manager, issue_manager, _ = self._create_manager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        state_manager.derive_state.return_value = ReleaseState.SNAPSHOT_ACTIVE
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.1 (RC)",
                "body": f"{WORKFLOW_MARKER}\n<!-- BEGIN:STATE -->old<!-- END:STATE -->",
                "labels": [{"name": "release-state:planned"}]  # Old label
            }
        ]
        gh.get_issue.return_value = {"number": 1, "title": "Release r4.1 (RC)"}
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "**State**: SNAPSHOT_ACTIVE"
        issue_manager.update_section.return_value = "updated body"

        result = manager.sync_release_issue(release_plan)

        assert result.action == "updated"
        gh.remove_labels.assert_called()
        gh.add_labels.assert_called()

    def test_no_action_when_not_planned_and_no_issue(self):
        """Test no action when not PLANNED and no existing issue."""
        manager, gh, state_manager, _, _ = self._create_manager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        state_manager.derive_state.return_value = ReleaseState.CANCELLED
        gh.search_issues.return_value = []

        result = manager.sync_release_issue(release_plan)

        assert result.action == "none"
        assert result.reason == "no_planned_release"
        gh.create_issue.assert_not_called()

    def test_returns_none_action_when_missing_release_tag(self):
        """Test returns none action when release tag is missing."""
        manager, _, _, _, _ = self._create_manager()

        release_plan = {"repository": {}}

        result = manager.sync_release_issue(release_plan)

        assert result.action == "none"
        assert result.reason == "missing_release_tag"


class TestCreateReleaseIssue:
    """Tests for create_release_issue method."""

    def test_creates_issue_with_correct_labels(self):
        """Test issue is created with correct labels."""
        gh = MagicMock()
        issue_manager = MagicMock()
        gh.create_issue.return_value = {"number": 1}
        issue_manager.generate_title.return_value = "Release r4.1 (RC)"
        issue_manager.generate_issue_body_template.return_value = f"Body\n{WORKFLOW_MARKER}"

        manager = IssueSyncManager(gh, MagicMock(), issue_manager, MagicMock())

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc"
            }
        }

        manager.create_release_issue(release_plan, trigger_pr=123)

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
        issue_manager.generate_issue_body_template.return_value = "## Release\nContent"

        manager = IssueSyncManager(gh, MagicMock(), issue_manager, MagicMock())

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

        manager = IssueSyncManager(MagicMock(), MagicMock(), issue_manager, MagicMock())

        issue = {
            "labels": [{"name": "release-state:planned"}]
        }

        result = manager._needs_update(issue, ReleaseState.SNAPSHOT_ACTIVE, {})
        assert result is True

    def test_no_update_when_state_matches(self):
        """Test returns False when state label matches."""
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False

        manager = IssueSyncManager(MagicMock(), MagicMock(), issue_manager, MagicMock())

        issue = {
            "labels": [{"name": "release-state:planned"}]
        }

        result = manager._needs_update(issue, ReleaseState.PLANNED, {})
        assert result is False

    def test_needs_update_when_title_changed(self):
        """Test returns True when title needs updating."""
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = True

        manager = IssueSyncManager(MagicMock(), MagicMock(), issue_manager, MagicMock())

        issue = {
            "title": "Old title",
            "labels": [{"name": "release-state:planned"}]
        }

        result = manager._needs_update(issue, ReleaseState.PLANNED, {"repository": {}})
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

        manager = IssueSyncManager(gh, MagicMock(), issue_manager, MagicMock())

        issue = {
            "number": 1,
            "body": "body",
            "labels": [{"name": "release-state:planned"}]
        }

        manager._update_release_issue(issue, ReleaseState.SNAPSHOT_ACTIVE, {})

        gh.remove_labels.assert_called_with(1, ["release-state:planned"])
        gh.add_labels.assert_called_with(1, ["release-state:snapshot-active"])

    def test_updates_issue_body(self):
        """Test issue body is updated when changed."""
        gh = MagicMock()
        issue_manager = MagicMock()
        issue_manager.should_update_title.return_value = False
        issue_manager.generate_state_section.return_value = "new state"
        issue_manager.update_section.return_value = "new body"  # Different from current

        manager = IssueSyncManager(gh, MagicMock(), issue_manager, MagicMock())

        issue = {
            "number": 1,
            "body": "old body",
            "labels": []
        }

        manager._update_release_issue(issue, ReleaseState.PLANNED, {})

        gh.update_issue.assert_called()
        call_args = gh.update_issue.call_args
        assert call_args.kwargs.get("body") == "new body"


class TestGetStateLabel:
    """Tests for get_state_label method."""

    def test_returns_correct_label_for_each_state(self):
        """Test correct label returned for each state."""
        manager = IssueSyncManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())

        assert manager.get_state_label(ReleaseState.PLANNED) == "release-state:planned"
        assert manager.get_state_label(ReleaseState.SNAPSHOT_ACTIVE) == "release-state:snapshot-active"
        assert manager.get_state_label(ReleaseState.DRAFT_READY) == "release-state:draft-ready"
        assert manager.get_state_label(ReleaseState.PUBLISHED) == "release-state:published"
        assert manager.get_state_label(ReleaseState.CANCELLED) == "release-state:cancelled"


class TestWorkflowMarkerConstant:
    """Tests for WORKFLOW_MARKER constant."""

    def test_marker_format(self):
        """Test marker has expected format."""
        assert "release-automation" in WORKFLOW_MARKER
        assert "workflow-owned" in WORKFLOW_MARKER
        assert WORKFLOW_MARKER.startswith("<!--")
        assert WORKFLOW_MARKER.endswith("-->")
