"""
Git operations helper for CAMARA release automation.

This module provides local git operations for snapshot creation,
using subprocess calls to git and gh CLI commands.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class PullRequestInfo:
    """Information about a created pull request."""
    number: int
    url: str


class GitOperationsError(Exception):
    """Base exception for git operations errors."""
    pass


class CloneError(GitOperationsError):
    """Raised when repository cloning fails."""
    pass


class BranchError(GitOperationsError):
    """Raised when branch operations fail."""
    pass


class CommitError(GitOperationsError):
    """Raised when commit operations fail."""
    pass


class PushError(GitOperationsError):
    """Raised when push operations fail."""
    pass


class PullRequestError(GitOperationsError):
    """Raised when PR creation fails."""
    pass


class GitOperations:
    """
    Local git operations for snapshot creation.

    Provides methods for cloning, branching, committing, and pushing
    changes using local git commands and gh CLI for PR creation.
    """

    def __init__(self, repo: str, work_dir: str, token: Optional[str] = None):
        """
        Initialize git operations.

        Args:
            repo: Repository in format "owner/name" (e.g., "camaraproject/QualityOnDemand")
            work_dir: Local directory path for git operations
            token: Optional GitHub token for authentication
        """
        self.repo = repo
        self.work_dir = work_dir
        self.token = token
        self._repo_url = f"https://github.com/{repo}.git"

    def _run_git(
        self,
        args: list,
        check: bool = True,
        cwd: Optional[str] = None
    ) -> str:
        """
        Run a git command and return output.

        Args:
            args: Command arguments (without 'git')
            check: Whether to raise on non-zero exit code
            cwd: Working directory (defaults to self.work_dir)

        Returns:
            Command output as string

        Raises:
            GitOperationsError: If command fails and check=True
        """
        cmd = ["git"] + args
        env = os.environ.copy()

        # Set GH_TOKEN if provided
        if self.token:
            env["GH_TOKEN"] = self.token

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
                cwd=cwd or self.work_dir,
                env=env,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise GitOperationsError(f"git {' '.join(args)} failed: {e.stderr}")

    def _run_gh(self, args: list, check: bool = True) -> str:
        """
        Run a gh CLI command and return output.

        Args:
            args: Command arguments (without 'gh')
            check: Whether to raise on non-zero exit code

        Returns:
            Command output as string

        Raises:
            GitOperationsError: If command fails and check=True
        """
        cmd = ["gh"] + args
        env = os.environ.copy()

        # Set GH_TOKEN if provided
        if self.token:
            env["GH_TOKEN"] = self.token

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
                cwd=self.work_dir,
                env=env,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise GitOperationsError(f"gh {' '.join(args)} failed: {e.stderr}")

    def clone(self, branch: str = "main") -> None:
        """
        Clone repository to work_dir.

        Args:
            branch: Branch to checkout after cloning

        Raises:
            CloneError: If cloning fails
        """
        try:
            # Clone to parent directory first, then check the result is in work_dir
            parent_dir = os.path.dirname(self.work_dir)
            repo_name = os.path.basename(self.work_dir)

            # Build clone URL with token if available
            if self.token:
                clone_url = f"https://x-access-token:{self.token}@github.com/{self.repo}.git"
            else:
                clone_url = self._repo_url

            subprocess.run(
                ["git", "clone", "--branch", branch, clone_url, repo_name],
                capture_output=True,
                text=True,
                check=True,
                cwd=parent_dir,
            )
        except subprocess.CalledProcessError as e:
            raise CloneError(f"Failed to clone {self.repo}: {e.stderr}")

    def get_commit_sha(self, ref: str = "HEAD") -> str:
        """
        Get commit SHA for a reference.

        Args:
            ref: Git reference (branch, tag, or "HEAD")

        Returns:
            Full commit SHA string

        Raises:
            GitOperationsError: If reference doesn't exist
        """
        return self._run_git(["rev-parse", ref])

    def create_branch(self, name: str, from_ref: str = "HEAD") -> None:
        """
        Create and checkout a new branch.

        Args:
            name: Name of the new branch
            from_ref: Reference to branch from

        Raises:
            BranchError: If branch creation fails
        """
        try:
            self._run_git(["checkout", "-b", name, from_ref])
        except GitOperationsError as e:
            raise BranchError(str(e))

    def checkout(self, ref: str) -> None:
        """
        Checkout a branch or reference.

        Args:
            ref: Branch name, tag, or commit SHA

        Raises:
            BranchError: If checkout fails
        """
        try:
            self._run_git(["checkout", ref])
        except GitOperationsError as e:
            raise BranchError(str(e))

    def commit_all(self, message: str, author: Optional[str] = None) -> str:
        """
        Stage all changes and create a commit.

        Args:
            message: Commit message
            author: Optional author string ("Name <email>")

        Returns:
            Commit SHA of the new commit

        Raises:
            CommitError: If staging or commit fails
        """
        try:
            # Stage all changes
            self._run_git(["add", "-A"])

            # Check if there are changes to commit
            status = self._run_git(["status", "--porcelain"])
            if not status:
                raise CommitError("No changes to commit")

            # Build commit command
            commit_args = ["commit", "-m", message]
            if author:
                commit_args.extend(["--author", author])

            self._run_git(commit_args)

            # Return the new commit SHA
            return self.get_commit_sha("HEAD")
        except GitOperationsError as e:
            raise CommitError(str(e))

    def push(self, branch: str, set_upstream: bool = True) -> None:
        """
        Push branch to remote origin.

        Args:
            branch: Branch name to push
            set_upstream: Whether to set upstream tracking

        Raises:
            PushError: If push fails
        """
        try:
            args = ["push"]
            if set_upstream:
                args.extend(["-u", "origin", branch])
            else:
                args.extend(["origin", branch])

            self._run_git(args)
        except GitOperationsError as e:
            raise PushError(str(e))

    def delete_remote_branch(self, branch: str) -> bool:
        """
        Delete a remote branch.

        Args:
            branch: Branch name to delete

        Returns:
            True if deleted successfully, False if branch didn't exist

        Raises:
            BranchError: If deletion fails for other reasons
        """
        try:
            self._run_git(["push", "origin", "--delete", branch])
            return True
        except GitOperationsError as e:
            # Check if error is because branch doesn't exist
            error_str = str(e).lower()
            if "remote ref does not exist" in error_str or "not found" in error_str:
                return False
            raise BranchError(str(e))

    def fetch(self, remote: str = "origin", ref: Optional[str] = None) -> None:
        """
        Fetch from remote.

        Args:
            remote: Remote name (default: origin)
            ref: Optional specific ref to fetch

        Raises:
            GitOperationsError: If fetch fails
        """
        args = ["fetch", remote]
        if ref:
            args.append(ref)
        self._run_git(args)

    def branch_exists(self, branch: str, remote: bool = False) -> bool:
        """
        Check if a branch exists.

        Args:
            branch: Branch name to check
            remote: If True, check remote branch (origin/{branch})

        Returns:
            True if branch exists
        """
        try:
            ref = f"origin/{branch}" if remote else branch
            self._run_git(["rev-parse", "--verify", ref])
            return True
        except GitOperationsError:
            return False

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
    ) -> PullRequestInfo:
        """
        Create a pull request using gh CLI.

        Args:
            title: PR title
            body: PR body/description
            head: Source branch
            base: Target branch
            draft: Whether to create as draft PR

        Returns:
            PullRequestInfo with number and URL

        Raises:
            PullRequestError: If PR creation fails
        """
        try:
            args = [
                "pr", "create",
                "--repo", self.repo,
                "--title", title,
                "--body", body,
                "--head", head,
                "--base", base,
            ]

            if draft:
                args.append("--draft")

            output = self._run_gh(args)

            # gh pr create outputs the PR URL
            pr_url = output.strip()

            # Extract PR number from URL
            # Format: https://github.com/owner/repo/pull/123
            try:
                pr_number = int(pr_url.rstrip("/").split("/")[-1])
            except (ValueError, IndexError):
                raise PullRequestError(f"Failed to parse PR number from: {pr_url}")

            return PullRequestInfo(number=pr_number, url=pr_url)
        except GitOperationsError as e:
            raise PullRequestError(str(e))

    def get_remote_url(self) -> str:
        """
        Get the remote URL for origin.

        Returns:
            Remote URL string
        """
        return self._run_git(["remote", "get-url", "origin"])

    def configure_user(self, name: str, email: str) -> None:
        """
        Configure git user name and email for commits.

        Args:
            name: User name
            email: User email
        """
        self._run_git(["config", "user.name", name])
        self._run_git(["config", "user.email", email])
