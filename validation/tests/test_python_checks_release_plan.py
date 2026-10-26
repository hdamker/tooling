"""Unit tests for validation.engines.python_checks.release_plan_checks."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from validation.context import ActiveReleaseState, ApiContext, ValidationContext
from validation.context.release_history import parse_release_history
from validation.engines.python_checks.release_plan_checks import (
    ALLOWED_META_RELEASES,
    _check_file_existence,
    _check_release_type_consistency,
    _check_track_consistency,
    check_declared_dependency_tags_exist,
    check_orphan_api_definitions,
    check_release_plan_active_release_state,
    check_release_plan_api_names_unique,
    check_release_plan_exclusivity,
    check_release_plan_maintenance_api_versions,
    check_release_plan_maintenance_line,
    check_release_plan_published_history,
    check_release_plan_semantics,
    check_release_plan_terminal_api_status,
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
    target_release_tag: str | None = "r4.3",
    apis: list[dict] | None = None,
) -> dict:
    repo: dict = {
        "release_track": release_track,
        "target_release_type": target_release_type,
    }
    if target_release_tag is not None:
        repo["target_release_tag"] = target_release_tag
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
# TestCheckReleasePlanApiNamesUnique (P-034)
# ---------------------------------------------------------------------------


class TestCheckReleasePlanApiNamesUnique:
    def test_no_release_plan(self, tmp_path: Path):
        assert check_release_plan_api_names_unique(tmp_path, _make_context()) == []

    def test_unique_api_names(self, tmp_path: Path):
        plan = _make_plan(
            apis=[
                {"api_name": "quality-on-demand", "target_api_status": "public"},
                {"api_name": "qos-booking", "target_api_status": "public"},
            ]
        )
        _write_release_plan(tmp_path, plan)
        assert check_release_plan_api_names_unique(tmp_path, _make_context()) == []

    def test_duplicate_api_name_errors(self, tmp_path: Path):
        plan = _make_plan(
            apis=[
                {"api_name": "quality-on-demand", "target_api_status": "public"},
                {"api_name": "quality-on-demand", "target_api_status": "rc"},
                {"api_name": "qos-booking", "target_api_status": "public"},
            ]
        )
        _write_release_plan(tmp_path, plan)

        findings = check_release_plan_api_names_unique(tmp_path, _make_context())

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-api-names-unique"
        assert findings[0]["level"] == "error"
        assert findings[0]["path"] == "release-plan.yaml"
        assert findings[0]["api_name"] == "quality-on-demand"
        assert "2 entries" in findings[0]["message"]
        assert "quality-on-demand" in findings[0]["message"]

    def test_pre_existing_duplicate_prefixes_message(self, tmp_path: Path):
        plan = _make_plan(
            apis=[
                {"api_name": "quality-on-demand", "target_api_status": "public"},
                {"api_name": "quality-on-demand", "target_api_status": "public"},
            ]
        )
        _write_release_plan(tmp_path, plan)
        context = _context_with_active_release_state(release_plan_changed=False)

        findings = check_release_plan_api_names_unique(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["message"].startswith(
            "Pre-existing release-plan condition:"
        )
        assert "dedicated release-plan PR" in findings[0]["message"]


# ---------------------------------------------------------------------------
# TestCheckReleasePlanPublishedHistory (P-035)
# ---------------------------------------------------------------------------


def _published_release(
    tag: str,
    *,
    release_type: str = "public-release",
    apis: list[dict] | None = None,
    commonalities_release: str | None = None,
    icm_release: str | None = None,
    metadata_available: bool = True,
) -> dict:
    if apis is None:
        apis = [
            {
                "api_name": "quality-on-demand",
                "api_version": "1.0.0",
                "api_file_name": "quality-on-demand",
            }
        ]
    return {
        "tag": tag,
        "release_type": release_type,
        "prerelease": release_type.startswith("pre-release"),
        "published_at": "2026-01-15T00:00:00Z",
        "src_commit_sha": "a" * 40,
        "metadata_available": metadata_available,
        "commonalities_release": commonalities_release if metadata_available else None,
        "icm_release": icm_release if metadata_available else None,
        "apis": apis if metadata_available else [],
    }


def _release_history(
    *releases: dict,
    lookup_status: str = "complete",
    base_ref: str = "main",
    maintenance_branches: list[str] | None = None,
) -> dict:
    history = {
        "schema_version": 1,
        "repository": "camaraproject/QualityOnDemand",
        "base_ref": base_ref,
        "lookup_status": lookup_status,
        "published_releases": list(releases),
    }
    if maintenance_branches is not None:
        history["maintenance_branches"] = maintenance_branches
    return history


def _context_with_release_history(
    history: dict,
    *,
    release_plan_changed: bool | None = True,
    base_release_track: str | None = None,
    base_meta_release: str | None = None,
) -> ValidationContext:
    return dataclasses.replace(
        _make_context(),
        release_plan_changed=release_plan_changed,
        base_release_track=base_release_track,
        base_meta_release=base_meta_release,
        release_history=parse_release_history(history),
    )


def _api(version: str, status: str = "public", name: str = "quality-on-demand") -> dict:
    return {"api_name": name, "target_api_status": status, "target_api_version": version}


def _published_api(version: str, name: str = "quality-on-demand") -> dict:
    return {"api_name": name, "api_version": version, "api_file_name": name}


class TestPublishedHistoryMaintenanceLine:
    """P-035 compares a maintenance-line plan with its own cycle's tags (M11)."""

    def _cycle_one_and_two(self) -> dict:
        return _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]),
            _published_release(
                "r1.9", release_type="pre-release-rc", apis=[_published_api("1.2.1-rc.1")]
            ),
            _published_release("r2.1", apis=[_published_api("2.0.0")]),
            base_ref="maintenance/r1",
            maintenance_branches=["maintenance/r1"],
        )

    def test_maintenance_plan_below_later_cycle_is_not_a_regression(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_type="maintenance-release",
                target_release_tag="r1.10",
                apis=[_api("1.2.1")],
            ),
        )
        context = _context_with_release_history(self._cycle_one_and_two())

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_maintenance_plan_regression_within_cycle_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_type="maintenance-release",
                target_release_tag="r1.8",
                apis=[_api("1.2.1")],
            ),
        )
        context = _context_with_release_history(self._cycle_one_and_two())

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "lower than latest published release tag 'r1.9'" in findings[0]["message"]

    def test_published_maintenance_release_on_line_stays_quiet(self, tmp_path: Path):
        history = self._cycle_one_and_two()
        history["published_releases"].append(
            _published_release(
                "r1.10", release_type="maintenance-release", apis=[_published_api("1.2.1")]
            )
        )
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_type="maintenance-release",
                target_release_tag="r1.10",
                apis=[_api("1.2.1")],
            ),
        )
        context = _context_with_release_history(history)

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_none_plan_on_older_line_tag_errors_when_edited(self, tmp_path: Path):
        # Closes the inactive-match edge: a parked plan pointing at r1.6 after
        # r1.7 was published on the same line regresses.
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_type="none",
                target_release_tag="r1.6",
                apis=[_api("1.2.0")],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r1.6", apis=[_published_api("1.2.0")]),
                _published_release(
                    "r1.7", release_type="maintenance-release", apis=[_published_api("1.2.1")]
                ),
            )
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "lower than latest published release tag 'r1.7'" in findings[0]["message"]

    def test_none_plan_on_latest_line_tag_stays_quiet(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_type="none",
                target_release_tag="r1.7",
                apis=[_api("1.2.1")],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r1.6", apis=[_published_api("1.2.0")]),
                _published_release(
                    "r1.7", release_type="maintenance-release", apis=[_published_api("1.2.1")]
                ),
                _published_release("r2.1", release_type="pre-release-alpha",
                                   apis=[_published_api("2.0.0-alpha.1")]),
            )
        )

        assert check_release_plan_published_history(tmp_path, context) == []


