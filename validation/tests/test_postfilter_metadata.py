"""Unit tests for validation.postfilter.metadata_loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validation.postfilter.metadata_loader import (
    ConditionalLevel,
    ConditionalOverride,
    RuleMetadata,
    build_lookup_index,
    load_all_rules,
    load_rules_from_file,
    parse_rule_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_rule_dict(**overrides: object) -> dict:
    """Build a minimal valid rule metadata dict (only required fields)."""
    base: dict = {
        "id": "S-001",
        "engine": "spectral",
        "engine_rule": "camara-test-rule",
    }
    base.update(overrides)
    return base


def _full_rule_dict(**overrides: object) -> dict:
    """Build a rule metadata dict with all optional fields populated."""
    base: dict = {
        "id": "S-001",
        "name": "test-rule",
        "engine": "spectral",
        "engine_rule": "camara-test-rule",
        "message_override": "Overridden message.",
        "hint": "Fix this issue.",
        "conditional_level": {"default": "warn"},
    }
    base.update(overrides)
    return base


def _write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestParseRuleMetadata
# ---------------------------------------------------------------------------


class TestParseRuleMetadata:
    def test_identity_only(self):
        """Minimal entry: just id, engine, engine_rule."""
        raw = _minimal_rule_dict()
        rule = parse_rule_metadata(raw)
        assert rule.id == "S-001"
        assert rule.name == "camara-test-rule"  # defaults to engine_rule
        assert rule.engine == "spectral"
        assert rule.engine_rule == "camara-test-rule"
        assert rule.message_override is None
        assert rule.hint is None
        assert rule.applicability == {}
        assert rule.conditional_level is None

    def test_full_entry(self):
        raw = _full_rule_dict()
        rule = parse_rule_metadata(raw)
        assert rule.id == "S-001"
        assert rule.name == "test-rule"
        assert rule.message_override == "Overridden message."
        assert rule.hint == "Fix this issue."
        assert rule.conditional_level is not None
        assert rule.conditional_level.default == "warn"
        assert rule.conditional_level.overrides == ()

    def test_name_defaults_to_engine_rule(self):
        raw = _minimal_rule_dict()
        rule = parse_rule_metadata(raw)
        assert rule.name == "camara-test-rule"

    def test_explicit_name_overrides_default(self):
        raw = _minimal_rule_dict(name="custom-name")
        rule = parse_rule_metadata(raw)
        assert rule.name == "custom-name"

    def test_optional_fields_default_to_none(self):
        raw = _minimal_rule_dict()
        rule = parse_rule_metadata(raw)
        assert rule.message_override is None
        assert rule.hint is None
        assert rule.suppress_schema_paths == ()

    def test_suppress_schema_paths_parsed(self):
        """suppress_schema_paths is an optional list that becomes a tuple."""
        raw = _minimal_rule_dict(
            suppress_schema_paths=[
                "components.schemas.ErrorInfo.properties.code",
                "components.schemas.NetworkAccessIdentifier",
            ]
        )
        rule = parse_rule_metadata(raw)
        assert rule.suppress_schema_paths == (
            "components.schemas.ErrorInfo.properties.code",
            "components.schemas.NetworkAccessIdentifier",
        )

    def test_suppress_schema_paths_empty_list(self):
        raw = _minimal_rule_dict(suppress_schema_paths=[])
        rule = parse_rule_metadata(raw)
        assert rule.suppress_schema_paths == ()

    def test_suppress_schema_paths_invalid_type_raises(self):
        raw = _minimal_rule_dict(suppress_schema_paths="not-a-list")
        with pytest.raises(ValueError, match="suppress_schema_paths"):
            parse_rule_metadata(raw)

    def test_suppress_schema_paths_drops_non_string_entries(self):
        """Non-string entries are silently dropped (defensive)."""
        raw = _minimal_rule_dict(
            suppress_schema_paths=[
                "components.schemas.Valid",
                123,  # not a string
                "",   # empty
                "components.schemas.AlsoValid",
            ]
        )
        rule = parse_rule_metadata(raw)
        assert rule.suppress_schema_paths == (
            "components.schemas.Valid",
            "components.schemas.AlsoValid",
        )

    def test_explicit_message_override(self):
        raw = _minimal_rule_dict(message_override="Better message.")
        rule = parse_rule_metadata(raw)
        assert rule.message_override == "Better message."

    def test_explicit_hint(self):
        raw = _minimal_rule_dict(hint="Do this instead.")
        rule = parse_rule_metadata(raw)
        assert rule.hint == "Do this instead."

    def test_both_message_override_and_hint(self):
        raw = _minimal_rule_dict(
            message_override="Overridden.", hint="Fix guidance."
        )
        rule = parse_rule_metadata(raw)
        assert rule.message_override == "Overridden."
        assert rule.hint == "Fix guidance."

    def test_with_applicability(self):
        raw = _minimal_rule_dict(
            applicability={"branch_types": ["main", "release"]}
        )
        rule = parse_rule_metadata(raw)
        assert rule.applicability == {"branch_types": ["main", "release"]}

    def test_with_overrides(self):
        raw = _full_rule_dict(
            conditional_level={
                "default": "hint",
                "overrides": [
                    {
                        "condition": {"target_api_maturity": ["stable"]},
                        "level": "warn",
                    },
                    {
                        "condition": {"branch_types": ["release"]},
                        "level": "error",
                    },
                ],
            }
        )
        rule = parse_rule_metadata(raw)
        assert rule.conditional_level.default == "hint"
        assert len(rule.conditional_level.overrides) == 2
        assert rule.conditional_level.overrides[0].level == "warn"
        assert rule.conditional_level.overrides[1].level == "error"
        assert rule.conditional_level.overrides[0].condition == {
            "target_api_maturity": ["stable"]
        }

    def test_missing_required_field(self):
        with pytest.raises(ValueError, match="engine_rule"):
            parse_rule_metadata({"id": "S-001", "engine": "spectral"})

    def test_missing_multiple_fields(self):
        with pytest.raises(ValueError, match="id"):
            parse_rule_metadata({"engine": "spectral"})

    def test_conditional_level_missing_default(self):
        raw = _minimal_rule_dict(conditional_level={"overrides": []})
        with pytest.raises(ValueError, match="default"):
            parse_rule_metadata(raw)

    def test_conditional_level_not_a_dict(self):
        raw = _minimal_rule_dict(conditional_level="error")
        with pytest.raises(ValueError, match="mapping"):
            parse_rule_metadata(raw)

    def test_override_with_empty_condition(self):
        raw = _full_rule_dict(
            conditional_level={
                "default": "warn",
                "overrides": [{"condition": {}, "level": "error"}],
            }
        )
        rule = parse_rule_metadata(raw)
        assert rule.conditional_level.overrides[0].condition == {}

    def test_non_dict_override_entries_skipped(self):
        raw = _full_rule_dict(
            conditional_level={
                "default": "warn",
                "overrides": ["invalid", {"condition": {}, "level": "hint"}],
            }
        )
        rule = parse_rule_metadata(raw)
        assert len(rule.conditional_level.overrides) == 1


# ---------------------------------------------------------------------------
# TestLoadRulesFromFile
# ---------------------------------------------------------------------------


class TestLoadRulesFromFile:
    def test_valid_file(self, tmp_path: Path):
        f = tmp_path / "spectral-rules.yaml"
        _write_yaml(f, [_minimal_rule_dict()])
        rules = load_rules_from_file(f)
        assert len(rules) == 1
        assert rules[0].id == "S-001"

    def test_multiple_rules(self, tmp_path: Path):
        f = tmp_path / "spectral-rules.yaml"
        _write_yaml(
            f,
            [
                _minimal_rule_dict(id="S-001", engine_rule="rule-a"),
                _minimal_rule_dict(id="S-002", engine_rule="rule-b"),
            ],
        )
        rules = load_rules_from_file(f)
        assert len(rules) == 2

    def test_missing_file(self, tmp_path: Path):
        f = tmp_path / "does-not-exist.yaml"
        assert load_rules_from_file(f) == []

    def test_malformed_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.yaml"
        f.write_text(": :\n  : - [\n", encoding="utf-8")
        assert load_rules_from_file(f) == []

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        # yaml.safe_load returns None for empty → not a list → []
        assert load_rules_from_file(f) == []

    def test_non_array_yaml(self, tmp_path: Path):
        f = tmp_path / "dict.yaml"
        _write_yaml(f, {"not": "a list"})
        assert load_rules_from_file(f) == []

    def test_malformed_entry_skipped(self, tmp_path: Path):
        f = tmp_path / "mixed.yaml"
        _write_yaml(
            f,
            [
                _minimal_rule_dict(id="S-001"),
                {"name": "no-id"},  # missing required fields
                _minimal_rule_dict(id="S-003", engine_rule="rule-b"),
            ],
        )
        rules = load_rules_from_file(f)
        assert len(rules) == 2
        assert rules[0].id == "S-001"
        assert rules[1].id == "S-003"

    def test_non_dict_entry_skipped(self, tmp_path: Path):
        f = tmp_path / "mixed.yaml"
        _write_yaml(f, [_minimal_rule_dict(id="S-001"), "not a dict"])
        rules = load_rules_from_file(f)
        assert len(rules) == 1


# ---------------------------------------------------------------------------
# TestLoadAllRules
# ---------------------------------------------------------------------------


class TestLoadAllRules:
    def test_multiple_files(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "spectral-rules.yaml",
            [_minimal_rule_dict(id="S-001", engine="spectral")],
        )
        _write_yaml(
            tmp_path / "python-rules.yaml",
            [_minimal_rule_dict(id="P-001", engine="python", engine_rule="check-x")],
        )
        rules = load_all_rules(tmp_path)
        assert len(rules) == 2
        ids = {r.id for r in rules}
        assert ids == {"S-001", "P-001"}

    def test_empty_directory(self, tmp_path: Path):
        assert load_all_rules(tmp_path) == []

    def test_nonexistent_directory(self, tmp_path: Path):
        assert load_all_rules(tmp_path / "nope") == []

    def test_ignores_non_matching_files(self, tmp_path: Path):
        _write_yaml(tmp_path / "spectral-rules.yaml", [_minimal_rule_dict()])
        _write_yaml(
            tmp_path / "README.yaml",
            [_minimal_rule_dict(id="X-001", engine_rule="other")],
        )
        rules = load_all_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0].id == "S-001"


# ---------------------------------------------------------------------------
# TestBuildLookupIndex
# ---------------------------------------------------------------------------


class TestBuildLookupIndex:
    def test_normal_case(self):
        rules = [
            parse_rule_metadata(
                _minimal_rule_dict(id="S-001", engine="spectral", engine_rule="rule-a")
            ),
            parse_rule_metadata(
                _minimal_rule_dict(id="P-001", engine="python", engine_rule="check-x")
            ),
        ]
        index = build_lookup_index(rules)
        assert ("spectral", "rule-a") in index
        assert ("python", "check-x") in index
        assert index[("spectral", "rule-a")].id == "S-001"

    def test_duplicate_key_first_wins(self):
        r1 = _minimal_rule_dict(id="S-001", engine="spectral", engine_rule="rule-a")
        r2 = _minimal_rule_dict(id="S-099", engine="spectral", engine_rule="rule-a")
        rules = [parse_rule_metadata(r1), parse_rule_metadata(r2)]
        index = build_lookup_index(rules)
        assert index[("spectral", "rule-a")].id == "S-001"
        assert len(index) == 1

    def test_empty_list(self):
        assert build_lookup_index([]) == {}
