"""Unit tests for validation.engines.spectral_adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from validation.engines.spectral_adapter import (
    DEFAULT_RULESET,
    ENGINE_NAME,
    SpectralResult,
    derive_api_name,
    map_severity,
    normalize_finding,
    parse_spectral_output,
    run_spectral,
    run_spectral_engine,
    select_ruleset_path,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A typical Spectral JSON finding (one element of the --format json array).
SAMPLE_SPECTRAL_FINDING = {
    "code": "camara-parameter-casing-convention",
    "path": ["paths", "/qualityOnDemand", "post"],
    "message": "qualityOnDemand is not kebab-case",
    "severity": 0,
    "source": "code/API_definitions/quality-on-demand.yaml",
    "range": {
        "start": {"line": 46, "character": 4},
        "end": {"line": 46, "character": 30},
    },
}

SAMPLE_SPECTRAL_WARN = {
    "code": "camara-path-param-id",
    "path": ["paths", "/sessions/{id}", "get", "parameters", "0"],
    "message": "Use 'resource_id' instead of just 'id'",
    "severity": 1,
    "source": "code/API_definitions/qos-booking.yaml",
    "range": {
        "start": {"line": 120, "character": 8},
        "end": {"line": 120, "character": 20},
    },
}

SAMPLE_SPECTRAL_INFO = {
    "code": "camara-operationid-casing-convention",
    "path": ["paths", "/sessions", "post", "operationId"],
    "message": "Operation Id must be in Camel case",
    "severity": 2,
    "source": "code/API_definitions/quality-on-demand.yaml",
    "range": {
        "start": {"line": 50, "character": 18},
        "end": {"line": 50, "character": 40},
    },
}


# ---------------------------------------------------------------------------
# TestMapSeverity
# ---------------------------------------------------------------------------


class TestMapSeverity:
    def test_error(self):
        assert map_severity(0) == "error"

    def test_warn(self):
        assert map_severity(1) == "warn"

    def test_info_maps_to_hint(self):
        assert map_severity(2) == "hint"

    def test_hint_maps_to_hint(self):
        assert map_severity(3) == "hint"

    def test_unknown_severity_raises(self):
        with pytest.raises(KeyError):
            map_severity(99)


# ---------------------------------------------------------------------------
# TestDeriveApiName
# ---------------------------------------------------------------------------


class TestDeriveApiName:
    def test_standard_api_path(self):
        assert (
            derive_api_name("code/API_definitions/quality-on-demand.yaml")
            == "quality-on-demand"
        )

    def test_another_api(self):
        assert (
            derive_api_name("code/API_definitions/qos-booking.yaml")
            == "qos-booking"
        )

    def test_test_definitions_returns_none(self):
        assert derive_api_name("code/Test_definitions/foo.feature") is None

    def test_repo_level_file_returns_none(self):
        assert derive_api_name("release-plan.yaml") is None

    def test_empty_string_returns_none(self):
        assert derive_api_name("") is None

    def test_nested_api_definitions(self):
        """Handles unusual nesting (takes first file after API_definitions)."""
        assert (
            derive_api_name("some/prefix/API_definitions/my-api.yaml")
            == "my-api"
        )


# ---------------------------------------------------------------------------
# TestSelectRulesetPath
# ---------------------------------------------------------------------------


class TestSelectRulesetPath:
    def test_r4_release_selects_r4_ruleset(self, tmp_path):
        (tmp_path / ".spectral-r4.yaml").touch()
        result = select_ruleset_path("r4.1", tmp_path)
        assert result.name == ".spectral-r4.yaml"

    def test_r3_release_selects_r3_ruleset(self, tmp_path):
        (tmp_path / ".spectral-r3.4.yaml").touch()
        result = select_ruleset_path("r3.4", tmp_path)
        assert result.name == ".spectral-r3.4.yaml"

    def test_none_defaults_to_latest(self, tmp_path):
        (tmp_path / ".spectral-r4.yaml").touch()
        result = select_ruleset_path(None, tmp_path)
        assert result.name == ".spectral-r4.yaml"

    def test_unrecognised_version_defaults_to_latest(self, tmp_path):
        (tmp_path / ".spectral-r4.yaml").touch()
        result = select_ruleset_path("r99.0", tmp_path)
        assert result.name == ".spectral-r4.yaml"

    def test_version_specific_missing_falls_back(self, tmp_path):
        (tmp_path / ".spectral.yaml").touch()
        # r4 version-specific not present — fall back to default.
        result = select_ruleset_path("r4.1", tmp_path)
        assert result.name == ".spectral.yaml"

    def test_all_missing_returns_fallback_path(self, tmp_path):
        """Even if no ruleset file exists, returns the fallback path."""
        result = select_ruleset_path("r4.1", tmp_path)
        assert result.name == DEFAULT_RULESET


# ---------------------------------------------------------------------------
# TestNormalizeFinding
# ---------------------------------------------------------------------------


class TestNormalizeFinding:
    def test_standard_finding(self):
        finding = normalize_finding(SAMPLE_SPECTRAL_FINDING)
        assert finding["engine"] == "spectral"
        assert finding["engine_rule"] == "camara-parameter-casing-convention"
        assert finding["level"] == "error"
        assert finding["message"] == "qualityOnDemand is not kebab-case"
        assert finding["path"] == "code/API_definitions/quality-on-demand.yaml"
        assert finding["line"] == 47  # 0-indexed 46 -> 1-indexed 47
        assert finding["column"] == 5  # 0-indexed 4 -> 1-indexed 5
        assert finding["api_name"] == "quality-on-demand"

    def test_warn_severity(self):
        finding = normalize_finding(SAMPLE_SPECTRAL_WARN)
        assert finding["level"] == "warn"
        assert finding["api_name"] == "qos-booking"

    def test_info_severity_maps_to_hint(self):
        finding = normalize_finding(SAMPLE_SPECTRAL_INFO)
        assert finding["level"] == "hint"

    def test_missing_character_omits_column(self):
        raw = {
            "code": "some-rule",
            "message": "msg",
            "severity": 1,
            "source": "code/API_definitions/api.yaml",
            "range": {"start": {"line": 10}},
        }
        finding = normalize_finding(raw)
        assert finding["line"] == 11
        assert "column" not in finding

    def test_rule_id_and_hint_not_set(self):
        """Adapter does not assign rule_id or hint — post-filter does."""
        finding = normalize_finding(SAMPLE_SPECTRAL_FINDING)
        assert "rule_id" not in finding
        assert "hint" not in finding


# ---------------------------------------------------------------------------
# TestParseSpectralOutput
# ---------------------------------------------------------------------------


class TestParseSpectralOutput:
    def test_valid_json_array(self):
        raw = json.dumps([SAMPLE_SPECTRAL_FINDING, SAMPLE_SPECTRAL_WARN])
        findings = parse_spectral_output(raw)
        assert len(findings) == 2
        assert findings[0]["engine_rule"] == "camara-parameter-casing-convention"
        assert findings[1]["engine_rule"] == "camara-path-param-id"

    def test_empty_array(self):
        assert parse_spectral_output("[]") == []

    def test_empty_string(self):
        assert parse_spectral_output("") == []

    def test_whitespace_only(self):
        assert parse_spectral_output("   \n  ") == []

    def test_json_with_trailing_diagnostic(self):
        """Spectral appends diagnostic text after JSON when not using --quiet."""
        findings = parse_spectral_output(
            "[]No results with a severity of 'error' found!"
        )
        assert findings == []

    def test_invalid_json_returns_empty(self):
        findings = parse_spectral_output("not json at all")
        assert findings == []

    def test_json_object_instead_of_array(self):
        findings = parse_spectral_output('{"error": "oops"}')
        assert findings == []

    def test_mixed_severities(self):
        raw = json.dumps([
            SAMPLE_SPECTRAL_FINDING,  # error
            SAMPLE_SPECTRAL_WARN,     # warn
            SAMPLE_SPECTRAL_INFO,     # info -> hint
        ])
        findings = parse_spectral_output(raw)
        levels = [f["level"] for f in findings]
        assert levels == ["error", "warn", "hint"]


# ---------------------------------------------------------------------------
# TestRunSpectral
# ---------------------------------------------------------------------------


class TestRunSpectral:
    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_0_no_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert result.findings == []
        assert result.error_message == ""

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_1_with_findings(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=json.dumps([SAMPLE_SPECTRAL_FINDING]),
            stderr="",
        )
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0]["engine_rule"] == "camara-parameter-casing-convention"

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_2_runtime_error(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="Error: invalid ruleset",
        )
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is False
        assert "invalid ruleset" in result.error_message

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_spectral_not_installed(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("spectral")
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is False
        assert "not found" in result.error_message

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_spectral_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="spectral", timeout=300)
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is False
        assert "timed out" in result.error_message

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_command_includes_ruleset_and_patterns(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        ruleset = tmp_path / ".spectral-r4.yaml"
        run_spectral(ruleset, ["code/API_definitions/*.yaml"], cwd=tmp_path)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--ruleset" in cmd
        assert "--quiet" in cmd
        assert str(ruleset) in cmd
        assert "code/API_definitions/*.yaml" in cmd
        assert call_args[1]["cwd"] == str(tmp_path)


# ---------------------------------------------------------------------------
# TestRunSpectralEngine
# ---------------------------------------------------------------------------


class TestRunSpectralEngine:
    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_normal_execution(self, mock_run, tmp_path):
        findings = [{"engine": "spectral", "engine_rule": "r1", "level": "warn",
                      "message": "m", "path": "f.yaml", "line": 1}]
        mock_run.return_value = SpectralResult(findings=findings, success=True)
        (tmp_path / ".spectral.yaml").touch()

        result = run_spectral_engine(tmp_path, tmp_path, commonalities_release="r4.1")
        assert result == findings

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_spectral_error_returns_error_finding(self, mock_run, tmp_path):
        mock_run.return_value = SpectralResult(
            findings=[], success=False, error_message="CLI not found",
        )
        (tmp_path / ".spectral.yaml").touch()

        result = run_spectral_engine(tmp_path, tmp_path)
        assert len(result) == 1
        assert result[0]["level"] == "error"
        assert result[0]["engine_rule"] == "spectral-execution-error"
        assert "CLI not found" in result[0]["message"]

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_default_spec_patterns(self, mock_run, tmp_path):
        mock_run.return_value = SpectralResult(findings=[], success=True)
        (tmp_path / ".spectral.yaml").touch()

        run_spectral_engine(tmp_path, tmp_path)
        call_args = mock_run.call_args
        assert call_args[0][1] == ["code/API_definitions/*.yaml"]

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_custom_spec_patterns(self, mock_run, tmp_path):
        mock_run.return_value = SpectralResult(findings=[], success=True)
        (tmp_path / ".spectral.yaml").touch()

        custom = ["bundled/*.yaml"]
        run_spectral_engine(tmp_path, tmp_path, spec_patterns=custom)
        call_args = mock_run.call_args
        assert call_args[0][1] == custom

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_ruleset_selection_uses_commonalities(self, mock_run, tmp_path):
        """Verifies that the correct ruleset is selected and passed."""
        mock_run.return_value = SpectralResult(findings=[], success=True)
        r4 = tmp_path / ".spectral-r4.yaml"
        r4.touch()

        run_spectral_engine(tmp_path, tmp_path, commonalities_release="r4.2")
        call_args = mock_run.call_args
        assert call_args[0][0] == r4
