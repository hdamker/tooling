"""Unit tests for validation.engines.python_checks.release_plan_checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.release_plan_checks import (
    ALLOWED_META_RELEASES,
    _check_file_existence,
    _check_release_type_consistency,
    _check_track_consistency,
    check_release_plan_semantics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> ValidationContext:
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
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


def _write_release_plan(tmp_path: Path, plan: dict) -> None:
    (tmp_path / "release-plan.yaml").write_text(
        yaml.dump(plan, default_flow_style=False)
    )


def _make_plan(
    release_track: str = "meta-release",
    meta_release: str | None = "Spring26",
    target_release_type: str = "public-release",
    apis: list[dict] | None = None,
) -> dict:
    repo: dict = {
        "release_track": release_track,
        "target_release_type": target_release_type,
    }
    if meta_release is not None:
        repo["meta_release"] = meta_release
    if apis is None:
        apis = [{"api_name": "qod", "target_api_status": "public", "target_api_version": "1.0.0"}]
    return {"repository": repo, "apis": apis}


# ---------------------------------------------------------------------------
# TestCheckTrackConsistency
# ---------------------------------------------------------------------------


class TestCheckTrackConsistency:
    def test_meta_release_with_value(self):
        plan = _make_plan(release_track="meta-release", meta_release="Spring26")
        assert _check_track_consistency(plan) == []

    def test_meta_release_missing_value(self):
        plan = _make_plan(release_track="meta-release", meta_release=None)
        findings = _check_track_consistency(plan)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "meta_release field is missing" in findings[0]["message"]

    def test_independent_with_meta_release(self):
        plan = _make_plan(release_track="independent", meta_release="Spring26")
        findings = _check_track_consistency(plan)
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"

    def test_independent_without_meta_release(self):
        plan = _make_plan(release_track="independent", meta_release=None)
        assert _check_track_consistency(plan) == []

    def test_invalid_meta_release_value(self):
        plan = _make_plan(meta_release="Winter99")
        findings = _check_track_consistency(plan)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "Winter99" in findings[0]["message"]

    def test_valid_meta_release_values(self):
        for value in ALLOWED_META_RELEASES:
            plan = _make_plan(meta_release=value)
            assert _check_track_consistency(plan) == [], f"Failed for {value}"


# ---------------------------------------------------------------------------
# TestCheckReleaseTypeConsistency
# ---------------------------------------------------------------------------


class TestCheckReleaseTypeConsistency:
    def test_none_no_constraints(self):
        plan = _make_plan(
            target_release_type="none",
            apis=[{"api_name": "qod", "target_api_status": "draft"}],
        )
        assert _check_release_type_consistency(plan) == []

    def test_alpha_with_draft_error(self):
        plan = _make_plan(
            target_release_type="pre-release-alpha",
            apis=[{"api_name": "qod", "target_api_status": "draft"}],
        )
        findings = _check_release_type_consistency(plan)
        assert len(findings) == 1
        assert "draft" in findings[0]["message"]

    def test_alpha_with_alpha_ok(self):
        plan = _make_plan(
            target_release_type="pre-release-alpha",
            apis=[{"api_name": "qod", "target_api_status": "alpha"}],
        )
        assert _check_release_type_consistency(plan) == []

    def test_rc_with_alpha_error(self):
        plan = _make_plan(
            target_release_type="pre-release-rc",
            apis=[{"api_name": "qod", "target_api_status": "alpha"}],
        )
        findings = _check_release_type_consistency(plan)
        assert len(findings) == 1

    def test_rc_with_rc_ok(self):
        plan = _make_plan(
            target_release_type="pre-release-rc",
            apis=[{"api_name": "qod", "target_api_status": "rc"}],
        )
        assert _check_release_type_consistency(plan) == []

    def test_public_with_rc_error(self):
        plan = _make_plan(
            target_release_type="public-release",
            apis=[{"api_name": "qod", "target_api_status": "rc"}],
        )
        findings = _check_release_type_consistency(plan)
        assert len(findings) == 1

    def test_public_with_public_ok(self):
        plan = _make_plan(
            target_release_type="public-release",
            apis=[{"api_name": "qod", "target_api_status": "public"}],
        )
        assert _check_release_type_consistency(plan) == []

    def test_maintenance_with_non_public_error(self):
        plan = _make_plan(
            target_release_type="maintenance-release",
            apis=[{"api_name": "qod", "target_api_status": "alpha"}],
        )
        findings = _check_release_type_consistency(plan)
        assert len(findings) == 1

    def test_multiple_apis_some_invalid(self):
        plan = _make_plan(
            target_release_type="public-release",
            apis=[
                {"api_name": "good", "target_api_status": "public"},
                {"api_name": "bad", "target_api_status": "rc"},
            ],
        )
        findings = _check_release_type_consistency(plan)
        assert len(findings) == 1
        assert "bad" in findings[0]["message"]
        assert "good" not in findings[0]["message"]


# ---------------------------------------------------------------------------
# TestCheckFileExistence
# ---------------------------------------------------------------------------


class TestCheckFileExistence:
    def test_file_exists(self, tmp_path: Path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "public"}])
        assert _check_file_existence(plan, tmp_path) == []

    def test_public_missing_file_error(self, tmp_path: Path):
        (tmp_path / "code" / "API_definitions").mkdir(parents=True)
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "public"}])
        findings = _check_file_existence(plan, tmp_path)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"

    def test_draft_missing_with_orphans_warn(self, tmp_path: Path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "quality-on-demand.yaml").touch()  # orphan
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "draft"}])
        findings = _check_file_existence(plan, tmp_path)
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert "quality-on-demand" in findings[0]["message"]

    def test_draft_missing_without_orphans(self, tmp_path: Path):
        (tmp_path / "code" / "API_definitions").mkdir(parents=True)
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "draft"}])
        assert _check_file_existence(plan, tmp_path) == []


# ---------------------------------------------------------------------------
# TestCheckReleasePlanSemantics (integration)
# ---------------------------------------------------------------------------


class TestCheckReleasePlanSemantics:
    def test_no_release_plan(self, tmp_path: Path):
        ctx = _make_context()
        assert check_release_plan_semantics(tmp_path, ctx) == []

    def test_valid_plan(self, tmp_path: Path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        _write_release_plan(tmp_path, _make_plan())
        ctx = _make_context()
        assert check_release_plan_semantics(tmp_path, ctx) == []

    def test_collects_all_findings(self, tmp_path: Path):
        """Multiple issues are collected from all sub-checks."""
        plan = _make_plan(
            release_track="meta-release",
            meta_release=None,
            target_release_type="public-release",
            apis=[{"api_name": "qod", "target_api_status": "draft"}],
        )
        _write_release_plan(tmp_path, plan)
        ctx = _make_context()
        findings = check_release_plan_semantics(tmp_path, ctx)
        # meta_release missing (track) + draft in public-release (type) = 2
        assert len(findings) >= 2
