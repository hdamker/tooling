"""
Unit tests for git_operations module.

These tests verify the git command wrapper functionality by mocking
subprocess calls to avoid actual git operations.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import subprocess

from release_automation.scripts.git_operations import (
    GitOperations,
    PullRequestInfo,
    GitOperationsError,
    CloneError,
    BranchError,
    CommitError,
    PushError,
    PullRequestError,
)


@pytest.fixture
def git_ops():
    """Create a GitOperations instance for testing."""
    return GitOperations(
        repo="hdamker/TestRepo-QoD",
        work_dir="/tmp/test-repo",
        token="test-token"
    )


class TestGitOperationsInit:
    """Tests for GitOperations initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        ops = GitOperations(
            repo="owner/repo",
            work_dir="/path/to/dir",
            token="my-token"
        )
        assert ops.repo == "owner/repo"
        assert ops.work_dir == "/path/to/dir"
        assert ops.token == "my-token"

    def test_init_without_token(self):
        """Test initialization without token."""
        ops = GitOperations(repo="owner/repo", work_dir="/path")
        assert ops.token is None

    def test_repo_url_construction(self):
        """Test that repo URL is constructed correctly."""
        ops = GitOperations(repo="owner/repo", work_dir="/path")
        assert ops._repo_url == "https://github.com/owner/repo.git"


class TestClone:
    """Tests for clone operation."""

    @patch("subprocess.run")
    def test_clone_success(self, mock_run, git_ops):
        """Test successful clone."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.clone(branch="main")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "git" in call_args[0][0]
        assert "clone" in call_args[0][0]
        assert "--branch" in call_args[0][0]
        assert "main" in call_args[0][0]

    @patch("subprocess.run")
    def test_clone_with_token_in_url(self, mock_run, git_ops):
        """Test that token is included in clone URL."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.clone()

        call_args = mock_run.call_args[0][0]
        # Token should be in the URL
        url_part = [arg for arg in call_args if "github.com" in arg][0]
        assert "x-access-token:test-token@github.com" in url_part

    @patch("subprocess.run")
    def test_clone_failure(self, mock_run, git_ops):
        """Test clone failure raises CloneError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="Repository not found"
        )

        with pytest.raises(CloneError) as exc_info:
            git_ops.clone()

        assert "Failed to clone" in str(exc_info.value)


class TestGetCommitSha:
    """Tests for get_commit_sha operation."""

    @patch("subprocess.run")
    def test_get_commit_sha_head(self, mock_run, git_ops):
        """Test getting HEAD commit SHA."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="abc1234567890abcdef1234567890abcdef123456\n",
            stderr=""
        )

        sha = git_ops.get_commit_sha("HEAD")

        assert sha == "abc1234567890abcdef1234567890abcdef123456"
        call_args = mock_run.call_args[0][0]
        assert "rev-parse" in call_args
        assert "HEAD" in call_args

    @patch("subprocess.run")
    def test_get_commit_sha_branch(self, mock_run, git_ops):
        """Test getting commit SHA for a branch."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="def4567890abcdef1234567890abcdef12345678\n",
            stderr=""
        )

        sha = git_ops.get_commit_sha("main")

        assert sha == "def4567890abcdef1234567890abcdef12345678"


class TestCreateBranch:
    """Tests for create_branch operation."""

    @patch("subprocess.run")
    def test_create_branch_from_head(self, mock_run, git_ops):
        """Test creating branch from HEAD."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.create_branch("feature/new-branch")

        call_args = mock_run.call_args[0][0]
        assert "checkout" in call_args
        assert "-b" in call_args
        assert "feature/new-branch" in call_args

    @patch("subprocess.run")
    def test_create_branch_from_ref(self, mock_run, git_ops):
        """Test creating branch from specific ref."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.create_branch("release-snapshot/r4.1-abc1234", from_ref="abc1234")

        call_args = mock_run.call_args[0][0]
        assert "release-snapshot/r4.1-abc1234" in call_args
        assert "abc1234" in call_args

    @patch("subprocess.run")
    def test_create_branch_failure(self, mock_run, git_ops):
        """Test branch creation failure raises BranchError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="branch already exists"
        )

        with pytest.raises(BranchError):
            git_ops.create_branch("existing-branch")


