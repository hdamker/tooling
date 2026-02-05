"""
Unit tests for the post-release sync PR creator module.

These tests verify the sync PR creation flow including CHANGELOG sync,
README update, and PR creation.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from release_automation.scripts.github_client import Branch, GitHubClientError
from release_automation.scripts.post_release_syncer import (
    SyncPRResult,
    PostReleaseSyncer,
)


@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient with default behavior."""
    client = Mock()
    client.repo = "test-org/test-repo"
    client.list_branches.return_value = [Branch(name="main", sha="main-sha-123")]
    client.get_file_content.return_value = None
    client.update_file.return_value = {"commit": {"sha": "abc123"}}
    client.find_pr_for_branch.return_value = None
    client.get_label.return_value = None
    client.create_label.return_value = {"name": "test"}
    client.add_labels.return_value = None
    # Mock _run_gh for branch creation and PR creation
    client._run_gh.return_value = "https://github.com/test-org/test-repo/pull/42"
    return client


@pytest.fixture
def syncer(mock_github_client):
    """Create a PostReleaseSyncer with mocked client."""
    return PostReleaseSyncer(mock_github_client)


class TestSyncPRResult:
    """Tests for SyncPRResult dataclass."""

    def test_success_result(self):
        """Success result has PR details."""
        result = SyncPRResult(
            success=True,
            pr_number=42,
            pr_url="https://github.com/test/pull/42"
        )
        assert result.success is True
        assert result.pr_number == 42
        assert result.pr_url == "https://github.com/test/pull/42"
        assert result.error_message is None

    def test_failure_result(self):
        """Failure result has error message."""
        result = SyncPRResult(
            success=False,
            error_message="Something went wrong"
        )
        assert result.success is False
        assert result.error_message == "Something went wrong"
        assert result.pr_number is None
        assert result.pr_url is None


class TestCreateSyncPR:
    """Tests for create_sync_pr method."""

    def test_create_sync_pr_success(self, syncer, mock_github_client):
        """Full sync PR flow succeeds."""
        # Setup: CHANGELOG/CHANGELOG-r4.md exists
        mock_github_client.get_file_content.side_effect = [
            "# CHANGELOG\n\n## r4.1",  # CHANGELOG/CHANGELOG-r4.md from snapshot
            "# README\n<!-- CAMARA:RELEASE-INFO:START -->\nold\n<!-- CAMARA:RELEASE-INFO:END -->"  # README
        ]

        release_metadata = {
            "repository": {
                "release_type": "public-release",
                "release_date": "2026-02-05"
            },
            "apis": [
                {"api_name": "quality-on-demand", "api_version": "1.0.0"}
            ]
        }

        result = syncer.create_sync_pr(
            "r4.1",
            "release-snapshot/r4.1-abc123",
            release_metadata
        )

        assert result.success is True
        assert result.pr_number == 42
        assert "pull/42" in result.pr_url

    def test_create_sync_pr_no_main_branch(self, syncer, mock_github_client):
        """No main branch - returns error."""
        mock_github_client.list_branches.return_value = []

        result = syncer.create_sync_pr(
            "r4.1",
            "release-snapshot/r4.1-abc123",
            {}
        )

        assert result.success is False
        assert "main branch SHA" in result.error_message

    def test_create_sync_pr_no_changelog(self, syncer, mock_github_client):
        """No CHANGELOG but README updates - still succeeds."""
        mock_github_client.get_file_content.side_effect = [
            None,  # No CHANGELOG
            "# README\n<!-- CAMARA:RELEASE-INFO:START -->\nold\n<!-- CAMARA:RELEASE-INFO:END -->"
        ]

        release_metadata = {
            "repository": {"release_type": "public-release"},
            "apis": [{"api_name": "test-api", "api_version": "1.0.0"}]
        }

        result = syncer.create_sync_pr(
            "r4.1",
            "release-snapshot/r4.1-abc123",
            release_metadata
        )

        assert result.success is True

    def test_create_sync_pr_no_content_changes(self, syncer, mock_github_client):
        """No CHANGELOG and no README delimiters - returns error."""
        mock_github_client.get_file_content.side_effect = [
            None,  # No CHANGELOG
            "# README without markers"  # README without delimiters
        ]

        result = syncer.create_sync_pr(
            "r4.1",
            "release-snapshot/r4.1-abc123",
            {}
        )

        assert result.success is False
        assert "No content changes" in result.error_message

    def test_create_sync_pr_api_error(self, syncer, mock_github_client):
        """GitHub API error during branch creation - returns error."""
        # List branches works but branch creation fails
        mock_github_client.get_file_content.side_effect = [
            "# CHANGELOG",  # CHANGELOG exists
            "# README\n<!-- CAMARA:RELEASE-INFO:START -->\nold\n<!-- CAMARA:RELEASE-INFO:END -->"
        ]
        mock_github_client._run_gh.side_effect = GitHubClientError("API error")

        result = syncer.create_sync_pr(
            "r4.1",
            "release-snapshot/r4.1-abc123",
            {"repository": {"release_type": "public"}, "apis": []}
        )

        assert result.success is False
        assert "GitHub API error" in result.error_message