def _cycle_one_history(*extra: dict, **kwargs) -> dict:
    """Cycle 1 with public r1.6 (spec notation), plus optional releases."""
    return _release_history(
        _published_release("r1.5", release_type="pre-release-rc",
                           apis=[_published_api("1.2.0-rc.1")]),
        _published_release("r1.6", apis=[_published_api("1.2.0")]),
        *extra,
        **kwargs,
    )


def _maintenance_plan(tag: str, release_type: str = "maintenance-release",
                      version: str = "1.2.1") -> dict:
    status = "rc" if release_type == "pre-release-rc" else "public"
    return _make_plan(
        target_release_type=release_type,
        target_release_tag=tag,
        apis=[_api(version, status)],
    )


class TestCheckReleasePlanMaintenanceLine:
    def _findings(self, tmp_path: Path, plan: dict, history: dict, **ctx) -> list:
        _write_release_plan(tmp_path, plan)
        context = _context_with_release_history(history, **ctx)
        return check_release_plan_maintenance_line(tmp_path, context)

    def test_absent_history_skips(self, tmp_path: Path):
        _write_release_plan(tmp_path, _maintenance_plan("r1.9"))
        assert check_release_plan_maintenance_line(tmp_path, _make_context()) == []

    # Spec 2.4 / 1.1: case A on main
    def test_case_a_maintenance_plan_on_main_ok(self, tmp_path: Path):
        history = _cycle_one_history(maintenance_branches=[])
        assert self._findings(tmp_path, _maintenance_plan("r1.7"), history) == []

    def test_case_a_rc_on_line_ok(self, tmp_path: Path):
        history = _cycle_one_history(maintenance_branches=[])
        plan = _maintenance_plan("r1.7", "pre-release-rc")
        assert self._findings(tmp_path, plan, history) == []

    def test_case_a_allowed_while_later_cycle_only_planned(self, tmp_path: Path):
        # Spec 2.4: main may be rewritten from unpublished r2.1 back to r1.7.
        history = _cycle_one_history(maintenance_branches=[])
        assert self._findings(tmp_path, _maintenance_plan("r1.7"), history) == []

    # Spec 1.7
    @pytest.mark.parametrize("release_type", ["pre-release-alpha", "public-release"])
    def test_disallowed_type_on_maintenance_line(self, tmp_path: Path, release_type):
        plan = _make_plan(
            target_release_type=release_type,
            target_release_tag="r1.7",
            apis=[_api("1.3.0", "alpha" if release_type == "pre-release-alpha" else "public")],
        )
        findings = self._findings(tmp_path, plan, _cycle_one_history())

        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-release-plan-maintenance-line"
        assert "release cycle r1 already has a public release" in findings[0]["message"]
        assert f"'{release_type}'" in findings[0]["message"]
        # The message starts from the branch and the patched release; the suggestion names the alternative on main
        assert findings[0]["message"].startswith("on 'main', which maintains release cycle r1 from r1.6: ")
        assert findings[0]["suggestion"] == (
            "Use maintenance-release or pre-release-rc for a fix of release cycle r1 here; "
            "new work is released from main in the next release cycle (r2.1)."
        )

    def test_skipped_tag_on_a_maintenance_branch_names_the_branch(self, tmp_path: Path):
        history = _cycle_one_history(
            _published_release("r1.7", release_type="maintenance-release", apis=[_published_api("1.2.1")]),
            base_ref="maintenance/r1", maintenance_branches=["maintenance/r1"],
        )
        findings = self._findings(tmp_path, _maintenance_plan("r1.9", version="1.2.2"), history)

        assert len(findings) == 1
        assert findings[0]["message"].startswith(
            "on 'maintenance/r1', which maintains release cycle r1 from r1.7: target_release_tag 'r1.9' skips tags"
        )
        assert findings[0]["suggestion"] == "Set target_release_tag: r1.8."

    # Spec 1.8
    def test_tag_must_be_next_in_cycle(self, tmp_path: Path):
        history = _cycle_one_history(
            _published_release("r1.7", release_type="pre-release-rc",
                               apis=[_published_api("1.2.1-rc.1")]),
        )
        findings = self._findings(tmp_path, _maintenance_plan("r1.9"), history)

        assert len(findings) == 1
        assert "next tag of release cycle r1 is 'r1.8'" in findings[0]["message"]

    # Spec 2.3
    @pytest.mark.parametrize("later_type", ["pre-release-alpha", "public-release"])
    def test_case_a_ended_by_later_cycle_release(self, tmp_path: Path, later_type):
        history = _cycle_one_history(
            _published_release("r2.1", release_type=later_type,
                               apis=[_published_api("2.0.0")]),
            maintenance_branches=[],
        )
        findings = self._findings(tmp_path, _maintenance_plan("r1.7"), history)

        assert len(findings) == 1
        assert "'r2.1' is already published" in findings[0]["message"]
        assert "maintenance/r1" in findings[0]["message"]
        # 107 D1: the suggestion says how the branch is created and where it is explained
        assert findings[0]["suggestion"] == (
            "Create 'maintenance/r1' from main: Actions → CAMARA Release Automation → Run workflow, "
            "action create-maintenance-branch, cycle r1. Then plan 'r1.7' there, or plan a later release "
            "on main. See https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/release-process/maintenance-releases.md"
        )

    # Spec 1.5
    def test_main_must_not_return_to_maintained_cycle(self, tmp_path: Path):
        history = _cycle_one_history(maintenance_branches=["maintenance/r1"])
        findings = self._findings(tmp_path, _maintenance_plan("r1.7"), history)

        assert len(findings) == 1
        assert "maintained on branch 'maintenance/r1'" in findings[0]["message"]

    def test_unknown_branch_list_skips_branch_check(self, tmp_path: Path):
        history = _cycle_one_history()
        assert self._findings(tmp_path, _maintenance_plan("r1.7"), history) == []

    # Spec 1.6: published plan on main stays quiet
    def test_published_target_is_left_to_p035(self, tmp_path: Path):
        plan = _make_plan(target_release_type="public-release",
                          target_release_tag="r1.6", apis=[_api("1.2.0")])
        history = _cycle_one_history(maintenance_branches=["maintenance/r1"])
        assert self._findings(tmp_path, plan, history) == []

    def test_non_maintenance_plans_unchanged(self, tmp_path: Path):
        # Next cycle after a public release, and a cycle without one.
        plan = _make_plan(target_release_type="pre-release-alpha",
                          target_release_tag="r2.1", apis=[_api("2.0.0", "alpha")])
        assert self._findings(tmp_path, plan, _cycle_one_history()) == []

        plan = _make_plan(target_release_type="public-release",
                          target_release_tag="r4.3", apis=[_api("1.0.0")])
        history = _release_history(
            _published_release("r4.1", release_type="pre-release-alpha",
                               apis=[_published_api("1.0.0-alpha.1")]),
            _published_release("r4.2", release_type="pre-release-rc",
                               apis=[_published_api("1.0.0-rc.1")]),
        )
        assert self._findings(tmp_path, plan, history) == []

    def test_legacy_public_release_without_metadata_is_not_a_line(self, tmp_path: Path):
        plan = _make_plan(target_release_type="public-release",
                          target_release_tag="r1.7", apis=[_api("1.3.0")])
        history = _release_history(
            _published_release("r1.6", metadata_available=False),
            lookup_status="partial",
        )
        assert self._findings(tmp_path, plan, history) == []

    def test_none_unrelated_pr_is_silent(self, tmp_path: Path):
        plan = _maintenance_plan("r1.9", "none")
        findings = self._findings(
            tmp_path, plan, _cycle_one_history(), release_plan_changed=False
        )
        assert findings == []

    def test_none_edited_plan_still_checks_tag(self, tmp_path: Path):
        plan = _maintenance_plan("r1.9", "none")
        findings = self._findings(tmp_path, plan, _cycle_one_history())
        assert len(findings) == 1
        assert "next tag of release cycle r1 is 'r1.7'" in findings[0]["message"]

    def test_pre_existing_condition_prefix(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, _maintenance_plan("r1.9"), _cycle_one_history(),
            release_plan_changed=False,
        )
        assert findings[0]["message"].startswith("Pre-existing release-plan condition:")

    # On maintenance/rX
    def _branch_history(self, *extra: dict) -> dict:
        return _cycle_one_history(
            _published_release("r2.1", apis=[_published_api("2.0.0")]),
            *extra,
            base_ref="maintenance/r1",
            maintenance_branches=["maintenance/r1"],
        )

    @pytest.mark.parametrize("release_type", ["maintenance-release", "pre-release-rc", "none"])
    def test_branch_allows_line_types(self, tmp_path: Path, release_type):
        plan = _maintenance_plan("r1.7", release_type)
        assert self._findings(tmp_path, plan, self._branch_history()) == []

    def test_branch_rejects_other_cycle(self, tmp_path: Path):
        plan = _make_plan(target_release_type="pre-release-alpha",
                          target_release_tag="r2.2", apis=[_api("2.1.0", "alpha")])
        findings = self._findings(tmp_path, plan, self._branch_history())

        assert len(findings) == 1
        assert "on branch 'maintenance/r1' target_release_tag must be in release cycle r1" in findings[0]["message"]

    def test_branch_rejects_public_release(self, tmp_path: Path):
        plan = _make_plan(target_release_type="public-release",
                          target_release_tag="r1.7", apis=[_api("1.2.1")])
        findings = self._findings(tmp_path, plan, self._branch_history())

        assert len(findings) == 1
        assert "'public-release'" in findings[0]["message"]

    def test_branch_tag_must_be_next(self, tmp_path: Path):
        findings = self._findings(tmp_path, _maintenance_plan("r1.8"), self._branch_history())

        assert len(findings) == 1
        assert "next tag of release cycle r1 is 'r1.7'" in findings[0]["message"]


