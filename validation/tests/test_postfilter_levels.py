"""Unit tests for validation.postfilter.level_resolver."""

from __future__ import annotations

import pytest

from validation.context import ApiContext, ValidationContext
from validation.postfilter.level_resolver import (
    apply_profile_blocking,
    resolve_level,
)
from validation.postfilter.metadata_loader import (
    ConditionalLevel,
    ConditionalOverride,
    RuleMetadata,
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
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type=branch_type,
        trigger_type=trigger_type,
        profile=profile,
        stage="enabled",
        target_release_type=target_release_type,
        commonalities_release=commonalities_release,
        commonalities_version=None,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


def _make_api(
    target_api_maturity: str = "stable",
    target_api_status: str = "public",
) -> ApiContext:
    return ApiContext(
        api_name="quality-on-demand",
        target_api_version="1.0.0",
        target_api_status=target_api_status,
        target_api_maturity=target_api_maturity,
        api_pattern="request-response",
        spec_file="code/API_definitions/quality-on-demand.yaml",
    )


def _make_rule(
    default: str = "warn",
    overrides: list[tuple[dict, str]] | None = None,
) -> RuleMetadata:
    """Build a RuleMetadata with given conditional level."""
    override_objs = tuple(
        ConditionalOverride(condition=cond, level=lvl)
        for cond, lvl in (overrides or [])
    )
    return RuleMetadata(
        id="S-001",
        name="test-rule",
        engine="spectral",
        engine_rule="test-rule",
        message_override=None,
        suggestion="Fix it.",
        applicability={},
        conditional_level=ConditionalLevel(
            default=default,
            overrides=override_objs,
        ),
    )


# ---------------------------------------------------------------------------
# TestResolveLevel
# ---------------------------------------------------------------------------


class TestResolveLevel:
    def test_default_only(self):
        rule = _make_rule(default="warn")
        ctx = _make_context()
        assert resolve_level(rule, ctx, None) == "warn"

    def test_override_matches(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"branch_types": ["main"]}, "warn"),
            ],
        )
        ctx = _make_context(branch_type="main")
        assert resolve_level(rule, ctx, None) == "warn"

    def test_override_does_not_match(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"branch_types": ["release"]}, "error"),
            ],
        )
        ctx = _make_context(branch_type="main")
        assert resolve_level(rule, ctx, None) == "hint"

    def test_first_match_wins(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"branch_types": ["main"]}, "warn"),
                ({"branch_types": ["main"]}, "error"),
            ],
        )
        ctx = _make_context(branch_type="main")
        assert resolve_level(rule, ctx, None) == "warn"

    def test_second_override_matches(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"branch_types": ["release"]}, "error"),
                ({"branch_types": ["main"]}, "warn"),
            ],
        )
        ctx = _make_context(branch_type="main")
        assert resolve_level(rule, ctx, None) == "warn"

    def test_override_resolves_to_muted(self):
        rule = _make_rule(
            default="warn",
            overrides=[
                ({"target_api_status": ["draft"]}, "muted"),
            ],
        )
        ctx = _make_context()
        api = _make_api(target_api_status="draft")
        assert resolve_level(rule, ctx, api) == "muted"

    def test_api_context_used_in_override(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"target_api_maturity": ["stable"]}, "warn"),
            ],
        )
        ctx = _make_context()
        api = _make_api(target_api_maturity="stable")
        assert resolve_level(rule, ctx, api) == "warn"

    def test_api_context_initial_no_match(self):
        rule = _make_rule(
            default="hint",
            overrides=[
                ({"target_api_maturity": ["stable"]}, "warn"),
            ],
        )
        ctx = _make_context()
        api = _make_api(target_api_maturity="initial")
        assert resolve_level(rule, ctx, api) == "hint"


# ---------------------------------------------------------------------------
# TestApplyProfileBlocking
# ---------------------------------------------------------------------------


class TestApplyProfileBlocking:
    # Advisory — nothing blocks
    def test_advisory_error(self):
        assert apply_profile_blocking("error", "advisory") is False

    def test_advisory_warn(self):
        assert apply_profile_blocking("warn", "advisory") is False

    def test_advisory_hint(self):
        assert apply_profile_blocking("hint", "advisory") is False

    # Standard — only errors block
    def test_standard_error(self):
        assert apply_profile_blocking("error", "standard") is True

    def test_standard_warn(self):
        assert apply_profile_blocking("warn", "standard") is False

    def test_standard_hint(self):
        assert apply_profile_blocking("hint", "standard") is False

    # Strict — errors and warnings block
    def test_strict_error(self):
        assert apply_profile_blocking("error", "strict") is True

    def test_strict_warn(self):
        assert apply_profile_blocking("warn", "strict") is True

    def test_strict_hint(self):
        assert apply_profile_blocking("hint", "strict") is False

    # Unknown profile — safe default
    def test_unknown_profile(self):
        assert apply_profile_blocking("error", "unknown") is False


# ---------------------------------------------------------------------------
# Regression: real S-016 / S-307 metadata must grade monotonically by maturity
#
# Both are completeness rules graded `warn` for draft/alpha/rc and `error` for
# public. The draft cell must not be stricter than alpha (no severity decrease
# draft -> alpha). See camaraproject/tooling#324 and the S-016 draft-cell fix.
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from validation.postfilter.metadata_loader import load_all_rules  # noqa: E402

_RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
_SEVERITY_ORDER = {"muted": 0, "hint": 1, "warn": 2, "error": 3}


def _rule_by_id(rule_id: str) -> RuleMetadata:
    for r in load_all_rules(_RULES_DIR):
        if r.id == rule_id:
            return r
    raise AssertionError(f"rule {rule_id} not found")


class TestCompletenessRuleMaturityGrading:
    """S-016 and S-307 grade warn pre-public, error at public — monotonically."""

    @pytest.mark.parametrize("rule_id", ["S-016", "S-307"])
    def test_warn_for_pre_public(self, rule_id):
        rule = _rule_by_id(rule_id)
        ctx = _make_context()
        for status in ("draft", "alpha", "rc"):
            api = _make_api(target_api_status=status)
            assert resolve_level(rule, ctx, api) == "warn", (
                f"{rule_id} at {status} should be warn"
            )

    @pytest.mark.parametrize("rule_id", ["S-016", "S-307"])
    def test_error_at_public(self, rule_id):
        rule = _rule_by_id(rule_id)
        api = _make_api(target_api_status="public")
        assert resolve_level(rule, _make_context(), api) == "error"

    @pytest.mark.parametrize("rule_id", ["S-016", "S-307"])
    def test_monotonic_non_decreasing(self, rule_id):
        """Severity must not decrease as maturity increases (draft cell guard)."""
        rule = _rule_by_id(rule_id)
        ctx = _make_context()
        levels = [
            _SEVERITY_ORDER[
                resolve_level(rule, ctx, _make_api(target_api_status=s))
            ]
            for s in ("draft", "alpha", "rc", "public")
        ]
        assert levels == sorted(levels), f"{rule_id} severity decreases: {levels}"


# ---------------------------------------------------------------------------
# Regression: P-006/P-007/P-008 (test-file rules) ramp on target_api_status,
# not target_release_type, anchored on the public/stable obligation with
# overrides only demoting.
# ---------------------------------------------------------------------------


class TestTestFileRulesStatusRamp:
    """P-006 splits by maturity; P-007/P-008 grade the same for both."""

    @pytest.mark.parametrize("status", ["draft", "alpha"])
    def test_p006_hint_pre_alpha_both_maturities(self, status):
        rule = _rule_by_id("P-006")
        ctx = _make_context()
        for maturity in ("stable", "initial"):
            api = _make_api(target_api_maturity=maturity, target_api_status=status)
            assert resolve_level(rule, ctx, api) == "hint"

    @pytest.mark.parametrize("status", ["rc", "public"])
    def test_p006_stable_error_initial_warn(self, status):
        rule = _rule_by_id("P-006")
        ctx = _make_context()
        stable = _make_api(target_api_maturity="stable", target_api_status=status)
        initial = _make_api(target_api_maturity="initial", target_api_status=status)
        assert resolve_level(rule, ctx, stable) == "error"
        assert resolve_level(rule, ctx, initial) == "warn"

    def test_p006_monotonic_both_maturities(self):
        rule = _rule_by_id("P-006")
        ctx = _make_context()
        for maturity in ("stable", "initial"):
            levels = [
                _SEVERITY_ORDER[
                    resolve_level(
                        rule,
                        ctx,
                        _make_api(target_api_maturity=maturity, target_api_status=s),
                    )
                ]
                for s in ("draft", "alpha", "rc", "public")
            ]
            assert levels == sorted(levels), f"P-006 ({maturity}) decreases: {levels}"

    @pytest.mark.parametrize("status", ["draft", "alpha"])
    def test_p007_hint_pre_rc_stable(self, status):
        rule = _rule_by_id("P-007")
        ctx = _make_context()
        api = _make_api(target_api_maturity="stable", target_api_status=status)
        assert resolve_level(rule, ctx, api) == "hint"

    @pytest.mark.parametrize("status", ["rc", "public"])
    def test_p007_warn_at_rc_public_stable(self, status):
        rule = _rule_by_id("P-007")
        ctx = _make_context()
        api = _make_api(target_api_maturity="stable", target_api_status=status)
        assert resolve_level(rule, ctx, api) == "warn"

    @pytest.mark.parametrize("status", ["draft", "alpha", "rc", "public"])
    def test_p007_initial_stays_hint(self, status):
        rule = _rule_by_id("P-007")
        ctx = _make_context()
        api = _make_api(target_api_maturity="initial", target_api_status=status)
        assert resolve_level(rule, ctx, api) == "hint"

    @pytest.mark.parametrize("status", ["draft", "alpha"])
    def test_p008_hint_pre_rc(self, status):
        rule = _rule_by_id("P-008")
        ctx = _make_context()
        for maturity in ("stable", "initial"):
            api = _make_api(target_api_maturity=maturity, target_api_status=status)
            assert resolve_level(rule, ctx, api) == "hint"

    @pytest.mark.parametrize("status", ["rc", "public"])
    def test_p008_warn_at_rc_public(self, status):
        rule = _rule_by_id("P-008")
        ctx = _make_context()
        for maturity in ("stable", "initial"):
            api = _make_api(target_api_maturity=maturity, target_api_status=status)
            assert resolve_level(rule, ctx, api) == "warn"
