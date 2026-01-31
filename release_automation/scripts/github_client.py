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
        import os as _os

        cmd = ["gh"] + args
        if self.token:
            # Extend environment with GH_TOKEN, don't replace it
            env = {**_os.environ, "GH_TOKEN": self.token}
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

    # -------------------------------------------------------------------------
    # Issue Operations (added for issue_sync.py)
    # -------------------------------------------------------------------------

    def get_issue(self, issue_number: int) -> dict:
        """
        Get issue details including body and labels.

        Args:
            issue_number: The issue number

        Returns:
            Dict with issue details (number, title, body, labels, html_url, state)

        Raises:
            GitHubClientError: If issue doesn't exist or API fails
        """
        output = self._run_gh([
            "api",
            f"repos/{self.repo}/issues/{issue_number}",
            "--jq", "."
        ])

        try:
            issue = json.loads(output)
            return {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body", ""),
                "labels": issue.get("labels", []),
                "html_url": issue["html_url"],
                "state": issue["state"]
            }
        except json.JSONDecodeError as e:
            raise GitHubClientError(f"Failed to parse issue response: {e}")

    def search_issues(
        self,
        labels: Optional[List[str]] = None,
        state: str = "open"
    ) -> List[dict]:
        """
        Search issues by labels and state.

        Args:
            labels: List of label names to filter by
            state: Issue state ('open', 'closed', 'all')

        Returns:
            List of issue dicts with number, title, body, labels, html_url
        """
        # Build gh issue list command
        args = [
            "issue", "list",
            "--repo", self.repo,
            "--state", state,
            "--json", "number,title,body,labels,url"
        ]

        if labels:
            for label in labels:
                args.extend(["--label", label])

        try:
            output = self._run_gh(args)
        except GitHubClientError:
            return []

        try:
            issues_data = json.loads(output) if output.strip() else []
        except json.JSONDecodeError:
            return []

        return [
            {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body", ""),
                "labels": issue.get("labels", []),
                "html_url": issue.get("url", "")
            }
            for issue in issues_data
        ]

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None
    ) -> dict:
        """
        Create a new issue.

        Args:
            title: Issue title
            body: Issue body (markdown)
            labels: List of label names to add

        Returns:
            Dict with created issue details

        Raises:
            GitHubClientError: If creation fails
        """
        args = [
            "issue", "create",
            "--repo", self.repo,
            "--title", title,
            "--body", body
        ]

        if labels:
            for label in labels:
                args.extend(["--label", label])

        output = self._run_gh(args)

        # gh issue create outputs the URL of the created issue
        issue_url = output.strip()

        # Extract issue number from URL
        # URL format: https://github.com/owner/repo/issues/123
        try:
            issue_number = int(issue_url.rstrip('/').split('/')[-1])
        except (ValueError, IndexError):
            raise GitHubClientError(f"Failed to parse issue number from: {issue_url}")

        # Fetch full issue details
        return self.get_issue(issue_number)

    def update_issue(
        self,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None
    ) -> dict:
        """
        Update an existing issue's title and/or body.

        Args:
            issue_number: The issue number to update
            title: New title (optional)
            body: New body (optional)

        Returns:
            Dict with updated issue details

        Raises:
            GitHubClientError: If update fails
        """
        # Use PATCH on the issues API
        args = [
            "api",
            f"repos/{self.repo}/issues/{issue_number}",
            "-X", "PATCH"
        ]

        if title is not None:
            args.extend(["-f", f"title={title}"])
        if body is not None:
            args.extend(["-f", f"body={body}"])

        output = self._run_gh(args)

        try:
            issue = json.loads(output)
            return {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body", ""),
                "labels": issue.get("labels", []),
                "html_url": issue["html_url"],
                "state": issue["state"]
            }
        except json.JSONDecodeError as e:
            raise GitHubClientError(f"Failed to parse update response: {e}")

    def add_labels(self, issue_number: int, labels: List[str]) -> None:
        """
        Add labels to an issue.

        Args:
            issue_number: The issue number
            labels: List of label names to add

        Raises:
            GitHubClientError: If operation fails
        """
        if not labels:
            return

        # POST to labels endpoint
        labels_json = json.dumps(labels)
        self._run_gh([
            "api",
            f"repos/{self.repo}/issues/{issue_number}/labels",
            "-X", "POST",
            "-f", f"labels={labels_json}"
        ])

    def remove_labels(self, issue_number: int, labels: List[str]) -> None:
        """
        Remove labels from an issue.

        Args:
            issue_number: The issue number
            labels: List of label names to remove

        Raises:
            GitHubClientError: If operation fails
        """
        for label in labels:
            try:
                self._run_gh([
                    "api",
                    f"repos/{self.repo}/issues/{issue_number}/labels/{label}",
                    "-X", "DELETE"
                ])
            except GitHubClientError:
                # Label might not exist, continue
                pass

    def set_labels(self, issue_number: int, labels: List[str]) -> None:
        """
        Replace all labels on an issue with the specified labels.

        Args:
            issue_number: The issue number
            labels: List of label names to set

        Raises:
            GitHubClientError: If operation fails
        """
        labels_json = json.dumps(labels)
        self._run_gh([
            "api",
            f"repos/{self.repo}/issues/{issue_number}/labels",
            "-X", "PUT",
            "-f", f"labels={labels_json}"
        ])
