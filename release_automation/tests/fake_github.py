"""In-memory stand-in for GitHubClient, for the act-phase modules.

State is plain dicts the tests set up and inspect. ``fail`` maps a method name
to a list of exceptions raised by its next calls, in order.
"""

import fnmatch
import itertools
from typing import Any, Dict, List, Optional

from release_automation.scripts.github_client import Branch, GitHubClientError, Release

REPO_URL = "https://github.com/camaraproject/Example"


class FakeGitHub:
    def __init__(self, files=None, branches=None, tags=None, releases=None, fail=None, issues=None, permissions=None):
        self.repo = "camaraproject/Example"
        self.files: Dict[tuple, str] = dict(files or {})   # (ref, path) -> content
        self.branches: Dict[str, str] = dict(branches or {})  # name -> sha
        self.tags: Dict[str, str] = dict(tags or {})  # name -> sha
        self.releases: List[Dict[str, Any]] = list(releases or [])
        self.fail: Dict[str, List[Exception]] = {k: list(v) for k, v in (fail or {}).items()}
        self.issues: List[Dict[str, Any]] = list(issues or [])  # open issues
        self.permissions: Dict[str, str] = dict(permissions or {})
        self.commits: List[Dict[str, str]] = []
        self.closed_prs: List[int] = []
        self.reopened: List[int] = []
        self.comments: List[Dict[str, Any]] = []
        self.calls: List[str] = []
        self._ids = itertools.count(100)

    def _call(self, name: str) -> None:
        self.calls.append(name)
        queue = self.fail.get(name)
        if queue:
            raise queue.pop(0)

    # ── files ──
    def get_file_content(self, path, ref="main", strict=False):
        self._call("get_file_content")
        return self.files.get((ref, path))

    def update_file(self, path, content, message, branch):
        self._call("update_file")
        self.files[(branch, path)] = content
        sha = f"c{next(self._ids)}"
        self.branches[branch] = sha
        self.commits.append({"branch": branch, "path": path, "message": message, "sha": sha})
        return {"commit": {"sha": sha}}

    # ── branches and tags ──
    def get_branch_sha(self, branch_name):
        self._call("get_branch_sha")
        return self.branches.get(branch_name)

    def delete_branch(self, branch_name):
        self._call("delete_branch")
        return self.branches.pop(branch_name, None) is not None

    def list_branches(self, pattern=""):
        self._call("list_branches")
        return [Branch(name=n, sha=sha) for n, sha in self.branches.items() if fnmatch.fnmatch(n, pattern or "*")]

    def create_branch_at_sha(self, branch_name, sha):
        self._call("create_branch_at_sha")
        if branch_name in self.branches:
            return False
        self.branches[branch_name] = sha
        return True

    def tag_exists(self, tag):
        return tag in self.tags

    def get_tag_sha(self, tag):
        return self.tags.get(tag)

    def create_tag(self, tag_name, sha):
        self._call("create_tag")
        self.tags[tag_name] = sha
        return {"ref": f"refs/tags/{tag_name}"}

    def delete_tag(self, tag):
        self._call("delete_tag")
        return self.tags.pop(tag, None) is not None

    # ── releases ──
    def _release(self, tag, draft_only=False):
        for r in self.releases:
            if r["tag"] == tag and (r["draft"] or not draft_only):
                return r
        return None

    def draft_release_exists(self, tag):
        return self._release(tag, draft_only=True) is not None

    def get_draft_release(self, tag) -> Optional[Release]:
        r = self._release(tag, draft_only=True)
        if not r:
            return None
        return Release(tag_name=r["tag"], name=r["tag"], draft=True, prerelease=r["prerelease"], html_url=r["html_url"])

    def get_releases(self, include_drafts=False) -> List[Release]:
        self._call("get_releases")
        return [
            Release(tag_name=r["tag"], name=r["tag"], draft=r["draft"], prerelease=r["prerelease"], html_url=r["html_url"])
            for r in reversed(self.releases) if include_drafts or not r["draft"]
        ]

    def get_release_id(self, tag, draft_only=False):
        r = self._release(tag, draft_only)
        return r["id"] if r else None

    def create_release(self, tag, target, name, body, draft, prerelease, make_latest=None):
        self._call("create_release")
        rid = next(self._ids)
        release = {
            "id": rid, "tag": tag, "target": target, "name": name, "body": body,
            "draft": draft, "prerelease": prerelease, "make_latest": make_latest,
            "html_url": f"{REPO_URL}/releases/{'untagged-' + str(rid) if draft else 'tag/' + tag}",
        }
        if not draft:
            self.tags[tag] = self.branches[target]
        self.releases.append(release)
        return {"id": rid, "html_url": release["html_url"]}

    def update_release(self, release_id, draft=None, prerelease=None, name=None, body=None, make_latest=None):
        self._call("update_release")
        r = next(r for r in self.releases if r["id"] == release_id)
        if draft is False and r["draft"]:
            r["draft"] = False
            self.tags[r["tag"]] = self.branches[r["target"]]
            r["html_url"] = f"{REPO_URL}/releases/tag/{r['tag']}"
        if prerelease is not None:
            r["prerelease"] = prerelease
        if make_latest is not None:
            r["make_latest"] = make_latest
        return {"html_url": r["html_url"]}

    def delete_release(self, release_id):
        self._call("delete_release")
        self.releases = [r for r in self.releases if r["id"] != release_id]

    # ── PRs, issues, comments ──
    def search_issues(self, labels=None, state="open"):
        self._call("search_issues")
        return [i for i in self.issues if set(labels or []) <= set(i.get("label_names", []))]

    def get_collaborator_permission(self, username):
        self._call("get_collaborator_permission")
        return self.permissions.get(username, "none")

    def close_pr(self, pr_number, comment=""):
        self._call("close_pr")
        self.closed_prs.append(pr_number)

    def reopen_issue(self, issue_number):
        self._call("reopen_issue")
        self.reopened.append(issue_number)

    def create_comment(self, issue_number, body):
        self._call("create_comment")
        cid = next(self._ids)
        self.comments.append({"id": cid, "issue": issue_number, "body": body})
        return cid

    def update_comment(self, comment_id, body):
        self._call("update_comment")
        self.comments.append({"id": comment_id, "issue": None, "body": body})


def gh_error(text: str) -> GitHubClientError:
    return GitHubClientError(f"gh command failed: {text}")
