"""Tests for sync_pr.py (post-release README/CHANGELOG sync PR).

Expected values reproduce the former create-sync-pr job of
release-automation-reusable.yml (two github-script blocks and the
"Create sync PR" shell step). Git runs for real against a local bare
repository; the GitHub side is a fake.
"""

from pathlib import Path

import pytest

from release_automation.scripts.github_client import GitHubClientError
from release_automation.scripts.sync_pr import SyncPrOutcome, create_sync_pr
from release_automation.tests.local_git import git, git_ops, make_remote, push_branch

START = "<!-- CAMARA:RELEASE-INFO:START -->"
END = "<!-- CAMARA:RELEASE-INFO:END -->"

MAIN_README = f"# Example\n\nIntro.\n\n{START}\nNo release yet.\n{END}\n\nFooter.\n"
TAG_README = f"# Example\n\nIntro at tag.\n\n{START}\nRelease r1.3 is out.\n{END}\n"
SYNCED_README = f"# Example\n\nIntro.\n\n{START}\nRelease r1.3 is out.\n{END}\n\nFooter.\n"

PR_BODY = (
    "Automated post-release sync PR for r1.3.\n"
    "\n"
    "This PR updates:\n"
    "- README.md Release Information section (copied from release tag)\n"
    "- CHANGELOG for the release cycle\n"
    "\n"
    "Created by release automation workflow."
)


class FakeGitHub:
    def __init__(self, files=None, open_prs=None, fail_create=False, fail_labels=False):
        self.files = files or {}
        self.open_prs = open_prs or {}
        self.fail_create = fail_create
        self.fail_labels = fail_labels
        self.created = []
        self.labelled = []
        self.labels = set()
        self.created_labels = []

    def get_file_content(self, path, ref="main", strict=False):
        return self.files.get((ref, path))

    def find_open_pr(self, head_branch):
        return self.open_prs.get(head_branch)

    def create_pr(self, title, body, head, base):
        if self.fail_create:
            raise GitHubClientError("gh command failed: pull request create failed")
        self.created.append({"title": title, "body": body, "head": head, "base": base})
        return 31, "https://github.com/camaraproject/Example/pull/31"

    def get_label(self, name):
        return {"name": name} if name in self.labels else None

    def create_label(self, name, color, description=""):
        self.labels.add(name)
        self.created_labels.append(name)

    def add_pr_labels(self, pr_number, labels):
        if self.fail_labels:
            raise GitHubClientError("gh command failed: label not found")
        self.labelled.append((pr_number, list(labels)))


@pytest.fixture
def remote(tmp_path):
    return make_remote(tmp_path, "api", {
        "README.md": MAIN_README,
        "CHANGELOG/CHANGELOG-r1.md": "# r1.2\n",
    })


def run(tmp_path, remote, gh, tag="r1.3"):
    return create_sync_pr(gh, git_ops(remote, tmp_path / "api"), tag, "release-bot[bot]", "7+release-bot[bot]@users.noreply.github.com")


def remote_file(remote, branch, path):
    return git(remote, "show", f"{branch}:{path}")


def tag_files(tag="r1.3", **files):
    return {(tag, path): content for path, content in files.items()}


def test_readme_block_and_cycle_changelog_from_tag(tmp_path, remote):
    gh = FakeGitHub(files={
        ("r1.3", "README.md"): TAG_README,
        ("r1.3", "CHANGELOG/CHANGELOG-r1.md"): "# r1.3\n\n# r1.2\n",
    })

    outcome = run(tmp_path, remote, gh)

    assert outcome == SyncPrOutcome(
        status="created", pr_url="https://github.com/camaraproject/Example/pull/31", pr_number="31"
    )
    assert remote_file(remote, "pr-to-main/r1.3", "README.md") == SYNCED_README.rstrip("\n")
    assert remote_file(remote, "pr-to-main/r1.3", "CHANGELOG/CHANGELOG-r1.md") == "# r1.3\n\n# r1.2"
    assert git(remote, "log", "-1", "--format=%s|%an|%ae|%cn", "pr-to-main/r1.3") == (
        "chore: post-release sync for r1.3|release-bot[bot]|"
        "7+release-bot[bot]@users.noreply.github.com|release-bot[bot]"
    )
    assert git(remote, "rev-parse", "pr-to-main/r1.3~1") == git(remote, "rev-parse", "main")
    assert gh.created == [{
        "title": "Release Automation: Post-release sync (r1.3)",
        "body": PR_BODY,
        "head": "pr-to-main/r1.3",
        "base": "main",
    }]
    assert gh.created_labels == ["post-release", "automated"]
    assert gh.labelled == [(31, ["post-release", "automated"])]


