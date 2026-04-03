"""Unit tests for validation.engines.python_checks.metadata_checks (DG-028)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.metadata_checks import (
    check_commonalities_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    api_name: str = "quality-on-demand",
    branch_type: str = "main",
    commonalities_version: Optional[str] = None,
) -> ValidationContext:
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
        branch_type=branch_type,
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        commonalities_version=commonalities_version,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(api,),
        workflow_run_url="",
        tooling_ref="",
    )


def _write_spec(
    tmp_path: Path,
    api_name: str = "quality-on-demand",
    commonalities_value: object = "0.7.0",
    include_field: bool = True,
) -> None:
    spec: dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "Test API",
            "version": "1.0.0",
        },
        "paths": {},
    }
    if include_field:
        spec["info"]["x-camara-commonalities"] = commonalities_value

    spec_dir = tmp_path / "code" / "API_definitions"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{api_name}.yaml").write_text(
        yaml.dump(spec, default_flow_style=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckCommonalitiesVersion:

    # --- Presence ---

    def test_missing_field_error(self, tmp_path: Path):
        _write_spec(tmp_path, include_field=False)
        ctx = _make_context()
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "missing" in findings[0]["message"]

    def test_missing_field_error_on_release(self, tmp_path: Path):
        _write_spec(tmp_path, include_field=False)
        ctx = _make_context(branch_type="release")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    # --- Main branch: valid formats ---

    def test_wip_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="wip")
        ctx = _make_context(branch_type="main")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_tbd_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="tbd")
        ctx = _make_context(branch_type="main")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_short_version_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7")
        ctx = _make_context(branch_type="main")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_full_version_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0")
        ctx = _make_context(branch_type="main")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_prerelease_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0-rc.1")
        ctx = _make_context(branch_type="main")
        assert check_commonalities_version(tmp_path, ctx) == []

    # --- Main branch: invalid formats ---

    def test_garbage_on_main_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="foo")
        ctx = _make_context(branch_type="main")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "invalid format" in findings[0]["message"]

    def test_empty_string_on_main_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="")
        ctx = _make_context(branch_type="main")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    # --- Feature branch: same as main ---

    def test_wip_on_feature_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="wip")
        ctx = _make_context(branch_type="feature")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_full_version_on_feature_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0")
        ctx = _make_context(branch_type="feature")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_garbage_on_feature_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="xyz")
        ctx = _make_context(branch_type="feature")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    # --- Release branch: valid formats ---

    def test_full_version_on_release_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0")
        ctx = _make_context(branch_type="release")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_prerelease_on_release_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0-rc.1")
        ctx = _make_context(branch_type="release")
        assert check_commonalities_version(tmp_path, ctx) == []

    # --- Release branch: invalid formats ---

    def test_wip_on_release_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="wip")
        ctx = _make_context(branch_type="release")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "full version" in findings[0]["message"]

    def test_tbd_on_release_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="tbd")
        ctx = _make_context(branch_type="release")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    def test_short_version_on_release_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7")
        ctx = _make_context(branch_type="release")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    # --- Maintenance branch: same as release ---

    def test_wip_on_maintenance_error(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="wip")
        ctx = _make_context(branch_type="maintenance")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    # --- Version mismatch ---

    def test_version_match_ok(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.7.0")
        ctx = _make_context(commonalities_version="0.7.0")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_version_mismatch_warn(self, tmp_path: Path):
        _write_spec(tmp_path, commonalities_value="0.6.0")
        ctx = _make_context(commonalities_version="0.7.0")
        findings = check_commonalities_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert "does not match" in findings[0]["message"]

    def test_short_version_matches_full(self, tmp_path: Path):
        """Short form 0.7 should match 0.7.0."""
        _write_spec(tmp_path, commonalities_value="0.7")
        ctx = _make_context(commonalities_version="0.7.0")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_prerelease_matches_exact(self, tmp_path: Path):
        """0.7.0-rc.1 in spec matches 0.7.0-rc.1 from context."""
        _write_spec(tmp_path, commonalities_value="0.7.0-rc.1")
        ctx = _make_context(commonalities_version="0.7.0-rc.1")
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_no_commonalities_version_skips_mismatch(self, tmp_path: Path):
        """When context has no commonalities_version, skip mismatch check."""
        _write_spec(tmp_path, commonalities_value="0.7.0")
        ctx = _make_context(commonalities_version=None)
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_wip_skips_mismatch_check(self, tmp_path: Path):
        """Placeholder values don't trigger mismatch check."""
        _write_spec(tmp_path, commonalities_value="wip")
        ctx = _make_context(commonalities_version="0.7.0")
        assert check_commonalities_version(tmp_path, ctx) == []

    # --- Edge cases ---

    def test_missing_spec_file(self, tmp_path: Path):
        ctx = _make_context()
        assert check_commonalities_version(tmp_path, ctx) == []

    def test_numeric_value(self, tmp_path: Path):
        """YAML may parse bare 0.7 as float — should be handled via str()."""
        _write_spec(tmp_path, commonalities_value=0.7)
        ctx = _make_context(branch_type="main")
        # 0.7 as float becomes "0.7" as string — valid short form
        assert check_commonalities_version(tmp_path, ctx) == []
