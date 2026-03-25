"""Unit tests for validation.engines.yamllint_adapter."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from validation.engines.yamllint_adapter import (
    ENGINE_NAME,
    YamllintResult,
    derive_api_name,
    map_severity,
    parse_parsable_line,
    parse_yamllint_output,
    run_yamllint,
    run_yamllint_engine,
)


# ---------------------------------------------------------------------------
# TestMapSeverity
# ---------------------------------------------------------------------------


class TestMapSeverity:
    def test_error(self):
        assert map_severity("error") == "error"

    def test_warning(self):
        assert map_severity("warning") == "warn"

    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            map_severity("info")


# ---------------------------------------------------------------------------
# TestDeriveApiName
# ---------------------------------------------------------------------------


class TestDeriveApiName:
    def test_standard_api_path(self):
        assert (
            derive_api_name("code/API_definitions/quality-on-demand.yaml")
            == "quality-on-demand"
        )

    def test_non_api_path(self):
        assert derive_api_name("release-plan.yaml") is None

    def test_empty_string(self):
        assert derive_api_name("") is None

    def test_nested_prefix(self):
        assert (
            derive_api_name("some/prefix/API_definitions/my-api.yaml")
            == "my-api"
        )


# ---------------------------------------------------------------------------
# TestParseParsableLine
# ---------------------------------------------------------------------------


class TestParseParsableLine:
    def test_error_with_rule(self):
        line = 'code/API_definitions/api.yaml:2:1: [error] duplication of key "key" in mapping (key-duplicates)'
        finding = parse_parsable_line(line)
        assert finding is not None
        assert finding["engine"] == "yamllint"
        assert finding["engine_rule"] == "key-duplicates"
        assert finding["level"] == "error"
        assert finding["message"] == 'duplication of key "key" in mapping'
        assert finding["path"] == "code/API_definitions/api.yaml"
        assert finding["line"] == 2
        assert finding["column"] == 1
        assert finding["api_name"] == "api"

    def test_warning_with_rule(self):
        line = "file.yaml:10:5: [warning] trailing spaces (trailing-spaces)"
        finding = parse_parsable_line(line)
        assert finding is not None
        assert finding["level"] == "warn"
        assert finding["engine_rule"] == "trailing-spaces"

    def test_no_rule_suffix(self):
        """Syntax errors may not have a rule name in parentheses."""
        line = "file.yaml:3:1: [error] syntax error: mapping values are not allowed here"
        finding = parse_parsable_line(line)
        assert finding is not None
        assert finding["engine_rule"] == "syntax-error"
        assert "mapping values" in finding["message"]

    def test_message_with_parentheses(self):
        """Rule name is always the last (...) group."""
        line = 'file.yaml:5:1: [error] wrong value (got "yes") (truthy)'
        finding = parse_parsable_line(line)
        assert finding is not None
        assert finding["engine_rule"] == "truthy"
        assert 'wrong value (got "yes")' in finding["message"]

    def test_invalid_line_returns_none(self):
        assert parse_parsable_line("not a yamllint line") is None

    def test_empty_line_returns_none(self):
        assert parse_parsable_line("") is None


# ---------------------------------------------------------------------------
# TestParseYamllintOutput
# ---------------------------------------------------------------------------


class TestParseYamllintOutput:
    def test_multiple_findings(self):
        raw = (
            "a.yaml:1:1: [error] dup key (key-duplicates)\n"
            "b.yaml:5:3: [warning] trailing spaces (trailing-spaces)\n"
        )
        findings = parse_yamllint_output(raw)
        assert len(findings) == 2
        assert findings[0]["level"] == "error"
        assert findings[1]["level"] == "warn"

    def test_empty_output(self):
        assert parse_yamllint_output("") == []

    def test_blank_lines_skipped(self):
        raw = "\na.yaml:1:1: [error] bad (truthy)\n\n"
        findings = parse_yamllint_output(raw)
        assert len(findings) == 1

    def test_mixed_levels(self):
        raw = (
            "f.yaml:1:1: [error] err (e1)\n"
            "f.yaml:2:1: [warning] warn (w1)\n"
            "f.yaml:3:1: [error] err2 (e2)\n"
        )
        findings = parse_yamllint_output(raw)
        levels = [f["level"] for f in findings]
        assert levels == ["error", "warn", "error"]

    def test_all_warnings(self):
        raw = (
            "f.yaml:1:1: [warning] w1 (r1)\n"
            "f.yaml:2:1: [warning] w2 (r2)\n"
        )
        findings = parse_yamllint_output(raw)
        assert all(f["level"] == "warn" for f in findings)


# ---------------------------------------------------------------------------
# TestRunYamllint
# ---------------------------------------------------------------------------


class TestRunYamllint:
    @patch("validation.engines.yamllint_adapter.subprocess.run")
    def test_exit_0_no_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        result = run_yamllint(tmp_path / ".yamllint.yaml", ["*.yaml"], cwd=tmp_path)
        assert result.success is True
        assert result.findings == []

    @patch("validation.engines.yamllint_adapter.subprocess.run")
    def test_exit_1_with_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="f.yaml:1:1: [error] dup (key-duplicates)\n",
            stderr="",
        )
        result = run_yamllint(tmp_path / ".yamllint.yaml", ["*.yaml"], cwd=tmp_path)
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0]["engine_rule"] == "key-duplicates"

    @patch("validation.engines.yamllint_adapter.subprocess.run")
    def test_runtime_error(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="invalid config",
        )
        result = run_yamllint(tmp_path / ".yamllint.yaml", ["*.yaml"], cwd=tmp_path)
        assert result.success is False
        assert "invalid config" in result.error_message

    @patch("validation.engines.yamllint_adapter.subprocess.run")
    def test_not_installed(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("python3")
        result = run_yamllint(tmp_path / ".yamllint.yaml", ["*.yaml"], cwd=tmp_path)
        assert result.success is False
        assert "not found" in result.error_message

    @patch("validation.engines.yamllint_adapter.subprocess.run")
    def test_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yamllint", timeout=120)
        result = run_yamllint(tmp_path / ".yamllint.yaml", ["*.yaml"], cwd=tmp_path)
        assert result.success is False
        assert "timed out" in result.error_message


# ---------------------------------------------------------------------------
# TestRunYamllintEngine
# ---------------------------------------------------------------------------


class TestRunYamllintEngine:
    @patch("validation.engines.yamllint_adapter.run_yamllint")
    def test_normal_execution(self, mock_run, tmp_path):
        findings = [{"engine": "yamllint", "engine_rule": "r1", "level": "warn",
                      "message": "m", "path": "f.yaml", "line": 1}]
        mock_run.return_value = YamllintResult(findings=findings, success=True)

        result = run_yamllint_engine(tmp_path, tmp_path / ".yamllint.yaml")
        assert result == findings

    @patch("validation.engines.yamllint_adapter.run_yamllint")
    def test_error_returns_error_finding(self, mock_run, tmp_path):
        mock_run.return_value = YamllintResult(
            findings=[], success=False, error_message="not found",
        )
        result = run_yamllint_engine(tmp_path, tmp_path / ".yamllint.yaml")
        assert len(result) == 1
        assert result[0]["level"] == "error"
        assert result[0]["engine_rule"] == "yamllint-execution-error"

    @patch("validation.engines.yamllint_adapter.run_yamllint")
    def test_default_patterns(self, mock_run, tmp_path):
        mock_run.return_value = YamllintResult(findings=[], success=True)
        run_yamllint_engine(tmp_path, tmp_path / ".yamllint.yaml")
        call_args = mock_run.call_args
        assert call_args[0][1] == ["code/API_definitions/*.yaml"]

    @patch("validation.engines.yamllint_adapter.run_yamllint")
    def test_custom_patterns(self, mock_run, tmp_path):
        mock_run.return_value = YamllintResult(findings=[], success=True)
        custom = ["custom/*.yaml"]
        run_yamllint_engine(tmp_path, tmp_path / ".yamllint.yaml", file_patterns=custom)
        call_args = mock_run.call_args
        assert call_args[0][1] == custom