class TestCheckReleasePlanMaintenanceApiVersions:
    def _findings(self, tmp_path: Path, plan_apis: list[dict], patched_apis: list[dict],
                  *later: dict, release_type: str = "maintenance-release", **ctx) -> list:
        _write_release_plan(
            tmp_path,
            _make_plan(target_release_type=release_type, target_release_tag="r1.7",
                       apis=plan_apis),
        )
        history = _release_history(
            _published_release("r1.6", apis=patched_apis),
            *later,
        )
        context = _context_with_release_history(history, **ctx)
        return check_release_plan_maintenance_api_versions(tmp_path, context)

    def test_absent_history_skips(self, tmp_path: Path):
        _write_release_plan(tmp_path, _maintenance_plan("r1.7"))
        assert check_release_plan_maintenance_api_versions(tmp_path, _make_context()) == []

    # Spec 4.1
    def test_patch_bump_ok(self, tmp_path: Path):
        assert self._findings(tmp_path, [_api("1.2.1")], [_published_api("1.2.0")]) == []

    # Spec 4.2
    def test_unchanged_api_next_to_bumped_api_ok(self, tmp_path: Path):
        findings = self._findings(
            tmp_path,
            [_api("1.2.0"), _api("0.3.1", name="qos-profiles")],
            [_published_api("1.2.0"), _published_api("0.3.0", name="qos-profiles")],
        )
        assert findings == []

    # Spec 4.3
    def test_minor_bump_errors(self, tmp_path: Path):
        findings = self._findings(tmp_path, [_api("1.3.0")], [_published_api("1.2.0")])

        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert findings[0]["engine_rule"] == "check-release-plan-maintenance-api-versions"
        assert findings[0]["api_name"] == "quality-on-demand"
        assert "minor version" in findings[0]["message"]
        assert "'1.2.0' in r1.6" in findings[0]["message"]
        # 107 F15: the branch, the patched release, and the alternative on main
        assert findings[0]["message"].startswith("on 'main', which maintains release cycle r1 from r1.6: API ")
        assert findings[0]["suggestion"] == (
            "Keep '1.2.0' or raise only its patch version for a maintenance release of r1.6; a new minor or "
            "major version of 'quality-on-demand' is released from main in a later release cycle (r2.y)."
        )

    def test_minor_bump_on_a_maintenance_branch_names_the_branch(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(target_release_type="maintenance-release", target_release_tag="r1.7", apis=[_api("0.2.0")]),
        )
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("0.1.2")]),
            base_ref="maintenance/r1", maintenance_branches=["maintenance/r1"],
        )
        findings = check_release_plan_maintenance_api_versions(tmp_path, _context_with_release_history(history))

        assert len(findings) == 1
        assert findings[0]["message"].startswith(
            "on 'maintenance/r1', which maintains release cycle r1 from r1.6: API 'quality-on-demand' changes "
            "'0.1.2' in r1.6 to '0.2.0'; for 0.y.z versions the minor version is breaking"
        )

    # Spec 4.4
    def test_minor_bump_ok_when_later_cycle_published_higher_major(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, [_api("1.3.0")], [_published_api("1.2.0")],
            _published_release("r2.1", apis=[_published_api("2.0.0")]),
        )
        assert findings == []

    def test_later_cycle_prerelease_of_higher_major_does_not_allow_minor(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, [_api("1.3.0")], [_published_api("1.2.0")],
            _published_release("r2.1", release_type="pre-release-alpha",
                               apis=[_published_api("2.0.0-alpha.1")]),
        )
        assert len(findings) == 1

    # Spec 4.5
    def test_initial_version_minor_bump_errors_despite_later_major(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, [_api("0.2.0")], [_published_api("0.1.0")],
            _published_release("r2.1", apis=[_published_api("1.0.0")]),
        )
        assert len(findings) == 1
        assert "0.y.z" in findings[0]["message"]

    # Spec 4.6
    @pytest.mark.parametrize("version", ["2.0.0", "1.1.9", "1.2.0-x"])
    def test_major_bump_or_decrease_errors(self, tmp_path: Path, version):
        findings = self._findings(tmp_path, [_api(version)], [_published_api("1.2.0")])
        if version == "1.2.0-x":
            assert findings == []  # not a semantic version: schema's concern
        else:
            assert len(findings) == 1

    # Spec 4.7
    @pytest.mark.parametrize(
        "plan_names, expected",
        [
            (["quality-on-demand", "qos-profiles", "qos-provisioning"], "added: qos-provisioning"),
            (["quality-on-demand"], "removed: qos-profiles"),
        ],
    )
    def test_api_set_must_equal_patched_release(self, tmp_path: Path, plan_names, expected):
        findings = self._findings(
            tmp_path,
            [_api("1.2.1" if n == "quality-on-demand" else "0.3.0", name=n) for n in plan_names],
            [_published_api("1.2.0"), _published_api("0.3.0", name="qos-profiles")],
        )
        assert len(findings) == 1
        assert "same APIs as r1.6" in findings[0]["message"]
        assert expected in findings[0]["message"]

    # Spec 4.8
    def test_rc_on_line_patch_bump_ok(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, [_api("1.2.1", "rc")], [_published_api("1.2.0")],
            release_type="pre-release-rc",
        )
        assert findings == []

    def test_rc_skipped_for_patched_release(self, tmp_path: Path):
        # Spec 1.9: an rc after r1.6 does not become the patched release.
        _write_release_plan(tmp_path, _make_plan(
            target_release_type="maintenance-release", target_release_tag="r1.8",
            apis=[_api("1.3.0")]))
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]),
            _published_release("r1.7", release_type="pre-release-rc",
                               apis=[_published_api("1.3.0-rc.1")]),
        )
        findings = check_release_plan_maintenance_api_versions(
            tmp_path, _context_with_release_history(history))
        assert len(findings) == 1
        assert "'1.2.0' in r1.6" in findings[0]["message"]

    def test_non_maintenance_plan_not_checked(self, tmp_path: Path):
        _write_release_plan(tmp_path, _make_plan(
            target_release_type="public-release", target_release_tag="r2.3",
            apis=[_api("3.0.0")]))
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]),
            _published_release("r2.2", release_type="pre-release-rc",
                               apis=[_published_api("2.0.0-rc.1")]),
        )
        assert check_release_plan_maintenance_api_versions(
            tmp_path, _context_with_release_history(history)) == []

    def test_unknown_patched_release_skips(self, tmp_path: Path):
        _write_release_plan(tmp_path, _maintenance_plan("r1.8", version="1.3.0"))
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]),
            _published_release("r1.7", metadata_available=False),
            lookup_status="partial",
        )
        assert check_release_plan_maintenance_api_versions(
            tmp_path, _context_with_release_history(history)) == []

    def test_none_unrelated_pr_is_silent(self, tmp_path: Path):
        findings = self._findings(
            tmp_path, [_api("1.3.0")], [_published_api("1.2.0")],
            release_type="none", release_plan_changed=False,
        )
        assert findings == []

    def test_published_target_is_left_to_p035(self, tmp_path: Path):
        _write_release_plan(tmp_path, _make_plan(
            target_release_type="public-release", target_release_tag="r1.6",
            apis=[_api("1.2.0")]))
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]))
        assert check_release_plan_maintenance_api_versions(
            tmp_path, _context_with_release_history(history)) == []


