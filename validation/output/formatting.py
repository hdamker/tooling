"""Shared formatting utilities for the output pipeline.

Pure functions for counting, sorting, and labelling findings.  Used by
all output surface modules (workflow summary, annotations, PR comment,
commit status, diagnostics).

Design doc references:
  - Section 9.2: finding grouping and priority ordering
  - Section 9.3: engine summary table
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority ordering for levels
# ---------------------------------------------------------------------------

_LEVEL_PRIORITY = {"error": 0, "warn": 1, "hint": 2}

# Sentinel label for repo-level findings (api_name is None)
REPO_LEVEL_LABEL = "(repository)"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FindingCounts:
    """Aggregate counts for a set of findings."""

    errors: int
    warnings: int
    hints: int
    total: int
    blocking: int


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def count_findings(findings: List[dict]) -> FindingCounts:
    """Count findings by level and blocking status."""
    errors = 0
    warnings = 0
    hints = 0
    blocking = 0
    for f in findings:
        level = f.get("level", "")
        if level == "error":
            errors += 1
        elif level == "warn":
            warnings += 1
        elif level == "hint":
            hints += 1
        if f.get("blocks"):
            blocking += 1
    return FindingCounts(
        errors=errors,
        warnings=warnings,
        hints=hints,
        total=len(findings),
        blocking=blocking,
    )


# ---------------------------------------------------------------------------
# Result label
# ---------------------------------------------------------------------------

_RESULT_LABEL = {
    "pass": "PASS",
    "fail": "FAIL",
    "error": "ERROR",
    "advisory": "ADVISORY",
}


def resolve_result_label(result: str, profile: str, counts: FindingCounts) -> str:
    """Map a post-filter result string to its display label.

    Two refinements on a passing run:
      * Advisory profile never blocks, so the post-filter always returns
        ``"pass"``; show **ADVISORY** when any findings exist, since **PASS**
        would hide them.
      * Under a blocking profile, a pass with warnings present is genuine but
        incomplete; show **PASS (with warnings)** so the warnings stay visible.
        Hints alone never change the label.
    """
    if result == "pass" and profile == "advisory" and counts.total:
        return _RESULT_LABEL["advisory"]
    if result == "pass" and counts.warnings > 0:
        return f"{_RESULT_LABEL['pass']} (with warnings)"
    return _RESULT_LABEL.get(result, result.upper())


def count_findings_by_api(
    findings: List[dict],
) -> Dict[str, FindingCounts]:
    """Group findings by ``api_name`` and count each group.

    Findings with ``api_name`` of ``None`` are grouped under
    :data:`REPO_LEVEL_LABEL`.  Keys are returned in insertion order
    (first-seen API name).
    """
    groups: Dict[str, List[dict]] = {}
    for f in findings:
        key = f.get("api_name") or REPO_LEVEL_LABEL
        groups.setdefault(key, []).append(f)
    return {api: count_findings(fs) for api, fs in groups.items()}


def count_findings_by_engine(
    findings: List[dict],
) -> Dict[str, FindingCounts]:
    """Group findings by ``engine`` and count each group.

    Keys are returned in insertion order (first-seen engine).
    """
    groups: Dict[str, List[dict]] = {}
    for f in findings:
        key = f.get("engine", "unknown")
        groups.setdefault(key, []).append(f)
    return {engine: count_findings(fs) for engine, fs in groups.items()}


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

# Cap on the number of messages to concatenate when merging duplicates.
_MAX_MERGED_MESSAGES = 3


def deduplicate_findings(findings: List[dict]) -> List[dict]:
    """Merge findings that share the same ``(path, line, engine_rule)`` key.

    Spectral's ``oas3-schema`` (and similar meta-rules) can fire multiple
    times on the same source line with different messages.  Merging them
    reduces annotation noise without losing information.

    For each group of duplicates:
    - The highest severity (error > warn > hint) is kept.
    - Distinct messages are concatenated with ``" | "``, capped at
      :data:`_MAX_MERGED_MESSAGES` (extras noted as ``"... and N more"``).
    - All other fields come from the first finding in the group.

    Order of first occurrence is preserved.
    """
    groups: dict[tuple, List[dict]] = {}
    order: list[tuple] = []

    for f in findings:
        key = (f.get("path", ""), f.get("line", 0), f.get("engine_rule", ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)

    result: List[dict] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            result.append(group[0])
            continue

        merged = dict(group[0])

        # Highest severity wins.
        best_priority = min(
            _LEVEL_PRIORITY.get(f.get("level", ""), 99) for f in group
        )
        for level_name, priority in _LEVEL_PRIORITY.items():
            if priority == best_priority:
                merged["level"] = level_name
                break

        # Concatenate distinct messages.
        seen_messages: list[str] = []
        for f in group:
            msg = f.get("message", "")
            if msg and msg not in seen_messages:
                seen_messages.append(msg)

        if len(seen_messages) <= _MAX_MERGED_MESSAGES:
            merged["message"] = " | ".join(seen_messages)
        else:
            shown = " | ".join(seen_messages[:_MAX_MERGED_MESSAGES])
            extra = len(seen_messages) - _MAX_MERGED_MESSAGES
            merged["message"] = f"{shown} | ... and {extra} more"

        result.append(merged)

    return result


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def sort_findings_by_priority(findings: List[dict]) -> List[dict]:
    """Sort findings: errors first, then warnings, then hints.

    Within the same level, sort by file path then line number.
    The sort is stable — equal items preserve their original order.
    """
    return sorted(
        findings,
        key=lambda f: (
            _LEVEL_PRIORITY.get(f.get("level", ""), 99),
            f.get("path", ""),
            f.get("line", 0),
        ),
    )


# ---------------------------------------------------------------------------
# Label formatting
# ---------------------------------------------------------------------------


def format_rule_label(finding: dict) -> str:
    """Return the best short label for a finding's rule.

    Uses ``rule_id`` when present (e.g. ``"S-042"``), otherwise falls
    back to ``engine_rule``.
    """
    return finding.get("rule_id") or finding.get("engine_rule", "unknown")


# Hard cap matches rule-metadata-schema.yaml maxLength for short_title.
# Titles wider than this wrap in the GitHub file-diff annotation UI.
_ANNOTATION_TITLE_MAX = 70


def resolve_annotation_title(finding: dict) -> str:
    """Return the annotation title for a finding.

    Uses ``short_title`` when present (populated from rule metadata by
    the post-filter).  Otherwise falls back to the finding ``message``,
    truncated with an ellipsis when it would exceed
    :data:`_ANNOTATION_TITLE_MAX`.  The full, untruncated message
    remains available on the finding for the annotation body.
    """
    short = finding.get("short_title")
    if short:
        return short
    message = finding.get("message", "")
    if len(message) <= _ANNOTATION_TITLE_MAX:
        return message
    return message[: _ANNOTATION_TITLE_MAX - 1].rstrip() + "…"


# Matches the Spectral-engine ``schema_path`` (a dot-joined JSONPath) for a
# named OpenAPI component, capturing the component name.
_COMPONENT_PATH_RE = re.compile(
    r"^components\.(?:schemas|parameters|responses|requestBodies|headers)\.([^.]+)"
)


def format_finding_location(finding: dict) -> str:
    """Format a finding's location as ``path:line`` or ``path:line:column``.

    When ``schema_path`` identifies a named OpenAPI component (Spectral-engine
    findings only), the component name is appended in parens, e.g.
    ``spec.yaml:42 (QosProfile)``.
    """
    path = finding.get("path", "")
    line = finding.get("line", 0)
    column = finding.get("column")
    if column is not None:
        location = f"{path}:{line}:{column}"
    else:
        location = f"{path}:{line}"
    match = _COMPONENT_PATH_RE.match(finding.get("schema_path") or "")
    if match:
        return f"{location} ({match.group(1)})"
    return location


# Inline-syntax characters that GFM interprets specially.  Backslash is
# handled separately and must run first to avoid double-escaping.
_GFM_INLINE_CHARS = ("*", "_", "~", "`", "[", "]", "<")


def escape_gfm_inline(text: str) -> str:
    """Backslash-escape GFM inline-syntax characters in *text*.

    Engine-emitted messages are not authored as Markdown — Spectral and
    other linters can include regex quantifiers, RFC 6901 path
    encoding, or bracketed identifiers that GFM otherwise parses as
    emphasis, links, or code spans.  Apply this to messages before
    interpolating them into a Markdown surface.

    Out of scope: HTML entity escaping (the workflow summary is server-
    rendered Markdown, not raw HTML — ``&`` and ``>`` need no special
    handling), block-level constructs, and reference-link
    disambiguation.  Inline-only is the documented contract.
    """
    text = text.replace("\\", "\\\\")
    for ch in _GFM_INLINE_CHARS:
        text = text.replace(ch, "\\" + ch)
    return text
