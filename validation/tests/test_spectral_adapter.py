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
    _deduplicate_findings,
    _normalize_path,
    _resolve_spec_files,
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
    "code": "camara-path-casing-convention",
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
# TestNormalizePath
# ---------------------------------------------------------------------------


class TestNormalizePath:
    def test_absolute_path_stripped(self):
        source = "/home/runner/work/Repo/Repo/code/API_definitions/api.yaml"
        result = _normalize_path(source, "/home/runner/work/Repo/Repo")
        assert result == "code/API_definitions/api.yaml"

    def test_absolute_path_with_trailing_slash(self):
        source = "/home/runner/work/Repo/Repo/code/API_definitions/api.yaml"
        result = _normalize_path(source, "/home/runner/work/Repo/Repo/")
        assert result == "code/API_definitions/api.yaml"

    def test_already_relative_unchanged(self):
        source = "code/API_definitions/api.yaml"
        result = _normalize_path(source, "/home/runner/work/Repo/Repo")
        assert result == "code/API_definitions/api.yaml"

    def test_no_repo_root_unchanged(self):
        source = "/absolute/path/to/file.yaml"
        assert _normalize_path(source, None) == source

    def test_empty_source(self):
        assert _normalize_path("", "/some/root") == ""

    def test_empty_repo_root(self):
        source = "/absolute/path/to/file.yaml"
        assert _normalize_path(source, "") == source

    def test_partial_prefix_not_stripped(self):
        """A path that starts with a substring of repo_root is not stripped."""
        source = "/home/runner/work/RepoExtra/code/api.yaml"
        result = _normalize_path(source, "/home/runner/work/Repo")
        assert result == source


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

    def test_none_defaults_to_oldest(self, tmp_path):
        """No release-plan.yaml → conservative default (r3.4)."""
        (tmp_path / ".spectral-r3.4.yaml").touch()
        result = select_ruleset_path(None, tmp_path)
        assert result.name == ".spectral-r3.4.yaml"

    def test_unrecognised_version_defaults_to_latest(self, tmp_path):
        """Unknown version (likely newer) → latest available (r4)."""
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
        assert finding["engine_rule"] == "camara-path-casing-convention"
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

    def test_schema_path_dot_joined(self):
        """Spectral's JSONPath array is dot-joined into finding['schema_path']."""
        finding = normalize_finding(SAMPLE_SPECTRAL_FINDING)
        # raw path is ["paths", "/qualityOnDemand", "post"]
        assert finding["schema_path"] == "paths./qualityOnDemand.post"

    def test_schema_path_mixed_string_and_int_segments(self):
        """JSONPath segments can include array indices — cast to str."""
        raw = {
            **SAMPLE_SPECTRAL_FINDING,
            "path": ["components", "schemas", "Foo", "allOf", 0, "properties", "bar"],
        }
        finding = normalize_finding(raw)
        assert finding["schema_path"] == "components.schemas.Foo.allOf.0.properties.bar"

    def test_schema_path_none_when_empty(self):
        """An empty JSONPath list yields schema_path=None."""
        raw = {**SAMPLE_SPECTRAL_FINDING, "path": []}
        finding = normalize_finding(raw)
        assert finding["schema_path"] is None

    def test_schema_path_none_when_missing(self):
        raw = {
            "code": "some-rule",
            "message": "msg",
            "severity": 1,
            "source": "code/API_definitions/api.yaml",
            "range": {"start": {"line": 0, "character": 0}},
        }
        finding = normalize_finding(raw)
        assert finding["schema_path"] is None

    def test_absolute_path_normalised_with_repo_root(self):
        raw = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": "/home/runner/work/R/R/code/API_definitions/quality-on-demand.yaml",
        }
        finding = normalize_finding(raw, repo_root="/home/runner/work/R/R")
        assert finding["path"] == "code/API_definitions/quality-on-demand.yaml"
        assert finding["api_name"] == "quality-on-demand"

    def test_relative_path_unchanged_with_repo_root(self):
        finding = normalize_finding(
            SAMPLE_SPECTRAL_FINDING,
            repo_root="/home/runner/work/R/R",
        )
        assert finding["path"] == "code/API_definitions/quality-on-demand.yaml"

    def test_external_file_finding_downgraded_to_hint(self):
        """Findings on files outside API_definitions/ (e.g. common schemas
        followed via $ref) are downgraded to hint."""
        raw = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": "code/common/CAMARA_common.yaml",
        }
        finding = normalize_finding(raw)
        assert finding["level"] == "hint"
        assert finding["path"] == "code/common/CAMARA_common.yaml"

    def test_external_file_absolute_path_downgraded_to_hint(self):
        raw = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": "/home/runner/work/R/R/code/common/CAMARA_common.yaml",
        }
        finding = normalize_finding(raw, repo_root="/home/runner/work/R/R")
        assert finding["level"] == "hint"

    def test_empty_source_keeps_original_severity(self):
        """Findings with empty source (e.g. engine-level errors) keep severity."""
        raw = {
            "code": "some-rule",
            "message": "msg",
            "severity": 0,
            "source": "",
            "range": {"start": {"line": 0}},
        }
        finding = normalize_finding(raw)
        assert finding["level"] == "error"
        assert finding["path"] == ""


