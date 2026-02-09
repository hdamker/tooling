"""
Unit tests for the release publisher module.

These tests verify the publish flow including draft release lookup,
metadata finalization, and release publication.
"""

import pytest
from unittest.mock import Mock, patch

from release_automation.scripts.github_client import Release, GitHubClientError
from release_automation.scripts.release_publisher import (
    PublishResult,
    ReleasePublisher,
)


@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient with default behavior."""
    client = Mock()
    client.repo = "test-org/test-repo"
    client.get_draft_release.return_value = None
    client.get_release_id.return_value = None
    client.get_releases.return_value = []
    client.get_file_content.return_value = None
    client.update_file.return_value = {"commit": {"sha": "abc123"}}
    client.update_release.return_value = {"html_url": "https://github.com/test/releases/1"}
    # Reference tag methods
    client.tag_exists.return_value = False
    client.create_tag.return_value = {"ref": "refs/tags/src/r4.1"}
    # Branch cleanup methods
    client.delete_branch.return_value = True
    client.rename_branch.return_value = True
    return client


@pytest.fixture
def publisher(mock_github_client):
    """Create a ReleasePublisher with mocked client."""
    return ReleasePublisher(mock_github_client)


class TestGetDraftRelease:
    """Tests for get_draft_release method."""

    def test_draft_release_found(self, publisher, mock_github_client):
        """Draft release exists - returns dict with release info."""
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = 12345

        result = publisher.get_draft_release("r4.1")

        assert result is not None
        assert result["id"] == 12345
        assert result["tag_name"] == "r4.1"
        assert result["name"] == "Release r4.1"
        assert result["draft"] is True
        mock_github_client.get_draft_release.assert_called_once_with("r4.1")

    def test_draft_release_not_found(self, publisher, mock_github_client):
        """No draft release - returns None."""
        mock_github_client.get_draft_release.return_value = None

        result = publisher.get_draft_release("r4.1")

        assert result is None

    def test_draft_release_found_but_no_id(self, publisher, mock_github_client):
        """Draft release found but ID lookup fails - returns dict with None id."""
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = None

        result = publisher.get_draft_release("r4.1")

        assert result is not None
        assert result["id"] is None
        assert result["tag_name"] == "r4.1"


class TestFinalizeMetadata:
    """Tests for finalize_metadata method."""

    def test_finalize_metadata_success(self, publisher, mock_github_client):
        """Successfully finalize metadata - returns commit SHA."""
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
  release_type: pre-release-alpha
apis:
  - name: quality-on-demand
    version: 1.0.0-alpha.1
"""
        mock_github_client.update_file.return_value = {
            "commit": {"sha": "new-commit-sha"}
        }

        result = publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        assert result == "new-commit-sha"
        mock_github_client.get_file_content.assert_called_once_with(
            "release-metadata.yaml",
            ref="release-snapshot/r4.1-abc123"
        )
        # Verify update_file was called with release_date in content
        call_args = mock_github_client.update_file.call_args
        assert "release_date" in call_args.kwargs["content"]
        assert call_args.kwargs["branch"] == "release-snapshot/r4.1-abc123"

    def test_finalize_metadata_file_not_found(self, publisher, mock_github_client):
        """Metadata file doesn't exist - returns None."""
        mock_github_client.get_file_content.return_value = None

        result = publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        assert result is None
        mock_github_client.update_file.assert_not_called()

    def test_finalize_metadata_invalid_yaml(self, publisher, mock_github_client):
        """Metadata file has invalid YAML - returns None."""
        mock_github_client.get_file_content.return_value = "invalid: yaml: content: ["

        result = publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        assert result is None
        mock_github_client.update_file.assert_not_called()

    def test_finalize_metadata_update_fails(self, publisher, mock_github_client):
        """Metadata update fails - returns None."""
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
"""
        mock_github_client.update_file.side_effect = GitHubClientError("Update failed")

        result = publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        assert result is None

    def test_finalize_metadata_creates_repository_section(self, publisher, mock_github_client):
        """Metadata without repository section - creates it."""
        mock_github_client.get_file_content.return_value = """
apis:
  - name: quality-on-demand
    version: 1.0.0
