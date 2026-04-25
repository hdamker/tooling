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
    check_declared_dependency_tags_exist,
    check_orphan_api_definitions,
    check_release_plan_exclusivity,
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


# ---------------------------------------------------------------------------
# P-019: check-orphan-api-definitions
# ---------------------------------------------------------------------------


class TestCheckOrphanApiDefinitions:
    def test_no_orphans(self, tmp_path: Path):
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "alpha"}])
        _write_release_plan(tmp_path, plan)
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        findings = check_orphan_api_definitions(tmp_path, _make_context())
        assert findings == []

    def test_orphan_file_warn(self, tmp_path: Path):
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "alpha"}])
        _write_release_plan(tmp_path, plan)
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        (api_dir / "old-api.yaml").touch()
        findings = check_orphan_api_definitions(tmp_path, _make_context())
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert "old-api" in findings[0]["message"]

    def test_multiple_orphans(self, tmp_path: Path):
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "alpha"}])
        _write_release_plan(tmp_path, plan)
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        (api_dir / "orphan-a.yaml").touch()
        (api_dir / "orphan-b.yaml").touch()
        findings = check_orphan_api_definitions(tmp_path, _make_context())
        assert len(findings) == 2

    def test_no_release_plan(self, tmp_path: Path):
        assert check_orphan_api_definitions(tmp_path, _make_context()) == []

    def test_no_api_definitions_dir(self, tmp_path: Path):
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "alpha"}])
        _write_release_plan(tmp_path, plan)
        assert check_orphan_api_definitions(tmp_path, _make_context()) == []

    def test_non_yaml_files_ignored(self, tmp_path: Path):
        plan = _make_plan(apis=[{"api_name": "qod", "target_api_status": "alpha"}])
        _write_release_plan(tmp_path, plan)
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").touch()
        (api_dir / "README.md").touch()
        findings = check_orphan_api_definitions(tmp_path, _make_context())
        assert findings == []


# ---------------------------------------------------------------------------
# TestCheckReleasePlanExclusivity (P-022)
# ---------------------------------------------------------------------------


def _context_with_other_files(*files: str) -> ValidationContext:
    """Build a context with a populated non_release_plan_files_changed."""
    base = _make_context()
    return ValidationContext(
        repository=base.repository,
        branch_type=base.branch_type,
        trigger_type=base.trigger_type,
        profile=base.profile,
        stage=base.stage,
        target_release_type=base.target_release_type,
        commonalities_release=base.commonalities_release,
        commonalities_version=base.commonalities_version,
        icm_release=base.icm_release,
        base_ref=base.base_ref,
        is_release_review_pr=base.is_release_review_pr,
        release_plan_changed=True,
        pr_number=base.pr_number,
        apis=base.apis,
        workflow_run_url=base.workflow_run_url,
        tooling_ref=base.tooling_ref,
        non_release_plan_files_changed=tuple(files),
    )


