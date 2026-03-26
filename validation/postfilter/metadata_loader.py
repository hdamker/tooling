"""Rule metadata loading and lookup index.

Loads rule metadata YAML files from the ``validation/rules/`` directory,
parses them into frozen dataclasses, and builds a lookup index keyed by
``(engine, engine_rule)`` for O(1) finding-to-metadata resolution.

Design doc references:
  - Section 1.1: rule metadata model
  - Section 8.4.1: rule metadata lookup
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields in a rule metadata entry
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("id", "name", "engine", "engine_rule", "hint", "conditional_level")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConditionalOverride:
    """One condition/level pair within ``conditional_level.overrides``.

    Attributes:
        condition: Condition dict using the same field vocabulary as
            applicability (AND across fields, OR within arrays).
        level: Severity when this override matches — ``error``, ``warn``,
            ``hint``, or ``off``.
    """

    condition: dict
    level: str


@dataclass(frozen=True)
class ConditionalLevel:
    """Conditional severity specification for a rule.

    Attributes:
        default: Base severity when no override matches.
        overrides: Ordered list of overrides — first match wins.
    """

    default: str
    overrides: Tuple[ConditionalOverride, ...]


@dataclass(frozen=True)
class RuleMetadata:
    """Framework-level metadata for a single validation rule.

    Attributes:
        id: Stable ID with engine prefix (e.g. ``"S-042"``).
        name: Human-readable kebab-case name.
        engine: Engine responsible for producing the finding.
        engine_rule: Native rule identifier within the engine.
        hint: Actionable fix guidance shown to developers.
        applicability: Condition dict — omitted fields are unconstrained.
        conditional_level: Severity specification with optional overrides.
    """

    id: str
    name: str
    engine: str
    engine_rule: str
    hint: str
    applicability: dict
    conditional_level: ConditionalLevel


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_conditional_level(raw: object) -> ConditionalLevel:
    """Parse the ``conditional_level`` block from raw YAML data.

    Raises:
        ValueError: If ``default`` is missing or data is malformed.
    """
    if not isinstance(raw, dict):
        raise ValueError("conditional_level must be a mapping")
    if "default" not in raw:
        raise ValueError("conditional_level.default is required")

    overrides: list[ConditionalOverride] = []
    for entry in raw.get("overrides", []):
        if not isinstance(entry, dict):
            continue
        overrides.append(
            ConditionalOverride(
                condition=entry.get("condition", {}),
                level=entry["level"],
            )
        )

    return ConditionalLevel(
        default=raw["default"],
        overrides=tuple(overrides),
    )


def parse_rule_metadata(raw: dict) -> RuleMetadata:
    """Parse a single rule metadata dict into a :class:`RuleMetadata`.

    Args:
        raw: Dict from YAML with keys matching ``rule-metadata-schema.yaml``.

    Returns:
        Parsed rule metadata.

    Raises:
        ValueError: If required fields are missing or malformed.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    return RuleMetadata(
        id=raw["id"],
        name=raw["name"],
        engine=raw["engine"],
        engine_rule=raw["engine_rule"],
        hint=raw["hint"],
        applicability=raw.get("applicability", {}),
        conditional_level=_parse_conditional_level(raw["conditional_level"]),
    )


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def load_rules_from_file(file_path: Path) -> List[RuleMetadata]:
    """Load a YAML file containing an array of rule metadata objects.

    Returns an empty list if the file does not exist, is empty, or
    contains malformed data.  Individual malformed entries are skipped
    with a warning.
    """
    if not file_path.is_file():
        return []

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    if not isinstance(data, list):
        logger.warning("Expected array in %s, got %s", file_path, type(data).__name__)
        return []

    rules: list[RuleMetadata] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict entry at index %d in %s", i, file_path)
            continue
        try:
            rules.append(parse_rule_metadata(entry))
        except (ValueError, KeyError) as exc:
            logger.warning(
                "Skipping malformed rule at index %d in %s: %s", i, file_path, exc
            )
    return rules


def load_all_rules(rules_dir: Path) -> List[RuleMetadata]:
    """Load all ``*-rules.yaml`` files from *rules_dir*.

    Returns an empty list if the directory does not exist or contains
    no rule files.
    """
    if not rules_dir.is_dir():
        logger.info("Rules directory does not exist: %s", rules_dir)
        return []

    files = sorted(rules_dir.glob("*-rules.yaml"))
    if not files:
        logger.info("No rule metadata files found in %s", rules_dir)
        return []

    all_rules: list[RuleMetadata] = []
    for f in files:
        all_rules.extend(load_rules_from_file(f))
    return all_rules


# ---------------------------------------------------------------------------
# Lookup index
# ---------------------------------------------------------------------------


def build_lookup_index(
    rules: List[RuleMetadata],
) -> Dict[Tuple[str, str], RuleMetadata]:
    """Build a dict keyed by ``(engine, engine_rule)`` for O(1) lookup.

    On duplicate keys the first entry wins and a warning is logged.
    """
    index: dict[tuple[str, str], RuleMetadata] = {}
    for rule in rules:
        key = (rule.engine, rule.engine_rule)
        if key in index:
            logger.warning(
                "Duplicate rule metadata for (%s, %s): keeping %s, ignoring %s",
                rule.engine,
                rule.engine_rule,
                index[key].id,
                rule.id,
            )
            continue
        index[key] = rule
    return index
