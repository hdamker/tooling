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
        stage="standard",
        target_release_type=target_release_type,
        commonalities_release=commonalities_release,
        icm_release=None,
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
        hint="Fix it.",
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

    def test_override_resolves_to_off(self):
        rule = _make_rule(
            default="warn",
            overrides=[
                ({"target_api_status": ["draft"]}, "off"),
            ],
        )
        ctx = _make_context()
        api = _make_api(target_api_status="draft")
        assert resolve_level(rule, ctx, api) == "off"

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
