"""Unit tests for validation.orchestrator."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from validation.output.commit_status import CommitStatusPayload
from validation.orchestrator import (
    EXIT_INFRA_ERROR,
    EXIT_OK,
    OrchestratorArgs,
    ToolingPaths,
    discover_spec_files,
    discover_test_files,
    main,
    parse_args,
    resolve_tooling_paths,
    run_engines,
    write_outputs,
    write_result_json,
    write_skip_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def args():
    """Default orchestrator args."""
    return OrchestratorArgs(
        repo_path=Path("/repo"),
        tooling_path=Path("/tooling"),
        output_dir=Path("/output"),
        repo_name="camaraproject/QualityOnDemand",
        repo_owner="camaraproject",
        event_name="pull_request",
        ref_name="refs/heads/main",
        base_ref="main",
        mode="",
        profile="",
        pr_number=42,
        release_plan_changed=False,
        workflow_run_url="https://github.com/example/runs/1",
        tooling_ref="abc123",
        commit_sha="def456",
    )


@pytest.fixture
def paths():
    """Default tooling paths."""
    return resolve_tooling_paths(Path("/tooling"))


def _make_finding(
    engine: str = "spectral",
    engine_rule: str = "some-rule",
    level: str = "warn",
    message: str = "Something is wrong",
    path: str = "code/API_definitions/quality-on-demand.yaml",
    line: int = 10,
    api_name: str | None = "quality-on-demand",
    blocks: bool = False,
) -> dict:
    return {
        "engine": engine,
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
        "api_name": api_name,
        "blocks": blocks,
    }


def _make_context(**overrides):
    """Create a mock ValidationContext."""
    defaults = {
        "repository": "camaraproject/QualityOnDemand",
        "branch_type": "main",
        "trigger_type": "pr",
        "profile": "standard",
        "stage": "standard",
        "target_release_type": None,
        "commonalities_release": None,
        "icm_release": None,
        "is_release_review_pr": False,
        "release_plan_changed": False,
        "pr_number": 42,
        "apis": (),
        "workflow_run_url": "https://github.com/example/runs/1",
        "tooling_ref": "abc123",
    }
    defaults.update(overrides)
    ctx = MagicMock()
    for k, v in defaults.items():
        setattr(ctx, k, v)
    ctx.to_dict.return_value = defaults
    return ctx


def _make_post_filter_result(
    result: str = "pass",
    summary: str = "All checks passed",
    findings: list | None = None,
):
    """Create a mock PostFilterResult."""
    mock = MagicMock()
    mock.result = result
    mock.summary = summary
    mock.findings = findings or []
    return mock


# ---------------------------------------------------------------------------
# TestParseArgs
# ---------------------------------------------------------------------------


class TestParseArgs:
    """Tests for environment variable parsing."""

    def test_defaults_when_no_env_vars(self):
        with patch.dict("os.environ", {}, clear=True):
            result = parse_args()
        assert result.repo_path == Path(".")
        assert result.tooling_path == Path(".tooling")
        assert result.output_dir == Path("validation-output")
        assert result.repo_name == ""
        assert result.pr_number is None
        assert result.release_plan_changed is None

    def test_all_env_vars_set(self):
        env = {
            "VALIDATION_REPO_PATH": "/my/repo",
            "VALIDATION_TOOLING_PATH": "/my/tooling",
            "VALIDATION_OUTPUT_DIR": "/my/output",
            "VALIDATION_REPO_NAME": "camaraproject/QoD",
            "VALIDATION_REPO_OWNER": "camaraproject",
            "VALIDATION_EVENT_NAME": "pull_request",
            "VALIDATION_REF_NAME": "refs/heads/feature/foo",
            "VALIDATION_BASE_REF": "main",
            "VALIDATION_MODE": "pre-snapshot",
            "VALIDATION_PROFILE": "strict",
            "VALIDATION_PR_NUMBER": "42",
            "VALIDATION_RELEASE_PLAN_CHANGED": "true",
            "VALIDATION_WORKFLOW_RUN_URL": "https://example.com/runs/1",
            "VALIDATION_TOOLING_REF": "abc123",
            "VALIDATION_COMMIT_SHA": "def456",
        }
        with patch.dict("os.environ", env, clear=True):
            result = parse_args()
        assert result.repo_path == Path("/my/repo")
        assert result.repo_name == "camaraproject/QoD"
        assert result.mode == "pre-snapshot"
        assert result.profile == "strict"
        assert result.pr_number == 42
        assert result.release_plan_changed is True
        assert result.commit_sha == "def456"

    def test_pr_number_non_numeric(self):
        env = {"VALIDATION_PR_NUMBER": "not-a-number"}
        with patch.dict("os.environ", env, clear=True):
            result = parse_args()
        assert result.pr_number is None

    def test_release_plan_changed_false(self):
        env = {"VALIDATION_RELEASE_PLAN_CHANGED": "false"}
        with patch.dict("os.environ", env, clear=True):
            result = parse_args()
        assert result.release_plan_changed is False

    def test_release_plan_changed_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            result = parse_args()
        assert result.release_plan_changed is None


# ---------------------------------------------------------------------------
# TestResolveToolingPaths
# ---------------------------------------------------------------------------


class TestResolveToolingPaths:
    """Tests for path resolution within tooling checkout."""

    def test_paths_resolved(self):
        result = resolve_tooling_paths(Path("/tooling"))
        assert result.config_file == Path("/tooling/validation/config/validation-config.yaml")
        assert result.config_schema == Path("/tooling/validation/schemas/validation-config-schema.yaml")
        assert result.release_plan_schema == Path("/tooling/validation/schemas/release-plan-schema.yaml")
        assert result.linting_config_dir == Path("/tooling/linting/config")
        assert result.rules_dir == Path("/tooling/validation/rules")


# ---------------------------------------------------------------------------
# TestDiscoverFiles
# ---------------------------------------------------------------------------


class TestDiscoverFiles:
    """Tests for spec and test file discovery."""

    def test_discover_spec_files(self, tmp_path):
        api_dir = tmp_path / "code" / "API_definitions"
        api_dir.mkdir(parents=True)
        (api_dir / "quality-on-demand.yaml").write_text("openapi: 3.0.0")
        (api_dir / "device-location.yaml").write_text("openapi: 3.0.0")
        (api_dir / "README.md").write_text("Not a spec")  # should not match

        result = discover_spec_files(tmp_path)
        assert len(result) == 2
        assert all(p.suffix == ".yaml" for p in result)
        # sorted alphabetically
        assert result[0].name == "device-location.yaml"
        assert result[1].name == "quality-on-demand.yaml"

    def test_discover_spec_files_empty(self, tmp_path):
        result = discover_spec_files(tmp_path)
        assert result == []

    def test_discover_test_files(self, tmp_path):
        test_dir = tmp_path / "code" / "Test_definitions"
        test_dir.mkdir(parents=True)
        (test_dir / "quality-on-demand.feature").write_text("Feature: QoD")
        sub = test_dir / "subfolder"
        sub.mkdir()
        (sub / "nested.feature").write_text("Feature: Nested")

        result = discover_test_files(tmp_path)
        assert len(result) == 2

    def test_discover_test_files_empty(self, tmp_path):
        result = discover_test_files(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# TestRunEngines
# ---------------------------------------------------------------------------


class TestRunEngines:
    """Tests for engine orchestration."""

    @patch("validation.orchestrator.run_gherkin_engine")
    @patch("validation.orchestrator.run_python_engine")
    @patch("validation.orchestrator.run_spectral_engine")
    @patch("validation.orchestrator.run_yamllint_engine")
    def test_all_engines_called(
        self, mock_yamllint, mock_spectral, mock_python, mock_gherkin, paths
    ):
        mock_yamllint.return_value = [_make_finding(engine="yamllint")]
        mock_spectral.return_value = [_make_finding(engine="spectral")]
        mock_python.return_value = [_make_finding(engine="python")]
        mock_gherkin.return_value = [_make_finding(engine="gherkin")]
        context = _make_context()
        test_files = [Path("/repo/code/Test_definitions/test.feature")]

        findings, statuses = run_engines(Path("/repo"), paths, context, test_files)

        assert len(findings) == 4
        assert mock_yamllint.called
        assert mock_spectral.called
        assert mock_python.called
        assert mock_gherkin.called
        assert "finding(s)" in statuses["yamllint"]
        assert "finding(s)" in statuses["spectral"]
        assert "finding(s)" in statuses["python"]
        assert "finding(s)" in statuses["gherkin"]
        assert statuses["bundling"] == "separate workflow step"

    @patch("validation.orchestrator.run_gherkin_engine")
    @patch("validation.orchestrator.run_python_engine")
    @patch("validation.orchestrator.run_spectral_engine")
    @patch("validation.orchestrator.run_yamllint_engine")
    def test_release_review_runs_all_engines(
        self, mock_yamllint, mock_spectral, mock_python, mock_gherkin, paths
    ):
        """All engines run on release-review PRs (DEC-011 revision)."""
        mock_yamllint.return_value = [_make_finding(engine="yamllint")]
        mock_spectral.return_value = [_make_finding(engine="spectral")]
        mock_python.return_value = [_make_finding(engine="python")]
        mock_gherkin.return_value = [_make_finding(engine="gherkin")]
        context = _make_context(is_release_review_pr=True)
        test_files = [Path("/repo/code/Test_definitions/test.feature")]

        findings, statuses = run_engines(Path("/repo"), paths, context, test_files)

        assert mock_yamllint.called
        assert mock_spectral.called
        assert mock_python.called
        assert mock_gherkin.called
        assert len(findings) == 4
        assert "skipped" not in statuses.get("yamllint", "")
        assert "skipped" not in statuses.get("spectral", "")

    @patch("validation.orchestrator.run_gherkin_engine")
    @patch("validation.orchestrator.run_python_engine")
    @patch("validation.orchestrator.run_spectral_engine")
    @patch("validation.orchestrator.run_yamllint_engine")
    def test_no_test_files_skips_gherkin(
        self, mock_yamllint, mock_spectral, mock_python, mock_gherkin, paths
    ):
        mock_yamllint.return_value = []
        mock_spectral.return_value = []
        mock_python.return_value = []
        context = _make_context()

        findings, statuses = run_engines(Path("/repo"), paths, context, test_files=[])

        assert not mock_gherkin.called
        assert "skipped" in statuses["gherkin"]

    @patch("validation.orchestrator.run_python_engine")
    @patch("validation.orchestrator.run_spectral_engine")
    @patch("validation.orchestrator.run_yamllint_engine")
    def test_engine_exception_captured(
        self, mock_yamllint, mock_spectral, mock_python, paths
    ):
        mock_yamllint.side_effect = RuntimeError("yamllint boom")
        mock_spectral.return_value = []
        mock_python.return_value = []
        context = _make_context()

        findings, statuses = run_engines(Path("/repo"), paths, context, test_files=[])

        assert "error:" in statuses["yamllint"]
        assert "finding(s)" in statuses["spectral"]


# ---------------------------------------------------------------------------
# TestWriteOutputs
# ---------------------------------------------------------------------------


class TestWriteResultJson:
    """Tests for result.json writing."""

    def test_pass(self, tmp_path):
        write_result_json(tmp_path, "pass", "All checks passed")
        data = json.loads((tmp_path / "result.json").read_text())
        assert data["result"] == "pass"
        assert data["should_fail"] is False

    def test_fail(self, tmp_path):
        write_result_json(tmp_path, "fail", "2 errors")
        data = json.loads((tmp_path / "result.json").read_text())
        assert data["result"] == "fail"
        assert data["should_fail"] is True

    def test_error(self, tmp_path):
        write_result_json(tmp_path, "error", "Engine crashed")
        data = json.loads((tmp_path / "result.json").read_text())
        assert data["result"] == "error"
        assert data["should_fail"] is True


class TestWriteSkipOutput:
    """Tests for skip output writing."""

    def test_creates_output_dir(self, tmp_path):
        out = tmp_path / "nested" / "output"
        write_skip_output(out, "Validation disabled")
        assert out.exists()
        assert (out / "summary.md").exists()
        assert (out / "result.json").exists()

    def test_skip_reason_in_summary(self, tmp_path):
        write_skip_output(tmp_path, "Validation is advisory — use dispatch")
        content = (tmp_path / "summary.md").read_text()
        assert "advisory" in content

    def test_skip_result_json(self, tmp_path):
        write_skip_output(tmp_path, "Disabled")
        data = json.loads((tmp_path / "result.json").read_text())
        assert data["result"] == "skipped"
        assert data["should_fail"] is False


class TestWriteOutputs:
    """Tests for full output writing."""

    @patch("validation.orchestrator.write_diagnostics")
    @patch("validation.orchestrator.generate_commit_status")
    @patch("validation.orchestrator.generate_pr_comment")
    @patch("validation.orchestrator.generate_workflow_summary")
    @patch("validation.orchestrator.generate_annotations")
    def test_all_files_written(
        self,
        mock_annotations,
        mock_summary,
        mock_pr_comment,
        mock_commit_status,
        mock_diagnostics,
        tmp_path,
    ):
        # Setup mocks
        mock_annotations.return_value = MagicMock(
            commands=["::warning file=a.yaml::msg"],
            total_findings=1,
            annotations_emitted=1,
            truncated=False,
        )
        mock_summary.return_value = MagicMock(
            markdown="# Summary\nAll good",
            truncated=False,
            truncation_note="",
        )
        mock_pr_comment.return_value = "<!-- camara-validation -->\nAll good"
        mock_commit_status.return_value = CommitStatusPayload(
            state="success",
            description="All checks passed",
            context="CAMARA Validation",
            target_url="https://example.com",
        )
        mock_diagnostics.return_value = []

        pfr = _make_post_filter_result()
        ctx = _make_context()

        write_outputs(pfr, ctx, tmp_path, {"spectral": "0 finding(s)"}, "abc123")

        # Verify files
        assert (tmp_path / "annotations.txt").exists()
        assert "::warning" in (tmp_path / "annotations.txt").read_text()
        assert (tmp_path / "summary.md").exists()
        assert (tmp_path / "pr-comment.md").exists()
        assert "camara-validation" in (tmp_path / "pr-comment.md").read_text()
        assert (tmp_path / "commit-status.json").exists()
        status = json.loads((tmp_path / "commit-status.json").read_text())
        assert status["state"] == "success"
        assert (tmp_path / "result.json").exists()

    @patch("validation.orchestrator.write_diagnostics")
    @patch("validation.orchestrator.generate_commit_status")
    @patch("validation.orchestrator.generate_pr_comment")
    @patch("validation.orchestrator.generate_workflow_summary")
    @patch("validation.orchestrator.generate_annotations")
    def test_no_annotations_file_when_empty(
        self,
        mock_annotations,
        mock_summary,
        mock_pr_comment,
        mock_commit_status,
        mock_diagnostics,
        tmp_path,
    ):
        mock_annotations.return_value = MagicMock(
            commands=[],
            total_findings=0,
            annotations_emitted=0,
            truncated=False,
        )
        mock_summary.return_value = MagicMock(markdown="# ok", truncated=False, truncation_note="")
        mock_pr_comment.return_value = "ok"
        mock_commit_status.return_value = CommitStatusPayload(
            state="success", description="ok", context="test", target_url=""
        )
        mock_diagnostics.return_value = []

        write_outputs(
            _make_post_filter_result(), _make_context(), tmp_path, {}, ""
        )

        assert not (tmp_path / "annotations.txt").exists()

    @patch("validation.orchestrator.write_diagnostics")
    @patch("validation.orchestrator.generate_commit_status")
    @patch("validation.orchestrator.generate_pr_comment")
    @patch("validation.orchestrator.generate_workflow_summary")
    @patch("validation.orchestrator.generate_annotations")
    def test_creates_output_dir(
        self,
        mock_annotations,
        mock_summary,
        mock_pr_comment,
        mock_commit_status,
        mock_diagnostics,
        tmp_path,
    ):
        out = tmp_path / "nested" / "output"
        mock_annotations.return_value = MagicMock(
            commands=[], total_findings=0, annotations_emitted=0, truncated=False
        )
        mock_summary.return_value = MagicMock(markdown="ok", truncated=False, truncation_note="")
        mock_pr_comment.return_value = "ok"
        mock_commit_status.return_value = CommitStatusPayload(
            state="success", description="ok", context="test", target_url=""
        )
        mock_diagnostics.return_value = []

        write_outputs(
            _make_post_filter_result(), _make_context(), out, {}, ""
        )

        assert out.exists()
        assert (out / "result.json").exists()


# ---------------------------------------------------------------------------
# TestMainPipeline
# ---------------------------------------------------------------------------


class TestMainPipeline:
    """Integration tests for the main() pipeline."""

    def _set_env(self, tmp_path, **overrides):
        """Return env dict for a standard pipeline run."""
        env = {
            "VALIDATION_REPO_PATH": str(tmp_path / "repo"),
            "VALIDATION_TOOLING_PATH": str(tmp_path / "tooling"),
            "VALIDATION_OUTPUT_DIR": str(tmp_path / "output"),
            "VALIDATION_REPO_NAME": "camaraproject/QualityOnDemand",
            "VALIDATION_REPO_OWNER": "camaraproject",
            "VALIDATION_EVENT_NAME": "pull_request",
            "VALIDATION_REF_NAME": "refs/heads/main",
            "VALIDATION_BASE_REF": "main",
            "VALIDATION_MODE": "",
            "VALIDATION_PROFILE": "",
            "VALIDATION_PR_NUMBER": "42",
            "VALIDATION_RELEASE_PLAN_CHANGED": "false",
            "VALIDATION_WORKFLOW_RUN_URL": "https://example.com/runs/1",
            "VALIDATION_TOOLING_REF": "abc123",
            "VALIDATION_COMMIT_SHA": "def456",
        }
        env.update(overrides)
        return env

    @patch("validation.orchestrator.run_post_filter")
    @patch("validation.orchestrator.run_engines")
    @patch("validation.orchestrator.build_validation_context")
    @patch("validation.orchestrator.resolve_stage_from_files")
    def test_full_pipeline_pass(
        self, mock_gate, mock_context, mock_engines, mock_postfilter, tmp_path
    ):
        env = self._set_env(tmp_path)
        (tmp_path / "repo").mkdir()
        (tmp_path / "tooling").mkdir()

        mock_gate.return_value = MagicMock(
            stage="standard",
            should_continue=True,
            is_fork=False,
            fork_override_applied=False,
            reason="",
        )
        ctx = _make_context()
        mock_context.return_value = ctx
        mock_engines.return_value = ([], {"spectral": "0 finding(s)"})
        mock_postfilter.return_value = _make_post_filter_result(
            result="pass", summary="All checks passed", findings=[]
        )

        with patch.dict("os.environ", env, clear=True):
            exit_code = main()

        assert exit_code == EXIT_OK
        result_file = tmp_path / "output" / "result.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["result"] == "pass"
        assert data["should_fail"] is False

    @patch("validation.orchestrator.run_post_filter")
    @patch("validation.orchestrator.run_engines")
    @patch("validation.orchestrator.build_validation_context")
    @patch("validation.orchestrator.resolve_stage_from_files")
    def test_full_pipeline_fail(
        self, mock_gate, mock_context, mock_engines, mock_postfilter, tmp_path
    ):
        env = self._set_env(tmp_path)
        (tmp_path / "repo").mkdir()
        (tmp_path / "tooling").mkdir()

        mock_gate.return_value = MagicMock(
            stage="standard", should_continue=True, is_fork=False,
            fork_override_applied=False, reason="",
        )
        mock_context.return_value = _make_context()
        findings = [_make_finding(level="error", blocks=True)]
        mock_engines.return_value = (findings, {"spectral": "1 finding(s)"})
        mock_postfilter.return_value = _make_post_filter_result(
            result="fail", summary="1 error", findings=findings
        )

        with patch.dict("os.environ", env, clear=True):
            exit_code = main()

        assert exit_code == EXIT_OK  # orchestrator always returns 0
        data = json.loads((tmp_path / "output" / "result.json").read_text())
        assert data["result"] == "fail"
        assert data["should_fail"] is True

    @patch("validation.orchestrator.resolve_stage_from_files")
    def test_config_gate_skip(self, mock_gate, tmp_path):
        env = self._set_env(tmp_path)
        (tmp_path / "repo").mkdir()
        (tmp_path / "tooling").mkdir()

        mock_gate.return_value = MagicMock(
            stage="disabled", should_continue=False,
            is_fork=False, fork_override_applied=False,
            reason="Validation is not enabled for this repository",
        )

        with patch.dict("os.environ", env, clear=True):
            exit_code = main()

        assert exit_code == EXIT_OK
        data = json.loads((tmp_path / "output" / "result.json").read_text())
        assert data["result"] == "skipped"
        assert data["should_fail"] is False

    @patch("validation.orchestrator.run_post_filter")
    @patch("validation.orchestrator.run_engines")
    @patch("validation.orchestrator.build_validation_context")
    @patch("validation.orchestrator.resolve_stage_from_files")
    def test_engine_statuses_passed_to_summary(
        self, mock_gate, mock_context, mock_engines, mock_postfilter, tmp_path
    ):
        env = self._set_env(tmp_path)
        (tmp_path / "repo").mkdir()
        (tmp_path / "tooling").mkdir()

        mock_gate.return_value = MagicMock(
            stage="standard", should_continue=True, is_fork=False,
            fork_override_applied=False, reason="",
        )
        mock_context.return_value = _make_context()
        statuses = {
            "yamllint": "2 finding(s)",
            "spectral": "3 finding(s)",
            "python": "0 finding(s)",
            "gherkin": "skipped (no test files)",
            "bundling": "separate workflow step",
        }
        mock_engines.return_value = ([], statuses)
        mock_postfilter.return_value = _make_post_filter_result()

        with patch.dict("os.environ", env, clear=True):
            exit_code = main()

        assert exit_code == EXIT_OK
        # summary.md should exist
        assert (tmp_path / "output" / "summary.md").exists()


# ---------------------------------------------------------------------------
# TestExitCodes
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Tests for exit code semantics."""

    def test_exit_ok_constant(self):
        assert EXIT_OK == 0

    def test_exit_infra_error_constant(self):
        assert EXIT_INFRA_ERROR == 2
