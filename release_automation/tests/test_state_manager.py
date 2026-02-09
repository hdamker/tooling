"""
Unit tests for the release state manager.

These tests verify the state derivation logic for all 5 release states
and edge cases.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from release_automation.scripts.github_client import Branch
from release_automation.scripts.state_manager import (
    ConfigurationError,
    ReleaseInfoResult,
    ReleaseState,
    ReleaseStateManager,
    SnapshotInfo,
)


@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient with default behavior."""
    client = Mock()
    client.tag_exists.return_value = False
    client.list_branches.return_value = []
    client.draft_release_exists.return_value = False
    client.get_file_content.return_value = None
    client.get_branch_creation_time.return_value = "2026-01-29T12:00:00Z"
    client.find_pr_for_branch.return_value = None
    client.search_issues.return_value = []  # No release issues by default
    return client


@pytest.fixture
def state_manager(mock_github_client):
    """Create a ReleaseStateManager with mocked client."""
    return ReleaseStateManager(mock_github_client)


class TestDeriveState:
    """Tests for derive_state method."""

    def test_published_when_tag_exists(self, state_manager, mock_github_client):
        """Tag exists → PUBLISHED state."""
        mock_github_client.tag_exists.return_value = True

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.PUBLISHED
        mock_github_client.tag_exists.assert_called_once_with("r4.1")

    def test_draft_ready_when_snapshot_and_draft_release(
        self, state_manager, mock_github_client
    ):
        """Snapshot branch + draft release → DRAFT_READY state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        mock_github_client.draft_release_exists.return_value = True

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.DRAFT_READY
        mock_github_client.list_branches.assert_called_once_with(
            "release-snapshot/r4.1-*"
        )
        mock_github_client.draft_release_exists.assert_called_once_with("r4.1")

    def test_snapshot_active_when_snapshot_no_draft(
        self, state_manager, mock_github_client
    ):
        """Snapshot branch exists, no draft release → SNAPSHOT_ACTIVE state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        mock_github_client.draft_release_exists.return_value = False

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.SNAPSHOT_ACTIVE

    def test_planned_when_release_plan_defines_release(
        self, state_manager, mock_github_client
    ):
        """release-plan.yaml with matching target → PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.PLANNED

    def test_not_planned_when_release_type_is_none(
        self, state_manager, mock_github_client
    ):
        """release-plan.yaml with target_release_type: none → NOT_PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: none
"""

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.NOT_PLANNED

    def test_not_planned_when_tag_mismatch(self, state_manager, mock_github_client):
        """release-plan.yaml with different tag → NOT_PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r5.0
  target_release_type: initial
"""

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.NOT_PLANNED

    def test_not_planned_when_no_release_plan(self, state_manager, mock_github_client):
        """No release-plan.yaml → NOT_PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = None

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.NOT_PLANNED

    def test_not_planned_when_malformed_yaml(self, state_manager, mock_github_client):
        """Malformed release-plan.yaml → NOT_PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = "{{invalid yaml::"

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.NOT_PLANNED

    def test_not_planned_when_missing_repository_section(
        self, state_manager, mock_github_client
    ):
        """release-plan.yaml without repository section → NOT_PLANNED state."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.list_branches.return_value = []
        mock_github_client.get_file_content.return_value = """
apis:
  - name: quality-on-demand
    version: 1.0.0
"""

        state = state_manager.derive_state("r4.1")

        assert state == ReleaseState.NOT_PLANNED