class TestCheckReleasePlanPublishedHistory:
    def test_no_release_plan(self, tmp_path: Path):
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )
        assert check_release_plan_published_history(tmp_path, context) == []

    def test_absent_history_skips(self, tmp_path: Path):
        _write_release_plan(tmp_path, _make_plan(target_release_tag="r4.3"))

        assert check_release_plan_published_history(tmp_path, _make_context()) == []

    def test_partial_history_tag_regression_still_errors_when_tags_available(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r4.2", metadata_available=False),
                _published_release("r4.3", metadata_available=False),
                lookup_status="partial",
            )
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "lower than latest published release tag 'r4.3'" in findings[0]["message"]

    def test_partial_history_missing_target_metadata_skips_tag_mismatch(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r4.2", metadata_available=False),
                lookup_status="partial",
            )
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_parked_after_publish_matching_latest_release_skips(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.1"), _published_release("r4.2"))
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_published_tag_with_changed_attribution_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                release_track="meta-release",
                meta_release="Sync26",
                target_release_tag="r4.2",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2")),
            release_plan_changed=True,
            base_release_track="independent",
            base_meta_release=None,
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert (
            findings[0]["message"]
            == "target_release_tag 'r4.2' is already published, so release_track "
            "and meta_release must not be changed for this release."
        )
        assert findings[0]["suggestion"] == (
            "Start a new release cycle in this repository. The inclusion of an "
            "already-published release, if approved, is handled by Release "
            "Management outside this repository's release-plan."
        )

    def test_parked_published_tag_with_unchanged_attribution_and_dependencies_skips(
        self, tmp_path: Path
    ):
        plan = _make_plan(
            release_track="independent",
            meta_release=None,
            target_release_tag="r4.2",
            target_release_type="none",
            apis=[
                {
                    "api_name": "quality-on-demand",
                    "target_api_status": "public",
                    "target_api_version": "1.0.0",
                }
            ],
        )
        plan["dependencies"] = {
            "commonalities_release": "r4.1",
            "identity_consent_management_release": "r3.1",
        }
        _write_release_plan(tmp_path, plan)
        context = _context_with_release_history(
            _release_history(
                _published_release(
                    "r4.2",
                    commonalities_release="r4.1",
                    icm_release="r3.1",
                )
            ),
            release_plan_changed=True,
            base_release_track="independent",
            base_meta_release="",
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_unpublished_tag_with_changed_attribution_starts_new_cycle(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                release_track="meta-release",
                meta_release="Sync26",
                target_release_tag="r4.3",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2")),
            release_plan_changed=True,
            base_release_track="independent",
            base_meta_release=None,
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_published_tag_with_dependency_drift_errors(self, tmp_path: Path):
        plan = _make_plan(
            target_release_tag="r4.2",
            target_release_type="public-release",
            apis=[
                {
                    "api_name": "quality-on-demand",
                    "target_api_status": "public",
                    "target_api_version": "1.0.0",
                }
            ],
        )
        plan["dependencies"] = {
            "commonalities_release": "r5.0",
            "identity_consent_management_release": "r4.0",
        }
        _write_release_plan(tmp_path, plan)
        context = _context_with_release_history(
            _release_history(
                _published_release(
                    "r4.2",
                    commonalities_release="r4.1",
                    icm_release="r3.1",
                )
            )
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert (
            findings[0]["message"]
            == "target_release_tag 'r4.2' is already published, so dependencies "
            "must not be changed for this release."
        )
        assert findings[0]["suggestion"] == (
            "Restore the dependency tags published with this release, or start "
            "a new release cycle with an unpublished target_release_tag."
        )

    def test_not_planning_new_release_keeps_published_plan_quiet(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="none",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.1"), _published_release("r4.2"))
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_existing_published_tag_with_changed_api_entries_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-published-history"
        assert "target_release_tag 'r4.2' is already published" in findings[0]["message"]

    def test_tag_regression_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"), _published_release("r4.3"))
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "lower than latest published release tag 'r4.3'" in findings[0]["message"]

    def test_cycle_opening_without_previous_cycle_errors(self, tmp_path: Path):
        _write_release_plan(tmp_path, _make_plan(target_release_tag="r4.1"))
        context = _context_with_release_history(
            _release_history(_published_release("r2.4"))
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "opens release cycle r4 without any published r3.y release" in findings[0]["message"]

    def test_null_tag_with_non_none_release_type_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag=None,
                target_release_type="public-release",
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "target_release_tag is required" in findings[0]["message"]

    def test_type_none_with_tag_is_allowed(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="none",
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_public_release_without_new_api_content_errors(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "cannot start a new release" in findings[0]["message"]

    def test_partial_history_missing_terminal_metadata_skips_no_new_content(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r4.2", metadata_available=False),
                lookup_status="partial",
            )
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_public_release_after_alpha_history_counts_as_new_content(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "qos-profiles",
                        "target_api_status": "public",
                        "target_api_version": "1.2.0",
                    },
                    {
                        "api_name": "qos-provisioning",
                        "target_api_status": "public",
                        "target_api_version": "0.4.0",
                    },
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.2.0",
                    },
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release(
                    "r3.2",
                    apis=[
                        {
                            "api_name": "qos-profiles",
                            "api_version": "1.1.0",
                        },
                        {
                            "api_name": "qos-provisioning",
                            "api_version": "0.3.0",
                        },
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.1.0",
                        },
                    ],
                ),
                _published_release(
                    "r4.1",
                    release_type="pre-release-alpha",
                    apis=[
                        {
                            "api_name": "qos-profiles",
                            "api_version": "1.2.0-alpha.1",
                        },
                        {
                            "api_name": "qos-provisioning",
                            "api_version": "0.4.0-alpha.1",
                        },
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.2.0-alpha.1",
                        },
                    ],
                ),
            )
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_pre_release_alpha_with_only_published_public_content_errors(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="pre-release-alpha",
                apis=[
                    {
                        "api_name": "qos-profiles",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    },
                    {
                        "api_name": "qos-provisioning",
                        "target_api_status": "public",
                        "target_api_version": "0.3.0",
                    },
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    },
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release(
                    "r3.2",
                    apis=[
                        {
                            "api_name": "qos-profiles",
                            "api_version": "1.1.0",
                        },
                        {
                            "api_name": "qos-provisioning",
                            "api_version": "0.3.0",
                        },
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.1.0",
                        },
                    ],
                )
            )
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "cannot start a new release" in findings[0]["message"]
        assert "Change at least one API entry in a valid way" in findings[0]["suggestion"]

    # Spec 3.8: on a maintenance line the message names the branch, the patched release and the alternative
    def test_no_new_content_on_a_maintenance_line_names_the_branch(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(target_release_type="maintenance-release", target_release_tag="r1.9",
                       apis=[_api("1.2.1")]),
        )
        history = _release_history(
            _published_release("r1.6", apis=[_published_api("1.2.0")]),
            _published_release("r1.8", release_type="maintenance-release", apis=[_published_api("1.2.1")]),
            _published_release("r2.1", apis=[_published_api("2.0.0")]),
            base_ref="maintenance/r1",
            maintenance_branches=["maintenance/r1"],
        )
        context = _context_with_release_history(history)

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["message"].startswith(
            "on 'maintenance/r1', which maintains release cycle r1 from r1.8, target_release_type "
            "'maintenance-release' cannot start a new release"
        )
        assert findings[0]["message"].endswith("(no new content).")
        assert findings[0]["suggestion"] == (
            "Raise the patch version of each API the release fixes, keeping the API list of r1.8; "
            "new content is released from main in a later release cycle (r2.y)."
        )

    def test_pre_release_rc_after_rc_history_counts_as_new_content(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="pre-release-rc",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "rc",
                        "target_api_version": "1.2.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release(
                    "r4.2",
                    release_type="pre-release-rc",
                    apis=[
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.2.0-rc.1",
                        }
                    ],
                )
            )
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_pre_existing_history_condition_prefixes_message(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2")),
            release_plan_changed=False,
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["message"].startswith(
            "Pre-existing release-plan condition:"
        )
        assert "dedicated release-plan PR" in findings[0]["message"]

    def test_none_unrelated_pr_silences_history_findings(self, tmp_path: Path):
        # Parked plan, PR did not touch release-plan.yaml: stay silent even
        # though target_release_tag r4.1 would regress against latest r4.3.
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.1",
                target_release_type="none",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"), _published_release("r4.3")),
            release_plan_changed=False,
        )

        assert check_release_plan_published_history(tmp_path, context) == []

    def test_none_changed_tag_regression_errors(self, tmp_path: Path):
        # Same parked plan, but the PR edits release-plan.yaml: a regressing tag
        # must not be merged regardless of target_release_type.
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.1",
                target_release_type="none",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"), _published_release("r4.3")),
            release_plan_changed=True,
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "lower than latest published release tag 'r4.3'" in findings[0]["message"]

    def test_none_changed_entries_differ_from_published_tag_errors(
        self, tmp_path: Path
    ):
        # Editing a none plan to disagree with the published tag is an error: the
        # plan must stay in a shape where flipping the release type is valid.
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="none",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.1.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2")),
            release_plan_changed=True,
        )

        findings = check_release_plan_published_history(tmp_path, context)

        assert len(findings) == 1
        assert "target_release_tag 'r4.2' is already published" in findings[0]["message"]


