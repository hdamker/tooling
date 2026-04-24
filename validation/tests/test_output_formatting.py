"""Unit tests for validation.output.formatting."""

from __future__ import annotations

from validation.output.formatting import (
    REPO_LEVEL_LABEL,
    FindingCounts,
    count_findings,
    count_findings_by_api,
    deduplicate_findings,
    format_finding_location,
    format_rule_label,
    resolve_annotation_title,
    sort_findings_by_priority,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    level: str = "warn",
    path: str = "code/API_definitions/quality-on-demand.yaml",
    line: int = 10,
    api_name: str | None = "quality-on-demand",
    blocks: bool = False,
    rule_id: str | None = None,
    engine_rule: str = "some-rule",
    column: int | None = None,
) -> dict:
    f: dict = {
        "engine": "spectral",
        "engine_rule": engine_rule,
        "level": level,
        "message": "Something is wrong",
        "path": path,
        "line": line,
        "api_name": api_name,
        "blocks": blocks,
    }
    if rule_id is not None:
        f["rule_id"] = rule_id
    if column is not None:
        f["column"] = column
    return f


# ---------------------------------------------------------------------------
# deduplicate_findings
# ---------------------------------------------------------------------------


class TestDeduplicateFindings:
    def test_no_duplicates_passthrough(self):
        """Non-duplicate findings pass through unchanged."""
        findings = [
            _make_finding(path="a.yaml", line=10, engine_rule="rule-a"),
            _make_finding(path="a.yaml", line=20, engine_rule="rule-a"),
            _make_finding(path="a.yaml", line=10, engine_rule="rule-b"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 3

    def test_same_rule_same_line_merged(self):
        """Findings with same (path, line, engine_rule) are merged."""
        f1 = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
        f1["message"] = "type is not valid"
        f2 = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
        f2["message"] = "format is not valid"

        result = deduplicate_findings([f1, f2])
        assert len(result) == 1
        assert "type is not valid" in result[0]["message"]
        assert "format is not valid" in result[0]["message"]
        assert " | " in result[0]["message"]

    def test_different_lines_not_merged(self):
        """Same rule on different lines stays separate."""
        f1 = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
        f1["message"] = "msg1"
        f2 = _make_finding(path="a.yaml", line=20, engine_rule="oas3-schema")
        f2["message"] = "msg2"

        result = deduplicate_findings([f1, f2])
        assert len(result) == 2

    def test_different_rules_not_merged(self):
        """Different rules on same line stay separate."""
        f1 = _make_finding(path="a.yaml", line=10, engine_rule="rule-a")
        f2 = _make_finding(path="a.yaml", line=10, engine_rule="rule-b")

        result = deduplicate_findings([f1, f2])
        assert len(result) == 2

    def test_severity_promotion(self):
        """Merged group gets the highest severity."""
        f1 = _make_finding(
            path="a.yaml", line=10, engine_rule="oas3-schema", level="hint",
        )
        f1["message"] = "msg1"
        f2 = _make_finding(
            path="a.yaml", line=10, engine_rule="oas3-schema", level="error",
        )
        f2["message"] = "msg2"

        result = deduplicate_findings([f1, f2])
        assert len(result) == 1
        assert result[0]["level"] == "error"

    def test_duplicate_messages_not_repeated(self):
        """Identical messages within a group appear only once."""
        f1 = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
        f1["message"] = "same message"
        f2 = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
        f2["message"] = "same message"

        result = deduplicate_findings([f1, f2])
        assert len(result) == 1
        assert result[0]["message"] == "same message"

    def test_message_cap_at_three(self):
        """More than 3 distinct messages are truncated."""
        findings = []
        for i in range(5):
            f = _make_finding(path="a.yaml", line=10, engine_rule="oas3-schema")
            f["message"] = f"msg{i}"
            findings.append(f)

        result = deduplicate_findings(findings)
        assert len(result) == 1
        assert "... and 2 more" in result[0]["message"]
        assert "msg0" in result[0]["message"]
        assert "msg1" in result[0]["message"]
        assert "msg2" in result[0]["message"]

    def test_empty_list(self):
        assert deduplicate_findings([]) == []

    def test_single_finding(self):
        f = _make_finding()
        result = deduplicate_findings([f])
        assert result == [f]

    def test_order_preserved(self):
        """First occurrence order is preserved."""
        f1 = _make_finding(path="b.yaml", line=5, engine_rule="rule-x")
        f2 = _make_finding(path="a.yaml", line=1, engine_rule="rule-y")
        f3 = _make_finding(path="b.yaml", line=5, engine_rule="rule-x")
        f3["message"] = "extra msg"

        result = deduplicate_findings([f1, f2, f3])
        assert len(result) == 2
        assert result[0]["path"] == "b.yaml"  # first occurrence
        assert result[1]["path"] == "a.yaml"


# ---------------------------------------------------------------------------
# count_findings
# ---------------------------------------------------------------------------


class TestCountFindings:
    def test_empty(self):
        result = count_findings([])
        assert result == FindingCounts(
            errors=0, warnings=0, hints=0, total=0, blocking=0
        )

    def test_mixed_levels(self):
        findings = [
            _make_finding(level="error", blocks=True),
            _make_finding(level="warn"),
            _make_finding(level="warn", blocks=True),
            _make_finding(level="hint"),
        ]
        result = count_findings(findings)
        assert result.errors == 1
        assert result.warnings == 2
        assert result.hints == 1
        assert result.total == 4
        assert result.blocking == 2

    def test_all_same_level(self):
        findings = [_make_finding(level="error") for _ in range(3)]
        result = count_findings(findings)
        assert result.errors == 3
        assert result.warnings == 0
        assert result.hints == 0
        assert result.total == 3


# ---------------------------------------------------------------------------
# count_findings_by_api
# ---------------------------------------------------------------------------


class TestCountFindingsByApi:
    def test_multi_api(self):
        findings = [
            _make_finding(api_name="api-a", level="error"),
            _make_finding(api_name="api-a", level="warn"),
            _make_finding(api_name="api-b", level="hint"),
        ]
        result = count_findings_by_api(findings)
        assert set(result.keys()) == {"api-a", "api-b"}
        assert result["api-a"].errors == 1
        assert result["api-a"].warnings == 1
        assert result["api-b"].hints == 1

    def test_repo_level_findings(self):
        findings = [
            _make_finding(api_name=None, level="error"),
            _make_finding(api_name=None, level="warn"),
        ]
        result = count_findings_by_api(findings)
        assert REPO_LEVEL_LABEL in result
        assert result[REPO_LEVEL_LABEL].total == 2

    def test_empty(self):
        result = count_findings_by_api([])
        assert result == {}

    def test_mixed_api_and_repo(self):
        findings = [
            _make_finding(api_name="api-a", level="error"),
            _make_finding(api_name=None, level="warn"),
        ]
        result = count_findings_by_api(findings)
        assert set(result.keys()) == {"api-a", REPO_LEVEL_LABEL}


# ---------------------------------------------------------------------------
# sort_findings_by_priority
# ---------------------------------------------------------------------------


class TestSortFindingsByPriority:
    def test_level_ordering(self):
        findings = [
            _make_finding(level="hint", path="a.yaml", line=1),
            _make_finding(level="error", path="a.yaml", line=1),
            _make_finding(level="warn", path="a.yaml", line=1),
        ]
        sorted_f = sort_findings_by_priority(findings)
        levels = [f["level"] for f in sorted_f]
        assert levels == ["error", "warn", "hint"]

    def test_secondary_sort_by_path_then_line(self):
        findings = [
            _make_finding(level="error", path="z.yaml", line=5),
            _make_finding(level="error", path="a.yaml", line=20),
            _make_finding(level="error", path="a.yaml", line=3),
        ]
        sorted_f = sort_findings_by_priority(findings)
        locs = [(f["path"], f["line"]) for f in sorted_f]
        assert locs == [("a.yaml", 3), ("a.yaml", 20), ("z.yaml", 5)]

    def test_empty(self):
        assert sort_findings_by_priority([]) == []

    def test_single_item(self):
        f = _make_finding()
        assert sort_findings_by_priority([f]) == [f]


# ---------------------------------------------------------------------------
# format_rule_label
# ---------------------------------------------------------------------------


class TestFormatRuleLabel:
    def test_with_rule_id(self):
        f = _make_finding(rule_id="S-042", engine_rule="some-spectral-rule")
        assert format_rule_label(f) == "S-042"

    def test_without_rule_id(self):
        f = _make_finding(engine_rule="camara-path-casing")
        assert format_rule_label(f) == "camara-path-casing"

    def test_empty_rule_id_falls_back(self):
        f = _make_finding(engine_rule="my-rule")
        f["rule_id"] = ""
        assert format_rule_label(f) == "my-rule"

    def test_missing_both(self):
        assert format_rule_label({}) == "unknown"


# ---------------------------------------------------------------------------
# format_finding_location
# ---------------------------------------------------------------------------


class TestFormatFindingLocation:
    def test_with_column(self):
        f = _make_finding(path="spec.yaml", line=42, column=8)
        assert format_finding_location(f) == "spec.yaml:42:8"

    def test_without_column(self):
        f = _make_finding(path="spec.yaml", line=42)
        assert format_finding_location(f) == "spec.yaml:42"

    def test_column_none_explicit(self):
        f = _make_finding(path="spec.yaml", line=42)
        f["column"] = None
        assert format_finding_location(f) == "spec.yaml:42"

    def test_empty_finding(self):
        assert format_finding_location({}) == ":0"


# ---------------------------------------------------------------------------
# resolve_annotation_title
# ---------------------------------------------------------------------------


class TestResolveAnnotationTitle:
    def test_uses_short_title_when_present(self):
        f = {"short_title": "Path must be kebab-case", "message": "Long message"}
        assert resolve_annotation_title(f) == "Path must be kebab-case"

    def test_falls_back_to_message_when_short_title_missing(self):
        f = {"message": "Bad pattern"}
        assert resolve_annotation_title(f) == "Bad pattern"

    def test_falls_back_to_message_when_short_title_empty(self):
        # Empty string is treated as absent — use message instead.
        f = {"short_title": "", "message": "Bad pattern"}
        assert resolve_annotation_title(f) == "Bad pattern"

    def test_message_exactly_at_70_chars_passes_through(self):
        msg = "x" * 70
        assert resolve_annotation_title({"message": msg}) == msg

    def test_message_at_71_chars_truncated(self):
        msg = "x" * 71
        result = resolve_annotation_title({"message": msg})
        assert result == "x" * 69 + "…"
        assert len(result) == 70

    def test_long_message_truncated_with_ellipsis(self):
        msg = "The quick brown fox jumps over the lazy dog and carries on for quite a while"
        result = resolve_annotation_title({"message": msg})
        assert result.endswith("…")
        # Cap enforces ≤ 70; trailing whitespace is rstripped before the
        # ellipsis so the title reads cleanly on a word boundary.
        assert len(result) <= 70
        # Prefix matches the first up-to-69 chars of the message, rstripped.
        assert result[:-1] == msg[:69].rstrip()

    def test_empty_message_returns_empty(self):
        assert resolve_annotation_title({}) == ""
        assert resolve_annotation_title({"message": ""}) == ""

    def test_short_title_not_length_capped_at_read(self):
        # The emitter assumes rule-metadata validation already enforced
        # the 70-char cap.  If somehow a longer short_title slipped
        # through, it is returned as-is (rather than silently truncated).
        long_short = "x" * 80
        assert resolve_annotation_title({"short_title": long_short}) == long_short
