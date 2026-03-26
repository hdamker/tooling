"""Unit tests for validation.engines.python_checks.test_checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.test_checks import (
    check_test_directory_exists,
    check_test_file_version,
    check_test_files_exist,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    api_name: str = "quality-on-demand",
    version: str = "1.0.0",
    apis: tuple[ApiContext, ...] | None = None,
) -> ValidationContext:
    if apis is None:
        api = ApiContext(
            api_name=api_name,
            target_api_version=version,
            target_api_status="public",
            target_api_maturity="stable",
            api_pattern="request-response",
            spec_file=f"code/API_definitions/{api_name}.yaml",
        )
        apis = (api,)
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="dispatch",
        profile="advisory",
        stage="standard",
        target_release_type=None,
        commonalities_release=None,
        icm_release=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=apis,
        workflow_run_url="",
        tooling_ref="",
    )


def _make_test_dir(tmp_path: Path) -> Path:
    test_dir = tmp_path / "code" / "Test_definitions"
    test_dir.mkdir(parents=True)
    return test_dir


# ---------------------------------------------------------------------------
# TestCheckTestDirectoryExists
# ---------------------------------------------------------------------------


class TestCheckTestDirectoryExists:
    def test_directory_present(self, tmp_path: Path):
        _make_test_dir(tmp_path)
        ctx = _make_context()
        assert check_test_directory_exists(tmp_path, ctx) == []

    def test_directory_absent(self, tmp_path: Path):
        ctx = _make_context()
        findings = check_test_directory_exists(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-test-directory-exists"

    def test_no_apis_skip(self, tmp_path: Path):
        ctx = _make_context(apis=())
        assert check_test_directory_exists(tmp_path, ctx) == []


# ---------------------------------------------------------------------------
# TestCheckTestFilesExist
# ---------------------------------------------------------------------------


class TestCheckTestFilesExist:
    def test_exact_match(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "quality-on-demand.v1.feature").touch()
        ctx = _make_context("quality-on-demand")
        assert check_test_files_exist(tmp_path, ctx) == []

    def test_prefix_match(self, tmp_path: Path):
        """operation-specific test file: api-name-operationId.feature"""
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "quality-on-demand-createSession.v1.feature").touch()
        ctx = _make_context("quality-on-demand")
        assert check_test_files_exist(tmp_path, ctx) == []

    def test_no_matching_file(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "other-api.v1.feature").touch()
        ctx = _make_context("quality-on-demand")
        findings = check_test_files_exist(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "quality-on-demand" in findings[0]["message"]

    def test_no_test_directory(self, tmp_path: Path):
        """No test dir => skip (directory check reports it)."""
        ctx = _make_context("quality-on-demand")
        assert check_test_files_exist(tmp_path, ctx) == []

    def test_non_feature_file_ignored(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "quality-on-demand.yaml").touch()
        ctx = _make_context("quality-on-demand")
        findings = check_test_files_exist(tmp_path, ctx)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# TestCheckTestFileVersion
# ---------------------------------------------------------------------------


class TestCheckTestFileVersion:
    def test_matching_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.v1.feature").touch()
        ctx = _make_context("qod", version="1.0.0")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_matching_initial_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.v0.3.feature").touch()
        ctx = _make_context("qod", version="0.3.0")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_matching_wip_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.vwip.feature").touch()
        ctx = _make_context("qod", version="wip")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_matching_alpha_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.v0.2alpha2.feature").touch()
        ctx = _make_context("qod", version="0.2.0-alpha.2")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_mismatched_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.v2.feature").touch()
        ctx = _make_context("qod", version="1.0.0")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "v2" in findings[0]["message"]
        assert "v1" in findings[0]["message"]

    def test_no_version_suffix(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.feature").touch()
        ctx = _make_context("qod", version="1.0.0")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "no version suffix" in findings[0]["message"]

    def test_no_test_dir(self, tmp_path: Path):
        ctx = _make_context("qod")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_no_matching_files(self, tmp_path: Path):
        """No test files for this API => skip (other check reports it)."""
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "other-api.v1.feature").touch()
        ctx = _make_context("qod")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_operation_specific_file(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod-createSession.v1.feature").touch()
        ctx = _make_context("qod", version="1.0.0")
        assert check_test_file_version(tmp_path, ctx) == []