"""
        mock_github_client.update_file.return_value = {
            "commit": {"sha": "new-commit-sha"}
        }

        result = publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        assert result == "new-commit-sha"
        call_args = mock_github_client.update_file.call_args
        assert "repository:" in call_args.kwargs["content"]
        assert "release_date:" in call_args.kwargs["content"]

    def test_finalize_metadata_uses_iso8601_with_time(self, publisher, mock_github_client):
        """release_date uses ISO 8601 format with time, not date-only."""
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
  release_date: null
"""
        mock_github_client.update_file.return_value = {
            "commit": {"sha": "new-commit-sha"}
        }

        publisher.finalize_metadata("release-snapshot/r4.1-abc123", "r4.1")

        call_args = mock_github_client.update_file.call_args
        content = call_args.kwargs["content"]
        # Should contain time component (T and Z), not just date
        import re
        assert re.search(r"release_date: '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'", content), \
            f"Expected ISO 8601 with time in: {content}"


class TestPublishRelease:
    """Tests for publish_release method."""

    def test_publish_release_success(self, publisher, mock_github_client):
        """Full publish flow succeeds."""
        # Setup: draft exists with ID
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = 12345

        # Setup: metadata finalization succeeds
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
"""
        mock_github_client.update_file.return_value = {
            "commit": {"sha": "metadata-commit"}
        }

        # Setup: publish succeeds
        mock_github_client.update_release.return_value = {
            "html_url": "https://github.com/test/releases/tag/r4.1",
            "id": 12345
        }

        result = publisher.publish_release("r4.1", "release-snapshot/r4.1-abc123")

        assert result.success is True
        assert result.release_url == "https://github.com/test/releases/tag/r4.1"
        assert result.release_id == 12345
        assert result.error_message is None
        # Publish call (draft=False) + separate make_latest call
        assert mock_github_client.update_release.call_count == 2
        mock_github_client.update_release.assert_any_call(
            12345, draft=False, prerelease=False
        )
        mock_github_client.update_release.assert_any_call(
            12345, make_latest='true'
        )

    def test_publish_release_no_draft(self, publisher, mock_github_client):
        """Draft doesn't exist - returns error."""
        mock_github_client.get_draft_release.return_value = None

        result = publisher.publish_release("r4.1", "release-snapshot/r4.1-abc123")

        assert result.success is False
        assert "No draft release found" in result.error_message
        mock_github_client.update_file.assert_not_called()
        mock_github_client.update_release.assert_not_called()

    def test_publish_release_no_release_id(self, publisher, mock_github_client):
        """Draft exists but can't get ID - returns error."""
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = None

        result = publisher.publish_release("r4.1", "release-snapshot/r4.1-abc123")

        assert result.success is False
        assert "Cannot determine release ID" in result.error_message

    def test_publish_release_metadata_error(self, publisher, mock_github_client):
        """Metadata finalization fails - returns error."""
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = 12345
        mock_github_client.get_file_content.return_value = None  # Can't read metadata

        result = publisher.publish_release("r4.1", "release-snapshot/r4.1-abc123")

        assert result.success is False
        assert "finalize release-metadata.yaml" in result.error_message
        mock_github_client.update_release.assert_not_called()

    def test_publish_release_api_error(self, publisher, mock_github_client):
        """GitHub API error during publish - returns error."""
        mock_github_client.get_draft_release.return_value = Release(
            tag_name="r4.1",
            name="Release r4.1",
            draft=True,
            prerelease=False,
            html_url="https://github.com/test/releases/tag/r4.1"
        )
        mock_github_client.get_release_id.return_value = 12345
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
"""
        mock_github_client.update_file.return_value = {"commit": {"sha": "abc"}}
        mock_github_client.update_release.side_effect = GitHubClientError("API error")

        result = publisher.publish_release("r4.1", "release-snapshot/r4.1-abc123")

        assert result.success is False
        assert "Failed to publish release" in result.error_message


class TestPublishResult:
    """Tests for PublishResult dataclass."""

    def test_publish_result_success(self):
        """Success result has all fields populated."""
        result = PublishResult(
            success=True,
            release_url="https://github.com/test/releases/1",
            release_id=123
        )
        assert result.success is True
        assert result.release_url == "https://github.com/test/releases/1"
        assert result.release_id == 123
        assert result.error_message is None

    def test_publish_result_failure(self):
        """Failure result has error message."""
        result = PublishResult(
            success=False,
            error_message="Something went wrong"
        )
        assert result.success is False
        assert result.error_message == "Something went wrong"
        assert result.release_url is None
        assert result.release_id is None


class TestCreateReferenceTag:
    """Tests for create_reference_tag method."""

    def test_create_reference_tag_success(self, publisher, mock_github_client):
        """Successfully creates src/rX.Y tag."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.create_tag.return_value = {"ref": "refs/tags/src/r4.1"}

        result = publisher.create_reference_tag("r4.1", "abc123def456")

        assert result == "src/r4.1"
        mock_github_client.tag_exists.assert_called_once_with("src/r4.1")
        mock_github_client.create_tag.assert_called_once_with("src/r4.1", "abc123def456")

    def test_create_reference_tag_already_exists(self, publisher, mock_github_client):
        """Tag already exists - returns tag name without error."""
        mock_github_client.tag_exists.return_value = True

        result = publisher.create_reference_tag("r4.1", "abc123def456")

        assert result == "src/r4.1"
        mock_github_client.tag_exists.assert_called_once_with("src/r4.1")
        mock_github_client.create_tag.assert_not_called()

    def test_create_reference_tag_race_condition(self, publisher, mock_github_client):
        """Tag created between check and create - handles gracefully."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.create_tag.side_effect = GitHubClientError(
            "422: Reference already exists"
        )

        result = publisher.create_reference_tag("r4.1", "abc123def456")

        assert result == "src/r4.1"

    def test_create_reference_tag_api_error(self, publisher, mock_github_client):
        """API error - returns None."""
        mock_github_client.tag_exists.return_value = False
        mock_github_client.create_tag.side_effect = GitHubClientError(
            "500: Internal server error"
        )

        result = publisher.create_reference_tag("r4.1", "abc123def456")

        assert result is None


class TestCleanupBranches:
    """Tests for cleanup_branches method."""

    def test_cleanup_branches_success(self, publisher, mock_github_client):
        """Both operations succeed."""
        mock_github_client.delete_branch.return_value = True
        mock_github_client.rename_branch.return_value = True

        result = publisher.cleanup_branches(
            "release-snapshot/r4.1-abc1234",
            "release-review/r4.1-abc1234"
        )

        assert result["snapshot_deleted"] == "deleted"
        assert result["review_renamed"] == "renamed"
        mock_github_client.delete_branch.assert_called_once_with("release-snapshot/r4.1-abc1234")
        mock_github_client.rename_branch.assert_called_once_with(
            "release-review/r4.1-abc1234",
            "release-review/r4.1-abc1234-published"
        )

    def test_cleanup_snapshot_already_deleted(self, publisher, mock_github_client):
        """Snapshot branch already deleted - reports not_found."""
        mock_github_client.delete_branch.return_value = False
        mock_github_client.rename_branch.return_value = True

        result = publisher.cleanup_branches(
            "release-snapshot/r4.1-abc1234",
            "release-review/r4.1-abc1234"
        )

        assert result["snapshot_deleted"] == "not_found"
        assert result["review_renamed"] == "renamed"

    def test_cleanup_review_already_renamed(self, publisher, mock_github_client):
        """Review branch already renamed - reports not_found."""
        mock_github_client.delete_branch.return_value = True
        mock_github_client.rename_branch.return_value = False

        result = publisher.cleanup_branches(
            "release-snapshot/r4.1-abc1234",
            "release-review/r4.1-abc1234"
        )

        assert result["snapshot_deleted"] == "deleted"
        assert result["review_renamed"] == "not_found"

    def test_cleanup_partial_failure(self, publisher, mock_github_client):
        """One operation fails - continues with other."""
        mock_github_client.delete_branch.side_effect = GitHubClientError("API error")
        mock_github_client.rename_branch.return_value = True

        result = publisher.cleanup_branches(
            "release-snapshot/r4.1-abc1234",
            "release-review/r4.1-abc1234"
        )

        assert result["snapshot_deleted"] == "error"
        assert result["review_renamed"] == "renamed"

    def test_cleanup_both_not_found(self, publisher, mock_github_client):
        """Both branches not found - idempotent behavior."""
        mock_github_client.delete_branch.return_value = False
        mock_github_client.rename_branch.return_value = False

        result = publisher.cleanup_branches(
            "release-snapshot/r4.1-abc1234",
            "release-review/r4.1-abc1234"
        )

        assert result["snapshot_deleted"] == "not_found"
        assert result["review_renamed"] == "not_found"