class TestGetCurrentSnapshot:
    """Tests for get_current_snapshot method."""

    def test_returns_none_when_no_snapshot(self, state_manager, mock_github_client):
        """No snapshot branch → returns None."""
        mock_github_client.list_branches.return_value = []

        result = state_manager.get_current_snapshot("r4.1")

        assert result is None

    def test_returns_snapshot_info_when_exists(self, state_manager, mock_github_client):
        """Snapshot branch exists → returns SnapshotInfo."""
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234567890")
        ]
        mock_github_client.get_file_content.return_value = """
repository:
  src_commit_sha: full1234567890abcdef1234567890abcdef12345678
"""
        mock_github_client.get_branch_creation_time.return_value = (
            "2026-01-29T12:00:00Z"
        )
        mock_github_client.find_pr_for_branch.return_value = 42

        result = state_manager.get_current_snapshot("r4.1")

        assert result is not None
        assert result.snapshot_id == "r4.1-abc1234"
        assert result.snapshot_branch == "release-snapshot/r4.1-abc1234"
        assert result.release_review_branch == "release-review/r4.1-abc1234"
        assert result.src_commit_sha == "full1234567890abcdef1234567890abcdef12345678"
        assert result.release_pr_number == 42

    def test_uses_branch_sha_when_no_metadata(self, state_manager, mock_github_client):
        """No release-metadata.yaml → uses branch SHA."""
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="branch_sha_123")
        ]
        mock_github_client.get_file_content.return_value = None
        mock_github_client.get_branch_creation_time.return_value = (
            "2026-01-29T12:00:00Z"
        )

        result = state_manager.get_current_snapshot("r4.1")

        assert result is not None
        assert result.src_commit_sha == "branch_sha_123"

    def test_handles_invalid_datetime(self, state_manager, mock_github_client):
        """Invalid datetime string → uses current time."""
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        mock_github_client.get_file_content.return_value = None
        mock_github_client.get_branch_creation_time.return_value = "not-a-valid-date"

        result = state_manager.get_current_snapshot("r4.1")

        assert result is not None
        # Should not raise an exception, uses fallback datetime


class TestGetSnapshotHistory:
    """Tests for get_snapshot_history method."""

    def test_returns_empty_list_when_no_snapshot(
        self, state_manager, mock_github_client
    ):
        """No snapshot → returns empty list."""
        mock_github_client.list_branches.return_value = []

        result = state_manager.get_snapshot_history("r4.1")

        assert result == []

    def test_returns_current_snapshot_when_exists(
        self, state_manager, mock_github_client
    ):
        """Current snapshot exists → returns list with one item."""
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        mock_github_client.get_file_content.return_value = None
        mock_github_client.get_branch_creation_time.return_value = (
            "2026-01-29T12:00:00Z"
        )

        result = state_manager.get_snapshot_history("r4.1")

        assert len(result) == 1
        assert result[0].snapshot_id == "r4.1-abc1234"


class TestStateTransitions:
    """Integration tests for state transition scenarios."""

    def test_full_lifecycle_happy_path(self, mock_github_client):
        """Test state transitions through the happy path."""
        manager = ReleaseStateManager(mock_github_client)

        # Initial state: PLANNED
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        assert manager.derive_state("r4.1") == ReleaseState.PLANNED

        # After /create-snapshot: SNAPSHOT_ACTIVE
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        assert manager.derive_state("r4.1") == ReleaseState.SNAPSHOT_ACTIVE

        # After PR merge creates draft: DRAFT_READY
        mock_github_client.draft_release_exists.return_value = True
        assert manager.derive_state("r4.1") == ReleaseState.DRAFT_READY

        # After release published: PUBLISHED
        mock_github_client.tag_exists.return_value = True
        assert manager.derive_state("r4.1") == ReleaseState.PUBLISHED

    def test_discard_and_retry_path(self, mock_github_client):
        """Test state transitions through discard and retry path."""
        manager = ReleaseStateManager(mock_github_client)

        # Start with SNAPSHOT_ACTIVE
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-abc1234", sha="abc1234")
        ]
        assert manager.derive_state("r4.1") == ReleaseState.SNAPSHOT_ACTIVE

        # After /discard-snapshot: back to PLANNED
        mock_github_client.list_branches.return_value = []
        assert manager.derive_state("r4.1") == ReleaseState.PLANNED

        # New /create-snapshot: SNAPSHOT_ACTIVE again
        mock_github_client.list_branches.return_value = [
            Branch(name="release-snapshot/r4.1-def5678", sha="def5678")
        ]
        assert manager.derive_state("r4.1") == ReleaseState.SNAPSHOT_ACTIVE


