"""Unit tests for validation.engines.python_checks.version_checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.version_checks import (
    build_version_segment,
    check_feature_file_url_version,
    check_info_version_format,
    check_server_url_api_name,
    check_server_url_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    api_name: str = "quality-on-demand",
    branch_type: str = "main",
    version: str = "1.0.0",
) -> ValidationContext:
    api = ApiContext(
        api_name=api_name,
        target_api_version=version,
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


def _write_spec(
    tmp_path: Path,
    api_name: str,
    info_version: str,
    server_urls: list[str] | None = None,
) -> None:
    """Write a minimal OpenAPI spec file."""
    spec: dict = {
        "openapi": "3.0.3",
        "info": {"title": api_name, "version": info_version},
    }
    if server_urls is not None:
        spec["servers"] = [{"url": url} for url in server_urls]
    api_dir = tmp_path / "code" / "API_definitions"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / f"{api_name}.yaml").write_text(
        yaml.dump(spec, default_flow_style=False)
    )


# ---------------------------------------------------------------------------
# TestBuildVersionSegment
# ---------------------------------------------------------------------------


class TestBuildVersionSegment:
    def test_wip(self):
        assert build_version_segment("wip") == "vwip"

    def test_stable_major(self):
        assert build_version_segment("1.0.0") == "v1"

    def test_stable_major_higher(self):
        assert build_version_segment("2.1.0") == "v2"

    def test_initial_minor(self):
        assert build_version_segment("0.1.0") == "v0.1"

    def test_initial_higher_minor(self):
        assert build_version_segment("0.3.0") == "v0.3"

    def test_alpha_pre_release(self):
        assert build_version_segment("0.2.0-alpha.2") == "v0.2alpha2"

    def test_rc_pre_release_initial(self):
        assert build_version_segment("0.5.0-rc.1") == "v0.5rc1"

    def test_rc_pre_release_stable(self):
        assert build_version_segment("1.0.0-rc.1") == "v1rc1"

    def test_alpha_stable(self):
        assert build_version_segment("2.0.0-alpha.1") == "v2alpha1"

    def test_invalid_returns_none(self):
        assert build_version_segment("not-a-version") is None

    def test_empty_returns_none(self):
        assert build_version_segment("") is None


# ---------------------------------------------------------------------------
# TestCheckInfoVersionFormat
# ---------------------------------------------------------------------------


class TestCheckInfoVersionFormat:
    def test_wip_on_main_ok(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        ctx = _make_context("qod", branch_type="main")
        assert check_info_version_format(tmp_path, ctx) == []

    def test_semver_on_main_error(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "1.0.0")
        ctx = _make_context("qod", branch_type="main")
        findings = check_info_version_format(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "wip" in findings[0]["message"]

    def test_semver_on_release_ok(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "1.0.0")
        ctx = _make_context("qod", branch_type="release")
        assert check_info_version_format(tmp_path, ctx) == []

    def test_wip_on_release_error(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        ctx = _make_context("qod", branch_type="release")
        findings = check_info_version_format(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "must not be 'wip'" in findings[0]["message"]

    def test_invalid_version_on_release_error(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "not-semver")
        ctx = _make_context("qod", branch_type="release")
        findings = check_info_version_format(tmp_path, ctx)
        assert len(findings) == 1
        assert "not a valid semantic version" in findings[0]["message"]

    def test_wip_on_maintenance_error(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        ctx = _make_context("qod", branch_type="maintenance")
        findings = check_info_version_format(tmp_path, ctx)
        assert len(findings) == 1

    def test_feature_branch_no_constraint(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "anything-goes")
        ctx = _make_context("qod", branch_type="feature")
        assert check_info_version_format(tmp_path, ctx) == []

    def test_missing_spec_file(self, tmp_path: Path):
        """Missing spec file => empty (filename check reports this)."""
        ctx = _make_context("qod", branch_type="main")
        assert check_info_version_format(tmp_path, ctx) == []

    def test_missing_info_version(self, tmp_path: Path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "qod.yaml").write_text(
            yaml.dump({"openapi": "3.0.3", "info": {"title": "test"}})
        )
        ctx = _make_context("qod", branch_type="main")
        findings = check_info_version_format(tmp_path, ctx)
        assert len(findings) == 1
        assert "missing" in findings[0]["message"]

    def test_pre_release_on_release_ok(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "0.2.0-alpha.2")
        ctx = _make_context("qod", branch_type="release")
        assert check_info_version_format(tmp_path, ctx) == []


# ---------------------------------------------------------------------------
# TestCheckServerUrlVersion
# ---------------------------------------------------------------------------


class TestCheckServerUrlVersion:
    def test_matching_stable(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v1"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_matching_initial(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "0.3.0",
            server_urls=["{apiRoot}/qod/v0.3"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_matching_wip(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "wip",
            server_urls=["{apiRoot}/qod/vwip"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_matching_alpha(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "0.2.0-alpha.2",
            server_urls=["{apiRoot}/qod/v0.2alpha2"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_matching_rc(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0-rc.1",
            server_urls=["{apiRoot}/qod/v1rc1"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_mismatch(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v2"],
        )
        ctx = _make_context("qod")
        findings = check_server_url_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "v2" in findings[0]["message"]
        assert "v1" in findings[0]["message"]

    def test_no_version_in_url(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["https://example.com/qod"],
        )
        ctx = _make_context("qod")
        findings = check_server_url_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "no recognisable version" in findings[0]["message"]

    def test_no_servers(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "1.0.0")
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_multiple_servers_one_bad(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v1", "{apiRoot}/qod/v2"],
        )
        ctx = _make_context("qod")
        findings = check_server_url_version(tmp_path, ctx)
        assert len(findings) == 1  # Only the v2 mismatch

    def test_missing_spec(self, tmp_path: Path):
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_case_insensitive_match(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/V1"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []

    def test_trailing_slash(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v1/"],
        )
        ctx = _make_context("qod")
        assert check_server_url_version(tmp_path, ctx) == []


# ---------------------------------------------------------------------------
# TestCheckServerUrlApiName
# ---------------------------------------------------------------------------


class TestCheckServerUrlApiName:
    def test_matching(self, tmp_path: Path):
        _write_spec(
            tmp_path, "quality-on-demand", "1.0.0",
            server_urls=["{apiRoot}/quality-on-demand/v1"],
        )
        ctx = _make_context("quality-on-demand")
        assert check_server_url_api_name(tmp_path, ctx) == []

    def test_mismatch(self, tmp_path: Path):
        _write_spec(
            tmp_path, "quality-on-demand", "1.0.0",
            server_urls=["{apiRoot}/qod/v1"],
        )
        ctx = _make_context("quality-on-demand")
        findings = check_server_url_api_name(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["level"] == "error"
        assert "qod" in findings[0]["message"]
        assert "quality-on-demand" in findings[0]["message"]

    def test_no_api_name_segment(self, tmp_path: Path):
        """URL without recognisable api-name segment is silently skipped."""
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["https://example.com/v1"],
        )
        ctx = _make_context("qod")
        # No api-name segment to extract — version check handles this.
        assert check_server_url_api_name(tmp_path, ctx) == []

    def test_missing_spec(self, tmp_path: Path):
        ctx = _make_context("qod")
        assert check_server_url_api_name(tmp_path, ctx) == []

    def test_multiple_servers_all_matching(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v1", "https://sandbox.example.com/qod/v1"],
        )
        ctx = _make_context("qod")
        assert check_server_url_api_name(tmp_path, ctx) == []

    def test_multiple_servers_one_mismatch(self, tmp_path: Path):
        _write_spec(
            tmp_path, "qod", "1.0.0",
            server_urls=["{apiRoot}/qod/v1", "{apiRoot}/wrong-name/v1"],
        )
        ctx = _make_context("qod")
        findings = check_server_url_api_name(tmp_path, ctx)
        assert len(findings) == 1
        assert "wrong-name" in findings[0]["message"]


# ---------------------------------------------------------------------------
# TestCheckFeatureFileUrlVersion  (P-025)
# ---------------------------------------------------------------------------


def _write_feature(tmp_path: Path, name: str, body: str) -> Path:
    test_dir = tmp_path / "code" / "Test_definitions"
    test_dir.mkdir(parents=True, exist_ok=True)
    feature_path = test_dir / name
    feature_path.write_text(body)
    return feature_path


class TestCheckFeatureFileUrlVersion:
    """Tests for check_feature_file_url_version — P-025.

    On main, ``info.version == 'wip'`` -> expected ``vwip``.
    On release, ``info.version`` is a semver -> expected derived via
    :func:`build_version_segment` (e.g. ``1.0.0`` -> ``v1``).
    """

    def test_main_vwip_scenarios_pass(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  Scenario: Create session\n"
            "    When I send a POST to /quality-on-demand/vwip/sessions\n"
            "    Then the status code is 201\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_main_bare_wip_in_url_is_error(self, tmp_path: Path):
        """Bare /wip in a scenario step has no style-variation excuse."""
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  Scenario: Create session\n"
            "    When I send a POST to /quality-on-demand/wip/sessions\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        findings = check_feature_file_url_version(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-feature-file-url-version"
        assert findings[0]["level"] == "error"
        assert "/wip" in findings[0]["message"]
        assert "/vwip" in findings[0]["message"]
        assert findings[0]["line"] == 3

    def test_main_wrong_version_segment_is_error(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  When I send a POST to /quality-on-demand/v1/sessions\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        findings = check_feature_file_url_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "/v1" in findings[0]["message"]
        assert "/vwip" in findings[0]["message"]

    def test_release_matching_version_passes(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "1.0.0")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, v1.0.0\n"
            "  When I send a POST to /quality-on-demand/v1/sessions\n",
        )
        ctx = _make_context("qod", branch_type="release", version="1.0.0")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_release_wrong_version_is_error(self, tmp_path: Path):
        """/vwip survives into a release snapshot only if T2b failed —
        treat it as error relative to the release target version."""
        _write_spec(tmp_path, "qod", "1.0.0")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, v1.0.0\n"
            "  When I send a POST to /quality-on-demand/vwip/sessions\n",
        )
        ctx = _make_context("qod", branch_type="release", version="1.0.0")
        findings = check_feature_file_url_version(tmp_path, ctx)
        assert len(findings) == 1
        assert "/vwip" in findings[0]["message"]
        assert "/v1" in findings[0]["message"]

    def test_initial_version_minor_segment(self, tmp_path: Path):
        """info.version 0.3.0 -> v0.3 (initial-maturity mapping)."""
        _write_spec(tmp_path, "qod", "0.3.0")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, v0.3.0\n"
            "  When I send a POST to /quality-on-demand/v0.3/sessions\n",
        )
        ctx = _make_context("qod", branch_type="release", version="0.3.0")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_feature_without_url_steps(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  Scenario: plain prose only\n"
            "    Given an authenticated user\n"
            "    Then the service responds successfully\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_url_without_version_segment_skipped(self, tmp_path: Path):
        """A URL with no version/wip segment is silently ignored — scope
        is URL-version validation, not presence checking."""
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  When I send a GET to /static/index.html\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_multiple_lines_collect_all_findings(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  When I send a POST to /quality-on-demand/v1/sessions\n"
            "  And I send a GET to /quality-on-demand/wip/sessions/{id}\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        findings = check_feature_file_url_version(tmp_path, ctx)
        assert len(findings) == 2
        lines = {f["line"] for f in findings}
        assert lines == {2, 3}

    def test_spec_missing_returns_no_findings(self, tmp_path: Path):
        """No spec file => silent skip (filename/presence checks report)."""
        _write_feature(
            tmp_path, "qod.feature",
            "Feature: QoD, vwip\n"
            "  When I send a POST to /quality-on-demand/wip/sessions\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_test_dir_missing_returns_no_findings(self, tmp_path: Path):
        _write_spec(tmp_path, "qod", "wip")
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []

    def test_no_matching_feature_file(self, tmp_path: Path):
        """Feature file for a different API => skip (stem doesn't match)."""
        _write_spec(tmp_path, "qod", "wip")
        _write_feature(
            tmp_path, "other-api.feature",
            "Feature: Other, vwip\n"
            "  When I send a POST to /other-api/wip/resource\n",
        )
        ctx = _make_context("qod", branch_type="main", version="wip")
        assert check_feature_file_url_version(tmp_path, ctx) == []
