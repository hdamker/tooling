"""Unit tests for validation.engines.python_adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_adapter import (
    ENGINE_NAME,
    _make_error_finding,
    run_python_engine,
)
from validation.engines.python_checks import CheckDescriptor, CheckScope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    apis: tuple[ApiContext, ...] = (),
    branch_type: str = "main",
) -> ValidationContext:
    """Build a minimal ValidationContext for testing."""
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
        apis=apis,
        workflow_run_url="",
        tooling_ref="",
    )


def _make_api(name: str = "quality-on-demand") -> ApiContext:
    return ApiContext(
        api_name=name,
        target_api_version="1.0.0",
        target_api_status="public",
        target_api_maturity="stable",
        api_pattern="request-response",
        spec_file=f"code/API_definitions/{name}.yaml",
    )


def _good_repo_check(repo_path: Path, context: ValidationContext) -> list[dict]:
    """A check that always produces one finding."""
    return [
        {
            "engine": "python",
            "engine_rule": "good-repo-check",
            "level": "hint",
            "message": "repo-level finding",
            "path": "",
            "line": 1,
            "api_name": None,
        }
    ]


def _good_api_check(repo_path: Path, context: ValidationContext) -> list[dict]:
    """A per-API check that produces one finding per API."""
    api = context.apis[0]
    return [
        {
            "engine": "python",
            "engine_rule": "good-api-check",
            "level": "warn",
            "message": f"finding for {api.api_name}",
            "path": api.spec_file,
            "line": 1,
            "api_name": api.api_name,
        }
    ]


def _empty_check(repo_path: Path, context: ValidationContext) -> list[dict]:
    """A check that produces no findings."""
    return []


def _crashing_check(repo_path: Path, context: ValidationContext) -> list[dict]:
    """A check that raises."""
    raise RuntimeError("something went wrong")


# ---------------------------------------------------------------------------
# TestMakeErrorFinding
# ---------------------------------------------------------------------------


class TestMakeErrorFinding:
    def test_default_rule(self):
        f = _make_error_finding("oops")
        assert f["engine"] == ENGINE_NAME
        assert f["engine_rule"] == "python-execution-error"
        assert f["level"] == "error"
        assert f["message"] == "oops"
        assert f["path"] == ""
        assert f["line"] == 1
        assert f["api_name"] is None

    def test_custom_check_name(self):
        f = _make_error_finding("oops", check_name="my-check")
        assert f["engine_rule"] == "my-check"


# ---------------------------------------------------------------------------
# TestRunPythonEngine
# ---------------------------------------------------------------------------


class TestRunPythonEngine:
    def test_empty_registry(self, tmp_path: Path):
        """No checks registered -> empty findings."""
        with patch("validation.engines.python_adapter.CHECKS", []):
            result = run_python_engine(tmp_path, _make_context())
        assert result == []

    def test_repo_scope_called_once(self, tmp_path: Path):
        """REPO-scope check is called exactly once."""
        checks = [CheckDescriptor("repo-check", CheckScope.REPO, _good_repo_check)]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, _make_context())
        assert len(result) == 1
        assert result[0]["engine_rule"] == "good-repo-check"

    def test_api_scope_called_per_api(self, tmp_path: Path):
        """API-scope check is called once per API in context.apis."""
        api_a = _make_api("api-a")
        api_b = _make_api("api-b")
        ctx = _make_context(apis=(api_a, api_b))
        checks = [CheckDescriptor("api-check", CheckScope.API, _good_api_check)]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, ctx)
        assert len(result) == 2
        assert result[0]["message"] == "finding for api-a"
        assert result[1]["message"] == "finding for api-b"

    def test_api_scope_no_apis(self, tmp_path: Path):
        """API-scope check produces nothing when context.apis is empty."""
        ctx = _make_context(apis=())
        checks = [CheckDescriptor("api-check", CheckScope.API, _good_api_check)]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, ctx)
        assert result == []

    def test_api_scope_receives_single_api(self, tmp_path: Path):
        """Each API-scope call receives a context with exactly one API."""
        received_apis: list[tuple[ApiContext, ...]] = []

        def spy_check(repo_path: Path, ctx: ValidationContext) -> list[dict]:
            received_apis.append(ctx.apis)
            return []

        api_a = _make_api("api-a")
        api_b = _make_api("api-b")
        ctx = _make_context(apis=(api_a, api_b))
        checks = [CheckDescriptor("spy-check", CheckScope.API, spy_check)]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            run_python_engine(tmp_path, ctx)

        assert len(received_apis) == 2
        assert received_apis[0] == (api_a,)
        assert received_apis[1] == (api_b,)

    def test_error_isolation(self, tmp_path: Path):
        """A crashing check produces an error finding; other checks still run."""
        checks = [
            CheckDescriptor("crash", CheckScope.REPO, _crashing_check),
            CheckDescriptor("ok", CheckScope.REPO, _good_repo_check),
        ]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, _make_context())

        assert len(result) == 2
        # First: error finding from the crash
        assert result[0]["engine_rule"] == "crash"
        assert result[0]["level"] == "error"
        assert "something went wrong" in result[0]["message"]
        # Second: normal finding from the good check
        assert result[1]["engine_rule"] == "good-repo-check"

    def test_empty_check_contributes_nothing(self, tmp_path: Path):
        """A check returning [] adds no findings."""
        checks = [
            CheckDescriptor("empty", CheckScope.REPO, _empty_check),
            CheckDescriptor("ok", CheckScope.REPO, _good_repo_check),
        ]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, _make_context())
        assert len(result) == 1
        assert result[0]["engine_rule"] == "good-repo-check"

    def test_mixed_scopes(self, tmp_path: Path):
        """REPO and API checks can coexist in the registry."""
        api = _make_api("my-api")
        ctx = _make_context(apis=(api,))
        checks = [
            CheckDescriptor("repo", CheckScope.REPO, _good_repo_check),
            CheckDescriptor("api", CheckScope.API, _good_api_check),
        ]
        with patch("validation.engines.python_adapter.CHECKS", checks):
            result = run_python_engine(tmp_path, ctx)

        assert len(result) == 2
        assert result[0]["engine_rule"] == "good-repo-check"
        assert result[1]["engine_rule"] == "good-api-check"
