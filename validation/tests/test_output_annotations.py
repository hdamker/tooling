"""Unit tests for validation.output.annotations."""

from __future__ import annotations

from validation.output.annotations import (
    ANNOTATION_LIMIT,
    AnnotationResult,
    _build_command,
    _sanitize_message,
    generate_annotations,
)
from validation.postfilter.engine import PostFilterResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    level: str = "warn",
    path: str = "code/API_definitions/quality-on-demand.yaml",
    line: int = 10,
    column: int | None = None,
    message: str = "Something is wrong",
    hint: str | None = None,
    rule_id: str | None = None,
    engine_rule: str = "some-rule",
    api_name: str | None = "quality-on-demand",
    blocks: bool = False,
) -> dict:
    f: dict = {
        "engine": "spectral",
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
        "api_name": api_name,
        "blocks": blocks,
    }
    if column is not None:
        f["column"] = column
    if rule_id is not None:
        f["rule_id"] = rule_id
    if hint is not None:
        f["hint"] = hint
    return f


def _make_result(findings: list[dict]) -> PostFilterResult:
    return PostFilterResult(findings=findings, result="fail", summary="test")


# ---------------------------------------------------------------------------
# _sanitize_message
# ---------------------------------------------------------------------------


class TestSanitizeMessage:
    def test_newlines_replaced(self):
        assert " " in _sanitize_message("line1\nline2")
        assert "\n" not in _sanitize_message("line1\nline2")

    def test_carriage_return_replaced(self):
        assert "\r" not in _sanitize_message("a\rb")

    def test_crlf_replaced(self):
        assert "\r\n" not in _sanitize_message("a\r\nb")

    def test_colons_encoded(self):
        result = _sanitize_message("key::value")
        assert "::" not in result
        assert "%3A" in result

    def test_plain_text_unchanged(self):
        assert _sanitize_message("hello world") == "hello world"


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_error_level(self):
        f = _make_finding(level="error", path="a.yaml", line=5)
        cmd = _build_command(f)
        assert cmd.startswith("::error ")

    def test_warn_level(self):
        f = _make_finding(level="warn")
        cmd = _build_command(f)
        assert cmd.startswith("::warning ")

    def test_hint_level(self):
        f = _make_finding(level="hint")
        cmd = _build_command(f)
        assert cmd.startswith("::notice ")

    def test_file_and_line(self):
        f = _make_finding(path="spec.yaml", line=42)
        cmd = _build_command(f)
        assert "file=spec.yaml" in cmd
        assert "line=42" in cmd

    def test_column_included(self):
        f = _make_finding(column=8)
        cmd = _build_command(f)
        assert "col=8" in cmd

    def test_column_omitted_when_none(self):
        f = _make_finding(column=None)
        cmd = _build_command(f)
        assert "col=" not in cmd

    def test_title_uses_message(self):
        f = _make_finding(rule_id="S-042", message="Bad path")
        cmd = _build_command(f)
        assert "title=Bad path" in cmd

    def test_rule_id_in_message_body(self):
        f = _make_finding(rule_id="S-042", message="Bad path")
        cmd = _build_command(f)
        assert "[S-042] Bad path" in cmd

    def test_rule_id_fallback_in_message_body(self):
        f = _make_finding(engine_rule="camara-path-casing", message="Bad path")
        cmd = _build_command(f)
        assert "[camara-path-casing] Bad path" in cmd

    def test_hint_appended(self):
        f = _make_finding(message="Bad path", hint="Use kebab-case")
        cmd = _build_command(f)
        assert "Bad path | Hint%3A Use kebab-case" in cmd

    def test_no_hint(self):
        f = _make_finding(message="Bad path")
        cmd = _build_command(f)
        assert "Hint" not in cmd


# ---------------------------------------------------------------------------
# generate_annotations
# ---------------------------------------------------------------------------


class TestGenerateAnnotations:
    def test_empty_findings(self):
        result = generate_annotations(_make_result([]))
        assert result == AnnotationResult(
            commands=[], total_findings=0, annotations_emitted=0, truncated=False
        )

    def test_single_finding(self):
        findings = [_make_finding(level="error")]
        result = generate_annotations(_make_result(findings))
        assert result.total_findings == 1
        assert result.annotations_emitted == 1
        assert not result.truncated
        assert result.commands[0].startswith("::error ")

    def test_priority_ordering(self):
        findings = [
            _make_finding(level="hint", path="a.yaml", line=1),
            _make_finding(level="error", path="a.yaml", line=1),
            _make_finding(level="warn", path="a.yaml", line=1),
        ]
        result = generate_annotations(_make_result(findings))
        assert result.commands[0].startswith("::error ")
        assert result.commands[1].startswith("::warning ")
        assert result.commands[2].startswith("::notice ")

    def test_limit_enforced(self):
        findings = [
            _make_finding(level="error", line=i) for i in range(60)
        ]
        result = generate_annotations(_make_result(findings))
        assert result.total_findings == 60
        assert result.annotations_emitted == ANNOTATION_LIMIT
        assert result.truncated

    def test_limit_prioritises_errors(self):
        errors = [_make_finding(level="error", line=i) for i in range(30)]
        warnings = [_make_finding(level="warn", line=i) for i in range(30)]
        findings = warnings + errors  # Interleave — warnings first in input
        result = generate_annotations(_make_result(findings))
        # All 30 errors should be in the first 30 commands
        error_cmds = [c for c in result.commands if c.startswith("::error ")]
        assert len(error_cmds) == 30
        # Remaining 20 are warnings
        warn_cmds = [c for c in result.commands if c.startswith("::warning ")]
        assert len(warn_cmds) == 20

    def test_exactly_at_limit_not_truncated(self):
        findings = [_make_finding(line=i) for i in range(ANNOTATION_LIMIT)]
        result = generate_annotations(_make_result(findings))
        assert result.annotations_emitted == ANNOTATION_LIMIT
        assert not result.truncated
