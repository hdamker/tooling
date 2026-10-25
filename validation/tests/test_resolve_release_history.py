"""Unit tests for validation/scripts/resolve-release-history.py."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from release_automation.scripts.github_client import GitHubClientError

# validation/scripts/ is not a package — load the module directly.
_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "validation" / "scripts" / "resolve-release-history.py"
_spec = importlib.util.spec_from_file_location("resolve_release_history", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
resolve_release_history = importlib.util.module_from_spec(_spec)
sys.modules["resolve_release_history"] = resolve_release_history
_spec.loader.exec_module(resolve_release_history)


resolve_history = resolve_release_history.resolve_history
write_outputs = resolve_release_history.write_outputs


def _release(tag: str, prerelease: bool = False):
    return SimpleNamespace(tag_name=tag, prerelease=prerelease)


def test_resolve_history_writes_complete_metadata(monkeypatch):
    class FakeClient:
        def __init__(self, repo, token=None):
            self.repo = repo
            self.token = token

        def get_releases(self, include_drafts=False):
            return [_release("r4.2")]

        def list_branches(self, pattern=None):
            return []

        def get_release_metadata(self, tag):
            assert tag == "r4.2"
            return {
                "repository": {
                    "release_type": "public-release",
                    "src_commit_sha": "a" * 40,
                },
                "dependencies": {
                    "commonalities_release": "r4.1 (1.2.0)",
                    "identity_consent_management_release": "r3.1 (1.0.0)",
                },
                "apis": [
                    {
                        "api_name": "quality-on-demand",
                        "api_version": "1.0.0",
                    }
                ],
            }

    monkeypatch.setattr(resolve_release_history, "GitHubClient", FakeClient)

    snapshot = resolve_history(
        repo="camaraproject/QualityOnDemand",
        base_ref="main",
        token="token",
    )

    assert snapshot["lookup_status"] == "complete"
    assert snapshot["repository"] == "camaraproject/QualityOnDemand"
    assert snapshot["published_releases"][0]["tag"] == "r4.2"
    assert snapshot["published_releases"][0]["metadata_available"] is True
    assert snapshot["published_releases"][0]["commonalities_release"] == "r4.1"
    assert snapshot["published_releases"][0]["icm_release"] == "r3.1"
    assert snapshot["published_releases"][0]["apis"][0]["api_name"] == "quality-on-demand"


def test_resolve_history_marks_partial_when_metadata_lookup_fails(monkeypatch):
    class FakeClient:
        def __init__(self, repo, token=None):
            pass

        def get_releases(self, include_drafts=False):
            return [_release("r4.2")]

        def list_branches(self, pattern=None):
            return []

        def get_release_metadata(self, tag):
            raise GitHubClientError("boom")

    monkeypatch.setattr(resolve_release_history, "GitHubClient", FakeClient)

    snapshot = resolve_history(repo="camaraproject/QualityOnDemand", base_ref="main")

    assert snapshot["lookup_status"] == "partial"
    assert snapshot["published_releases"][0]["metadata_available"] is False
    assert snapshot["published_releases"][0]["apis"] == []


def test_resolve_history_marks_partial_when_metadata_is_absent(monkeypatch):
    class FakeClient:
        def __init__(self, repo, token=None):
            pass

        def get_releases(self, include_drafts=False):
            return [_release("r4.2")]

        def list_branches(self, pattern=None):
            return []

        def get_release_metadata(self, tag):
            return None

    monkeypatch.setattr(resolve_release_history, "GitHubClient", FakeClient)

    snapshot = resolve_history(repo="camaraproject/QualityOnDemand", base_ref="main")

    assert snapshot["lookup_status"] == "partial"
    assert snapshot["published_releases"][0]["metadata_available"] is False


def test_resolve_history_lists_maintenance_branches(monkeypatch):
    class FakeClient:
        def __init__(self, repo, token=None):
            pass

        def get_releases(self, include_drafts=False):
            return []

        def list_branches(self, pattern=None):
            assert pattern == "maintenance/*"
            return [
                SimpleNamespace(name="maintenance/r2", sha="b" * 40),
                SimpleNamespace(name="maintenance/r1", sha="a" * 40),
            ]

    monkeypatch.setattr(resolve_release_history, "GitHubClient", FakeClient)

    snapshot = resolve_history(repo="camaraproject/QualityOnDemand", base_ref="main")

    assert snapshot["lookup_status"] == "complete"
    assert snapshot["maintenance_branches"] == ["maintenance/r1", "maintenance/r2"]


def test_resolve_history_marks_maintenance_branches_unknown_on_lookup_failure(
    monkeypatch,
):
    class FakeClient:
        def __init__(self, repo, token=None):
            pass

        def get_releases(self, include_drafts=False):
            raise GitHubClientError("releases down")

        def list_branches(self, pattern=None):
            raise GitHubClientError("branches down")

    monkeypatch.setattr(resolve_release_history, "GitHubClient", FakeClient)

    snapshot = resolve_history(repo="camaraproject/QualityOnDemand", base_ref="main")

    assert snapshot["lookup_status"] == "partial"
    assert snapshot["maintenance_branches"] is None


def test_write_outputs_appends_github_output(tmp_path: Path):
    output = tmp_path / "github-output.txt"

    write_outputs({"release_history_path": "/tmp/history.json"}, output)

    assert output.read_text(encoding="utf-8") == (
        "release_history_path=/tmp/history.json\n"
    )


def test_script_imports_from_outside_tooling_root(tmp_path: Path):
    env = {**os.environ, "PYTHONPATH": "", "GITHUB_REPOSITORY": ""}

    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Release-history lookup skipped" in result.stdout