def test_flat_changelog_on_the_tag_is_not_synced(tmp_path, remote, capsys):
    gh = FakeGitHub(files=tag_files(**{"CHANGELOG.md": "# Changelog\n"}))

    assert run(tmp_path, remote, gh) == SyncPrOutcome(status="no_changes")
    assert "::warning::No CHANGELOG found at CHANGELOG/CHANGELOG-r1.md on tag r1.3" in capsys.readouterr().out


def test_cycle_changelog_directory_is_created(tmp_path):
    remote = make_remote(tmp_path, "api", {"README.md": MAIN_README})
    gh = FakeGitHub(files=tag_files("r2.1", **{"CHANGELOG/CHANGELOG-r2.md": "# r2.1\n"}))

    assert run(tmp_path, remote, gh, tag="r2.1").status == "created"
    assert remote_file(remote, "pr-to-main/r2.1", "CHANGELOG/CHANGELOG-r2.md") == "# r2.1"


@pytest.mark.parametrize(
    "files",
    [
        {},
        {"README.md": "# Example\n\nNo delimiters at the tag.\n"},
        {"README.md": f"# Example\n\n{START}\nonly a start marker\n"},
    ],
)
def test_nothing_to_copy_is_no_changes(tmp_path, remote, files, capsys):
    gh = FakeGitHub(files=tag_files(**files))

    assert run(tmp_path, remote, gh) == SyncPrOutcome(status="no_changes")
    assert "::warning::No content changes to sync" in capsys.readouterr().out
    assert "pr-to-main/r1.3" not in git(remote, "branch", "--list", "pr-to-main/*")
    assert gh.created == []


def test_main_readme_without_delimiters_is_left_alone(tmp_path, capsys):
    remote = make_remote(tmp_path, "api", {"README.md": "# Example\n"})
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README, "CHANGELOG/CHANGELOG-r1.md": "# c\n"}))

    assert run(tmp_path, remote, gh).status == "created"
    assert "::warning::Main README missing release info delimiters" in capsys.readouterr().out
    assert remote_file(remote, "pr-to-main/r1.3", "README.md") == "# Example"


def test_identical_content_is_no_changes(tmp_path, remote, capsys):
    gh = FakeGitHub(files=tag_files(**{
        "README.md": MAIN_README,
        "CHANGELOG/CHANGELOG-r1.md": "# r1.2\n",
    }))

    assert run(tmp_path, remote, gh) == SyncPrOutcome(status="no_changes")
    assert "::warning::No actual file changes detected" in capsys.readouterr().out
    assert gh.created == []


def test_pr_creation_failure_is_failed(tmp_path, remote, capsys):
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README}), fail_create=True)

    assert run(tmp_path, remote, gh) == SyncPrOutcome(status="failed")
    assert "::error::Failed to create post-release sync PR" in capsys.readouterr().out


def test_label_failure_is_a_warning(tmp_path, remote, capsys):
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README}), fail_labels=True)

    assert run(tmp_path, remote, gh).status == "created"
    assert "::warning::Could not add labels post-release, automated to #31" in capsys.readouterr().out


def test_clone_failure_is_failed(tmp_path, capsys):
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README}))

    outcome = run(tmp_path, tmp_path / "missing.git", gh)

    assert outcome == SyncPrOutcome(status="failed")
    assert "::error::Failed to create post-release sync PR" in capsys.readouterr().out


def test_push_failure_is_failed(tmp_path, remote, capsys):
    # A pre-receive hook rejecting every push stands in for a protected or unreachable remote.
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README}))

    assert run(tmp_path, remote, gh) == SyncPrOutcome(status="failed")
    assert gh.created == []
    assert "::error::Failed to create post-release sync PR" in capsys.readouterr().out


# ── re-runs: the pr-to-main/<tag> branch may already exist ───────────────────


def test_existing_branch_from_an_earlier_run_is_rebuilt(tmp_path, remote):
    push_branch(remote, tmp_path, "pr-to-main/r1.3", {"README.md": "half-done\n"})
    gh = FakeGitHub(files=tag_files(**{"README.md": TAG_README}))

    assert run(tmp_path, remote, gh).status == "created"
    assert remote_file(remote, "pr-to-main/r1.3", "README.md") == SYNCED_README.rstrip("\n")
    assert git(remote, "rev-parse", "pr-to-main/r1.3~1") == git(remote, "rev-parse", "main")


def test_existing_open_pr_is_reused(tmp_path, remote):
    push_branch(remote, tmp_path, "pr-to-main/r1.3", {"README.md": "kept\n"})
    gh = FakeGitHub(
        files=tag_files(**{"README.md": TAG_README}),
        open_prs={"pr-to-main/r1.3": (29, "https://github.com/camaraproject/Example/pull/29")},
    )

    assert run(tmp_path, remote, gh) == SyncPrOutcome(
        status="created", pr_url="https://github.com/camaraproject/Example/pull/29", pr_number="29"
    )
    assert remote_file(remote, "pr-to-main/r1.3", "README.md") == "kept"
    assert gh.created == []
