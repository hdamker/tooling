"""Unit tests for validation.output.commit_status."""

from __future__ import annotations

from validation.context import ValidationContext
from validation.output.commit_status import (
    STATUS_CONTEXT,
    CommitStatusPayload,
    generate_commit_status,
)
from validation.postfilter.engine import PostFilterResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    workflow_run_url: str = "https://github.com/test/run/1",
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="pr",
        profile="standard",
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(),
        workflow_run_url=workflow_run_url,
        tooling_ref="abc1234",
    )


def _make_result(
    result: str = "pass",
    summary: str = "Passed: no findings",
) -> PostFilterResult:
    return PostFilterResult(findings=[], result=result, summary=summary)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateCommitStatus:
    def test_pass_maps_to_success(self):
        payload = generate_commit_status(_make_result("pass"), _make_context())
        assert payload.state == "success"

    def test_fail_maps_to_failure(self):
        payload = generate_commit_status(_make_result("fail"), _make_context())
        assert payload.state == "failure"

    def test_error_maps_to_error(self):
        payload = generate_commit_status(_make_result("error"), _make_context())
        assert payload.state == "error"

    def test_unknown_result_maps_to_error(self):
        payload = generate_commit_status(_make_result("unknown"), _make_context())
        assert payload.state == "error"

    def test_context_is_camara_validation(self):
        payload = generate_commit_status(_make_result(), _make_context())
        assert payload.context == STATUS_CONTEXT
        assert payload.context == "CAMARA Validation"

    def test_target_url(self):
        url = "https://github.com/test/run/42"
        payload = generate_commit_status(
            _make_result(), _make_context(workflow_run_url=url)
        )
        assert payload.target_url == url

    def test_description_from_summary(self):
        payload = generate_commit_status(
            _make_result(summary="Passed: no findings"),
            _make_context(),
        )
        assert payload.description == "Passed: no findings"

    def test_description_truncated_at_140(self):
        long_summary = "x" * 200
        payload = generate_commit_status(
            _make_result(summary=long_summary),
            _make_context(),
        )
        assert len(payload.description) <= 140
        assert payload.description.endswith("\u2026")

    def test_description_exactly_140_not_truncated(self):
        summary = "x" * 140
        payload = generate_commit_status(
            _make_result(summary=summary),
            _make_context(),
        )
        assert payload.description == summary
        assert "\u2026" not in payload.description

    def test_frozen(self):
        payload = generate_commit_status(_make_result(), _make_context())
        try:
            payload.state = "failure"  # type: ignore[misc]
            assert False, "Should not be able to mutate frozen dataclass"
        except AttributeError:
            pass
