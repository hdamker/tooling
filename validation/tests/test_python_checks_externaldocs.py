"""Unit tests for validation.engines.python_checks.externaldocs_checks (P-038/P-039)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.externaldocs_checks import (
    check_externaldocs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    repository: str = "camaraproject/ConsentManagement",
    api_name: str = "consent-management",
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
        repository=repository,
        branch_type="release",
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
    api_name: str = "consent-management",
    external_docs: Optional[object] = "__default__",
) -> None:
    spec: dict = {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }
    if external_docs != "__default__":
        if external_docs is not None:
            spec["externalDocs"] = external_docs
    else:
        spec["externalDocs"] = {
            "description": "Product documentation at CAMARA",
            "url": "https://github.com/camaraproject/ConsentManagement",
        }

    spec_dir = tmp_path / "code" / "API_definitions"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{api_name}.yaml").write_text(
        yaml.dump(spec, default_flow_style=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckExternaldocs:

    # --- Happy path ---

    def test_matching_url_and_description_ok(self, tmp_path: Path):
        _write_spec(tmp_path)
        ctx = _make_context()
        assert check_externaldocs(tmp_path, ctx) == []

    # --- externalDocs missing entirely ---

    def test_missing_externaldocs_single_p038_finding(self, tmp_path: Path):
        _write_spec(tmp_path, external_docs=None)
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"
        assert findings[0]["level"] == "warn"
        assert "missing" in findings[0]["message"]

    def test_externaldocs_not_a_mapping_treated_as_missing(self, tmp_path: Path):
        _write_spec(tmp_path, external_docs="not-a-mapping")
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"

    # --- url mismatches (P-038) ---

    def test_source_case_stale_repo_reference(self, tmp_path: Path):
        """ConsentManagement r1.1 rc: url left pointing at sibling ConsentInfo."""
        _write_spec(
            tmp_path,
            external_docs={
                "description": "Product documentation at CAMARA",
                "url": "https://github.com/camaraproject/ConsentInfo",
            },
        )
        ctx = _make_context(repository="camaraproject/ConsentManagement")
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"
        assert findings[0]["level"] == "warn"
        assert "ConsentInfo" in findings[0]["message"]

    def test_url_key_missing_within_present_object(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={"description": "Product documentation at CAMARA"},
        )
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"
        assert "is missing" in findings[0]["message"]

    def test_trailing_slash_is_not_tolerated(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={
                "description": "Product documentation at CAMARA",
                "url": "https://github.com/camaraproject/ConsentManagement/",
            },
        )
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"

    def test_fork_repository_compares_against_camaraproject_org(self, tmp_path: Path):
        """context.repository is <owner>/<repo> during fork validation; the
        expected url always targets the canonical camaraproject org."""
        _write_spec(tmp_path)
        ctx = _make_context(repository="hdamker/ConsentManagement")
        assert check_externaldocs(tmp_path, ctx) == []

    def test_fork_repository_wrong_url_still_flagged(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={
                "description": "Product documentation at CAMARA",
                "url": "https://github.com/hdamker/ConsentManagement",
            },
        )
        ctx = _make_context(repository="hdamker/ConsentManagement")
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-repository"

    # --- description mismatches (P-039) ---

    def test_description_wrong_wording(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={
                "description": "Project documentation at Camara",
                "url": "https://github.com/camaraproject/ConsentManagement",
            },
        )
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-description"
        assert findings[0]["level"] == "hint"

    def test_description_key_missing_within_present_object(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={
                "url": "https://github.com/camaraproject/ConsentManagement"
            },
        )
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "check-externaldocs-description"
        assert "is missing" in findings[0]["message"]

    # --- both wrong: two distinct findings ---

    def test_both_url_and_description_wrong(self, tmp_path: Path):
        _write_spec(
            tmp_path,
            external_docs={
                "description": "Project documentation at Camara",
                "url": "https://github.com/camaraproject/WrongRepo",
            },
        )
        ctx = _make_context()
        findings = check_externaldocs(tmp_path, ctx)
        engine_rules = {f["engine_rule"] for f in findings}
        assert engine_rules == {
            "check-externaldocs-repository",
            "check-externaldocs-description",
        }
        levels = {f["engine_rule"]: f["level"] for f in findings}
        assert levels["check-externaldocs-repository"] == "warn"
        assert levels["check-externaldocs-description"] == "hint"

    # --- DeviceStatus-style self-reference (not a false positive) ---

    def test_repo_hosting_multiple_apis_self_references_repo_not_filename(
        self, tmp_path: Path
    ):
        _write_spec(
            tmp_path,
            api_name="device-reachability-status",
            external_docs={
                "description": "Product documentation at CAMARA",
                "url": "https://github.com/camaraproject/DeviceStatus",
            },
        )
        ctx = _make_context(
            repository="camaraproject/DeviceStatus",
            api_name="device-reachability-status",
        )
        assert check_externaldocs(tmp_path, ctx) == []

    # --- edge cases ---

    def test_missing_spec_file(self, tmp_path: Path):
        ctx = _make_context()
        assert check_externaldocs(tmp_path, ctx) == []