class TestSyncChangelog:
    """Tests for _sync_changelog method."""

    def test_sync_changelog_success(self, syncer, mock_github_client):
        """Successfully syncs release-specific CHANGELOG."""
        mock_github_client.get_file_content.return_value = "# CHANGELOG content"

        result = syncer._sync_changelog(
            "release-snapshot/r4.1-abc123",
            "post-release/r4.1",
            "r4.1"
        )

        assert result is True
        mock_github_client.update_file.assert_called_once()
        call_kwargs = mock_github_client.update_file.call_args.kwargs
        assert call_kwargs["path"] == "CHANGELOG/CHANGELOG-r4.md"
        assert call_kwargs["branch"] == "post-release/r4.1"

    def test_sync_changelog_not_found(self, syncer, mock_github_client):
        """CHANGELOG not found - returns False."""
        mock_github_client.get_file_content.return_value = None

        result = syncer._sync_changelog(
            "release-snapshot/r4.1-abc123",
            "post-release/r4.1",
            "r4.1"
        )

        assert result is False
        mock_github_client.update_file.assert_not_called()

    def test_sync_changelog_update_fails(self, syncer, mock_github_client):
        """CHANGELOG update fails - returns False."""
        mock_github_client.get_file_content.return_value = "# CHANGELOG"
        mock_github_client.update_file.side_effect = GitHubClientError("Update failed")

        result = syncer._sync_changelog(
            "release-snapshot/r4.1-abc123",
            "post-release/r4.1",
            "r4.1"
        )

        assert result is False

    def test_sync_changelog_invalid_release_tag(self, syncer, mock_github_client):
        """Invalid release tag format - returns False."""
        result = syncer._sync_changelog(
            "release-snapshot/invalid-abc123",
            "post-release/invalid",
            "invalid"
        )

        assert result is False
        mock_github_client.get_file_content.assert_not_called()


class TestUpdateReadme:
    """Tests for _update_readme method."""

    def test_update_readme_success(self, syncer, mock_github_client):
        """Successfully updates README release info."""
        mock_github_client.get_file_content.return_value = """# README

<!-- CAMARA:RELEASE-INFO:START -->
old content
<!-- CAMARA:RELEASE-INFO:END -->

More content here.
"""

        release_metadata = {
            "repository": {
                "release_type": "public-release",
                "release_date": "2026-02-05"
            },
            "apis": [
                {"api_name": "quality-on-demand", "api_version": "1.0.0"}
            ]
        }

        result = syncer._update_readme(
            "post-release/r4.1",
            "r4.1",
            release_metadata
        )

        assert result is True
        mock_github_client.update_file.assert_called_once()
        call_kwargs = mock_github_client.update_file.call_args.kwargs
        assert "r4.1" in call_kwargs["content"]
        assert "public release" in call_kwargs["content"]

    def test_update_readme_no_delimiters(self, syncer, mock_github_client):
        """README without delimiters - returns False."""
        mock_github_client.get_file_content.return_value = "# README without markers"

        result = syncer._update_readme(
            "post-release/r4.1",
            "r4.1",
            {}
        )

        assert result is False
        mock_github_client.update_file.assert_not_called()

    def test_update_readme_not_found(self, syncer, mock_github_client):
        """README not found - returns False."""
        mock_github_client.get_file_content.return_value = None

        result = syncer._update_readme(
            "post-release/r4.1",
            "r4.1",
            {}
        )

        assert result is False

    def test_update_readme_prerelease(self, syncer, mock_github_client):
        """Pre-release type shows correctly."""
        mock_github_client.get_file_content.return_value = """# README
<!-- CAMARA:RELEASE-INFO:START -->
old
<!-- CAMARA:RELEASE-INFO:END -->
"""

        release_metadata = {
            "repository": {
                "release_type": "pre-release-rc"
            },
            "apis": []
        }

        result = syncer._update_readme(
            "post-release/r4.1",
            "r4.1",
            release_metadata
        )

        assert result is True
        call_kwargs = mock_github_client.update_file.call_args.kwargs
        assert "pre-release" in call_kwargs["content"]


class TestCreatePR:
    """Tests for _create_pr method."""

    def test_create_pr_success(self, syncer, mock_github_client):
        """Successfully creates PR."""
        mock_github_client._run_gh.return_value = "https://github.com/test-org/test-repo/pull/42"

        result = syncer._create_pr("r4.1", "post-release/r4.1")

        assert result is not None
        assert result["number"] == 42
        assert "pull/42" in result["url"]

    def test_create_pr_already_exists(self, syncer, mock_github_client):
        """PR already exists - returns existing PR."""
        mock_github_client._run_gh.side_effect = GitHubClientError("PR already exists")
        mock_github_client.find_pr_for_branch.return_value = 99

        result = syncer._create_pr("r4.1", "post-release/r4.1")

        assert result is not None
        assert result["number"] == 99


class TestAddLabelsToPR:
    """Tests for _add_labels_to_pr method."""

    def test_add_labels_creates_missing(self, syncer, mock_github_client):
        """Creates missing labels before adding."""
        mock_github_client.get_label.return_value = None

        syncer._add_labels_to_pr(42)

        # Should create labels
        assert mock_github_client.create_label.call_count == 2
        # Should add labels to PR
        mock_github_client.add_labels.assert_called_once_with(42, ["post-release", "automated"])

    def test_add_labels_uses_existing(self, syncer, mock_github_client):
        """Uses existing labels without creating."""
        mock_github_client.get_label.return_value = {"name": "test"}

        syncer._add_labels_to_pr(42)

        # Should not create labels
        mock_github_client.create_label.assert_not_called()
        # Should add labels to PR
        mock_github_client.add_labels.assert_called_once()

    def test_add_labels_error_non_critical(self, syncer, mock_github_client):
        """Label error is non-critical - doesn't raise."""
        mock_github_client.get_label.side_effect = GitHubClientError("Error")

        # Should not raise
        syncer._add_labels_to_pr(42)