# ---------------------------------------------------------------------------
# TestParseSpectralOutput
# ---------------------------------------------------------------------------


class TestParseSpectralOutput:
    def test_valid_json_array(self):
        raw = json.dumps([SAMPLE_SPECTRAL_FINDING, SAMPLE_SPECTRAL_WARN])
        findings = parse_spectral_output(raw)
        assert len(findings) == 2
        assert findings[0]["engine_rule"] == "camara-path-casing-convention"
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

    def test_repo_root_normalises_paths(self):
        abs_finding = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": "/runner/work/code/API_definitions/quality-on-demand.yaml",
        }
        raw = json.dumps([abs_finding])
        findings = parse_spectral_output(raw, repo_root="/runner/work")
        assert findings[0]["path"] == "code/API_definitions/quality-on-demand.yaml"

    def test_sourceless_findings_pass_through(self):
        """Sourceless findings are not filtered — per-file invocation
        avoids the shared-cache bug that caused them (spectral#2640)."""
        sourceless = {
            "code": "owasp:api4:2023-string-restricted",
            "message": "Schema of type string should specify a format.",
            "severity": 1,
            "source": "",
            "path": ["components", "schemas", "Foo", "properties", "bar"],
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 0}},
        }
        raw = json.dumps([SAMPLE_SPECTRAL_FINDING, sourceless])
        findings = parse_spectral_output(raw)
        assert len(findings) == 2

    def test_external_file_findings_downgraded_to_hint(self):
        """Findings from common schemas (followed via $ref) become hints."""
        common_finding = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": "code/common/CAMARA_common.yaml",
            "code": "camara-properties-descriptions",
        }
        raw = json.dumps([SAMPLE_SPECTRAL_FINDING, common_finding])
        findings = parse_spectral_output(raw)
        assert len(findings) == 2
        assert findings[0]["level"] == "error"  # original API finding
        assert findings[1]["level"] == "hint"   # external finding downgraded


# ---------------------------------------------------------------------------
# TestRunSpectral
# ---------------------------------------------------------------------------


def _spectral_side_effect(
    json_content: str,
    returncode: int = 0,
    stderr: str = "",
):
    """Create a subprocess.run side_effect that writes JSON to the --output file.

    Simulates Spectral's behaviour: it writes results to the file specified
    by ``--output`` and exits with the given return code.
    """
    def side_effect(cmd, **kwargs):
        output_idx = cmd.index("--output")
        output_path = Path(cmd[output_idx + 1])
        output_path.write_text(json_content, encoding="utf-8")
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout="", stderr=stderr,
        )
    return side_effect


