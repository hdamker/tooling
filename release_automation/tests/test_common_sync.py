"""Tests for common_sync.py (code/common/ cache against the declared release).

Detection values reproduce the former inline `Check common cache sync` step of
release-automation-reusable.yml; sync values reproduce the common-sync steps
of its former update-issue job, plus the fix batch (H1, H2, M2, M3, L1) noted
on the tests. Git runs for real against local bare repositories.
"""

from pathlib import Path

import pytest

import yaml

from release_automation.scripts import common_sync
from release_automation.scripts.common_sync import (
    CacheCheck,
    CommonSyncOutcome,
    describe,
    detect,
    find_sync_pr,
    sync_common,
)
from release_automation.scripts.git_operations import GitOperations
from release_automation.scripts.github_client import GitHubClientError
from release_automation.tests.local_git import git, git_ops, make_remote, push_branch
from tooling_lib.cache_sync import SourceStatus, SyncStatus, git_blob_sha


@pytest.mark.parametrize("release", ["", "main", "r4", "v4.2", "r4.2.1"])
def test_unparsable_release_is_not_checked(tmp_path, release):
    assert detect(tmp_path, release) == CacheCheck()


@pytest.mark.parametrize("release", ["r3.9", "r4.0", "r4.1"])
def test_release_before_r4_2_is_not_checked(tmp_path, release):
    assert detect(tmp_path, release) == CacheCheck()


@pytest.mark.parametrize("release", ["r4.2", "r4.10", "r5.1"])
def test_checked_releases_pass_expected_mapping(tmp_path, monkeypatch, release):
    seen = {}

    def fake_check(path, expected):
        seen.update(path=path, expected=expected)
        return SyncStatus(sources=[SourceStatus(repository="Commonalities")])

    monkeypatch.setattr(common_sync, "check_sync_status", fake_check)

    assert detect(tmp_path, release) == CacheCheck(status="in_sync")
    assert seen == {"path": tmp_path, "expected": {"Commonalities": release}}


def test_missing_common_dir_on_disk_is_stale(tmp_path):
    assert detect(tmp_path, "r4.2") == CacheCheck(
        status="stale", details="code/common/ directory is missing"
    )


def test_stale_result(tmp_path, monkeypatch):
    monkeypatch.setattr(common_sync, "check_sync_status", lambda p, e: SyncStatus(no_manifest=True))

    assert detect(tmp_path, "r4.2") == CacheCheck(
        status="stale", details="code/common/.sync-manifest.yaml is missing"
    )


@pytest.mark.parametrize(
    "status,details",
    [
        (SyncStatus(no_common_dir=True, no_manifest=True), "code/common/ directory is missing"),
        (SyncStatus(no_manifest=True), "code/common/.sync-manifest.yaml is missing"),
        (
            SyncStatus(sources=[
                SourceStatus(
                    repository="Commonalities",
                    tag_mismatch=("r4.3", "r4.2"),
                    missing_files=["CAMARA_common.yaml"],
                    modified_files=["CAMARA_event_common.yaml"],
                ),
            ]),
            "Commonalities: expected r4.3, manifest has r4.2; "
            "CAMARA_common.yaml missing from code/common/; "
            "CAMARA_event_common.yaml modified since last sync",
        ),
        (SyncStatus(sources=[]), "cache mismatch detected"),
    ],
)
def test_describe(status, details):
    assert describe(status) == details




# ── detection: ICM release (M3) ──────────────────────────────────────────────

ICM = "IdentityAndConsentManagement"


def write_manifest(api_repo: Path, sources):
    common = api_repo / "code" / "common"
    common.mkdir(parents=True, exist_ok=True)
    (common / ".sync-manifest.yaml").write_text(yaml.safe_dump({"sources": sources}))


def capture_expected(monkeypatch):
    seen = {}

    def fake_check(path, expected):
        seen["expected"] = expected
        return SyncStatus(sources=[])

    monkeypatch.setattr(common_sync, "check_sync_status", fake_check)
    return seen


