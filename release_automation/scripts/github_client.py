"""
GitHub API client wrapper for release automation.

This module provides a thin wrapper around GitHub API operations
needed by the release automation workflow. It uses the `gh` CLI
for authentication and API access.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
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

        Note:
            Returns None only for 404 (file not found).
            Logs warnings for other errors (auth, server, etc.) but still returns None
            to maintain backward compatibility.
        """
        api_path = f"repos/{self.repo}/contents/{path}?ref={ref}"
        try:
            # Use gh api to get file content
            # Note: ref must be a query parameter, not a form field (-f)
            output = self._run_gh([
                "api",
                api_path,
                "-H", "Accept: application/vnd.github.raw"
            ])
            return output
        except GitHubClientError as e:
            error_msg = str(e).lower()
            # 404 is expected when file doesn't exist - return None silently
            if "404" in error_msg or "not found" in error_msg:
                return None
            # Other errors (auth, server, rate limit) should be surfaced
            print(f"Warning: Failed to read {path} from {ref}: {e}")
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

    def get_draft_release(self, tag: str) -> Optional[Release]:
        """Get draft release by tag name.

        Args:
            tag: Release tag to search for

        Returns:
            Release object if found, None otherwise
        """
        try:
            releases = self.get_releases(include_drafts=True)
            for release in releases:
                if release.draft and release.tag_name == tag:
                    return release
            return None
        except GitHubClientError:
            return None

    def get_release_id(self, tag: str, draft_only: bool = False) -> Optional[int]:
        """Get release ID by tag name.

        Args:
            tag: Release tag to search for
            draft_only: If True, only return ID for draft releases

        Returns:
            Release ID if found, None otherwise
        """
        try:
            jq_filter = f'.[] | select(.tag_name == "{tag}"'
            if draft_only:
                jq_filter += ' and .draft == true'
            jq_filter += ') | .id'

            output = self._run_gh([
                "api",
                f"repos/{self.repo}/releases",
                "--jq", jq_filter
            ])
            if output.strip():
                return int(output.strip())
        except (GitHubClientError, ValueError):
            pass
        return None

    def update_release(
        self,
        release_id: int,
        draft: Optional[bool] = None,
        prerelease: Optional[bool] = None,
        name: Optional[str] = None,
        body: Optional[str] = None,
        make_latest: Optional[str] = None
    ) -> dict:
        """Update a release.

        Args:
            release_id: Release ID to update
            draft: Set draft status (False to publish)
            prerelease: Set prerelease status (re-enforce on publish)
            name: New release name
            body: New release body
            make_latest: "true", "false", or "legacy" to control latest status

        Returns:
            Updated release data

        Raises:
            GitHubClientError: If update fails
        """
        args = ["api", "-X", "PATCH", f"repos/{self.repo}/releases/{release_id}"]

        if draft is not None:
            args.extend(["-F", f"draft={str(draft).lower()}"])
        if prerelease is not None:
            args.extend(["-F", f"prerelease={str(prerelease).lower()}"])
        if name is not None:
            args.extend(["-f", f"name={name}"])
        if body is not None:
            args.extend(["-f", f"body={body}"])
        if make_latest is not None:
            args.extend(["-f", f"make_latest={make_latest}"])

        output = self._run_gh(args)
        return json.loads(output)

    def get_release_by_id(self, release_id: int) -> dict:
        """Get release by ID.

        Args:
            release_id: Release ID

        Returns:
            Release data dict

        Raises:
            GitHubClientError: If not found
        """
        output = self._run_gh(["api", f"repos/{self.repo}/releases/{release_id}"])
        return json.loads(output)

    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str
    ) -> dict:
        """Update a file on a branch via GitHub Contents API.

        Args:
            path: File path in repository
            content: New file content
            message: Commit message
            branch: Target branch

        Returns:
            API response with commit info

        Raises:
            GitHubClientError: If update fails
        """
        import base64

        # Get current file SHA (required for update)
        try:
            file_info = self._run_gh([
                "api",
                f"repos/{self.repo}/contents/{path}?ref={branch}"
            ])
            file_data = json.loads(file_info)
            sha = file_data.get("sha")
        except GitHubClientError:
            sha = None  # File doesn't exist, will create

        # Encode content as base64
        encoded_content = base64.b64encode(content.encode()).decode()

        # Build API call
        args = [
            "api", "-X", "PUT",
            f"repos/{self.repo}/contents/{path}",
            "-f", f"message={message}",
            "-f", f"content={encoded_content}",
            "-f", f"branch={branch}"
        ]
        if sha:
            args.extend(["-f", f"sha={sha}"])

        output = self._run_gh(args)
        return json.loads(output)

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
    # Retry helper for eventual consistency
    # -------------------------------------------------------------------------

    def retry_on_not_found(self, fn, max_retries: int = 3, delay: float = 1.0):
        """
        Retry a callable that may fail with HTTP 404 due to GitHub API
        eventual consistency (e.g., operations on a freshly created issue).

        Args:
            fn: Zero-argument callable to execute
            max_retries: Maximum number of attempts (default 3)
            delay: Base delay in seconds between retries (multiplied by attempt number)

        Returns:
            The return value of fn()

        Raises:
            GitHubClientError: If all retries fail or error is not a 404
        """
        for attempt in range(max_retries):
            try:
                return fn()
            except GitHubClientError as e:
                error_msg = str(e).lower()
                is_not_found = "404" in error_msg or "not found" in error_msg
                if is_not_found and attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                raise

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

        # Return minimal issue details from the create response
        # Note: We avoid fetching via get_issue() immediately after creation
        # because GitHub API may return 404 due to eventual consistency.
        return {
            "number": issue_number,
            "title": title,
            "body": body,
            "labels": [{"name": l} for l in (labels or [])],
            "html_url": issue_url
        }

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

        # POST to labels endpoint using array syntax for gh api
        args = [
            "api",
            f"repos/{self.repo}/issues/{issue_number}/labels",
            "-X", "POST"
        ]
        for label in labels:
            args.extend(["-f", f"labels[]={label}"])
        self._run_gh(args)

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
        # PUT to labels endpoint using array syntax for gh api
        args = [
            "api",
            f"repos/{self.repo}/issues/{issue_number}/labels",
            "-X", "PUT"
        ]
        for label in labels:
            args.extend(["-f", f"labels[]={label}"])
        self._run_gh(args)

    def get_label(self, label_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a repository label by name.

        Args:
            label_name: The label name to look up

        Returns:
            Label dict with 'name', 'color', 'description' if found, None otherwise
        """
        import urllib.parse
        encoded_name = urllib.parse.quote(label_name, safe='')

        try:
            result = self._run_gh([
                "api",
                f"repos/{self.repo}/labels/{encoded_name}"
            ])
            label = json.loads(result)
            return {
                "name": label["name"],
                "color": label.get("color", ""),
                "description": label.get("description", "")
            }
        except GitHubClientError:
            # Label doesn't exist
            return None
        except json.JSONDecodeError:
            return None

    def create_label(
        self,
        name: str,
        color: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Create a repository label.

        Args:
            name: Label name
            color: Hex color without # (e.g., "0E8A16")
            description: Optional description

        Returns:
            Created label dict

        Raises:
            GitHubClientError: If creation fails
        """
        args = [
            "api",
            f"repos/{self.repo}/labels",
            "-X", "POST",
            "-f", f"name={name}",
            "-f", f"color={color}"
        ]
        if description:
            args.extend(["-f", f"description={description}"])

        result = self._run_gh(args)
        try:
            label = json.loads(result)
            return {
                "name": label["name"],
                "color": label.get("color", ""),
                "description": label.get("description", "")
            }
        except json.JSONDecodeError as e:
            raise GitHubClientError(f"Failed to parse label creation response: {e}")

    def compare_commits(self, base: str, head: str) -> dict:
        """
        Compare two commits/tags/branches using the GitHub compare API.

        Args:
            base: Base reference (tag, branch, or SHA)
            head: Head reference (tag, branch, or SHA)

        Returns:
            Parsed JSON response from the compare API, or empty dict on error.
        """
        try:
            output = self._run_gh([
                "api",
                f"repos/{self.repo}/compare/{base}...{head}",
                "--jq", "."
            ])
            return json.loads(output)
        except (GitHubClientError, json.JSONDecodeError):
            return {}

    def download_release_asset(self, tag: str, filename: str) -> Optional[str]:
        """Download a release asset by filename pattern.

        Uses `gh release download` to fetch asset content to stdout.
        This is the fallback for legacy releases where release-metadata.yaml
        is a release asset rather than a committed file.

        Args:
            tag: Release tag (e.g., "r3.2")
            filename: Asset filename pattern (e.g., "release-metadata.yaml")

        Returns:
            Asset content as string, or None if not found/error.
        """
        try:
            output = self._run_gh([
                "release", "download", tag,
                "--repo", self.repo,
                "-p", filename,
                "-O", "-"
            ])
            return output if output.strip() else None
        except GitHubClientError:
            return None

    def generate_release_notes(
        self, tag_name: str, previous_tag_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate release notes using GitHub's auto-generated release notes API.

        Uses POST /repos/{owner}/{repo}/releases/generate-notes to produce
        PR-level change descriptions matching GitHub's draft release format.

        Args:
            tag_name: Target tag for the release notes
            previous_tag_name: Previous tag for comparison (optional)

        Returns:
            Markdown body with PR-level changes, or None on error.
        """
        args = [
            "api", f"repos/{self.repo}/releases/generate-notes",
            "-f", f"tag_name={tag_name}",
            "--jq", ".body",
        ]
        if previous_tag_name:
            args.extend(["-f", f"previous_tag_name={previous_tag_name}"])
        try:
            output = self._run_gh(args)
            return output.strip() if output.strip() else None
        except GitHubClientError:
            return None

    def create_tag(self, tag_name: str, sha: str) -> dict:
        """Create a lightweight tag at a specific commit.

        Args:
            tag_name: Name of the tag to create (e.g., "src/r4.1")
            sha: Full commit SHA to tag

        Returns:
            API response dict with ref info

        Raises:
            GitHubClientError: If creation fails (except for already exists)
        """
        args = [
            "api",
            f"repos/{self.repo}/git/refs",
            "-X", "POST",
            "-f", f"ref=refs/tags/{tag_name}",
            "-f", f"sha={sha}"
        ]
        output = self._run_gh(args)
        return json.loads(output)

    def delete_branch(self, branch_name: str) -> bool:
        """Delete a branch from the repository.

        Args:
            branch_name: Branch name to delete (without refs/heads/)

        Returns:
            True if deleted, False if branch didn't exist

        Raises:
            GitHubClientError: If deletion fails for other reasons
        """
        try:
            self._run_gh([
                "api",
                f"repos/{self.repo}/git/refs/heads/{branch_name}",
                "-X", "DELETE"
            ])
            return True
        except GitHubClientError as e:
            error_msg = str(e).lower()
            if "404" in error_msg or "not found" in error_msg:
                return False
            raise

    def rename_branch(self, old_name: str, new_name: str) -> bool:
        """Rename a branch by creating new at same SHA and deleting old.

        Args:
            old_name: Current branch name
            new_name: New branch name

        Returns:
            True if renamed, False if old branch didn't exist

        Raises:
            GitHubClientError: If operation fails
        """
        # Get SHA of old branch
        try:
            sha_output = self._run_gh([
                "api",
                f"repos/{self.repo}/branches/{old_name}",
                "--jq", ".commit.sha"
            ])
            sha = sha_output.strip()
        except GitHubClientError as e:
            error_msg = str(e).lower()
            if "404" in error_msg or "not found" in error_msg:
                return False
            raise

        # Create new branch at same SHA
        self._run_gh([
            "api",
            f"repos/{self.repo}/git/refs",
            "-X", "POST",
            "-f", f"ref=refs/heads/{new_name}",
            "-f", f"sha={sha}"
        ])

        # Delete old branch
        self._run_gh([
            "api",
            f"repos/{self.repo}/git/refs/heads/{old_name}",
            "-X", "DELETE"
        ])

        return True

    def close_issue(
        self,
        issue_number: int,
        state_reason: str = "completed"
    ) -> dict:
        """Close an issue.

        Args:
            issue_number: Issue number to close
            state_reason: Reason for closing ("completed" or "not_planned")

        Returns:
            Updated issue dict

        Raises:
            GitHubClientError: If close fails
        """
        args = [
            "api",
            f"repos/{self.repo}/issues/{issue_number}",
            "-X", "PATCH",
            "-f", "state=closed",
            "-f", f"state_reason={state_reason}"
        ]
        output = self._run_gh(args)
        issue = json.loads(output)
        return {
            "number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body", ""),
            "labels": issue.get("labels", []),
            "html_url": issue["html_url"],
            "state": issue["state"]
        }
