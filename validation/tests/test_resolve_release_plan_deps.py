"""Unit tests for validation.scripts.resolve-release-plan-deps.

Covers plan parsing, diff semantics across the two declared dependencies,
gh tag-lookup tri-state mapping (success / 404 / other), and
GITHUB_OUTPUT file writing.  External commands (`git show`, `gh api`) are
mocked by providing an alternative `gh_bin` / `git_bin` that points at a
temp-directory shim script produced by the test.
"""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

# validation/scripts/ is not a package — load the module directly.
_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "validation" / "scripts" / "resolve-release-plan-deps.py"
_spec = importlib.util.spec_from_file_location("resolve_release_plan_deps", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
resolve_release_plan_deps = importlib.util.module_from_spec(_spec)
sys.modules["resolve_release_plan_deps"] = resolve_release_plan_deps
_spec.loader.exec_module(resolve_release_plan_deps)


get_dep = resolve_release_plan_deps.get_dep
_parse_plan = resolve_release_plan_deps._parse_plan
read_plan_at_path = resolve_release_plan_deps.read_plan_at_path
read_plan_at_ref = resolve_release_plan_deps.read_plan_at_ref
tag_exists = resolve_release_plan_deps.tag_exists
resolve = resolve_release_plan_deps.resolve
write_outputs = resolve_release_plan_deps.write_outputs


# ---------------------------------------------------------------------------
# Shim script factory — writes a tiny executable that echoes canned output
# and exits with a canned return code.  Keeps tests hermetic without
# needing to patch subprocess at the Python level.
# ---------------------------------------------------------------------------


def _make_shim(
    tmp_path: Path,
    name: str,
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
) -> Path:
    """Write an executable shim at tmp_path/<name> that prints fixed output.

    Implemented in Python rather than bash to sidestep shell-quoting edge
    cases with embedded newlines / quotes in the canned output.
    """
    script = tmp_path / name
    lines = [
        "#!/usr/bin/env python3",
        "import sys",
        f"sys.stdout.write({stdout!r})",
        f"sys.stderr.write({stderr!r})",
        f"sys.exit({exit_code})",
        "",
    ]
    script.write_text("\n".join(lines), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# get_dep / _parse_plan
# ---------------------------------------------------------------------------


class TestGetDep:
    def test_returns_value_when_present(self):
        plan = {"dependencies": {"commonalities_release": "r4.1"}}
        assert get_dep(plan, "commonalities_release") == "r4.1"

    def test_returns_none_when_field_absent(self):
        plan = {"dependencies": {"other": "value"}}
        assert get_dep(plan, "commonalities_release") is None

    def test_returns_none_when_dependencies_absent(self):
        assert get_dep({}, "commonalities_release") is None

    def test_returns_none_when_dependencies_not_a_dict(self):
        plan = {"dependencies": ["unexpected"]}
        assert get_dep(plan, "commonalities_release") is None

    def test_returns_none_when_value_empty_string(self):
        plan = {"dependencies": {"commonalities_release": ""}}
        assert get_dep(plan, "commonalities_release") is None

    def test_returns_none_when_value_not_a_string(self):
        plan = {"dependencies": {"commonalities_release": 4.1}}
        assert get_dep(plan, "commonalities_release") is None


class TestParsePlan:
    def test_parses_valid_yaml(self):
        assert _parse_plan("dependencies:\n  commonalities_release: r4.1\n") == {
            "dependencies": {"commonalities_release": "r4.1"}
        }

    def test_returns_empty_on_invalid_yaml(self):
        assert _parse_plan("dependencies: {\n  unterminated") == {}

    def test_returns_empty_when_top_level_is_scalar(self):
        assert _parse_plan("just-a-string") == {}

    def test_returns_empty_on_empty_string(self):
        assert _parse_plan("") == {}


# ---------------------------------------------------------------------------
# read_plan_at_path / read_plan_at_ref
# ---------------------------------------------------------------------------


class TestReadPlanAtPath:
    def test_reads_existing_file(self, tmp_path):
        plan_file = tmp_path / "release-plan.yaml"
        plan_file.write_text("dependencies:\n  commonalities_release: r4.1\n")
        assert read_plan_at_path(plan_file) == {
            "dependencies": {"commonalities_release": "r4.1"}
        }

    def test_returns_empty_when_file_missing(self, tmp_path):
        assert read_plan_at_path(tmp_path / "absent.yaml") == {}


class TestReadPlanAtRef:
    def test_returns_plan_when_git_succeeds(self, tmp_path):
        shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n",
            exit_code=0,
        )
        assert read_plan_at_ref("main", "release-plan.yaml", git_bin=str(shim)) == {
            "dependencies": {"commonalities_release": "r4.1"}
        }

    def test_returns_empty_when_git_fails(self, tmp_path):
        shim = _make_shim(
            tmp_path,
            "git",
            stderr="fatal: Path 'release-plan.yaml' does not exist in 'origin/main'\n",
            exit_code=128,
        )
        assert read_plan_at_ref("main", "release-plan.yaml", git_bin=str(shim)) == {}

    def test_returns_empty_when_git_not_found(self):
        assert read_plan_at_ref("main", "release-plan.yaml", git_bin="/no/such/bin") == {}


# ---------------------------------------------------------------------------
# tag_exists
# ---------------------------------------------------------------------------


class TestTagExists:
    def test_returns_true_on_success(self, tmp_path):
        shim = _make_shim(tmp_path, "gh", stdout='{"ref":"refs/tags/r4.1"}', exit_code=0)
        assert (
            tag_exists("camaraproject", "Commonalities", "r4.1", gh_bin=str(shim))
            == "true"
        )

    def test_returns_false_on_http_404(self, tmp_path):
        shim = _make_shim(
            tmp_path,
            "gh",
            stderr="gh: Not Found (HTTP 404)\n",
            exit_code=1,
        )
        assert (
            tag_exists("camaraproject", "Commonalities", "r9.9", gh_bin=str(shim))
            == "false"
        )

    def test_returns_empty_on_other_error(self, tmp_path, capsys):
        shim = _make_shim(
            tmp_path,
            "gh",
            stderr="gh: internal server error (HTTP 502)\n",
            exit_code=1,
        )
        assert (
            tag_exists("camaraproject", "Commonalities", "r4.1", gh_bin=str(shim))
            == ""
        )
        out = capsys.readouterr().out
        assert "::warning::Tag lookup for camaraproject/Commonalities@r4.1 failed" in out

    def test_returns_empty_when_gh_missing(self, capsys):
        assert (
            tag_exists(
                "camaraproject", "Commonalities", "r4.1", gh_bin="/no/such/bin"
            )
            == ""
        )
        out = capsys.readouterr().out
        assert "::warning::Tag lookup" in out
        assert "skipped: gh not found" in out


# ---------------------------------------------------------------------------
# resolve — end-to-end with shim binaries
# ---------------------------------------------------------------------------


def _write_plan(path: Path, commonalities: str | None, icm: str | None) -> None:
    deps = {}
    if commonalities is not None:
        deps["commonalities_release"] = commonalities
    if icm is not None:
        deps["identity_consent_management_release"] = icm
    body = "dependencies:\n" + "".join(f"  {k}: {v}\n" for k, v in deps.items())
    path.write_text(body, encoding="utf-8")


class TestResolve:
    def test_no_changes(self, tmp_path):
        """Same dep values on base and head → all changed flags false, all tag_exists empty."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_plan(workspace / "release-plan.yaml", "r4.1", "r3.0")

        git_shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n  identity_consent_management_release: r3.0\n",
            exit_code=0,
        )
        gh_shim = _make_shim(tmp_path, "gh", exit_code=0)  # should never be called

        out = resolve(
            base_ref="main",
            plan_path="release-plan.yaml",
            workspace_plan=workspace / "release-plan.yaml",
            gh_bin=str(gh_shim),
            git_bin=str(git_shim),
        )

        assert out == {
            "commonalities_release_changed": "false",
            "icm_release_changed": "false",
            "commonalities_tag_exists": "",
            "icm_tag_exists": "",
            "release_plan_check_only": "false",
        }

    def test_commonalities_advanced_to_existing_tag(self, tmp_path):
        """Commonalities bump only → check_only true, commonalities_tag_exists 'true'."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_plan(workspace / "release-plan.yaml", "r4.2", "r3.0")

        git_shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n  identity_consent_management_release: r3.0\n",
            exit_code=0,
        )
        gh_shim = _make_shim(tmp_path, "gh", stdout='{"ref":"refs/tags/r4.2"}', exit_code=0)

        out = resolve(
            base_ref="main",
            plan_path="release-plan.yaml",
            workspace_plan=workspace / "release-plan.yaml",
            gh_bin=str(gh_shim),
            git_bin=str(git_shim),
        )

        assert out["commonalities_release_changed"] == "true"
        assert out["icm_release_changed"] == "false"
        assert out["commonalities_tag_exists"] == "true"
        assert out["icm_tag_exists"] == ""
        assert out["release_plan_check_only"] == "true"

    def test_icm_advanced_to_missing_tag(self, tmp_path):
        """ICM bump to a tag that 404s → icm_tag_exists 'false', check_only remains false."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_plan(workspace / "release-plan.yaml", "r4.1", "r9.9")

        git_shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n  identity_consent_management_release: r3.0\n",
            exit_code=0,
        )
        gh_shim = _make_shim(
            tmp_path,
            "gh",
            stderr="gh: Not Found (HTTP 404)\n",
            exit_code=1,
        )

        out = resolve(
            base_ref="main",
            plan_path="release-plan.yaml",
            workspace_plan=workspace / "release-plan.yaml",
            gh_bin=str(gh_shim),
            git_bin=str(git_shim),
        )

        assert out["commonalities_release_changed"] == "false"
        assert out["icm_release_changed"] == "true"
        assert out["commonalities_tag_exists"] == ""
        assert out["icm_tag_exists"] == "false"
        assert out["release_plan_check_only"] == "false"

    def test_both_changed(self, tmp_path):
        """Both dependencies advance — both tag lookups performed, check_only true."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_plan(workspace / "release-plan.yaml", "r4.2", "r4.0")

        git_shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n  identity_consent_management_release: r3.0\n",
            exit_code=0,
        )
        gh_shim = _make_shim(tmp_path, "gh", stdout='{"ref":"refs/tags/x"}', exit_code=0)

        out = resolve(
            base_ref="main",
            plan_path="release-plan.yaml",
            workspace_plan=workspace / "release-plan.yaml",
            gh_bin=str(gh_shim),
            git_bin=str(git_shim),
        )

        assert out["commonalities_release_changed"] == "true"
        assert out["icm_release_changed"] == "true"
        assert out["commonalities_tag_exists"] == "true"
        assert out["icm_tag_exists"] == "true"
        assert out["release_plan_check_only"] == "true"

    def test_commonalities_removed_on_head(self, tmp_path):
        """Head plan drops commonalities_release → changed true, no tag lookup → '' tag_exists."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_plan(workspace / "release-plan.yaml", None, "r3.0")

        git_shim = _make_shim(
            tmp_path,
            "git",
            stdout="dependencies:\n  commonalities_release: r4.1\n  identity_consent_management_release: r3.0\n",
            exit_code=0,
        )
        gh_shim = _make_shim(tmp_path, "gh", exit_code=0)

        out = resolve(
            base_ref="main",
            plan_path="release-plan.yaml",
            workspace_plan=workspace / "release-plan.yaml",
            gh_bin=str(gh_shim),
            git_bin=str(git_shim),
        )

        assert out["commonalities_release_changed"] == "true"
        assert out["commonalities_tag_exists"] == ""  # no head tag to look up
        assert out["release_plan_check_only"] == "true"


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


class TestWriteOutputs:
    def test_appends_to_file(self, tmp_path):
        target = tmp_path / "outputs"
        target.write_text("existing=preserved\n", encoding="utf-8")
        write_outputs({"a": "1", "b": "2"}, target)
        content = target.read_text(encoding="utf-8")
        assert "existing=preserved" in content
        assert "a=1" in content
        assert "b=2" in content

    def test_prints_when_target_none(self, capsys):
        write_outputs({"a": "1"}, None)
        assert "a=1" in capsys.readouterr().out
