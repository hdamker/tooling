"""Unit tests for validation.engines.python_checks.filename_checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.filename_checks import (
    check_filename_kebab_case,
    check_filename_matches_api_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(api_name: str) -> ValidationContext:
    api = ApiContext(
        api_name=api_name,
        target_api_version="1.0.0",
        target_api_status="public",
        target_api_maturity="stable",
        api_pattern="request-response",
        spec_file=f"code/API_definitions/{api_name}.yaml",
    )
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
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
        apis=(api,),
        workflow_run_url="",
        tooling_ref="",
    )


# ---------------------------------------------------------------------------
# TestCheckFilenameKebabCase
# ---------------------------------------------------------------------------


class TestCheckFilenameKebabCase:
    def test_valid_kebab_case(self, tmp_path: Path):
        ctx = _make_context("quality-on-demand")
        assert check_filename_kebab_case(tmp_path, ctx) == []

    def test_single_word(self, tmp_path: Path):
        ctx = _make_context("location")
        assert check_filename_kebab_case(tmp_path, ctx) == []

    def test_with_numbers(self, tmp_path: Path):
        ctx = _make_context("sim-swap-2g")
        assert check_filename_kebab_case(tmp_path, ctx) == []

    def test_camel_case_rejected(self, tmp_path: Path):
        ctx = _make_context("qualityOnDemand")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-filename-kebab-case"
        assert "kebab-case" in findings[0]["message"]
        assert findings[0]["api_name"] == "qualityOnDemand"

    def test_underscore_rejected(self, tmp_path: Path):
        ctx = _make_context("quality_on_demand")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    def test_uppercase_rejected(self, tmp_path: Path):
        ctx = _make_context("QualityOnDemand")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1

    def test_starts_with_number_rejected(self, tmp_path: Path):
        ctx = _make_context("2g-sim-swap")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1

    def test_trailing_hyphen_rejected(self, tmp_path: Path):
        ctx = _make_context("quality-")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1

    def test_double_hyphen_rejected(self, tmp_path: Path):
        ctx = _make_context("quality--on-demand")
        findings = check_filename_kebab_case(tmp_path, ctx)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# TestCheckFilenameMatchesApiName
# ---------------------------------------------------------------------------


class TestCheckFilenameMatchesApiName:
    def test_file_exists(self, tmp_path: Path):
        ctx = _make_context("quality-on-demand")
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "quality-on-demand.yaml").write_text("openapi: 3.0.0")
        assert check_filename_matches_api_name(tmp_path, ctx) == []

    def test_file_missing(self, tmp_path: Path):
        ctx = _make_context("quality-on-demand")
        findings = check_filename_matches_api_name(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-filename-matches-api-name"
        assert "not found" in findings[0]["message"]
        assert "quality-on-demand" in findings[0]["message"]

    def test_wrong_name_on_disk(self, tmp_path: Path):
        """release-plan says 'qos-booking' but file is 'qos_booking.yaml'."""
        ctx = _make_context("qos-booking")
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qos_booking.yaml").write_text("openapi: 3.0.0")
        findings = check_filename_matches_api_name(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