def test_icm_release_checked_when_manifest_records_icm(tmp_path, monkeypatch):
    write_manifest(tmp_path, [
        {"repository": "Commonalities", "release": "r4.2", "files": {}},
        {"repository": ICM, "release": "r4.1", "files": {}},
    ])
    seen = capture_expected(monkeypatch)

    detect(tmp_path, "r4.3", icm_release="r4.2")

    assert seen["expected"] == {"Commonalities": "r4.3", ICM: "r4.2"}


@pytest.mark.parametrize("icm_release", ["", "r4.2"])
def test_icm_release_ignored_without_icm_files(tmp_path, monkeypatch, icm_release):
    # ICM publishes no artifacts/common today; requiring it would leave every cache stale.
    write_manifest(tmp_path, [{"repository": "Commonalities", "release": "r4.2", "files": {}}])
    seen = capture_expected(monkeypatch)

    detect(tmp_path, "r4.3", icm_release=icm_release)

    assert seen["expected"] == {"Commonalities": "r4.3"}


def test_icm_release_ignored_with_unreadable_manifest(tmp_path, monkeypatch):
    (tmp_path / "code" / "common").mkdir(parents=True)
    (tmp_path / "code" / "common" / ".sync-manifest.yaml").write_text(": not yaml :\n  - [")
    seen = capture_expected(monkeypatch)

    detect(tmp_path, "r4.3", icm_release="r4.2")

    assert seen["expected"] == {"Commonalities": "r4.3"}


# ── existing sync PR lookup (L1) ─────────────────────────────────────────────


class FakeGitHub:
    def __init__(self, open_prs=(), fail_create=False, fail_close=False):
        self.prs = list(open_prs)
        self.fail_create = fail_create
        self.fail_close = fail_close
        self.closed = []
        self.created = []
        self.labelled = []
        self.labels = {"automated"}
        self.created_labels = []

    def find_open_pr(self, head_branch):
        for pr in self.prs:
            if pr["head"] == head_branch:
                return pr["number"], pr["url"]
        return None

    def list_open_prs(self):
        return list(self.prs)

    def close_pr(self, pr_number, comment=""):
        if self.fail_close:
            raise GitHubClientError("gh command failed: close")
        self.closed.append((pr_number, comment))

    def create_pr(self, title, body, head, base):
        if self.fail_create:
            raise GitHubClientError("gh command failed: create")
        self.created.append({"title": title, "body": body, "head": head, "base": base})
        return 40, "https://github.com/camaraproject/Example/pull/40"

    def get_label(self, name):
        return {"name": name} if name in self.labels else None

    def create_label(self, name, color, description=""):
        self.labels.add(name)
        self.created_labels.append(name)

    def add_pr_labels(self, pr_number, labels):
        self.labelled.append((pr_number, list(labels)))


def pr(number, head):
    return {"number": number, "head": head, "url": f"https://github.com/camaraproject/Example/pull/{number}"}


def test_find_sync_pr_matches_the_exact_branch():
    gh = FakeGitHub([pr(5, "sync-common/r4.2"), pr(6, "sync-common/r4.3-old"), pr(7, "sync-common/r4.3")])

    assert find_sync_pr(gh, "r4.3", "main") == "https://github.com/camaraproject/Example/pull/7"


def test_find_sync_pr_ignores_other_sync_branches():
    gh = FakeGitHub([pr(5, "sync-common/r4.2")])

    assert find_sync_pr(gh, "r4.3", "main") == ""




# ── common sync ──────────────────────────────────────────────────────────────

OLD_COMMON = "openapi: 3.0.3\ninfo: {title: old}\n"
NEW_COMMON = "openapi: 3.0.3\ninfo: {title: new}\n"
NEW_EVENT = "openapi: 3.0.3\ninfo: {title: event}\n"