class TestCheckReleasePlanTerminalApiStatus:
    def test_matching_published_release_plan_has_no_history_findings(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        assert check_release_plan_published_history(tmp_path, context) == []
        assert check_release_plan_terminal_api_status(tmp_path, context) == []

    def test_none_unrelated_pr_still_locks_terminal_api_status(self, tmp_path: Path):
        # P-036 is a factual invariant about a published version: it fires
        # regardless of target_release_type and regardless of whether the PR
        # touched release-plan.yaml.
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.2",
                target_release_type="none",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "alpha",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2")),
            release_plan_changed=False,
        )

        findings = check_release_plan_terminal_api_status(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-terminal-api-status"
        assert "target_api_status must remain 'public'" in findings[0]["message"]

    def test_no_release_plan(self, tmp_path: Path):
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )
        assert check_release_plan_terminal_api_status(tmp_path, context) == []

    def test_absent_history_skips(self, tmp_path: Path):
        _write_release_plan(tmp_path, _make_plan(target_release_tag="r4.3"))

        assert check_release_plan_terminal_api_status(tmp_path, _make_context()) == []

    def test_partial_history_with_relevant_terminal_metadata_errors(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="pre-release-rc",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "rc",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r4.2"),
                _published_release("r4.3", metadata_available=False),
                lookup_status="partial",
            )
        )

        findings = check_release_plan_terminal_api_status(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-terminal-api-status"
        assert "target_api_status must remain 'public'" in findings[0]["message"]

    def test_partial_history_missing_terminal_metadata_skips_status_lock(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="pre-release-rc",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "rc",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(
                _published_release("r4.2", metadata_available=False),
                lookup_status="partial",
            )
        )

        assert check_release_plan_terminal_api_status(tmp_path, context) == []

    def test_terminal_published_version_with_different_status_errors(
        self, tmp_path: Path
    ):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="pre-release-rc",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "rc",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        findings = check_release_plan_terminal_api_status(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-terminal-api-status"
        assert findings[0]["api_name"] == "quality-on-demand"
        assert "API 'quality-on-demand' was already published as version 1.0.0" in (
            findings[0]["message"]
        )
        assert "target_api_status must remain 'public'" in findings[0]["message"]
        assert "Keep target_api_status aligned" in findings[0]["suggestion"]

    def test_matching_terminal_status_is_allowed(self, tmp_path: Path):
        _write_release_plan(
            tmp_path,
            _make_plan(
                target_release_tag="r4.3",
                target_release_type="public-release",
                apis=[
                    {
                        "api_name": "quality-on-demand",
                        "target_api_status": "public",
                        "target_api_version": "1.0.0",
                    }
                ],
            ),
        )
        context = _context_with_release_history(
            _release_history(_published_release("r4.2"))
        )

        assert check_release_plan_terminal_api_status(tmp_path, context) == []


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
# TestCheckReleasePlanActiveReleaseState (P-033)
# ---------------------------------------------------------------------------


def _context_with_active_release_state(
    *,
    state: str = "",
    snapshot_branch: str = "",
    release_issue_number: int | None = None,
    trigger_type: str = "pr",
    release_plan_changed: bool | None = True,
) -> ValidationContext:
    return dataclasses.replace(
        _make_context(),
        trigger_type=trigger_type,
        release_plan_changed=release_plan_changed,
        active_release_state=ActiveReleaseState(
            state=state,
            snapshot_branch=snapshot_branch,
            release_issue_number=release_issue_number,
        ),
    )


class TestCheckReleasePlanActiveReleaseState:
    def test_no_active_release_state(self, tmp_path: Path):
        context = _context_with_active_release_state()
        assert check_release_plan_active_release_state(tmp_path, context) == []

    def test_snapshot_branch_only_blocks(self, tmp_path: Path):
        context = _context_with_active_release_state(
            snapshot_branch="release-snapshot/r4.3-abc1234"
        )

        findings = check_release_plan_active_release_state(tmp_path, context)

        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-release-plan-active-release-state"
        assert findings[0]["level"] == "error"
        assert "release-snapshot/r4.3-abc1234" in findings[0]["message"]

    def test_active_state_only_blocks(self, tmp_path: Path):
        context = _context_with_active_release_state(state="snapshot-active")

        findings = check_release_plan_active_release_state(tmp_path, context)

        assert len(findings) == 1
        assert "snapshot-active" in findings[0]["message"]

    def test_release_issue_number_is_message_context_only(self, tmp_path: Path):
        context = _context_with_active_release_state(
            state="snapshot-active",
            release_issue_number=23,
        )

        findings = check_release_plan_active_release_state(tmp_path, context)

        assert len(findings) == 1
        assert "#23" in findings[0]["message"]
        assert "snapshot-active" in findings[0]["message"]

    def test_snapshot_branch_and_active_issue_state_block(self, tmp_path: Path):
        context = _context_with_active_release_state(
            state="draft-ready",
            snapshot_branch="release-snapshot/r4.3-abc1234",
            release_issue_number=23,
        )

        findings = check_release_plan_active_release_state(tmp_path, context)

        assert len(findings) == 1
        assert "release-snapshot/r4.3-abc1234" in findings[0]["message"]
        assert "#23" in findings[0]["message"]
        assert "draft-ready" in findings[0]["message"]

    def test_planned_state_does_not_block(self, tmp_path: Path):
        context = _context_with_active_release_state(
            state="planned",
            release_issue_number=23,
        )
        assert check_release_plan_active_release_state(tmp_path, context) == []

    def test_terminal_issue_state_does_not_block(self, tmp_path: Path):
        context = _context_with_active_release_state(
            state="published",
            release_issue_number=23,
        )
        assert check_release_plan_active_release_state(tmp_path, context) == []

    def test_non_pr_trigger_does_not_block(self, tmp_path: Path):
        context = _context_with_active_release_state(
            snapshot_branch="release-snapshot/r4.3-abc1234",
            trigger_type="dispatch",
        )
        assert check_release_plan_active_release_state(tmp_path, context) == []

    def test_release_plan_unchanged_does_not_block(self, tmp_path: Path):
        context = _context_with_active_release_state(
            snapshot_branch="release-snapshot/r4.3-abc1234",
            release_plan_changed=False,
        )
        assert check_release_plan_active_release_state(tmp_path, context) == []


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