class TestGetCurrentReleaseInfoErrors:
    """Tests for get_current_release_info() configuration error handling.

    Configuration errors should return error results, not NOT_PLANNED state.
    """

    def test_returns_error_when_file_missing(self, state_manager, mock_github_client):
        """Missing release-plan.yaml returns config error, not NOT_PLANNED."""
        mock_github_client.get_file_content.return_value = None

        result = state_manager.get_current_release_info()

        assert not result.success
        assert result.config_error is not None
        assert result.config_error.error_type == "missing_file"
        assert "release-plan.yaml" in result.config_error.message
        assert result.config_error.file_path == "release-plan.yaml"
        assert result.state is None  # NOT NOT_PLANNED

    def test_returns_error_when_yaml_malformed(self, state_manager, mock_github_client):
        """Malformed YAML returns config error, not NOT_PLANNED."""
        mock_github_client.get_file_content.return_value = "{{invalid yaml:: missing"

        result = state_manager.get_current_release_info()

        assert not result.success
        assert result.config_error is not None
        assert result.config_error.error_type == "malformed_yaml"
        assert result.config_error.file_path == "release-plan.yaml"
        assert result.state is None

    def test_returns_error_when_yaml_empty(self, state_manager, mock_github_client):
        """Empty YAML (null) returns config error."""
        mock_github_client.get_file_content.return_value = ""

        result = state_manager.get_current_release_info()

        assert not result.success
        assert result.config_error is not None
        assert result.config_error.error_type == "malformed_yaml"

    def test_returns_error_when_repository_section_missing(
        self, state_manager, mock_github_client
    ):
        """Missing repository section returns config error."""
        mock_github_client.get_file_content.return_value = """
apis:
  - api_name: quality-on-demand
"""
        result = state_manager.get_current_release_info()

        assert not result.success
        assert result.config_error is not None
        assert result.config_error.error_type == "missing_field"
        assert result.config_error.field_path == "repository"

    def test_returns_error_when_target_tag_missing(
        self, state_manager, mock_github_client
    ):
        """Missing target_release_tag returns config error."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_type: initial
"""
        result = state_manager.get_current_release_info()

        assert not result.success
        assert result.config_error is not None
        assert result.config_error.error_type == "missing_field"
        assert result.config_error.field_path == "repository.target_release_tag"

    def test_returns_not_planned_for_intentional_none(
        self, state_manager, mock_github_client
    ):
        """target_release_type: none returns NOT_PLANNED (success, not error)."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: none
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False

        result = state_manager.get_current_release_info()

        assert result.success
        assert result.state == ReleaseState.NOT_PLANNED
        assert result.config_error is None
        assert result.release_tag == "r4.1"

    def test_returns_not_planned_when_release_type_missing(
        self, state_manager, mock_github_client
    ):
        """Missing target_release_type defaults to NOT_PLANNED (like 'none')."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False

        result = state_manager.get_current_release_info()

        assert result.success
        assert result.state == ReleaseState.NOT_PLANNED
        assert result.release_tag == "r4.1"

    def test_returns_planned_for_valid_config(
        self, state_manager, mock_github_client
    ):
        """Valid config with release type returns PLANNED."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False

        result = state_manager.get_current_release_info()

        assert result.success
        assert result.state == ReleaseState.PLANNED
        assert result.release_tag == "r4.1"
        assert result.source == "release-plan.yaml"

    def test_to_dict_on_error_result(self, state_manager, mock_github_client):
        """to_dict() returns proper structure for error results."""
        mock_github_client.get_file_content.return_value = None

        result = state_manager.get_current_release_info()
        result_dict = result.to_dict()

        assert result_dict["release_tag"] is None
        assert result_dict["state"] is None
        assert result_dict["config_error"] is not None
        assert result_dict["config_error_type"] == "missing_file"

    def test_to_dict_on_success_result(self, state_manager, mock_github_client):
        """to_dict() returns proper structure for success results."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False
        mock_github_client.search_issues.return_value = []

        result = state_manager.get_current_release_info()
        result_dict = result.to_dict()

        assert result_dict["release_tag"] == "r4.1"
        assert result_dict["state"] == ReleaseState.PLANNED
        assert result_dict["config_error"] is None
        assert result_dict["config_error_type"] is None
        assert result_dict["release_issue_number"] is None