SYNC_PR_BODY = """> [!WARNING]
> This branch is owned by Release Automation and is rebuilt from `main` on every run.
> **Do not commit fixes to this branch** — any commits here are overwritten the next time the sync runs.

Automated sync of `code/common/` files from `camaraproject/Commonalities` at release tag `r4.3`.

This PR was created by release automation because the cached Commonalities files were out of sync with the declared dependency in `release-plan.yaml`.

**What changed:**
- Updated files in `code/common/` to match Commonalities r4.3
- Added/updated `.sync-manifest.yaml` with file integrity hashes

**How to handle this PR:**
- **Validation green** — review and merge.
- **Validation red** — choose one:
  - *(recommended)* fix the errors on `main`, then re-trigger the sync; this PR is rebuilt from the new `main` HEAD with the corrected content.
  - merge this PR with the errors and fix them on `main` afterwards.

To re-trigger the sync, run the **CAMARA Release Automation** workflow from the repository's **Actions** tab.

`/create-snapshot` is blocked until common files are in sync."""


@pytest.fixture
def remotes(tmp_path):
    api = make_remote(tmp_path, "api", {
        "README.md": "# Example\n",
        "code/common/CAMARA_common.yaml": OLD_COMMON,
    })
    commonalities = make_remote(tmp_path, "commonalities", {
        "artifacts/common/CAMARA_common.yaml": NEW_COMMON,
        "artifacts/common/CAMARA_event_common.yaml": NEW_EVENT,
        "artifacts/common/README.md": "not synced\n",
    }, tag="r4.3")
    return api, commonalities


def run_sync_common(tmp_path, remotes, gh, release="r4.3"):
    api, commonalities = remotes
    return sync_common(
        git_ops(api, tmp_path / "work-api"),
        git_ops(commonalities, tmp_path / "work-commonalities", repo="camaraproject/Commonalities"),
        gh,
        release,
        "release-bot[bot]",
        "7+release-bot[bot]@users.noreply.github.com",
        base_branch="main",
    )


def test_sync_copies_files_writes_manifest_and_opens_pr(tmp_path, remotes):
    api, _ = remotes
    gh = FakeGitHub()

    outcome = run_sync_common(tmp_path, remotes, gh)

    assert outcome == CommonSyncOutcome(
        status="created", pr_url="https://github.com/camaraproject/Example/pull/40", pr_number="40"
    )
    branch = "sync-common/r4.3"
    assert git(api, "show", f"{branch}:code/common/CAMARA_common.yaml") + "\n" == NEW_COMMON
    assert git(api, "show", f"{branch}:code/common/CAMARA_event_common.yaml") + "\n" == NEW_EVENT
    manifest = yaml.safe_load(git(api, "show", f"{branch}:code/common/.sync-manifest.yaml"))
    assert manifest == {"sources": [{
        "repository": "Commonalities",
        "release": "r4.3",
        "files": {
            "CAMARA_common.yaml": git_blob_sha(NEW_COMMON.encode()),
            "CAMARA_event_common.yaml": git_blob_sha(NEW_EVENT.encode()),
        },
    }]}
    assert git(api, "log", "-1", "--format=%s|%an", branch) == (
        "chore: sync common files from Commonalities r4.3|release-bot[bot]"
    )
    assert git(api, "rev-parse", f"{branch}~1") == git(api, "rev-parse", "main")
    assert gh.created == [{
        "title": "Sync common files from Commonalities r4.3",
        "body": SYNC_PR_BODY,
        "head": branch,
        "base": "main",
    }]
    assert gh.created_labels == ["common-sync"]
    assert gh.labelled == [(40, ["common-sync", "automated"])]


def test_synced_cache_is_in_sync(tmp_path, remotes):
    run_sync_common(tmp_path, remotes, FakeGitHub())

    assert detect(tmp_path / "work-api", "r4.3") == CacheCheck(status="in_sync")


def test_sync_branch_from_an_earlier_run_is_rebuilt_from_main(tmp_path, remotes):
    # H1: the sync branch is reset to main before the files are copied, so a
    # stale remote branch (or a hand commit on it) never blocks the run.
    api, _ = remotes
    push_branch(api, tmp_path, "sync-common/r4.3", {"code/common/CAMARA_common.yaml": "hand edit\n"})

    assert run_sync_common(tmp_path, remotes, FakeGitHub()).status == "created"
    assert git(api, "show", "sync-common/r4.3:code/common/CAMARA_common.yaml") + "\n" == NEW_COMMON
    assert git(api, "rev-parse", "sync-common/r4.3~1") == git(api, "rev-parse", "main")


