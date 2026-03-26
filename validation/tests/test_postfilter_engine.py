"""Unit tests for validation.postfilter.engine (integration)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validation.context import ApiContext, ValidationContext
from validation.postfilter.engine import (
    PostFilterResult,
    _is_engine_error_finding,
    _resolve_api_context,
    compute_overall_result,
    run_post_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    branch_type: str = "main",
    trigger_type: str = "pr",
    profile: str = "standard",
    target_release_type: str | None = "public-release",
    commonalities_release: str | None = "r4.1",
    is_release_review_pr: bool = False,
    apis: tuple[ApiContext, ...] = (),
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type=branch_type,
        trigger_type=trigger_type,
        profile=profile,
        stage="standard",
        target_release_type=target_release_type,
        commonalities_release=commonalities_release,
        icm_release=None,
        is_release_review_pr=is_release_review_pr,
        release_plan_changed=None,
        pr_number=None,
        apis=apis,
        workflow_run_url="",
        tooling_ref="",
    )


def _make_api(
    api_name: str = "quality-on-demand",
    target_api_status: str = "public",
    target_api_maturity: str = "stable",
) -> ApiContext:
    return ApiContext(
        api_name=api_name,
        target_api_version="1.0.0",
        target_api_status=target_api_status,
        target_api_maturity=target_api_maturity,
        api_pattern="request-response",
        spec_file=f"code/API_definitions/{api_name}.yaml",
    )


def _make_finding(
    engine: str = "spectral",
    engine_rule: str = "some-rule",
    level: str = "warn",
    message: str = "Something is wrong",
    path: str = "code/API_definitions/quality-on-demand.yaml",
    line: int = 10,
    api_name: str | None = "quality-on-demand",
) -> dict:
    return {
        "engine": engine,
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
        "api_name": api_name,
    }


def _write_rules(tmp_path: Path, rules: list[dict], filename: str = "spectral-rules.yaml") -> None:
    (tmp_path / filename).write_text(
        yaml.dump(rules, default_flow_style=False), encoding="utf-8"
    )


def _minimal_rule(
    id: str = "S-001",
    engine: str = "spectral",
    engine_rule: str = "some-rule",
    hint: str = "Fix this.",
    default_level: str = "warn",
    applicability: dict | None = None,
    overrides: list[dict] | None = None,
) -> dict:
    rule: dict = {
        "id": id,
        "name": "test-rule",
        "engine": engine,
        "engine_rule": engine_rule,
        "hint": hint,
        "conditional_level": {"default": default_level},
    }
    if applicability:
        rule["applicability"] = applicability
    if overrides:
        rule["conditional_level"]["overrides"] = overrides
    return rule


# ---------------------------------------------------------------------------
# TestIsEngineErrorFinding
# ---------------------------------------------------------------------------


class TestIsEngineErrorFinding:
    def test_spectral_error(self):
        f = _make_finding(engine_rule="spectral-execution-error")
        assert _is_engine_error_finding(f) is True

    def test_yamllint_error(self):
        f = _make_finding(engine_rule="yamllint-execution-error")
        assert _is_engine_error_finding(f) is True

    def test_normal_rule(self):
        f = _make_finding(engine_rule="camara-path-kebab-case")
        assert _is_engine_error_finding(f) is False

    def test_missing_engine_rule(self):
        assert _is_engine_error_finding({}) is False


# ---------------------------------------------------------------------------
# TestResolveApiContext
# ---------------------------------------------------------------------------


class TestResolveApiContext:
    def test_matching_api(self):
        api = _make_api(api_name="quality-on-demand")
        ctx = _make_context(apis=(api,))
        f = _make_finding(api_name="quality-on-demand")
        result = _resolve_api_context(f, ctx)
        assert result is not None
        assert result.api_name == "quality-on-demand"

    def test_no_matching_api(self):
        api = _make_api(api_name="qos-booking")
        ctx = _make_context(apis=(api,))
        f = _make_finding(api_name="quality-on-demand")
        assert _resolve_api_context(f, ctx) is None

    def test_repo_level_finding(self):
        ctx = _make_context()
        f = _make_finding(api_name=None)
        assert _resolve_api_context(f, ctx) is None

    def test_empty_api_name(self):
        ctx = _make_context()
        f = _make_finding()
        f["api_name"] = ""
        assert _resolve_api_context(f, ctx) is None


# ---------------------------------------------------------------------------
# TestComputeOverallResult
# ---------------------------------------------------------------------------


class TestComputeOverallResult:
    def test_engine_error_trumps_all(self):
        findings = [{"blocks": True}, {"blocks": False}]
        assert compute_overall_result(findings, had_engine_error=True) == "error"

    def test_blocking_finding_fails(self):
        findings = [{"blocks": True}, {"blocks": False}]
        assert compute_overall_result(findings, had_engine_error=False) == "fail"

    def test_no_blocking_passes(self):
        findings = [{"blocks": False}, {"blocks": False}]
        assert compute_overall_result(findings, had_engine_error=False) == "pass"

    def test_empty_findings_passes(self):
        assert compute_overall_result([], had_engine_error=False) == "pass"

    def test_empty_with_engine_error(self):
        assert compute_overall_result([], had_engine_error=True) == "error"


# ---------------------------------------------------------------------------
# TestRunPostFilter — integration tests
# ---------------------------------------------------------------------------


class TestRunPostFilter:
    """End-to-end tests for the full post-filter pipeline."""

    def test_empty_findings(self, tmp_path: Path):
        ctx = _make_context()
        result = run_post_filter([], ctx, tmp_path)
        assert result.result == "pass"
        assert result.findings == []

    def test_unmapped_rule_passthrough(self, tmp_path: Path):
        """Findings without metadata pass through with identity mapping."""
        ctx = _make_context(profile="standard")
        findings = [_make_finding(level="warn", message="Use kebab-case")]
        result = run_post_filter(findings, ctx, tmp_path)

        assert result.result == "pass"  # warn doesn't block in standard
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f["level"] == "warn"
        assert f["hint"] == "Use kebab-case"
        assert f["blocks"] is False
        assert "rule_id" not in f  # unmapped → no rule_id

    def test_unmapped_error_blocks_in_standard(self, tmp_path: Path):
        ctx = _make_context(profile="standard")
        findings = [_make_finding(level="error")]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.result == "fail"
        assert result.findings[0]["blocks"] is True

    def test_mapped_rule_enrichment(self, tmp_path: Path):
        """Mapped rules get rule_id, hint, and resolved level."""
        _write_rules(tmp_path, [
            _minimal_rule(
                id="S-001",
                engine_rule="some-rule",
                hint="Do this instead.",
                default_level="error",
            )
        ])
        ctx = _make_context(profile="standard")
        findings = [_make_finding(level="warn")]  # engine reports warn
        result = run_post_filter(findings, ctx, tmp_path)

        assert len(result.findings) == 1
        f = result.findings[0]
        assert f["rule_id"] == "S-001"
        assert f["hint"] == "Do this instead."
        assert f["level"] == "error"  # remapped from warn to error by metadata
        assert f["blocks"] is True

    def test_applicability_filters_finding(self, tmp_path: Path):
        """Non-applicable findings are silently removed."""
        _write_rules(tmp_path, [
            _minimal_rule(
                engine_rule="some-rule",
                applicability={"branch_types": ["release"]},
            )
        ])
        ctx = _make_context(branch_type="main")
        findings = [_make_finding()]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.findings == []
        assert result.result == "pass"

    def test_level_off_removes_finding(self, tmp_path: Path):
        """Level resolved to 'off' removes the finding."""
        _write_rules(tmp_path, [
            _minimal_rule(
                engine_rule="some-rule",
                default_level="off",
            )
        ])
        ctx = _make_context()
        findings = [_make_finding()]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.findings == []

    def test_conditional_override(self, tmp_path: Path):
        """Override changes level based on context."""
        _write_rules(tmp_path, [
            _minimal_rule(
                engine_rule="some-rule",
                default_level="hint",
                overrides=[
                    {
                        "condition": {"branch_types": ["release"]},
                        "level": "error",
                    }
                ],
            )
        ])
        # On main → default hint
        ctx_main = _make_context(branch_type="main", profile="standard")
        result_main = run_post_filter([_make_finding()], ctx_main, tmp_path)
        assert result_main.findings[0]["level"] == "hint"
        assert result_main.findings[0]["blocks"] is False

        # On release → override to error
        ctx_release = _make_context(branch_type="release", profile="standard")
        result_release = run_post_filter([_make_finding()], ctx_release, tmp_path)
        assert result_release.findings[0]["level"] == "error"
        assert result_release.findings[0]["blocks"] is True

    def test_engine_error_finding(self, tmp_path: Path):
        """Engine execution errors pass through and set result to 'error'."""
        ctx = _make_context()
        findings = [
            _make_finding(engine_rule="spectral-execution-error", level="error"),
        ]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.result == "error"
        assert len(result.findings) == 1
        assert result.findings[0]["blocks"] is True

    def test_advisory_profile_nothing_blocks(self, tmp_path: Path):
        ctx = _make_context(profile="advisory")
        findings = [_make_finding(level="error")]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.result == "pass"
        assert result.findings[0]["blocks"] is False

    def test_strict_profile_warns_block(self, tmp_path: Path):
        ctx = _make_context(profile="strict")
        findings = [_make_finding(level="warn")]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.result == "fail"
        assert result.findings[0]["blocks"] is True

    def test_empty_rules_dir(self, tmp_path: Path):
        """Empty rules directory → all findings pass through."""
        ctx = _make_context(profile="standard")
        findings = [
            _make_finding(level="warn"),
            _make_finding(engine_rule="other-rule", level="hint"),
        ]
        result = run_post_filter(findings, ctx, tmp_path)
        assert len(result.findings) == 2
        assert result.result == "pass"  # warn and hint don't block in standard

    def test_mixed_findings(self, tmp_path: Path):
        """Mix of mapped, unmapped, and filtered findings."""
        _write_rules(tmp_path, [
            _minimal_rule(
                id="S-001",
                engine_rule="mapped-rule",
                default_level="error",
            ),
            _minimal_rule(
                id="S-002",
                engine_rule="filtered-rule",
                applicability={"branch_types": ["release"]},
                default_level="error",
            ),
        ])
        ctx = _make_context(branch_type="main", profile="standard")
        findings = [
            _make_finding(engine_rule="mapped-rule"),
            _make_finding(engine_rule="filtered-rule"),
            _make_finding(engine_rule="unmapped-rule", level="hint"),
        ]
        result = run_post_filter(findings, ctx, tmp_path)

        # mapped-rule: enriched, error, blocks
        # filtered-rule: removed (applicability: release only)
        # unmapped-rule: pass-through, hint, doesn't block
        assert len(result.findings) == 2
        assert result.result == "fail"

        mapped = [f for f in result.findings if f.get("rule_id") == "S-001"]
        assert len(mapped) == 1
        assert mapped[0]["blocks"] is True

        unmapped = [f for f in result.findings if f["engine_rule"] == "unmapped-rule"]
        assert len(unmapped) == 1
        assert unmapped[0]["blocks"] is False

    def test_python_finding_lookup(self, tmp_path: Path):
        """Python findings go through metadata lookup like other engines."""
        _write_rules(tmp_path, [
            _minimal_rule(
                id="P-001",
                engine="python",
                engine_rule="check-info-version-format",
                hint="Use wip on main.",
                default_level="error",
            )
        ], filename="python-rules.yaml")

        ctx = _make_context(profile="standard")
        findings = [
            _make_finding(
                engine="python",
                engine_rule="check-info-version-format",
                level="warn",
            )
        ]
        result = run_post_filter(findings, ctx, tmp_path)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f["rule_id"] == "P-001"
        assert f["level"] == "error"  # remapped by metadata
        assert f["hint"] == "Use wip on main."

    def test_per_api_conditional_level(self, tmp_path: Path):
        """Different APIs get different levels based on their context."""
        _write_rules(tmp_path, [
            _minimal_rule(
                engine_rule="some-rule",
                default_level="hint",
                overrides=[
                    {
                        "condition": {"target_api_maturity": ["stable"]},
                        "level": "error",
                    }
                ],
            )
        ])

        stable_api = _make_api(api_name="stable-api", target_api_maturity="stable")
        initial_api = _make_api(api_name="initial-api", target_api_maturity="initial")
        ctx = _make_context(profile="standard", apis=(stable_api, initial_api))

        findings = [
            _make_finding(api_name="stable-api"),
            _make_finding(api_name="initial-api"),
        ]
        result = run_post_filter(findings, ctx, tmp_path)

        stable_f = [f for f in result.findings if f["api_name"] == "stable-api"][0]
        initial_f = [f for f in result.findings if f["api_name"] == "initial-api"][0]

        assert stable_f["level"] == "error"
        assert stable_f["blocks"] is True
        assert initial_f["level"] == "hint"
        assert initial_f["blocks"] is False

    def test_finding_with_unknown_api_name(self, tmp_path: Path):
        """Finding for an API not in context falls back to no api_context."""
        _write_rules(tmp_path, [
            _minimal_rule(
                engine_rule="some-rule",
                default_level="warn",
                applicability={"target_api_status": ["public"]},
            )
        ])
        ctx = _make_context()  # no APIs in context
        findings = [_make_finding(api_name="unknown-api")]
        result = run_post_filter(findings, ctx, tmp_path)
        # Per-API conditions with None api_context are unconstrained → applicable
        assert len(result.findings) == 1

    def test_passthrough_preserves_existing_hint(self, tmp_path: Path):
        """If a finding already has a hint, pass-through preserves it."""
        ctx = _make_context()
        finding = _make_finding()
        finding["hint"] = "Pre-existing hint"
        result = run_post_filter([finding], ctx, tmp_path)
        assert result.findings[0]["hint"] == "Pre-existing hint"

    def test_result_summary_content(self, tmp_path: Path):
        """Summary string contains useful information."""
        ctx = _make_context(profile="standard")
        findings = [
            _make_finding(level="error"),
            _make_finding(engine_rule="r2", level="warn"),
            _make_finding(engine_rule="r3", level="hint"),
        ]
        result = run_post_filter(findings, ctx, tmp_path)
        assert result.result == "fail"
        assert "1 errors" in result.summary
        assert "1 warnings" in result.summary
        assert "1 hints" in result.summary
