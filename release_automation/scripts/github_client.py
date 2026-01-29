"""
GitHub API client wrapper for release automation.

This module provides a thin wrapper around GitHub API operations
needed by the release automation workflow. It uses the `gh` CLI
for authentication and API access.
"""

import json
import subprocess
from dataclasses import dataclass
from typing import List, Optional
from fnmatch import fnmatch


@dataclass
class Branch:
    """Represents a GitHub branch."""
    name: str
    sha: str


@dataclass
class Release:
    """Represents a GitHub release."""
    tag_name: str
    name: str
    draft: bool
    prerelease: bool
    html_url: str


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""
    pass


class GitHubClient:
    """
    GitHub API client for release automation operations.

    Uses the `gh` CLI for authentication and API access.
    All methods are repository-scoped.
    """

    def __init__(self, repo: str, token: Optional[str] = None):
        """
        Initialize the GitHub client.

        Args:
            repo: Repository in format "owner/name"
            token: Optional GitHub token (uses gh CLI auth if not provided)
        """
        self.repo = repo
        self.token = token

    def _run_gh(self, args: List[str], check: bool = True) -> str:
        """
        Run a gh CLI command and return output.

        Args:
            args: Command arguments (without 'gh')
            check: Whether to raise on non-zero exit code

        Returns:
            Command output as string

        Raises:
            GitHubClientError: If command fails and check=True
        """
        cmd = ["gh"] + args
        if self.token:
            env = {"GH_TOKEN": self.token}
        else:
            env = None

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
                env=env
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise GitHubClientError(f"gh command failed: {e.stderr}")

    def tag_exists(self, tag: str) -> bool:
        """
        Check if a tag exists in the repository.

        Args:
            tag: Tag name to check (e.g., "r4.1")

        Returns:
            True if tag exists, False otherwise
        """
        try:
            output = self._run_gh([
                "api",
                f"repos/{self.repo}/git/refs/tags/{tag}",
                "--jq", ".ref"
            ])
            return bool(output.strip())
        except GitHubClientError:
            return False

    def list_branches(self, pattern: Optional[str] = None) -> List[Branch]:
        """
        List branches in the repository, optionally filtered by pattern.

        Args:
            pattern: Optional glob pattern to filter branches (e.g., "release-snapshot/r4.1-*")

        Returns:
            List of Branch objects matching the pattern
        """
        output = self._run_gh([
            "api",
            f"repos/{self.repo}/branches",
            "--paginate",
            "--jq", ".[].name"
        ])

        branch_names = [name.strip() for name in output.strip().split('\n') if name.strip()]

        if pattern:
            branch_names = [name for name in branch_names if fnmatch(name, pattern)]

        # Get SHA for each branch
        branches = []
        for name in branch_names:
            try:
                sha_output = self._run_gh([
                    "api",
                    f"repos/{self.repo}/branches/{name}",
                    "--jq", ".commit.sha"
                ])
                branches.append(Branch(name=name, sha=sha_output.strip()))
            except GitHubClientError:
                # Branch may have been deleted between listing and fetching
                continue

        return branches

    def draft_release_exists(self, tag: str) -> bool:
        """
        Check if a draft release exists for the given tag.

        Args:
            tag: Tag name to check (e.g., "r4.1")

        Returns:
            True if a draft release exists with this tag, False otherwise
        """
        try:
            output = self._run_gh([
                "api",
                f"repos/{self.repo}/releases",
                "--jq", f'[.[] | select(.tag_name == "{tag}" and .draft == true)] | length'
            ])
            return int(output.strip()) > 0
        except (GitHubClientError, ValueError):
            return False

    def get_file_content(self, path: str, ref: str = "main") -> Optional[str]:
        """
        Get the content of a file from the repository.

        Args:
            path: File path relative to repository root
            ref: Branch, tag, or commit SHA to read from

        Returns:
            File content as string, or None if file doesn't exist
        """
        try:
            # Use gh api to get file content (base64 encoded)
            output = self._run_gh([
                "api",
                f"repos/{self.repo}/contents/{path}",
                "-H", f"Accept: application/vnd.github.raw",
                "-f", f"ref={ref}"
            ])
            return output
        except GitHubClientError:
            return None

    def get_releases(self, include_drafts: bool = False) -> List[Release]:
        """
        Get all releases from the repository.

        Args:
            include_drafts: Whether to include draft releases

        Returns:
            List of Release objects
        """
        output = self._run_gh([
            "api",
            f"repos/{self.repo}/releases",
            "--paginate",
            "--jq", "."
        ])

        try:
            releases_data = json.loads(output)
        except json.JSONDecodeError:
            return []

        releases = []
        for r in releases_data:
            if not include_drafts and r.get("draft", False):
                continue
            releases.append(Release(
                tag_name=r["tag_name"],
                name=r.get("name", ""),
                draft=r.get("draft", False),
                prerelease=r.get("prerelease", False),
                html_url=r.get("html_url", "")
            ))

        return releases

    def get_branch_creation_time(self, branch: str) -> Optional[str]:
        """
        Get the creation time of a branch (approximated by first commit time).

        Note: GitHub doesn't track branch creation time directly.
        This returns the committer date of the branch's current HEAD.

        Args:
            branch: Branch name

        Returns:
            ISO 8601 timestamp or None if branch doesn't exist
        """
        try:
            output = self._run_gh([
                "api",
                f"repos/{self.repo}/branches/{branch}",
                "--jq", ".commit.commit.committer.date"
            ])
            return output.strip() if output.strip() else None
        except GitHubClientError:
            return None

    def find_pr_for_branch(self, head_branch: str) -> Optional[int]:
        """
        Find an open PR with the given head branch.

        Args:
            head_branch: The source branch of the PR

        Returns:
            PR number or None if no matching PR found
        """
        try:
            output = self._run_gh([
                "pr", "list",
                "--repo", self.repo,
                "--head", head_branch,
                "--state", "open",
                "--json", "number",
                "--jq", ".[0].number"
            ])
            return int(output.strip()) if output.strip() else None
        except (GitHubClientError, ValueError):
            return None