def test_branch_is_reset_before_files_are_copied(tmp_path, remotes, monkeypatch):
    calls = []
    real_copy = common_sync.copy_common_files
    real_branch = GitOperations.create_branch
    monkeypatch.setattr(common_sync, "copy_common_files", lambda *a: calls.append("copy") or real_copy(*a))
    monkeypatch.setattr(
        GitOperations, "create_branch",
        lambda self, *a, **k: calls.append("branch") or real_branch(self, *a, **k),
    )

    run_sync_common(tmp_path, remotes, FakeGitHub())

    assert calls == ["branch", "copy"]


def test_open_pr_for_the_branch_is_reused(tmp_path, remotes):
    gh = FakeGitHub([pr(33, "sync-common/r4.3")])

    assert run_sync_common(tmp_path, remotes, gh) == CommonSyncOutcome(
        status="updated", pr_url="https://github.com/camaraproject/Example/pull/33", pr_number="33"
    )
    assert gh.created == []


def test_sync_prs_for_other_releases_are_closed(tmp_path, remotes):
    gh = FakeGitHub([pr(31, "sync-common/r4.2"), pr(32, "feature/x"), pr(33, "sync-common/r4.3")])

    run_sync_common(tmp_path, remotes, gh)

    assert gh.closed == [(31, "Superseded by sync to Commonalities r4.3")]


def test_close_failure_does_not_stop_the_sync(tmp_path, remotes):
    gh = FakeGitHub([pr(31, "sync-common/r4.2")], fail_close=True)

    assert run_sync_common(tmp_path, remotes, gh).status == "created"


def test_cache_already_matching_is_no_changes(tmp_path, remotes):
    api, commonalities = remotes
    run_sync_common(tmp_path, remotes, FakeGitHub())
    git(api, "update-ref", "refs/heads/main", "refs/heads/sync-common/r4.3")

    outcome = sync_common(
        git_ops(api, tmp_path / "again-api"),
        git_ops(commonalities, tmp_path / "again-commonalities"),
        FakeGitHub(), "r4.3", "bot", "bot@example.com", base_branch="main",
    )

    assert outcome == CommonSyncOutcome(status="no_changes")


def test_unexpected_files_are_flagged_not_deleted(tmp_path, capsys):
    # M2: files under code/common/ that the Commonalities release does not provide
    api = make_remote(tmp_path, "api", {
        "code/common/CAMARA_common.yaml": OLD_COMMON,
        "code/common/local_extra.yaml": "x: 1\n",
        "code/common/notes.md": "notes\n",
    })
    commonalities = make_remote(tmp_path, "commonalities", {
        "artifacts/common/CAMARA_common.yaml": NEW_COMMON,
    }, tag="r4.3")
    gh = FakeGitHub()

    outcome = run_sync_common(tmp_path, (api, commonalities), gh)

    assert outcome.unexpected_files == ("local_extra.yaml", "notes.md")
    assert git(api, "show", "sync-common/r4.3:code/common/local_extra.yaml") == "x: 1"
    assert gh.created[0]["body"].endswith(
        "\n\n**Not provided by Commonalities r4.3:** `local_extra.yaml`, `notes.md` in "
        "`code/common/` — remove them on `main` if they are no longer needed."
    )
    assert (
        "::warning::code/common/ has files not provided by Commonalities r4.3: local_extra.yaml, notes.md"
        in capsys.readouterr().out
    )


# H2: every failed common sync step is a failed outcome (the caller posts common_sync_failed).


def test_unknown_commonalities_release_is_failed(tmp_path, remotes, capsys):
    gh = FakeGitHub()

    assert run_sync_common(tmp_path, remotes, gh, release="r9.9") == CommonSyncOutcome(status="failed")
    assert "::error::Could not fetch Commonalities r9.9" in capsys.readouterr().out
    assert gh.created == []


def test_api_clone_failure_is_failed(tmp_path, remotes):
    _, commonalities = remotes

    assert run_sync_common(tmp_path, (tmp_path / "missing.git", commonalities), FakeGitHub()).status == "failed"


