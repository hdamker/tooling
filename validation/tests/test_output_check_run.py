"""Unit tests for validation.output.check_run."""

from __future__ import annotations

from validation.context import ValidationContext
from validation.output.check_run import (
    CheckRunPayload,
    generate_check_run_payload,
)
from validation.postfilter.engine import PostFilterResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    profile: str = "standard",
    branch_type: str = "main",
    trigger_type: str = "pr",
) -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type=branch_type,
        trigger_type=trigger_type,
        profile=profile,
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        icm_release=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


def _make_finding(
    level: str = "warn",
    path: str = "code/API_definitions/quality-on-demand.yaml",
    line: int = 10,
    message: str = "Something is wrong",
    rule_id: str | None = None,
    engine_rule: str = "some-rule",
    hint: str | None = None,
) -> dict:
    f: dict = {
        "engine": "spectral",
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
        "api_name": "quality-on-demand",
        "blocks": False,
    }
    if rule_id is not None:
        f["rule_id"] = rule_id
    if hint is not None:
        f["hint"] = hint
    return f


def _make_result(
    findings: list[dict] | None = None,
    result: str = "pass",
) -> PostFilterResult:
    return PostFilterResult(
        findings=findings or [],
        result=result,
        summary="test summary",
    )


# ---------------------------------------------------------------------------
# Conclusion mapping
# ---------------------------------------------------------------------------


class TestConclusion:
    def test_pass_result(self):
        payload = generate_check_run_payload(_make_result(), _make_context())
        assert payload.conclusion == "success"

    def test_fail_result(self):
        findings = [_make_finding(level="error")]
        payload = generate_check_run_payload(
            _make_result(findings, result="fail"),
            _make_context(),
        )
        assert payload.conclusion == "failure"

    def test_error_result(self):
        payload = generate_check_run_payload(
            _make_result(result="error"),
            _make_context(),
        )
        assert payload.conclusion == "failure"

    def test_advisory_with_findings(self):
        """Advisory profile + pass + findings → neutral."""
        findings = [_make_finding()]
        payload = generate_check_run_payload(
            _make_result(findings, result="pass"),
            _make_context(profile="advisory"),
        )
        assert payload.conclusion == "neutral"

    def test_advisory_no_findings(self):
        """Advisory profile + pass + no findings → success."""
        payload = generate_check_run_payload(
            _make_result(),
            _make_context(profile="advisory"),
        )
        assert payload.conclusion == "success"


# ---------------------------------------------------------------------------
# Annotation level mapping
# ---------------------------------------------------------------------------


class TestAnnotationLevel:
    def test_error_to_failure(self):
        findings = [_make_finding(level="error")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert payload.annotations[0]["annotation_level"] == "failure"

    def test_warn_to_warning(self):
        findings = [_make_finding(level="warn")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert payload.annotations[0]["annotation_level"] == "warning"

    def test_hint_to_notice(self):
        findings = [_make_finding(level="hint")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert payload.annotations[0]["annotation_level"] == "notice"


# ---------------------------------------------------------------------------
# Annotation content
# ---------------------------------------------------------------------------


class TestAnnotationContent:
    def test_path_and_line(self):
        findings = [_make_finding(path="spec.yaml", line=42)]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        ann = payload.annotations[0]
        assert ann["path"] == "spec.yaml"
        assert ann["start_line"] == 42
        assert ann["end_line"] == 42

    def test_title_uses_rule_id(self):
        findings = [_make_finding(rule_id="S-042")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert payload.annotations[0]["title"] == "S-042"

    def test_title_falls_back_to_engine_rule(self):
        findings = [_make_finding(engine_rule="my-check")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert payload.annotations[0]["title"] == "my-check"

    def test_message_content(self):
        findings = [_make_finding(message="Bad pattern")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert "Bad pattern" in payload.annotations[0]["message"]

    def test_hint_appended_to_message(self):
        findings = [_make_finding(message="Bad", hint="Use kebab-case")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        msg = payload.annotations[0]["message"]
        assert "Bad" in msg
        assert "Hint: Use kebab-case" in msg


# ---------------------------------------------------------------------------
# Title and summary
# ---------------------------------------------------------------------------


class TestTitleAndSummary:
    def test_title_counts(self):
        findings = [
            _make_finding(level="error"),
            _make_finding(level="warn"),
            _make_finding(level="warn"),
            _make_finding(level="hint"),
        ]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert "1 error" in payload.title
        assert "2 warnings" in payload.title
        assert "1 hint" in payload.title

    def test_title_singular(self):
        findings = [_make_finding(level="error")]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert "1 error," in payload.title
        assert "0 warnings" in payload.title
        assert "0 hints" in payload.title

    def test_empty_findings_title(self):
        payload = generate_check_run_payload(_make_result(), _make_context())
        assert "0 errors" in payload.title

    def test_summary_contains_profile(self):
        payload = generate_check_run_payload(
            _make_result(),
            _make_context(profile="strict"),
        )
        assert "strict" in payload.summary


# ---------------------------------------------------------------------------
# All findings included (no truncation)
# ---------------------------------------------------------------------------


class TestNoTruncation:
    def test_all_findings_included(self):
        findings = [_make_finding(line=i) for i in range(100)]
        payload = generate_check_run_payload(
            _make_result(findings), _make_context(),
        )
        assert len(payload.annotations) == 100

    def test_empty_findings(self):
        payload = generate_check_run_payload(_make_result(), _make_context())
        assert payload.annotations == []
        assert payload.conclusion == "success"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict(self):
        payload = generate_check_run_payload(_make_result(), _make_context())
        d = payload.to_dict()
        assert isinstance(d, dict)
        assert "conclusion" in d
        assert "title" in d
        assert "summary" in d
        assert "annotations" in d

    def test_frozen(self):
        payload = CheckRunPayload(
            conclusion="success", title="t", summary="s", annotations=[],
        )
        try:
            payload.conclusion = "failure"  # type: ignore[misc]
            assert False, "Should not mutate frozen dataclass"
        except AttributeError:
            pass
