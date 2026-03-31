"""Unit tests for validation.postfilter.condition_evaluator."""

from __future__ import annotations

import pytest

from validation.context import ApiContext, ValidationContext
from validation.postfilter.condition_evaluator import (
    evaluate_condition,
    evaluate_version_range,
    is_applicable,
    parse_version_tuple,
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
    release_plan_changed: bool | None = None,
    apis: tuple[ApiContext, ...] = (),
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type=branch_type,
        trigger_type=trigger_type,
        profile=profile,
        stage="enabled",
        target_release_type=target_release_type,
        commonalities_release=commonalities_release,
        icm_release=None,
        is_release_review_pr=is_release_review_pr,
        release_plan_changed=release_plan_changed,
        pr_number=None,
        apis=apis,
        workflow_run_url="",
        tooling_ref="",
    )


def _make_api(
    api_name: str = "quality-on-demand",
    target_api_status: str = "public",
    target_api_maturity: str = "stable",
    api_pattern: str = "request-response",
) -> ApiContext:
    return ApiContext(
        api_name=api_name,
        target_api_version="1.0.0",
        target_api_status=target_api_status,
        target_api_maturity=target_api_maturity,
        api_pattern=api_pattern,
        spec_file=f"code/API_definitions/{api_name}.yaml",
    )


# ---------------------------------------------------------------------------
# TestParseVersionTuple
# ---------------------------------------------------------------------------


class TestParseVersionTuple:
    def test_r_prefix(self):
        assert parse_version_tuple("r3.4") == (3, 4)

    def test_capital_r_prefix(self):
        assert parse_version_tuple("R4.1") == (4, 1)

    def test_no_prefix(self):
        assert parse_version_tuple("4.1") == (4, 1)

    def test_single_digit(self):
        assert parse_version_tuple("r5") == (5,)

    def test_three_parts(self):
        assert parse_version_tuple("r4.1.2") == (4, 1, 2)

    def test_malformed(self):
        assert parse_version_tuple("abc") == (0,)

    def test_empty(self):
        assert parse_version_tuple("") == (0,)


# ---------------------------------------------------------------------------
# TestEvaluateVersionRange
# ---------------------------------------------------------------------------


class TestEvaluateVersionRange:
    def test_gte_match(self):
        assert evaluate_version_range(">=r3.4", "r4.1") is True

    def test_gte_exact(self):
        assert evaluate_version_range(">=r3.4", "r3.4") is True

    def test_gte_below(self):
        assert evaluate_version_range(">=r4.0", "r3.4") is False

    def test_gt(self):
        assert evaluate_version_range(">r3.4", "r3.5") is True
        assert evaluate_version_range(">r3.4", "r3.4") is False

    def test_lte(self):
        assert evaluate_version_range("<=r4.0", "r3.4") is True
        assert evaluate_version_range("<=r4.0", "r4.0") is True
        assert evaluate_version_range("<=r4.0", "r4.1") is False

    def test_lt(self):
        assert evaluate_version_range("<r5.0", "r4.2") is True
        assert evaluate_version_range("<r5.0", "r5.0") is False

    def test_eq(self):
        assert evaluate_version_range("==r4.1", "r4.1") is True
        assert evaluate_version_range("==r4.1", "r4.2") is False

    def test_neq(self):
        assert evaluate_version_range("!=r3.4", "r4.1") is True
        assert evaluate_version_range("!=r4.1", "r4.1") is False

    def test_none_version(self):
        assert evaluate_version_range(">=r3.4", None) is False

    def test_malformed_expression(self):
        assert evaluate_version_range("r3.4", "r4.1") is False

    def test_whitespace(self):
        assert evaluate_version_range(">= r3.4", "r4.1") is True


