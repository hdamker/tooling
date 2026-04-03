"""Unit tests for validation.engines.python_checks.changelog_checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.changelog_checks import (
    check_changelog_format,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    target_release_type: str | None = "public-release",
) -> ValidationContext:
    api = ApiContext(
        api_name="qod",
        target_api_version="1.0.0",
        target_api_status="public",
        target_api_maturity="stable",
        api_pattern="request-response",
        spec_file="code/API_definitions/qod.yaml",
    )
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
        target_release_type=target_release_type,
        commonalities_release=None,
        commonalities_version=None,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(api,),
        workflow_run_url="",
        tooling_ref="",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckChangelogFormat:
    def test_no_release_type_skip(self, tmp_path: Path):
        ctx = _make_context(target_release_type=None)
        assert check_changelog_format(tmp_path, ctx) == []

    def test_none_release_type_skip(self, tmp_path: Path):
        ctx = _make_context(target_release_type="none")
        assert check_changelog_format(tmp_path, ctx) == []

    def test_missing_changelog(self, tmp_path: Path):
        ctx = _make_context()
        findings = check_changelog_format(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "missing" in findings[0]["message"]

    def test_changelog_file_with_version(self, tmp_path: Path):
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 1.0.0\n\n- Initial release\n"
        )
        ctx = _make_context()
        assert check_changelog_format(tmp_path, ctx) == []

    def test_changelog_file_with_v_prefix(self, tmp_path: Path):
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## v1.0.0\n\n- Initial release\n"
        )
        ctx = _make_context()
        assert check_changelog_format(tmp_path, ctx) == []

    def test_changelog_file_with_pre_release(self, tmp_path: Path):
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.2.0-alpha.1\n\n- Alpha release\n"
        )
        ctx = _make_context()
        assert check_changelog_format(tmp_path, ctx) == []

    def test_changelog_file_no_version_heading(self, tmp_path: Path):
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\nSome text without version headings.\n"
        )
        ctx = _make_context()
        findings = check_changelog_format(tmp_path, ctx)
        assert len(findings) == 1
        assert "no version heading" in findings[0]["message"]

    def test_changelog_directory_with_files(self, tmp_path: Path):
        changelog_dir = tmp_path / "CHANGELOG"
        changelog_dir.mkdir()
        (changelog_dir / "r1.0.md").write_text("## 1.0.0\n")
        ctx = _make_context()
        assert check_changelog_format(tmp_path, ctx) == []

    def test_changelog_directory_empty(self, tmp_path: Path):
        changelog_dir = tmp_path / "CHANGELOG"
        changelog_dir.mkdir()
        ctx = _make_context()
        findings = check_changelog_format(tmp_path, ctx)
        assert len(findings) == 1
        assert "no .md files" in findings[0]["message"]

    def test_changelog_directory_preferred_over_file(self, tmp_path: Path):
        """Both exist — directory takes precedence (checked first)."""
        (tmp_path / "CHANGELOG.md").write_text("no version heading")
        changelog_dir = tmp_path / "CHANGELOG"
        changelog_dir.mkdir()
        (changelog_dir / "r1.0.md").write_text("## 1.0.0\n")
        ctx = _make_context()
        # Both exist, has_changelog is True. Since we check file first in
        # the code and directory is also checked, let's verify behavior.
        assert check_changelog_format(tmp_path, ctx) == []
