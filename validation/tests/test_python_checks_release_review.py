"""Unit tests for validation.engines.python_checks.release_review_checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.release_review_checks import (
    _is_allowed,
    check_release_review_file_restriction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    is_release_review: bool = True,
    base_ref: str = "release-snapshot/r1.0",
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type="release",
        trigger_type="pr",
        profile="strict",
        stage="enabled",
        target_release_type="public-release",
        commonalities_release=None,
        commonalities_version=None,
        icm_release=None,
        base_ref=base_ref,
        is_release_review_pr=is_release_review,
        release_plan_changed=None,
        pr_number=42,
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


# ---------------------------------------------------------------------------
# TestIsAllowed
# ---------------------------------------------------------------------------


class TestIsAllowed:
    def test_changelog_md(self):
        assert _is_allowed("CHANGELOG.md") is True

    def test_readme_md(self):
        assert _is_allowed("README.md") is True

    def test_changelog_dir_file(self):
        assert _is_allowed("CHANGELOG/r1.0.md") is True

    def test_api_spec_rejected(self):
        assert _is_allowed("code/API_definitions/qod.yaml") is False

    def test_release_plan_rejected(self):
        assert _is_allowed("release-plan.yaml") is False

    def test_workflow_rejected(self):
        assert _is_allowed(".github/workflows/pr_validation.yml") is False


# ---------------------------------------------------------------------------
# TestCheckReleaseReviewFileRestriction
# ---------------------------------------------------------------------------


class TestCheckReleaseReviewFileRestriction:
    def test_not_release_review_skip(self, tmp_path: Path):
        ctx = _make_context(is_release_review=False)
        assert check_release_review_file_restriction(tmp_path, ctx) == []

    @patch(
        "validation.engines.python_checks.release_review_checks._get_changed_files"
    )
    def test_allowed_files_only(self, mock_changed, tmp_path: Path):
        mock_changed.return_value = ["CHANGELOG.md", "README.md"]
        ctx = _make_context()
        assert check_release_review_file_restriction(tmp_path, ctx) == []

    @patch(
        "validation.engines.python_checks.release_review_checks._get_changed_files"
    )
    def test_disallowed_file(self, mock_changed, tmp_path: Path):
        mock_changed.return_value = [
            "CHANGELOG.md",
            "code/API_definitions/qod.yaml",
        ]
        ctx = _make_context()
        findings = check_release_review_file_restriction(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "qod.yaml" in findings[0]["message"]

    @patch(
        "validation.engines.python_checks.release_review_checks._get_changed_files"
    )
    def test_changelog_directory_allowed(self, mock_changed, tmp_path: Path):
        mock_changed.return_value = [
            "CHANGELOG/r1.0.md",
            "CHANGELOG/r1.1.md",
        ]
        ctx = _make_context()
        assert check_release_review_file_restriction(tmp_path, ctx) == []

    @patch(
        "validation.engines.python_checks.release_review_checks._get_changed_files"
    )
    def test_multiple_disallowed(self, mock_changed, tmp_path: Path):
        mock_changed.return_value = [
            "release-plan.yaml",
            "code/API_definitions/qod.yaml",
        ]
        ctx = _make_context()
        findings = check_release_review_file_restriction(tmp_path, ctx)
        assert len(findings) == 2

    @patch(
        "validation.engines.python_checks.release_review_checks._get_changed_files"
    )
    def test_no_changed_files(self, mock_changed, tmp_path: Path):
        mock_changed.return_value = []
        ctx = _make_context()
        assert check_release_review_file_restriction(tmp_path, ctx) == []
