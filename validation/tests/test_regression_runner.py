"""Unit tests for validation.scripts.regression_runner.

Covers pure-logic functions only: loader + schema validation, match-key
normalization, diff semantics (exact/subset, counts, summary mismatch),
capture→load round-trip, and markdown rendering. GitHub I/O helpers are
verified manually during integration.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

# validation/scripts/ is not a package — load the module directly.
_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "validation" / "scripts" / "regression_runner.py"
_spec = importlib.util.spec_from_file_location("regression_runner", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
regression_runner = importlib.util.module_from_spec(_spec)
sys.modules["regression_runner"] = regression_runner
_spec.loader.exec_module(regression_runner)


InfrastructureError = regression_runner.InfrastructureError
DiffReport = regression_runner.DiffReport
load_expected = regression_runner.load_expected
normalize_finding = regression_runner.normalize_finding
diff_findings = regression_runner.diff_findings
capture_to_yaml = regression_runner.capture_to_yaml
render_markdown = regression_runner.render_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    rule_id: str | None = "S-042",
    engine: str = "spectral",
    engine_rule: str = "operation-tag-defined",
    path: str = "code/API_definitions/sample-service.yaml",
    line: int = 12,
    level: str = "hint",
    message: str = "Operation tag is not defined",
) -> dict:
    finding: dict = {
        "engine": engine,
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
    }
    if rule_id is not None:
        finding["rule_id"] = rule_id
    return finding


def _valid_fixture() -> dict:
    return {
        "schema_version": 1,
        "branch": "regression/r4.1-main-baseline",
        "description": "baseline",
        "summary": {"errors": 0, "warnings": 0, "hints": 2},
        "match_mode": "exact",
        "findings": [
            {
                "rule_id": "S-042",
                "path": "code/API_definitions/sample-service.yaml",
                "level": "hint",
                "count": 2,
            },
            {
                "engine": "spectral",
                "engine_rule": "oas3-api-servers",
                "path": "code/API_definitions/sample-service.yaml",
                "level": "hint",
            },
        ],
    }


def _dump(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False)


# ---------------------------------------------------------------------------
# load_expected
# ---------------------------------------------------------------------------


class TestLoadExpected:
    def test_happy_path(self) -> None:
        data = load_expected(_dump(_valid_fixture()))
        assert data["branch"] == "regression/r4.1-main-baseline"
        assert len(data["findings"]) == 2

    def test_missing_schema_version(self) -> None:
        fixture = _valid_fixture()
        del fixture["schema_version"]
        with pytest.raises(InfrastructureError, match="schema_version"):
            load_expected(_dump(fixture))

    def test_invalid_rule_id_pattern(self) -> None:
        fixture = _valid_fixture()
        fixture["findings"][0]["rule_id"] = "foo-123"
        with pytest.raises(InfrastructureError, match="foo-123"):
            load_expected(_dump(fixture))

    def test_neither_rule_id_nor_engine_rule(self) -> None:
        fixture = _valid_fixture()
        fixture["findings"] = [
            {
                "path": "some.yaml",
                "level": "error",
            }
        ]
        with pytest.raises(InfrastructureError):
            load_expected(_dump(fixture))

    def test_duplicate_match_key_rejected(self) -> None:
        fixture = _valid_fixture()
        fixture["findings"] = [
            {
                "rule_id": "S-042",
                "path": "x.yaml",
                "level": "hint",
            },
            {
                "rule_id": "S-042",
                "path": "x.yaml",
                "level": "hint",
                "count": 2,
            },
        ]
        with pytest.raises(InfrastructureError, match="duplicate"):
            load_expected(_dump(fixture))

    def test_invalid_yaml_root(self) -> None:
        with pytest.raises(InfrastructureError, match="YAML mapping"):
            load_expected("- not-a-mapping\n")

    def test_invalid_match_mode(self) -> None:
        fixture = _valid_fixture()
        fixture["match_mode"] = "wibble"
        with pytest.raises(InfrastructureError):
            load_expected(_dump(fixture))


# ---------------------------------------------------------------------------
# normalize_finding
# ---------------------------------------------------------------------------


class TestNormalizeFinding:
    def test_strips_line_column_message(self) -> None:
        a = _make_finding(line=10, message="x")
        b = _make_finding(line=200, message="completely different message")
        assert normalize_finding(a) == normalize_finding(b)

    def test_uses_rule_id_when_present(self) -> None:
        f = _make_finding(rule_id="P-007")
        key = normalize_finding(f)
        assert key[0] == "P-007"

    def test_engine_rule_fallback_when_rule_id_absent(self) -> None:
        f = _make_finding(rule_id=None, engine="python", engine_rule="my-check")
        key = normalize_finding(f)
        assert key[0] == "python/my-check"


# ---------------------------------------------------------------------------
# diff_findings
# ---------------------------------------------------------------------------


class TestDiffFindings:
    def test_zero_vs_zero(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/empty",
            "match_mode": "exact",
            "findings": [],
        }))
        report = diff_findings(expected, [])
        assert report.passed
        assert report.matched == 0

    def test_baseline_clean_match(self) -> None:
        fixture = _valid_fixture()
        # Three actual hints total: S-042 ×2 + oas3-api-servers ×1
        fixture["summary"] = {"errors": 0, "warnings": 0, "hints": 3}
        expected = load_expected(_dump(fixture))
        actual = [
            _make_finding(rule_id="S-042", line=10),
            _make_finding(rule_id="S-042", line=20),
            _make_finding(
                rule_id=None, engine="spectral", engine_rule="oas3-api-servers"
            ),
        ]
        report = diff_findings(
            expected,
            actual,
            actual_summary={
                "counts": {
                    "errors": 0, "warnings": 0, "hints": 3,
                    "total": 3, "blocking": 0,
                }
            },
        )
        assert report.passed
        assert report.matched == 3
        assert not report.missing
        assert not report.unexpected
        assert report.summary_mismatch is None

    def test_missing_finding(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "findings": [
                {"rule_id": "S-042", "path": "a.yaml", "level": "hint"},
            ],
        }))
        report = diff_findings(expected, [])
        assert not report.passed
        assert len(report.missing) == 1
        assert report.missing[0]["rule"] == "S-042"
        assert report.missing[0]["expected"] == 1
        assert report.missing[0]["actual"] == 0

    def test_unexpected_extra_exact_mode(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "findings": [],
        }))
        actual = [_make_finding(rule_id="S-042")]
        report = diff_findings(expected, actual)
        assert not report.passed
        assert len(report.unexpected) == 1
        assert report.unexpected[0]["rule"] == "S-042"

    def test_unexpected_extra_subset_mode(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "subset",
            "findings": [],
        }))
        actual = [_make_finding(rule_id="S-042")]
        report = diff_findings(expected, actual)
        assert report.passed
        assert not report.unexpected

    def test_count_shortfall(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "findings": [
                {"rule_id": "S-042", "path": "a.yaml", "level": "hint", "count": 3},
            ],
        }))
        actual = [
            _make_finding(rule_id="S-042", path="a.yaml"),
            _make_finding(rule_id="S-042", path="a.yaml"),
        ]
        report = diff_findings(expected, actual)
        assert not report.passed
        assert len(report.missing) == 1
        assert report.missing[0]["expected"] == 3
        assert report.missing[0]["actual"] == 2

    def test_count_surplus_exact_mode(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "findings": [
                {"rule_id": "S-042", "path": "a.yaml", "level": "hint", "count": 2},
            ],
        }))
        actual = [
            _make_finding(rule_id="S-042", path="a.yaml"),
            _make_finding(rule_id="S-042", path="a.yaml"),
            _make_finding(rule_id="S-042", path="a.yaml"),
        ]
        report = diff_findings(expected, actual)
        assert not report.passed
        assert len(report.unexpected) == 1
        assert report.unexpected[0]["expected"] == 2
        assert report.unexpected[0]["actual"] == 3

    def test_count_surplus_subset_mode(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "subset",
            "findings": [
                {"rule_id": "S-042", "path": "a.yaml", "level": "hint", "count": 2},
            ],
        }))
        actual = [
            _make_finding(rule_id="S-042", path="a.yaml"),
            _make_finding(rule_id="S-042", path="a.yaml"),
            _make_finding(rule_id="S-042", path="a.yaml"),
        ]
        report = diff_findings(expected, actual)
        assert report.passed
        assert report.matched == 2  # min(expected=2, actual=3)

    def test_summary_mismatch_on_counts(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "summary": {"errors": 0, "warnings": 0, "hints": 0},
            "findings": [],
        }))
        report = diff_findings(expected, [], actual_summary={
            "counts": {"errors": 1, "warnings": 0, "hints": 0, "total": 1, "blocking": 1}
        })
        assert not report.passed
        assert report.summary_mismatch is not None
        assert "errors" in report.summary_mismatch

    def test_scrambled_order_still_matches(self) -> None:
        expected = load_expected(_dump({
            "schema_version": 1,
            "branch": "regression/x",
            "match_mode": "exact",
            "findings": [
                {"rule_id": "S-042", "path": "a.yaml", "level": "hint"},
                {"rule_id": "P-007", "path": "b.yaml", "level": "warn"},
            ],
        }))
        actual = [
            _make_finding(rule_id="P-007", path="b.yaml", level="warn"),
            _make_finding(rule_id="S-042", path="a.yaml", level="hint"),
        ]
        report = diff_findings(expected, actual)
        assert report.passed


# ---------------------------------------------------------------------------
# capture_to_yaml
# ---------------------------------------------------------------------------


class TestCaptureToYaml:
    def test_roundtrip(self) -> None:
        actual = [
            _make_finding(rule_id="S-042", path="a.yaml", level="hint"),
            _make_finding(rule_id="S-042", path="a.yaml", level="hint"),
            _make_finding(rule_id=None, engine="python",
                          engine_rule="check-x", path="b.yaml", level="warn"),
        ]
        text = capture_to_yaml(
            actual,
            branch="regression/r4.1-main-baseline",
            run_url="https://github.com/camaraproject/ReleaseTest/actions/runs/1",
            tooling_ref="b4c1c3e0000000000000000000000000000000b4",
            description="baseline",
        )
        # Round-trips through the loader + schema
        data = load_expected(text)
        assert data["branch"] == "regression/r4.1-main-baseline"
        assert data["summary"]["warnings"] == 1
        assert data["summary"]["hints"] == 2
        # Duplicates collapsed into count
        rule_042 = next(f for f in data["findings"] if f.get("rule_id") == "S-042")
        assert rule_042["count"] == 2
        # Engine-rule entry uses engine+engine_rule fields, not rule_id
        python_entry = next(
            f for f in data["findings"]
            if f.get("engine") == "python"
        )
        assert python_entry["engine_rule"] == "check-x"
        assert "rule_id" not in python_entry

    def test_deterministic_output(self) -> None:
        actual = [
            _make_finding(rule_id="S-099", path="z.yaml", level="hint"),
            _make_finding(rule_id="S-001", path="a.yaml", level="hint"),
        ]
        text1 = capture_to_yaml(
            actual, branch="regression/x", run_url=None, tooling_ref=None,
        )
        text2 = capture_to_yaml(
            list(reversed(actual)), branch="regression/x", run_url=None, tooling_ref=None,
        )
        # captured_at differs by timestamp but findings ordering should match
        doc1 = yaml.safe_load(text1)
        doc2 = yaml.safe_load(text2)
        assert doc1["findings"] == doc2["findings"]
        # Sorted by rule_key
        assert doc1["findings"][0]["rule_id"] == "S-001"
        assert doc1["findings"][1]["rule_id"] == "S-099"


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_mixed_pass_fail(self) -> None:
        pass_report = DiffReport(
            branch="regression/clean", match_mode="exact", matched=5,
        )
        fail_report = DiffReport(
            branch="regression/broken",
            match_mode="exact",
            matched=1,
            missing=[{"rule": "S-042", "path": "a.yaml", "level": "hint",
                      "expected": 2, "actual": 1}],
            unexpected=[{"rule": "S-099", "path": "z.yaml", "level": "warn",
                         "expected": 0, "actual": 1}],
        )
        text = render_markdown({
            "regression/clean": pass_report,
            "regression/broken": fail_report,
        })
        assert "1/2 branches PASS" in text
        assert "`regression/clean` | PASS" in text
        assert "`regression/broken` | FAIL" in text
        assert "missing" in text
        assert "unexpected" in text
        assert "S-042" in text
        assert "S-099" in text

    def test_all_pass_no_detail_section(self) -> None:
        report = DiffReport(
            branch="regression/clean", match_mode="exact", matched=27,
        )
        text = render_markdown({"regression/clean": report})
        assert "1/1 branches PASS" in text
        assert "PASS" in text
        assert "diff detail" not in text
