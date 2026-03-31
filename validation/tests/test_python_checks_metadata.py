"""Unit tests for validation.engines.python_checks.metadata_checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.metadata_checks import (
    check_license_commonalities_consistency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api(name: str) -> ApiContext:
    return ApiContext(
        api_name=name,
        target_api_version="1.0.0",
        target_api_status="public",
        target_api_maturity="stable",
        api_pattern="request-response",
        spec_file=f"code/API_definitions/{name}.yaml",
    )


def _make_context(api_names: list[str]) -> ValidationContext:
    apis = tuple(_make_api(n) for n in api_names)
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
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


def _write_spec(
    tmp_path: Path,
    api_name: str,
    license_val: dict | None = None,
    commonalities_val: str | None = None,
) -> None:
    spec: dict = {
        "openapi": "3.0.3",
        "info": {"title": api_name, "version": "1.0.0"},
    }
    if license_val is not None:
        spec["info"]["license"] = license_val
    if commonalities_val is not None:
        spec["info"]["x-camara-commonalities"] = commonalities_val
    api_dir = tmp_path / "code" / "API_definitions"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / f"{api_name}.yaml").write_text(
        yaml.dump(spec, default_flow_style=False)
    )


LICENSE_A = {"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"}
LICENSE_B = {"name": "MIT", "url": "https://opensource.org/licenses/MIT"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckLicenseCommonalitiesConsistency:
    def test_no_apis(self, tmp_path: Path):
        ctx = _make_context([])
        assert check_license_commonalities_consistency(tmp_path, ctx) == []

    def test_single_api_all_present(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", license_val=LICENSE_A, commonalities_val="r4.1")
        ctx = _make_context(["qod"])
        assert check_license_commonalities_consistency(tmp_path, ctx) == []

    def test_single_api_missing_license(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", commonalities_val="r4.1")
        ctx = _make_context(["qod"])
        findings = check_license_commonalities_consistency(tmp_path, ctx)
        assert len(findings) == 1
        assert "license" in findings[0]["message"]

    def test_single_api_missing_commonalities(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", license_val=LICENSE_A)
        ctx = _make_context(["qod"])
        findings = check_license_commonalities_consistency(tmp_path, ctx)
        assert len(findings) == 1
        assert "x-camara-commonalities" in findings[0]["message"]

    def test_single_api_both_missing(self, tmp_path: Path):
        _write_spec(tmp_path, "qod")
        ctx = _make_context(["qod"])
        findings = check_license_commonalities_consistency(tmp_path, ctx)
        assert len(findings) == 2

    def test_two_apis_consistent(self, tmp_path: Path):
        _write_spec(tmp_path, "api-a", license_val=LICENSE_A, commonalities_val="r4.1")
        _write_spec(tmp_path, "api-b", license_val=LICENSE_A, commonalities_val="r4.1")
        ctx = _make_context(["api-a", "api-b"])
        assert check_license_commonalities_consistency(tmp_path, ctx) == []

    def test_two_apis_license_mismatch(self, tmp_path: Path):
        _write_spec(tmp_path, "api-a", license_val=LICENSE_A, commonalities_val="r4.1")
        _write_spec(tmp_path, "api-b", license_val=LICENSE_B, commonalities_val="r4.1")
        ctx = _make_context(["api-a", "api-b"])
        findings = check_license_commonalities_consistency(tmp_path, ctx)
        assert len(findings) == 1
        assert "license" in findings[0]["message"]
        assert "differs" in findings[0]["message"]

    def test_two_apis_commonalities_mismatch(self, tmp_path: Path):
        _write_spec(tmp_path, "api-a", license_val=LICENSE_A, commonalities_val="r4.1")
        _write_spec(tmp_path, "api-b", license_val=LICENSE_A, commonalities_val="r3.4")
        ctx = _make_context(["api-a", "api-b"])
        findings = check_license_commonalities_consistency(tmp_path, ctx)
        assert len(findings) == 1
        assert "x-camara-commonalities" in findings[0]["message"]
        assert "differs" in findings[0]["message"]

    def test_missing_spec_file_skipped(self, tmp_path: Path):
        """Missing spec file is silently skipped (filename check reports)."""
        ctx = _make_context(["qod"])
        assert check_license_commonalities_consistency(tmp_path, ctx) == []