class TestCommitAll:
    """Tests for commit_all operation."""

    @patch("subprocess.run")
    def test_commit_all_success(self, mock_run, git_ops):
        """Test successful commit."""
        # Mock status check returning changes
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # git add
            Mock(returncode=0, stdout="M file.txt\n", stderr=""),  # git status
            Mock(returncode=0, stdout="", stderr=""),  # git commit
            Mock(returncode=0, stdout="abc1234\n", stderr=""),  # git rev-parse
        ]

        sha = git_ops.commit_all("Test commit message")

        assert sha == "abc1234"

    @patch("subprocess.run")
    def test_commit_all_no_changes(self, mock_run, git_ops):
        """Test commit with no changes raises CommitError."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # git add
            Mock(returncode=0, stdout="", stderr=""),  # git status (empty)
        ]

        with pytest.raises(CommitError) as exc_info:
            git_ops.commit_all("Empty commit")

        assert "No changes to commit" in str(exc_info.value)

    @patch("subprocess.run")
    def test_commit_all_with_author(self, mock_run, git_ops):
        """Test commit with custom author."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # git add
            Mock(returncode=0, stdout="M file.txt\n", stderr=""),  # git status
            Mock(returncode=0, stdout="", stderr=""),  # git commit
            Mock(returncode=0, stdout="abc1234\n", stderr=""),  # git rev-parse
        ]

        git_ops.commit_all("Message", author="Bot <bot@example.com>")

        # Check that commit was called with --author
        commit_call = mock_run.call_args_list[2]
        call_args = commit_call[0][0]
        assert "--author" in call_args
        assert "Bot <bot@example.com>" in call_args


class TestPush:
    """Tests for push operation."""

    @patch("subprocess.run")
    def test_push_with_upstream(self, mock_run, git_ops):
        """Test push with upstream tracking."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.push("feature-branch", set_upstream=True)

        call_args = mock_run.call_args[0][0]
        assert "push" in call_args
        assert "-u" in call_args
        assert "origin" in call_args
        assert "feature-branch" in call_args

    @patch("subprocess.run")
    def test_push_without_upstream(self, mock_run, git_ops):
        """Test push without upstream tracking."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.push("feature-branch", set_upstream=False)

        call_args = mock_run.call_args[0][0]
        assert "-u" not in call_args

    @patch("subprocess.run")
    def test_push_failure(self, mock_run, git_ops):
        """Test push failure raises PushError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="Permission denied"
        )

        with pytest.raises(PushError):
            git_ops.push("branch")


class TestDeleteRemoteBranch:
    """Tests for delete_remote_branch operation."""

    @patch("subprocess.run")
    def test_delete_remote_branch_success(self, mock_run, git_ops):
        """Test successful remote branch deletion."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        result = git_ops.delete_remote_branch("old-branch")

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "push" in call_args
        assert "--delete" in call_args

    @patch("subprocess.run")
    def test_delete_nonexistent_branch(self, mock_run, git_ops):
        """Test deleting non-existent branch returns False."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="error: remote ref does not exist"
        )

        result = git_ops.delete_remote_branch("nonexistent")

        assert result is False


class TestCreatePR:
    """Tests for create_pr operation."""

    @patch("subprocess.run")
    def test_create_pr_success(self, mock_run, git_ops):
        """Test successful PR creation."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/hdamker/TestRepo-QoD/pull/42\n",
            stderr=""
        )

        result = git_ops.create_pr(
            title="Release r4.1",
            body="Release description",
            head="release-review/r4.1-abc1234",
            base="release-snapshot/r4.1-abc1234"
        )

        assert isinstance(result, PullRequestInfo)
        assert result.number == 42
        assert "pull/42" in result.url

    @patch("subprocess.run")
    def test_create_pr_draft(self, mock_run, git_ops):
        """Test creating draft PR."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/owner/repo/pull/1\n",
            stderr=""
        )

        git_ops.create_pr(
            title="Draft PR",
            body="WIP",
            head="feature",
            base="main",
            draft=True
        )

        call_args = mock_run.call_args[0][0]
        assert "--draft" in call_args

    @patch("subprocess.run")
    def test_create_pr_failure(self, mock_run, git_ops):
        """Test PR creation failure raises PullRequestError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "gh", stderr="Validation failed"
        )

        with pytest.raises(PullRequestError):
            git_ops.create_pr("Title", "Body", "head", "base")


class TestBranchExists:
    """Tests for branch_exists operation."""

    @patch("subprocess.run")
    def test_branch_exists_local(self, mock_run, git_ops):
        """Test checking local branch existence."""
        mock_run.return_value = Mock(returncode=0, stdout="abc1234\n", stderr="")

        result = git_ops.branch_exists("main", remote=False)

        assert result is True

    @patch("subprocess.run")
    def test_branch_exists_remote(self, mock_run, git_ops):
        """Test checking remote branch existence."""
        mock_run.return_value = Mock(returncode=0, stdout="abc1234\n", stderr="")

        result = git_ops.branch_exists("main", remote=True)

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "origin/main" in call_args

    @patch("subprocess.run")
    def test_branch_not_exists(self, mock_run, git_ops):
        """Test branch that doesn't exist."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="fatal: not a valid object name"
        )

        result = git_ops.branch_exists("nonexistent")

        assert result is False


class TestConfigureUser:
    """Tests for configure_user operation."""

    @patch("subprocess.run")
    def test_configure_user(self, mock_run, git_ops):
        """Test configuring git user."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        git_ops.configure_user("Bot", "bot@example.com")

        # Should have two calls: one for name, one for email
        assert mock_run.call_count == 2
        calls = mock_run.call_args_list

        name_call = calls[0][0][0]
        assert "user.name" in name_call
        assert "Bot" in name_call

        email_call = calls[1][0][0]
        assert "user.email" in email_call
        assert "bot@example.com" in email_call