class TestFindReleaseIssue:
    """Tests for find_release_issue method."""

    def test_returns_none_when_no_issues(self, state_manager, mock_github_client):
        """Returns None when no release issues exist."""
        mock_github_client.search_issues.return_value = []

        result = state_manager.find_release_issue("r4.1")

        assert result is None
        mock_github_client.search_issues.assert_called_once_with(
            labels=["release-issue"], state="open"
        )

    def test_returns_issue_number_when_found(self, state_manager, mock_github_client):
        """Returns issue number when workflow-owned issue exists."""
        mock_github_client.search_issues.return_value = [
            {
                "number": 42,
                "title": "Release r4.1 - Tracking Issue",
                "body": "<!-- release-automation:workflow-owned -->\nRelease content",
            }
        ]

        result = state_manager.find_release_issue("r4.1")

        assert result == 42

    def test_ignores_issues_without_workflow_marker(
        self, state_manager, mock_github_client
    ):
        """Ignores issues that don't have the workflow marker."""
        mock_github_client.search_issues.return_value = [
            {
                "number": 99,
                "title": "Release r4.1 - Manual Issue",
                "body": "This is a manually created issue without marker",
            }
        ]

        result = state_manager.find_release_issue("r4.1")

        assert result is None

    def test_ignores_issues_with_different_release_tag(
        self, state_manager, mock_github_client
    ):
        """Ignores issues for different release tags."""
        mock_github_client.search_issues.return_value = [
            {
                "number": 50,
                "title": "Release r3.0 - Tracking Issue",
                "body": "<!-- release-automation:workflow-owned -->\nRelease content",
            }
        ]

        result = state_manager.find_release_issue("r4.1")

        assert result is None

    def test_handles_none_body(self, state_manager, mock_github_client):
        """Handles issues with None body gracefully."""
        mock_github_client.search_issues.return_value = [
            {
                "number": 10,
                "title": "Release r4.1",
                "body": None,
            }
        ]

        result = state_manager.find_release_issue("r4.1")

        assert result is None

    def test_handles_none_title(self, state_manager, mock_github_client):
        """Handles issues with None title gracefully."""
        mock_github_client.search_issues.return_value = [
            {
                "number": 10,
                "title": None,
                "body": "<!-- release-automation:workflow-owned -->\nContent",
            }
        ]

        result = state_manager.find_release_issue("r4.1")

        assert result is None


class TestGetCurrentReleaseInfoWithIssue:
    """Tests for get_current_release_info including release_issue_number."""

    def test_includes_issue_number_when_found(self, state_manager, mock_github_client):
        """Includes release issue number when issue exists."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False
        mock_github_client.search_issues.return_value = [
            {
                "number": 123,
                "title": "Release r4.1 - Tracking Issue",
                "body": "<!-- release-automation:workflow-owned -->\nRelease content",
            }
        ]

        result = state_manager.get_current_release_info()

        assert result.success
        assert result.release_issue_number == 123

    def test_issue_number_is_none_when_not_found(
        self, state_manager, mock_github_client
    ):
        """release_issue_number is None when no issue exists."""
        mock_github_client.get_file_content.return_value = """
repository:
  target_release_tag: r4.1
  target_release_type: initial
"""
        mock_github_client.list_branches.return_value = []
        mock_github_client.tag_exists.return_value = False
        mock_github_client.search_issues.return_value = []

        result = state_manager.get_current_release_info()

        assert result.success
        assert result.release_issue_number is None
