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
    branch_type: str = "main",
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
        branch_type=branch_type,
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        commonalities_version=None,
        icm_release=None,
        base_ref=None,
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
    """Tests for check_test_file_version — parses Feature line content.

    Branch rules:
    - main/maintenance: Feature line must have vwip
    - release: Feature line must match target_api_version
    - feature: skipped (no constraint)
    """

    def _write_feature(self, path: Path, feature_line: str) -> None:
        path.write_text(f"{feature_line}\n  Background: setup\n")

    # --- main branch: always vwip ---

    def test_main_vwip_passes(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, vwip - Operation createSession",
        )
        ctx = _make_context("qod", branch_type="main")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_main_real_version_fails(self, tmp_path: Path):
        """On main, v1 is wrong even when target_api_version is 1.0.0."""
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v1 - Operation createSession",
        )
        ctx = _make_context("qod", version="1.0.0", branch_type="main")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "v1" in findings[0]["message"]
        assert "vwip" in findings[0]["message"]

    # --- maintenance branch: always vwip ---

    def test_maintenance_vwip_passes(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, vwip - Operation createSession",
        )
        ctx = _make_context("qod", branch_type="maintenance")
        assert check_test_file_version(tmp_path, ctx) == []

    # --- release branch: must match v{api_version} from T1b transformer ---

    def test_release_matching_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v1.0.0 - Operation createSession",
        )
        ctx = _make_context("qod", version="1.0.0", branch_type="release")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_release_matching_initial_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v0.3.0 - Operation createSession",
        )
        ctx = _make_context("qod", version="0.3.0", branch_type="release")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_release_matching_alpha_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v0.2.0-alpha.2 - Operation createSession",
        )
        ctx = _make_context("qod", version="0.2.0-alpha.2", branch_type="release")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_release_mismatched_version(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v2.0.0 - Operation createSession",
        )
        ctx = _make_context("qod", version="1.0.0", branch_type="release")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "v2.0.0" in findings[0]["message"]
        assert "v1.0.0" in findings[0]["message"]

    def test_release_vwip_fails(self, tmp_path: Path):
        """On release, vwip is wrong — must be the release version."""
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, vwip - Operation createSession",
        )
        ctx = _make_context("qod", version="1.0.0", branch_type="release")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "vwip" in findings[0]["message"]

    # --- feature branch: skipped ---

    def test_feature_branch_skipped(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, v999 - Operation createSession",
        )
        ctx = _make_context("qod", branch_type="feature")
        assert check_test_file_version(tmp_path, ctx) == []

    # --- common edge cases ---

    def test_no_version_in_feature_line(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: QoD API tests",
        )
        ctx = _make_context("qod", branch_type="main")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "no version" in findings[0]["message"]

    def test_empty_file(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        (test_dir / "qod.feature").write_text("")
        ctx = _make_context("qod", branch_type="main")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "no version" in findings[0]["message"]

    def test_no_test_dir(self, tmp_path: Path):
        ctx = _make_context("qod")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_no_matching_files(self, tmp_path: Path):
        """No test files for this API => skip (other check reports it)."""
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "other-api.feature",
            "Feature: CAMARA Other API, vwip - Operation foo",
        )
        ctx = _make_context("qod")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_operation_specific_file(self, tmp_path: Path):
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod-createSession.feature",
            "Feature: CAMARA QoD API, vwip - Operation createSession",
        )
        ctx = _make_context("qod", branch_type="main")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_feature_line_without_operation(self, tmp_path: Path):
        """Feature line with version but no operation suffix."""
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod.feature",
            "Feature: CAMARA QoD API, vwip",
        )
        ctx = _make_context("qod", branch_type="main")
        assert check_test_file_version(tmp_path, ctx) == []

    def test_multiple_files_mixed(self, tmp_path: Path):
        """Two files on release: one matching, one mismatched."""
        test_dir = _make_test_dir(tmp_path)
        self._write_feature(
            test_dir / "qod-createSession.feature",
            "Feature: CAMARA QoD API, v1.0.0 - Operation createSession",
        )
        self._write_feature(
            test_dir / "qod-deleteSession.feature",
            "Feature: CAMARA QoD API, v2.0.0 - Operation deleteSession",
        )
        ctx = _make_context("qod", version="1.0.0", branch_type="release")
        findings = check_test_file_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "deleteSession" in findings[0]["path"]
