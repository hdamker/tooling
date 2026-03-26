"""Unit tests for validation.output.formatting."""

from __future__ import annotations

from validation.output.formatting import (
    REPO_LEVEL_LABEL,
    FindingCounts,
    count_findings,
    count_findings_by_api,
    format_finding_location,
    format_rule_label,
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
