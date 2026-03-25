"""Unit tests for validation.engines.gherkin_adapter."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from validation.engines.gherkin_adapter import (
    DEFAULT_LEVEL,
    ENGINE_NAME,
    GherkinResult,
    derive_api_name,
    normalize_file_errors,
    parse_gherkin_output,
    run_gherkin_engine,
    run_gherkin_lint,
)


# ---------------------------------------------------------------------------
# Fixtures — sample gherkin-lint JSON entries
# ---------------------------------------------------------------------------

SAMPLE_FILE_ENTRY = {
    "filePath": "/repo/code/Test_definitions/quality-on-demand.feature",
    "errors": [
        {"message": "Missing Feature name", "rule": "no-unnamed-features", "line": 1},
        {"message": "Missing Scenario name", "rule": "no-unnamed-scenarios", "line": 5},
    ],
}

SAMPLE_CLEAN_ENTRY = {
    "filePath": "/repo/code/Test_definitions/clean.feature",
    "errors": [],
}


# ---------------------------------------------------------------------------
# TestDeriveApiName
# ---------------------------------------------------------------------------


class TestDeriveApiName:
    def test_standard_test_path(self):
        assert (
            derive_api_name("code/Test_definitions/quality-on-demand.feature")
            == "quality-on-demand"
        )

    def test_non_test_path(self):
        assert derive_api_name("code/API_definitions/api.yaml") is None

    def test_empty_string(self):
        assert derive_api_name("") is None

    def test_nested_prefix(self):
        assert (
            derive_api_name("some/prefix/Test_definitions/my-api.feature")
            == "my-api"
        )


# ---------------------------------------------------------------------------
# TestNormalizeFileErrors
# ---------------------------------------------------------------------------


class TestNormalizeFileErrors:
    def test_standard_errors(self):
        findings = normalize_file_errors(SAMPLE_FILE_ENTRY, "/repo")
        assert len(findings) == 2
        assert findings[0]["engine"] == "gherkin"
        assert findings[0]["engine_rule"] == "no-unnamed-features"
        assert findings[0]["level"] == DEFAULT_LEVEL
        assert findings[0]["message"] == "Missing Feature name"
        assert findings[0]["path"] == "code/Test_definitions/quality-on-demand.feature"
        assert findings[0]["line"] == 1
        assert findings[0]["api_name"] == "quality-on-demand"

    def test_empty_errors_list(self):
        findings = normalize_file_errors(SAMPLE_CLEAN_ENTRY, "/repo")
        assert findings == []

    def test_path_relativization(self):
        entry = {
            "filePath": "/workspace/project/code/Test_definitions/api.feature",
            "errors": [{"message": "m", "rule": "r", "line": 1}],
        }
        findings = normalize_file_errors(entry, "/workspace/project")
        assert findings[0]["path"] == "code/Test_definitions/api.feature"

    def test_missing_fields_use_defaults(self):
        entry = {
            "filePath": "/repo/test.feature",
            "errors": [{}],
        }
        findings = normalize_file_errors(entry, "/repo")
        assert len(findings) == 1
        assert findings[0]["engine_rule"] == "unknown"
        assert findings[0]["message"] == ""
        assert findings[0]["line"] == 1


# ---------------------------------------------------------------------------
# TestParseGherkinOutput
# ---------------------------------------------------------------------------


class TestParseGherkinOutput:
    def test_valid_json_with_errors(self):
        raw = json.dumps([SAMPLE_FILE_ENTRY])
        findings = parse_gherkin_output(raw, "/repo")
        assert len(findings) == 2
        assert findings[0]["engine_rule"] == "no-unnamed-features"

    def test_empty_array(self):
        assert parse_gherkin_output("[]", "/repo") == []

    def test_file_with_no_errors_skipped(self):
        raw = json.dumps([SAMPLE_CLEAN_ENTRY])
        findings = parse_gherkin_output(raw, "/repo")
        assert findings == []

    def test_invalid_json_returns_empty(self):
        assert parse_gherkin_output("not json", "/repo") == []

    def test_empty_string(self):
        assert parse_gherkin_output("", "/repo") == []

    def test_multiple_files(self):
        raw = json.dumps([SAMPLE_FILE_ENTRY, SAMPLE_CLEAN_ENTRY, SAMPLE_FILE_ENTRY])
        findings = parse_gherkin_output(raw, "/repo")
        # Two files with 2 errors each = 4 findings.
        assert len(findings) == 4

    def test_json_object_instead_of_array(self):
        findings = parse_gherkin_output('{"error": "oops"}', "/repo")
        assert findings == []


# ---------------------------------------------------------------------------
# TestRunGherkinLint
# ---------------------------------------------------------------------------


class TestRunGherkinLint:
    @patch("validation.engines.gherkin_adapter.subprocess.run")
    def test_exit_0_no_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        result = run_gherkin_lint(
            tmp_path / ".gherkin-lintrc", ["*.feature"], cwd=tmp_path,
        )
        assert result.success is True
        assert result.findings == []

    @patch("validation.engines.gherkin_adapter.subprocess.run")
    def test_exit_1_with_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=json.dumps([{
                "filePath": str(tmp_path / "code/Test_definitions/api.feature"),
                "errors": [{"message": "m", "rule": "r", "line": 1}],
            }]),
            stderr="",
        )
        result = run_gherkin_lint(
            tmp_path / ".gherkin-lintrc", ["*.feature"], cwd=tmp_path,
        )
        assert result.success is True
        assert len(result.findings) == 1

    @patch("validation.engines.gherkin_adapter.subprocess.run")
    def test_runtime_error(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="config not found",
        )
        result = run_gherkin_lint(
            tmp_path / ".gherkin-lintrc", ["*.feature"], cwd=tmp_path,
        )
        assert result.success is False
        assert "config not found" in result.error_message

    @patch("validation.engines.gherkin_adapter.subprocess.run")
    def test_npx_not_found(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("npx")
        result = run_gherkin_lint(
            tmp_path / ".gherkin-lintrc", ["*.feature"], cwd=tmp_path,
        )
        assert result.success is False
        assert "not found" in result.error_message

    @patch("validation.engines.gherkin_adapter.subprocess.run")
    def test_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="npx", timeout=120)
        result = run_gherkin_lint(
            tmp_path / ".gherkin-lintrc", ["*.feature"], cwd=tmp_path,
        )
        assert result.success is False
        assert "timed out" in result.error_message


# ---------------------------------------------------------------------------
# TestRunGherkinEngine
# ---------------------------------------------------------------------------


class TestRunGherkinEngine:
    @patch("validation.engines.gherkin_adapter.run_gherkin_lint")
    def test_normal_execution(self, mock_run, tmp_path):
        findings = [{"engine": "gherkin", "engine_rule": "r1", "level": "warn",
                      "message": "m", "path": "f.feature", "line": 1}]
        mock_run.return_value = GherkinResult(findings=findings, success=True)

        result = run_gherkin_engine(tmp_path, tmp_path / ".gherkin-lintrc")
        assert result == findings

    @patch("validation.engines.gherkin_adapter.run_gherkin_lint")
    def test_error_returns_error_finding(self, mock_run, tmp_path):
        mock_run.return_value = GherkinResult(
            findings=[], success=False, error_message="npx missing",
        )
        result = run_gherkin_engine(tmp_path, tmp_path / ".gherkin-lintrc")
        assert len(result) == 1
        assert result[0]["level"] == "error"
        assert result[0]["engine_rule"] == "gherkin-execution-error"

    @patch("validation.engines.gherkin_adapter.run_gherkin_lint")
    def test_default_patterns(self, mock_run, tmp_path):
        mock_run.return_value = GherkinResult(findings=[], success=True)
        run_gherkin_engine(tmp_path, tmp_path / ".gherkin-lintrc")
        call_args = mock_run.call_args
        assert call_args[0][1] == ["code/Test_definitions/**/*.feature"]

    @patch("validation.engines.gherkin_adapter.run_gherkin_lint")
    def test_custom_patterns(self, mock_run, tmp_path):
        mock_run.return_value = GherkinResult(findings=[], success=True)
        custom = ["tests/*.feature"]
        run_gherkin_engine(tmp_path, tmp_path / ".gherkin-lintrc", file_patterns=custom)
        call_args = mock_run.call_args
        assert call_args[0][1] == custom