# ---------------------------------------------------------------------------
# TestEvaluateCondition
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    """Test evaluate_condition with individual and combined fields."""

    # --- Array fields (repo-level) ---

    def test_branch_types_match(self):
        ctx = _make_context(branch_type="main")
        assert evaluate_condition({"branch_types": ["main", "release"]}, ctx, None)

    def test_branch_types_no_match(self):
        ctx = _make_context(branch_type="feature")
        assert not evaluate_condition({"branch_types": ["main", "release"]}, ctx, None)

    def test_trigger_types_match(self):
        ctx = _make_context(trigger_type="pr")
        assert evaluate_condition({"trigger_types": ["pr", "dispatch"]}, ctx, None)

    def test_trigger_types_no_match(self):
        ctx = _make_context(trigger_type="local")
        assert not evaluate_condition({"trigger_types": ["pr"]}, ctx, None)

    def test_target_release_type_match(self):
        ctx = _make_context(target_release_type="public-release")
        assert evaluate_condition(
            {"target_release_type": ["public-release", "pre-release-rc"]}, ctx, None
        )

    def test_target_release_type_none(self):
        ctx = _make_context(target_release_type=None)
        assert not evaluate_condition(
            {"target_release_type": ["public-release"]}, ctx, None
        )

    # --- Per-API array fields ---

    def test_target_api_status_match(self):
        ctx = _make_context()
        api = _make_api(target_api_status="public")
        assert evaluate_condition(
            {"target_api_status": ["public", "rc"]}, ctx, api
        )

    def test_target_api_status_no_match(self):
        ctx = _make_context()
        api = _make_api(target_api_status="draft")
        assert not evaluate_condition(
            {"target_api_status": ["public"]}, ctx, api
        )

    def test_target_api_maturity_match(self):
        ctx = _make_context()
        api = _make_api(target_api_maturity="stable")
        assert evaluate_condition(
            {"target_api_maturity": ["stable"]}, ctx, api
        )

    def test_api_pattern_match(self):
        ctx = _make_context()
        api = _make_api(api_pattern="implicit-subscription")
        assert evaluate_condition(
            {"api_pattern": ["implicit-subscription", "explicit-subscription"]},
            ctx,
            api,
        )

    def test_api_field_with_none_api_context(self):
        """Per-API conditions are unconstrained when api_context is None."""
        ctx = _make_context()
        assert evaluate_condition(
            {"target_api_status": ["public"]}, ctx, None
        )

    # --- Range field ---

    def test_commonalities_release_match(self):
        ctx = _make_context(commonalities_release="r4.1")
        assert evaluate_condition(
            {"commonalities_release": ">=r3.4"}, ctx, None
        )

    def test_commonalities_release_no_match(self):
        ctx = _make_context(commonalities_release="r3.3")
        assert not evaluate_condition(
            {"commonalities_release": ">=r3.4"}, ctx, None
        )

    # --- Boolean fields ---

    def test_is_release_review_pr_true(self):
        ctx = _make_context(is_release_review_pr=True)
        assert evaluate_condition({"is_release_review_pr": True}, ctx, None)

    def test_is_release_review_pr_false(self):
        ctx = _make_context(is_release_review_pr=False)
        assert not evaluate_condition({"is_release_review_pr": True}, ctx, None)

    def test_release_plan_changed_true(self):
        ctx = _make_context(release_plan_changed=True)
        assert evaluate_condition({"release_plan_changed": True}, ctx, None)

    def test_release_plan_changed_none(self):
        ctx = _make_context(release_plan_changed=None)
        assert not evaluate_condition({"release_plan_changed": True}, ctx, None)

    # --- AND across fields ---

    def test_and_logic_all_match(self):
        ctx = _make_context(branch_type="release", trigger_type="pr")
        api = _make_api(target_api_maturity="stable")
        condition = {
            "branch_types": ["release"],
            "trigger_types": ["pr"],
            "target_api_maturity": ["stable"],
        }
        assert evaluate_condition(condition, ctx, api)

    def test_and_logic_one_fails(self):
        ctx = _make_context(branch_type="main", trigger_type="pr")
        condition = {
            "branch_types": ["release"],
            "trigger_types": ["pr"],
        }
        assert not evaluate_condition(condition, ctx, None)

    # --- Empty condition ---

    def test_empty_condition_matches(self):
        ctx = _make_context()
        assert evaluate_condition({}, ctx, None)

    # --- Unknown field ---

    def test_unknown_field_does_not_match(self):
        ctx = _make_context()
        assert not evaluate_condition({"unknown_field": "value"}, ctx, None)


# ---------------------------------------------------------------------------
# TestIsApplicable
# ---------------------------------------------------------------------------


class TestIsApplicable:
    def test_empty_applicability(self):
        ctx = _make_context()
        assert is_applicable({}, ctx, None)

    def test_matching_applicability(self):
        ctx = _make_context(branch_type="main")
        assert is_applicable({"branch_types": ["main"]}, ctx, None)

    def test_non_matching_applicability(self):
        ctx = _make_context(branch_type="feature")
        assert not is_applicable({"branch_types": ["main"]}, ctx, None)
