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
    REQUIRED_LABELS,
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
        """Test finding an issue with workflow marker and release tag marker in body."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.1 (RC) — Sync26",
                "body": f"Some content\n{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.1 -->\nMore content",
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
        """Test that issues with different release tag marker are ignored."""
        gh = MagicMock()
        gh.search_issues.return_value = [
            {
                "number": 1,
                "title": "Release r4.0 (RC)",
                "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.0 -->",
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
                "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.0 -->",
                "labels": []
            },
            {
                "number": 2,
                "title": "Release r4.1 (RC)",
                "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.1 -->",
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

        # Make retry_on_not_found call the function directly (no actual retry in tests)
        gh.retry_on_not_found.side_effect = lambda fn, **kwargs: fn()

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)
        return manager, gh, state_manager, issue_manager, bot_responder

    def test_creates_issue_when_planned_and_no_issue(self):
        """Test issue creation when PLANNED and no existing issue."""
        manager, gh, state_manager, issue_manager, _ = self._create_manager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Sync26"
            }
        }

        state_manager.derive_state.return_value = ReleaseState.PLANNED
        gh.search_issues.return_value = []
        gh.create_issue.return_value = {"number": 1, "title": "Release r4.1 (RC)"}
        issue_manager.generate_title.return_value = "Release r4.1 (RC) — Sync26"
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
                "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.1 -->",
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
                "body": f"{WORKFLOW_MARKER}\n<!-- release-automation:release-tag:r4.1 -->\n<!-- BEGIN:STATE -->old<!-- END:STATE -->",
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

        state_manager.derive_state.return_value = ReleaseState.NOT_PLANNED
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
        issue_manager.generate_issue_body_template.return_value = "### Release Highlights\nContent"

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
        assert manager.get_state_label(ReleaseState.NOT_PLANNED) == "release-state:not-planned"


class TestWorkflowMarkerConstant:
    """Tests for WORKFLOW_MARKER constant."""

    def test_marker_format(self):
        """Test marker has expected format."""
        assert "release-automation" in WORKFLOW_MARKER
        assert "workflow-owned" in WORKFLOW_MARKER
        assert WORKFLOW_MARKER.startswith("<!--")
        assert WORKFLOW_MARKER.endswith("-->")


class TestRequiredLabels:
    """Tests for REQUIRED_LABELS constant."""

    def test_required_labels_defined(self):
        """Test required labels are defined."""
        assert len(REQUIRED_LABELS) == 6

    def test_required_labels_have_correct_format(self):
        """Test each label has (name, color, description) format."""
        for label in REQUIRED_LABELS:
            assert len(label) == 3
            name, color, description = label
            assert isinstance(name, str)
            assert isinstance(color, str)
            assert isinstance(description, str)
            # Color should be 6 hex chars
            assert len(color) == 6

    def test_required_labels_include_release_issue(self):
        """Test release-issue label is included."""
        names = [l[0] for l in REQUIRED_LABELS]
        assert "release-issue" in names

    def test_required_labels_include_all_states(self):
        """Test all state labels are included."""
        names = [l[0] for l in REQUIRED_LABELS]
        assert "release-state:planned" in names
        assert "release-state:snapshot-active" in names
        assert "release-state:draft-ready" in names
        assert "release-state:published" in names
        assert "release-state:not-planned" in names


class TestEnsureLabelsExist:
    """Tests for ensure_labels_exist method."""

    def test_creates_missing_labels(self):
        """Test missing labels are created."""
        gh = MagicMock()
        gh.get_label.return_value = None  # All labels missing

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        created = manager.ensure_labels_exist()

        assert len(created) == 6
        assert gh.create_label.call_count == 6

    def test_skips_existing_labels(self):
        """Test existing labels are not recreated."""
        gh = MagicMock()
        # Only release-issue exists
        gh.get_label.side_effect = lambda name: {"name": name} if name == "release-issue" else None

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        created = manager.ensure_labels_exist()

        assert len(created) == 5  # 6 - 1 = 5 created
        assert "release-issue" not in created
        assert gh.create_label.call_count == 5

    def test_is_idempotent(self):
        """Test calling multiple times only creates labels once."""
        gh = MagicMock()
        gh.get_label.return_value = None

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())

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

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
        created = manager.ensure_labels_exist()

        expected_names = [l[0] for l in REQUIRED_LABELS]
        assert sorted(created) == sorted(expected_names)

    def test_passes_correct_color_and_description(self):
        """Test labels are created with correct color and description."""
        gh = MagicMock()
        gh.get_label.return_value = None

        manager = IssueSyncManager(gh, MagicMock(), MagicMock(), MagicMock())
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
        state_manager = MagicMock()
        gh.get_label.return_value = None  # All labels missing
        state_manager.derive_state.return_value = ReleaseState.NOT_PLANNED
        gh.search_issues.return_value = []

        manager = IssueSyncManager(gh, state_manager, MagicMock(), MagicMock())

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1"
            }
        }

        manager.sync_release_issue(release_plan)

        # Labels should have been ensured
        assert gh.create_label.call_count == 6


class TestCloseReleaseIssue:
    """Tests for close_release_issue method."""

    def test_close_release_issue_success(self):
        """Test successful issue closure flow."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        # Setup issue
        gh.get_issue.return_value = {
            "number": 42,
            "body": "<!-- BEGIN:STATE -->\nold\n<!-- END:STATE -->\n<!-- BEGIN:ACTIONS -->\nold\n<!-- END:ACTIONS -->",
            "labels": [{"name": "release-state:draft-ready"}]
        }

        # Setup issue_manager section generators
        issue_manager.generate_published_state_section.return_value = "published state"
        issue_manager.generate_published_actions_section.return_value = "no actions"
        issue_manager.update_section.side_effect = lambda body, section, content: body.replace(
            f"<!-- BEGIN:{section} -->\nold\n<!-- END:{section} -->",
            f"<!-- BEGIN:{section} -->\n{content}\n<!-- END:{section} -->"
        )

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)

        result = manager.close_release_issue(
            issue_number=42,
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1",
            sync_pr_url="https://github.com/test/pull/123"
        )

        assert result is True

        # Verify STATE section was updated
        issue_manager.generate_published_state_section.assert_called_once_with(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1",
            sync_pr_url="https://github.com/test/pull/123"
        )

        # Verify ACTIONS section was updated
        issue_manager.generate_published_actions_section.assert_called_once()

        # Verify labels were updated
        gh.remove_labels.assert_called_once_with(42, ["release-state:draft-ready"])
        gh.add_labels.assert_called_once_with(42, ["release-state:published"])

        # Verify issue was closed
        gh.close_issue.assert_called_once_with(42, state_reason="completed")

    def test_close_release_issue_without_sync_pr(self):
        """Test closure without sync PR URL."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        gh.get_issue.return_value = {
            "number": 42,
            "body": "body content",
            "labels": []
        }
        issue_manager.update_section.side_effect = lambda body, section, content: body

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)

        result = manager.close_release_issue(
            issue_number=42,
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1"
        )

        assert result is True

        # sync_pr_url should be None when empty string passed
        issue_manager.generate_published_state_section.assert_called_once()
        call_kwargs = issue_manager.generate_published_state_section.call_args
        assert call_kwargs.kwargs.get("sync_pr_url") is None

    def test_close_release_issue_api_error(self):
        """Test graceful handling of API errors."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        # Simulate API error
        gh.get_issue.side_effect = Exception("API error")

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)

        result = manager.close_release_issue(
            issue_number=42,
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1"
        )

        # Should return False on error, not raise
        assert result is False

    def test_close_release_issue_no_existing_state_labels(self):
        """Test closure when no state labels exist."""
        gh = MagicMock()
        state_manager = MagicMock()
        issue_manager = MagicMock()
        bot_responder = MagicMock()

        gh.get_issue.return_value = {
            "number": 42,
            "body": "body",
            "labels": [{"name": "release-issue"}]  # No state label
        }
        issue_manager.update_section.side_effect = lambda body, section, content: body

        manager = IssueSyncManager(gh, state_manager, issue_manager, bot_responder)

        result = manager.close_release_issue(
            issue_number=42,
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1"
        )

        assert result is True

        # Should not call remove_labels if no state labels
        gh.remove_labels.assert_not_called()

        # Should still add published label
        gh.add_labels.assert_called_once_with(42, ["release-state:published"])
