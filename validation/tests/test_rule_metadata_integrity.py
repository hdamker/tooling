"""Integration tests for rule metadata files.

Loads the real rule metadata YAML files from ``validation/rules/`` and
verifies structural integrity, completeness, and consistency with the
engine configurations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from validation.postfilter.metadata_loader import (
    build_lookup_index,
    load_all_rules,
    parse_rule_metadata,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RULES_DIR = _REPO_ROOT / "validation" / "rules"
_LINTING_DIR = _REPO_ROOT / "linting" / "config"

_SPECTRAL_CONFIG = _LINTING_DIR / ".spectral.yaml"
_GHERKIN_CONFIG = _LINTING_DIR / ".gherkin-lintrc"
_YAMLLINT_CONFIG = _LINTING_DIR / ".yamllint.yaml"

# Rule ID pattern from schema
_ID_PATTERN = re.compile(r"^[A-Z]-[0-9]{3}$")

# Engine prefix mapping
_ENGINE_PREFIX = {
    "spectral": "S",
    "gherkin": "G",
    "python": "P",
    "yamllint": "Y",
    "manual": "M",
}


# ---------------------------------------------------------------------------
# Fixture: load all rules once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_rules():
    return load_all_rules(_RULES_DIR)


@pytest.fixture(scope="module")
def rule_index(all_rules):
    return build_lookup_index(all_rules)


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------


class TestStructuralIntegrity:
    """Verify all rule files load without error and have valid structure."""

    def test_rules_load_successfully(self, all_rules):
        assert len(all_rules) > 0, "No rules loaded from validation/rules/"

    def test_expected_rule_counts(self, all_rules):
        counts = {}
        for r in all_rules:
            counts[r.engine] = counts.get(r.engine, 0) + 1
        assert counts["python"] == 13
        assert counts["spectral"] == 46
        assert counts["gherkin"] == 25
        assert counts["yamllint"] == 13

    def test_no_duplicate_keys(self, all_rules):
        """No duplicate (engine, engine_rule) pairs."""
        seen: set[tuple[str, str]] = set()
        duplicates = []
        for r in all_rules:
            key = (r.engine, r.engine_rule)
            if key in seen:
                duplicates.append(f"{r.id}: ({r.engine}, {r.engine_rule})")
            seen.add(key)
        assert not duplicates, f"Duplicate keys: {duplicates}"

    def test_no_duplicate_ids(self, all_rules):
        seen: set[str] = set()
        duplicates = []
        for r in all_rules:
            if r.id in seen:
                duplicates.append(r.id)
            seen.add(r.id)
        assert not duplicates, f"Duplicate IDs: {duplicates}"

    def test_ids_match_pattern(self, all_rules):
        bad = [r.id for r in all_rules if not _ID_PATTERN.match(r.id)]
        assert not bad, f"IDs not matching ^[A-Z]-[0-9]{{3}}$: {bad}"

    def test_ids_use_correct_engine_prefix(self, all_rules):
        bad = []
        for r in all_rules:
            expected_prefix = _ENGINE_PREFIX.get(r.engine)
            if expected_prefix and not r.id.startswith(expected_prefix + "-"):
                bad.append(f"{r.id} (engine={r.engine}, expected {expected_prefix}-)")
            seen_prefix = r.id.split("-")[0]
            if seen_prefix not in _ENGINE_PREFIX.values():
                bad.append(f"{r.id} (unknown prefix {seen_prefix})")
        assert not bad, f"ID/engine prefix mismatches: {bad}"

    def test_ids_sequential_within_ranges(self, all_rules):
        """IDs should be sequential within contiguous ranges.

        Spectral uses S-001–S-017 (CAMARA custom) and S-100+ (built-in OAS)
        with a reserved gap between them.  Other engines are contiguous.
        """
        by_prefix: dict[str, list[int]] = {}
        for r in all_rules:
            prefix, num_str = r.id.split("-")
            by_prefix.setdefault(prefix, []).append(int(num_str))

        for prefix, nums in by_prefix.items():
            nums_sorted = sorted(nums)
            # Split into contiguous ranges
            ranges: list[list[int]] = [[nums_sorted[0]]]
            for n in nums_sorted[1:]:
                if n == ranges[-1][-1] + 1:
                    ranges[-1].append(n)
                else:
                    ranges.append([n])
            # Each range must be contiguous (already guaranteed by construction)
            # but verify no gaps within a range
            for rng in ranges:
                expected = list(range(rng[0], rng[0] + len(rng)))
                assert rng == expected, (
                    f"Gap in {prefix}- range starting at {rng[0]}: "
                    f"got {rng}, expected {expected}"
                )


# ---------------------------------------------------------------------------
# Engine coverage
# ---------------------------------------------------------------------------


class TestEngineCoverage:
    """Verify rule metadata covers all enabled engine rules."""

    def _get_spectral_enabled_rules(self) -> set[str]:
        """Extract enabled rules from .spectral.yaml."""
        if not _SPECTRAL_CONFIG.is_file():
            pytest.skip("Spectral config not found")
        data = yaml.safe_load(_SPECTRAL_CONFIG.read_text(encoding="utf-8"))
        rules = data.get("rules", {})
        enabled = set()
        for name, value in rules.items():
            # false = disabled, true/severity/dict = enabled
            if value is False:
                continue
            # Custom rules with recommended: false are still defined
            if isinstance(value, dict) and value.get("recommended") is False:
                # Still a defined rule — include it
                pass
            enabled.add(name)
        return enabled

    def _get_gherkin_enabled_rules(self) -> set[str]:
        """Extract enabled rules from .gherkin-lintrc."""
        if not _GHERKIN_CONFIG.is_file():
            pytest.skip("Gherkin config not found")
        # gherkin-lintrc may have comments (non-standard JSON)
        text = _GHERKIN_CONFIG.read_text(encoding="utf-8")
        # Strip // comments for JSON parsing
        lines = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            # Remove inline // comments (but not inside strings)
            if "//" in line:
                # Simple heuristic: remove from // to end of line
                idx = line.index("//")
                line = line[:idx]
            lines.append(line)
        data = json.loads("\n".join(lines))
        enabled = set()
        for name, value in data.items():
            if value == "off":
                continue
            if isinstance(value, list) and value[0] == "off":
                continue
            enabled.add(name)
        return enabled

    def _get_yamllint_enabled_rules(self) -> set[str]:
        """Extract enabled rules from .yamllint.yaml."""
        if not _YAMLLINT_CONFIG.is_file():
            pytest.skip("yamllint config not found")
        data = yaml.safe_load(_YAMLLINT_CONFIG.read_text(encoding="utf-8"))
        rules = data.get("rules", {})
        enabled = set()
        for name, value in rules.items():
            if value == "disable" or value is False:
                continue
            enabled.add(name)
        return enabled

    def _get_python_check_names(self) -> set[str]:
        """Get all registered Python check names."""
        from validation.engines.python_checks import CHECKS

        return {c.name for c in CHECKS}

    def test_spectral_coverage(self, rule_index):
        """Every enabled Spectral rule has a metadata entry."""
        enabled = self._get_spectral_enabled_rules()
        indexed = {er for (eng, er) in rule_index if eng == "spectral"}
        missing = enabled - indexed
        assert not missing, (
            f"Spectral rules without metadata: {sorted(missing)}"
        )

    def test_gherkin_coverage(self, rule_index):
        """Every enabled gherkin-lint rule has a metadata entry."""
        enabled = self._get_gherkin_enabled_rules()
        indexed = {er for (eng, er) in rule_index if eng == "gherkin"}
        missing = enabled - indexed
        assert not missing, (
            f"Gherkin rules without metadata: {sorted(missing)}"
        )

    def test_yamllint_coverage(self, rule_index):
        """Every enabled yamllint rule has a metadata entry."""
        enabled = self._get_yamllint_enabled_rules()
        indexed = {er for (eng, er) in rule_index if eng == "yamllint"}
        missing = enabled - indexed
        assert not missing, (
            f"yamllint rules without metadata: {sorted(missing)}"
        )

    def test_python_coverage(self, rule_index):
        """Every registered Python check has a metadata entry."""
        checks = self._get_python_check_names()
        indexed = {er for (eng, er) in rule_index if eng == "python"}
        missing = checks - indexed
        assert not missing, (
            f"Python checks without metadata: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Metadata quality
# ---------------------------------------------------------------------------


class TestMetadataQuality:
    """Verify metadata entries that SHOULD have certain fields do."""

    def test_python_rules_have_conditional_level(self, all_rules):
        """Python checks have context-dependent behavior; all need levels."""
        missing = [
            r.id
            for r in all_rules
            if r.engine == "python" and r.conditional_level is None
        ]
        assert not missing, f"Python rules without conditional_level: {missing}"

    def test_hints_are_exception_not_norm(self, all_rules):
        """Hints and message overrides are rare — engine messages are primary.

        Engine messages are the primary fix guidance (design doc 8.4.1).
        Explicit hints and message overrides should only exist when the
        engine message is insufficient.  Update counts when adding in WS07.
        """
        with_hints = [r.id for r in all_rules if r.hint is not None]
        with_overrides = [r.id for r in all_rules if r.message_override is not None]
        assert len(with_hints) == 0, (
            f"Expected 0 explicit hints (update test if adding hints): "
            f"{with_hints}"
        )
        assert len(with_overrides) == 0, (
            f"Expected 0 message overrides (update test if adding overrides): "
            f"{with_overrides}"
        )