@pytest.mark.parametrize(
    "files,message",
    [
        ({"README.md": "x\n"}, "Commonalities artifacts/common not found at tag r4.3"),
        ({"artifacts/common/README.md": "x\n"}, "No YAML files in Commonalities artifacts/common at r4.3"),
    ],
)
def test_release_without_common_files_is_failed(tmp_path, remotes, files, message, capsys):
    api, _ = remotes
    commonalities = make_remote(tmp_path, "bare-commonalities", files, tag="r4.3")

    assert run_sync_common(tmp_path, (api, commonalities), FakeGitHub()).status == "failed"
    assert f"::error::{message}" in capsys.readouterr().out


def test_push_failure_is_failed(tmp_path, remotes):
    api, _ = remotes
    hook = api / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    assert run_sync_common(tmp_path, remotes, FakeGitHub()).status == "failed"


def test_pr_creation_failure_is_failed(tmp_path, remotes, capsys):
    assert run_sync_common(tmp_path, remotes, FakeGitHub(fail_create=True)) == CommonSyncOutcome(status="failed")
    assert "::error::Failed to create sync PR" in capsys.readouterr().out


# ── per base branch (M10, spec 7.4/7.5) ──────────────────────────────────────

MB = "maintenance/r1"


@pytest.mark.parametrize(
    "base_branch,branch",
    [("main", "sync-common/r4.3"), (MB, "sync-common/maintenance/r1/r4.3")],
)
def test_sync_branch_per_line(base_branch, branch):
    assert common_sync.sync_branch("r4.3", base_branch) == branch


def test_find_sync_pr_matches_within_the_line():
    gh = FakeGitHub([pr(5, "sync-common/r4.3"), pr(6, "sync-common/maintenance/r1/r4.3")])

    assert find_sync_pr(gh, "r4.3", MB).endswith("/pull/6")
    assert find_sync_pr(gh, "r4.3", "main").endswith("/pull/5")
    assert find_sync_pr(gh, "r4.3", "maintenance/r2") == ""


def test_sync_on_a_maintenance_branch_opens_its_pr_into_that_branch(tmp_path, remotes):
    # spec 7.4
    api, commonalities = remotes
    push_branch(api, tmp_path, MB, {"code/common/CAMARA_common.yaml": "line copy\n"})
    gh = FakeGitHub()

    outcome = sync_common(
        git_ops(api, tmp_path / "work-api"),
        git_ops(commonalities, tmp_path / "work-commonalities", repo="camaraproject/Commonalities"),
        gh, "r4.3", "bot", "bot@example.com", base_branch=MB,
    )

    branch = "sync-common/maintenance/r1/r4.3"
    assert outcome.status == "created"
    assert git(api, "rev-parse", f"{branch}~1") == git(api, "rev-parse", MB)
    assert git(api, "show", f"{branch}:code/common/CAMARA_common.yaml") + "\n" == NEW_COMMON
    (created,) = gh.created
    assert (created["head"], created["base"]) == (branch, MB)
    assert f"rebuilt from `{MB}` on every run" in created["body"]
    assert f"fix the errors on `{MB}`" in created["body"]


def test_lines_do_not_close_each_others_sync_prs(tmp_path, remotes):
    # spec 7.5: main's sync and the line's sync for the same release coexist
    api, commonalities = remotes
    push_branch(api, tmp_path, MB, {"README.md": "line\n"})
    open_prs = [
        pr(31, "sync-common/r4.2"),
        pr(32, "sync-common/r4.3"),
        pr(41, "sync-common/maintenance/r1/r4.2"),
        pr(42, "sync-common/maintenance/r2/r4.2"),
    ]
    gh_main, gh_line = FakeGitHub(open_prs), FakeGitHub(open_prs)

    run_sync_common(tmp_path, remotes, gh_main)
    sync_common(
        git_ops(api, tmp_path / "line-api"),
        git_ops(commonalities, tmp_path / "line-commonalities", repo="camaraproject/Commonalities"),
        gh_line, "r4.3", "bot", "bot@example.com", base_branch=MB,
    )

    assert [n for n, _ in gh_main.closed] == [31]
    assert [n for n, _ in gh_line.closed] == [41]

