"""Unit tests for validation.output.diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from validation.context import ValidationContext
from validation.output.diagnostics import write_diagnostics
from validation.postfilter.engine import PostFilterResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="pr",
        profile="standard",
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        icm_release=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(),
        workflow_run_url="https://example.com/run/1",
        tooling_ref="abc1234",
    )


def _make_finding(
    level: str = "warn",
    message: str = "Something is wrong",
) -> dict:
    return {
        "engine": "spectral",
        "engine_rule": "some-rule",
        "level": level,
        "message": message,
        "path": "spec.yaml",
        "line": 10,
        "api_name": "quality-on-demand",
        "blocks": False,
    }


def _make_result(
    findings: list[dict] | None = None,
    result: str = "pass",
) -> PostFilterResult:
    return PostFilterResult(
        findings=findings or [],
        result=result,
        summary="Passed: no findings",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWriteDiagnostics:
    def test_creates_expected_files(self, tmp_path: Path):
        out = tmp_path / "output"
        paths = write_diagnostics(_make_result(), _make_context(), out)
        names = {p.name for p in paths}
        assert names == {"findings.json", "context.json", "summary.json"}

    def test_findings_json_content(self, tmp_path: Path):
        findings = [_make_finding(level="error"), _make_finding(level="warn")]
        out = tmp_path / "output"
        write_diagnostics(_make_result(findings), _make_context(), out)
        data = json.loads((out / "findings.json").read_text())
        assert len(data) == 2
        assert data[0]["level"] == "error"
        assert data[1]["level"] == "warn"

    def test_context_json_parseable(self, tmp_path: Path):
        out = tmp_path / "output"
        write_diagnostics(_make_result(), _make_context(), out)
        data = json.loads((out / "context.json").read_text())
        assert data["repository"] == "TestRepo"
        assert data["profile"] == "standard"

    def test_summary_json_content(self, tmp_path: Path):
        findings = [
            _make_finding(level="error"),
            _make_finding(level="warn"),
        ]
        out = tmp_path / "output"
        write_diagnostics(
            _make_result(findings, result="fail"),
            _make_context(),
            out,
        )
        data = json.loads((out / "summary.json").read_text())
        assert data["result"] == "fail"
        assert data["counts"]["errors"] == 1
        assert data["counts"]["warnings"] == 1
        assert data["counts"]["total"] == 2

    def test_engine_reports_written_when_provided(self, tmp_path: Path):
        out = tmp_path / "output"
        reports = {"spectral": {"raw": "data"}}
        paths = write_diagnostics(
            _make_result(), _make_context(), out, engine_reports=reports
        )
        names = {p.name for p in paths}
        assert "engine-reports.json" in names
        data = json.loads((out / "engine-reports.json").read_text())
        assert data["spectral"]["raw"] == "data"

    def test_engine_reports_omitted_when_none(self, tmp_path: Path):
        out = tmp_path / "output"
        paths = write_diagnostics(_make_result(), _make_context(), out)
        assert not (out / "engine-reports.json").exists()
        assert len(paths) == 3

    def test_empty_findings(self, tmp_path: Path):
        out = tmp_path / "output"
        write_diagnostics(_make_result([]), _make_context(), out)
        data = json.loads((out / "findings.json").read_text())
        assert data == []

    def test_creates_output_dir(self, tmp_path: Path):
        out = tmp_path / "nested" / "deep" / "output"
        assert not out.exists()
        write_diagnostics(_make_result(), _make_context(), out)
        assert out.exists()
        assert (out / "findings.json").exists()

    def test_returns_written_paths(self, tmp_path: Path):
        out = tmp_path / "output"
        paths = write_diagnostics(_make_result(), _make_context(), out)
        assert all(isinstance(p, Path) for p in paths)
        assert all(p.exists() for p in paths)