class TestCheckReleasePlanExclusivity:
    def test_no_other_files(self, tmp_path: Path):
        context = _context_with_other_files()
        assert check_release_plan_exclusivity(tmp_path, context) == []

    def test_single_other_file(self, tmp_path: Path):
        context = _context_with_other_files("code/API_definitions/qod.yaml")
        findings = check_release_plan_exclusivity(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-release-plan-exclusivity"
        assert findings[0]["path"] == "release-plan.yaml"
        assert "code/API_definitions/qod.yaml" in findings[0]["message"]
        assert "1 other file" in findings[0]["message"]

    def test_multiple_other_files(self, tmp_path: Path):
        files = [
            "code/API_definitions/qod.yaml",
            "code/Test_definitions/qod.feature",
            "CHANGELOG.md",
        ]
        context = _context_with_other_files(*files)
        findings = check_release_plan_exclusivity(tmp_path, context)
        assert len(findings) == 1
        assert "3 other file" in findings[0]["message"]
        for f in files:
            assert f in findings[0]["message"]

    def test_preview_truncation_over_ten_files(self, tmp_path: Path):
        files = [f"file-{i}.yaml" for i in range(15)]
        context = _context_with_other_files(*files)
        findings = check_release_plan_exclusivity(tmp_path, context)
        assert len(findings) == 1
        msg = findings[0]["message"]
        # First 10 files listed, remaining count summarised
        for f in files[:10]:
            assert f in msg
        assert "and 5 more" in msg

    def test_default_context_has_no_other_files(self, tmp_path: Path):
        # Ensures _make_context() default does not trigger the rule.
        assert check_release_plan_exclusivity(tmp_path, _make_context()) == []


# ---------------------------------------------------------------------------
# TestCheckDeclaredDependencyTagsExist (P-023)
# ---------------------------------------------------------------------------


def _context_with_dependency_changes(
    *,
    commonalities_release_changed: bool = False,
    icm_release_changed: bool = False,
    commonalities_tag_exists: bool | None = None,
    icm_tag_exists: bool | None = None,
) -> ValidationContext:
    base = _make_context()
    return ValidationContext(
        repository=base.repository,
        branch_type=base.branch_type,
        trigger_type=base.trigger_type,
        profile=base.profile,
        stage=base.stage,
        target_release_type=base.target_release_type,
        commonalities_release=base.commonalities_release,
        commonalities_version=base.commonalities_version,
        icm_release=base.icm_release,
        base_ref=base.base_ref,
        is_release_review_pr=base.is_release_review_pr,
        release_plan_changed=True,
        pr_number=base.pr_number,
        apis=base.apis,
        workflow_run_url=base.workflow_run_url,
        tooling_ref=base.tooling_ref,
        commonalities_release_changed=commonalities_release_changed,
        icm_release_changed=icm_release_changed,
        commonalities_tag_exists=commonalities_tag_exists,
        icm_tag_exists=icm_tag_exists,
    )


def _write_release_plan_with_dependencies(
    tmp_path: Path,
    commonalities: str | None = "r4.2",
    icm: str | None = "r2.3",
) -> None:
    plan = _make_plan()
    deps: dict = {}
    if commonalities is not None:
        deps["commonalities_release"] = commonalities
    if icm is not None:
        # Schema field name (not the shorter context attribute 'icm_release').
        deps["identity_consent_management_release"] = icm
    plan["dependencies"] = deps
    _write_release_plan(tmp_path, plan)


class TestCheckDeclaredDependencyTagsExist:
    def test_no_release_plan(self, tmp_path: Path):
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=False,
        )
        assert check_declared_dependency_tags_exist(tmp_path, context) == []

    def test_no_dependency_changed(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path)
        # Default context: no *_release_changed flags set
        assert check_declared_dependency_tags_exist(tmp_path, _make_context()) == []

    def test_commonalities_changed_tag_exists(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path)
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=True,
        )
        assert check_declared_dependency_tags_exist(tmp_path, context) == []

    def test_commonalities_changed_tag_missing(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path, commonalities="r9.9")
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=False,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-declared-dependency-tags-exist"
        assert "r9.9" in findings[0]["message"]
        assert "camaraproject/Commonalities" in findings[0]["message"]

    def test_commonalities_changed_lookup_failed(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path, commonalities="r4.2")
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=None,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert "r4.2" in findings[0]["message"]
        assert "Could not verify" in findings[0]["message"]

    def test_commonalities_changed_declaration_removed(self, tmp_path: Path):
        # Dependency declaration was advanced to null — not P-023's
        # concern (P-009 / schema handles this).
        _write_release_plan_with_dependencies(tmp_path, commonalities=None)
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=None,
        )
        assert check_declared_dependency_tags_exist(tmp_path, context) == []

    def test_icm_changed_tag_missing(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path, icm="r9.9")
        context = _context_with_dependency_changes(
            icm_release_changed=True,
            icm_tag_exists=False,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "r9.9" in findings[0]["message"]
        assert "camaraproject/IdentityAndConsentManagement" in findings[0]["message"]

    def test_both_changed_both_missing(self, tmp_path: Path):
        _write_release_plan_with_dependencies(
            tmp_path, commonalities="r9.9", icm="r9.9"
        )
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=False,
            icm_release_changed=True,
            icm_tag_exists=False,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 2
        messages = "\n".join(f["message"] for f in findings)
        assert "commonalities_release" in messages
        assert "icm_release" in messages

    def test_icm_changed_commonalities_unchanged(self, tmp_path: Path):
        # ICM-only advance: commonalities_release unchanged, icm_release changed.
        # Only ICM tag checked.
        _write_release_plan_with_dependencies(
            tmp_path, commonalities="r4.2", icm="r9.9"
        )
        context = _context_with_dependency_changes(
            commonalities_release_changed=False,
            icm_release_changed=True,
            icm_tag_exists=False,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert "icm_release" in findings[0]["message"]

    def test_commonalities_invalid_format_emits_format_error(
        self, tmp_path: Path
    ):
        """Malformed tag emits a format error before the existence lookup.

        Pre-fix this surfaced as the misleading "tag does not exist"
        even though the tag was rejected at the workflow layer for
        format reasons. The format precheck short-circuits the lookup.
        """
        _write_release_plan_with_dependencies(tmp_path, commonalities="r0.0")
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            # Lookup result intentionally non-False to prove the format
            # error fires regardless of what the workflow layer returned.
            commonalities_tag_exists=True,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "r0.0" in findings[0]["message"]
        assert "not a valid CAMARA release tag format" in findings[0]["message"]
        assert "does not exist" not in findings[0]["message"]

    def test_icm_invalid_format_emits_format_error(self, tmp_path: Path):
        _write_release_plan_with_dependencies(tmp_path, icm="r4.x")
        context = _context_with_dependency_changes(
            icm_release_changed=True,
            icm_tag_exists=None,
        )
        findings = check_declared_dependency_tags_exist(tmp_path, context)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "r4.x" in findings[0]["message"]
        assert "not a valid CAMARA release tag format" in findings[0]["message"]

    def test_valid_tag_passes_precheck(self, tmp_path: Path):
        """Valid tag falls through to existence handling (regression
        check: precheck does not eat valid tags)."""
        _write_release_plan_with_dependencies(tmp_path, commonalities="r4.2")
        context = _context_with_dependency_changes(
            commonalities_release_changed=True,
            commonalities_tag_exists=True,
        )
        # Tag exists → no finding (existence handling reached normally).
        assert check_declared_dependency_tags_exist(tmp_path, context) == []