class TestRunSpectral:
    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_0_no_findings(self, mock_run, tmp_path):
        mock_run.side_effect = _spectral_side_effect("[]", returncode=0)
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert result.findings == []
        assert result.error_message == ""

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_1_with_findings(self, mock_run, tmp_path):
        mock_run.side_effect = _spectral_side_effect(
            json.dumps([SAMPLE_SPECTRAL_FINDING]), returncode=1,
        )
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0]["engine_rule"] == "camara-path-casing-convention"

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_exit_2_runtime_error(self, mock_run, tmp_path):
        mock_run.side_effect = _spectral_side_effect(
            "", returncode=2, stderr="Error: invalid ruleset",
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
    def test_findings_paths_normalised_by_cwd(self, mock_run, tmp_path):
        """run_spectral passes cwd as repo_root to normalise absolute paths."""
        abs_finding = {
            **SAMPLE_SPECTRAL_FINDING,
            "source": f"{tmp_path}/code/API_definitions/quality-on-demand.yaml",
        }
        mock_run.side_effect = _spectral_side_effect(
            json.dumps([abs_finding]), returncode=1,
        )
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert result.findings[0]["path"] == "code/API_definitions/quality-on-demand.yaml"

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_command_includes_output_flag_and_patterns(self, mock_run, tmp_path):
        mock_run.side_effect = _spectral_side_effect("[]", returncode=0)
        ruleset = tmp_path / ".spectral-r4.yaml"
        run_spectral(ruleset, ["code/API_definitions/*.yaml"], cwd=tmp_path)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--ruleset" in cmd
        assert "--quiet" in cmd
        assert "--output" in cmd
        assert str(ruleset) in cmd
        assert "code/API_definitions/*.yaml" in cmd
        assert call_args[1]["cwd"] == str(tmp_path)

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_temp_file_cleaned_up_on_success(self, mock_run, tmp_path):
        """Temp output file is removed after successful invocation."""
        mock_run.side_effect = _spectral_side_effect("[]", returncode=0)
        run_spectral(tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path)
        # No leftover .json files in the working directory.
        remaining = list(tmp_path.glob("*.json"))
        assert remaining == []

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_temp_file_cleaned_up_on_error(self, mock_run, tmp_path):
        """Temp output file is removed even when Spectral fails."""
        mock_run.side_effect = _spectral_side_effect(
            "", returncode=2, stderr="boom",
        )
        run_spectral(tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path)
        remaining = list(tmp_path.glob("*.json"))
        assert remaining == []

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_temp_file_cleaned_up_on_timeout(self, mock_run, tmp_path):
        """Temp output file is removed when Spectral times out."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="spectral", timeout=300)
        run_spectral(tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path)
        remaining = list(tmp_path.glob("*.json"))
        assert remaining == []

    @patch("validation.engines.spectral_adapter.subprocess.run")
    def test_large_output_over_64kb(self, mock_run, tmp_path):
        """Output larger than 64 KB is correctly read from file (the original bug)."""
        # Generate >64 KB of JSON findings.
        findings_data = []
        for i in range(200):
            findings_data.append({
                **SAMPLE_SPECTRAL_FINDING,
                "message": f"Finding {i}: {'x' * 300}",
            })
        large_json = json.dumps(findings_data)
        assert len(large_json) > 65536, "Test data must exceed 64 KB"

        mock_run.side_effect = _spectral_side_effect(large_json, returncode=1)
        result = run_spectral(
            tmp_path / ".spectral.yaml", ["*.yaml"], cwd=tmp_path,
        )
        assert result.success is True
        assert len(result.findings) == 200


# ---------------------------------------------------------------------------
# TestRunSpectralEngine
# ---------------------------------------------------------------------------


class TestResolveSpecFiles:
    def test_glob_resolves_to_individual_files(self, tmp_path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "alpha.yaml").touch()
        (api_dir / "beta.yaml").touch()

        files = _resolve_spec_files(["code/API_definitions/*.yaml"], tmp_path)
        assert files == [
            "code/API_definitions/alpha.yaml",
            "code/API_definitions/beta.yaml",
        ]

    def test_no_matches_returns_empty(self, tmp_path):
        assert _resolve_spec_files(["nonexistent/*.yaml"], tmp_path) == []

    def test_deduplicates_overlapping_patterns(self, tmp_path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "api.yaml").touch()

        files = _resolve_spec_files(
            ["code/API_definitions/*.yaml", "code/API_definitions/api.yaml"],
            tmp_path,
        )
        assert files == ["code/API_definitions/api.yaml"]

    def test_multiple_patterns(self, tmp_path):
        api_dir = tmp_path / "code" / "API_definitions"
        bundled_dir = tmp_path / "bundled"
        api_dir.mkdir(parents=True)
        bundled_dir.mkdir()
        (api_dir / "api.yaml").touch()
        (bundled_dir / "bundled.yaml").touch()

        files = _resolve_spec_files(
            ["code/API_definitions/*.yaml", "bundled/*.yaml"], tmp_path,
        )
        assert "code/API_definitions/api.yaml" in files
        assert "bundled/bundled.yaml" in files


# ---------------------------------------------------------------------------
# TestDeduplicateFindings
# ---------------------------------------------------------------------------


class TestDeduplicateFindings:
    def test_identical_findings_deduped(self):
        f1 = {"path": "common.yaml", "line": 72, "engine_rule": "rule-a",
               "level": "hint", "message": "msg"}
        f2 = {"path": "common.yaml", "line": 72, "engine_rule": "rule-a",
               "level": "hint", "message": "msg"}
        assert len(_deduplicate_findings([f1, f2])) == 1

    def test_different_lines_kept(self):
        f1 = {"path": "common.yaml", "line": 72, "engine_rule": "rule-a"}
        f2 = {"path": "common.yaml", "line": 76, "engine_rule": "rule-a"}
        assert len(_deduplicate_findings([f1, f2])) == 2

    def test_different_rules_kept(self):
        f1 = {"path": "common.yaml", "line": 72, "engine_rule": "rule-a"}
        f2 = {"path": "common.yaml", "line": 72, "engine_rule": "rule-b"}
        assert len(_deduplicate_findings([f1, f2])) == 2

    def test_different_files_kept(self):
        f1 = {"path": "api-a.yaml", "line": 10, "engine_rule": "rule-a"}
        f2 = {"path": "api-b.yaml", "line": 10, "engine_rule": "rule-a"}
        assert len(_deduplicate_findings([f1, f2])) == 2

    def test_preserves_order(self):
        findings = [
            {"path": "b.yaml", "line": 1, "engine_rule": "r1"},
            {"path": "a.yaml", "line": 1, "engine_rule": "r1"},
            {"path": "b.yaml", "line": 1, "engine_rule": "r1"},  # dup
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 2
        assert result[0]["path"] == "b.yaml"
        assert result[1]["path"] == "a.yaml"

    def test_empty_list(self):
        assert _deduplicate_findings([]) == []


# ---------------------------------------------------------------------------
# TestRunSpectralEngine
# ---------------------------------------------------------------------------


class TestRunSpectralEngine:
    def _make_spec_files(self, tmp_path, names):
        """Create spec files and return the tmp_path for use as repo_path."""
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        for name in names:
            (api_dir / name).touch()
        (tmp_path / ".spectral.yaml").touch()
        return tmp_path

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_invokes_spectral_per_file(self, mock_run, tmp_path):
        """Each spec file gets its own Spectral invocation."""
        repo = self._make_spec_files(tmp_path, ["alpha.yaml", "beta.yaml"])
        mock_run.return_value = SpectralResult(findings=[], success=True)

        run_spectral_engine(repo, repo)
        assert mock_run.call_count == 2
        # Each call gets a single-element list.
        calls = [c[0][1] for c in mock_run.call_args_list]
        assert ["code/API_definitions/alpha.yaml"] in calls
        assert ["code/API_definitions/beta.yaml"] in calls

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_merges_findings_across_files(self, mock_run, tmp_path):
        repo = self._make_spec_files(tmp_path, ["a.yaml", "b.yaml"])

        def per_file(ruleset, patterns, cwd):
            name = patterns[0].split("/")[-1]
            return SpectralResult(
                findings=[{"engine": "spectral", "engine_rule": "r1",
                           "level": "warn", "message": name,
                           "path": patterns[0], "line": 1}],
                success=True,
            )
        mock_run.side_effect = per_file

        result = run_spectral_engine(repo, repo)
        assert len(result) == 2

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_deduplicates_common_file_findings(self, mock_run, tmp_path):
        """Findings from shared code/common/ schemas are deduped across files."""
        repo = self._make_spec_files(tmp_path, ["a.yaml", "b.yaml"])
        common_finding = {"engine": "spectral", "engine_rule": "owasp-rule",
                          "level": "hint", "message": "msg",
                          "path": "code/common/CAMARA_common.yaml", "line": 72}

        mock_run.return_value = SpectralResult(
            findings=[common_finding], success=True,
        )

        result = run_spectral_engine(repo, repo)
        # Same finding from two files → kept once.
        assert len(result) == 1

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_error_on_one_file_continues_others(self, mock_run, tmp_path):
        repo = self._make_spec_files(tmp_path, ["good.yaml", "bad.yaml"])
        good_finding = {"engine": "spectral", "engine_rule": "r1",
                        "level": "warn", "message": "m",
                        "path": "code/API_definitions/good.yaml", "line": 1}

        def per_file(ruleset, patterns, cwd):
            if "bad.yaml" in patterns[0]:
                return SpectralResult(findings=[], success=False,
                                      error_message="CLI not found")
            return SpectralResult(findings=[good_finding], success=True)
        mock_run.side_effect = per_file

        result = run_spectral_engine(repo, repo)
        # One real finding + one error finding for the bad file.
        assert len(result) == 2
        error_findings = [f for f in result if f["level"] == "error"]
        assert len(error_findings) == 1
        assert "bad.yaml" in error_findings[0]["message"]

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_no_matching_files_returns_empty(self, mock_run, tmp_path):
        (tmp_path / ".spectral.yaml").touch()
        # No spec files created.
        result = run_spectral_engine(tmp_path, tmp_path)
        assert result == []
        mock_run.assert_not_called()

    @patch("validation.engines.spectral_adapter.run_spectral")
    def test_ruleset_selection_uses_commonalities(self, mock_run, tmp_path):
        """Verifies that the correct ruleset is selected and passed."""
        repo = self._make_spec_files(tmp_path, ["api.yaml"])
        r4 = tmp_path / ".spectral-r4.yaml"
        r4.touch()
        mock_run.return_value = SpectralResult(findings=[], success=True)

        run_spectral_engine(repo, repo, commonalities_release="r4.2")
        assert mock_run.call_args[0][0] == r4
