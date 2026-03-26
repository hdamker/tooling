"""Condition evaluation for applicability and conditional-level overrides.

Pure functions that evaluate condition dicts against ``ValidationContext``
and optional ``ApiContext``.  No I/O, no external dependencies.

Design doc references:
  - Section 8.4: applicability evaluation (AND across fields, OR within arrays)
  - Section 8.4.1: condition field vocabulary
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

from validation.context import ApiContext, ValidationContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version range parsing
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^(>=|<=|!=|==|>|<)\s*(.+)$")

# Fields resolved from ApiContext rather than ValidationContext
_API_CONTEXT_FIELDS = frozenset(
    {"target_api_status", "target_api_maturity", "api_pattern"}
)


def parse_version_tuple(version_str: str) -> Tuple[int, ...]:
    """Parse a Commonalities version string into a comparable tuple.

    Strips a leading ``r`` or ``R`` prefix and splits on ``.``.

    Examples:
        >>> parse_version_tuple("r3.4")
        (3, 4)
        >>> parse_version_tuple("r4.1")
        (4, 1)
        >>> parse_version_tuple("4.1")
        (4, 1)

    Returns ``(0,)`` on parse failure.
    """
    s = version_str.lstrip("rR")
    try:
        return tuple(int(part) for part in s.split("."))
    except (ValueError, AttributeError):
        return (0,)


def evaluate_version_range(
    range_expr: str,
    actual_version: Optional[str],
) -> bool:
    """Evaluate a range expression against a concrete version string.

    Supports operators ``>=``, ``>``, ``<=``, ``<``, ``==``, ``!=``.

    Args:
        range_expr: Expression like ``">=r3.4"`` or ``"<r5.0"``.
        actual_version: Concrete version (e.g. ``"r4.1"``), or ``None``
            when no release plan exists.

    Returns:
        ``True`` if *actual_version* satisfies *range_expr*.
        ``False`` if *actual_version* is ``None`` or *range_expr* is
        malformed.
    """
    if actual_version is None:
        return False

    match = _RANGE_RE.match(range_expr.strip())
    if not match:
        logger.warning("Malformed version range expression: %r", range_expr)
        return False

    operator, version_part = match.group(1), match.group(2)
    expected = parse_version_tuple(version_part)
    actual = parse_version_tuple(actual_version)

    if operator == ">=":
        return actual >= expected
    if operator == ">":
        return actual > expected
    if operator == "<=":
        return actual <= expected
    if operator == "<":
        return actual < expected
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected

    return False  # pragma: no cover


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


def evaluate_condition(
    condition: dict,
    context: ValidationContext,
    api_context: Optional[ApiContext],
) -> bool:
    """Evaluate a condition dict against context.

    All present fields must match (AND logic).  Array fields use OR
    logic (the context value must be contained in the array).

    Per-API fields (``target_api_status``, ``target_api_maturity``,
    ``api_pattern``) are resolved from *api_context*.  When *api_context*
    is ``None`` (repo-level finding), these fields are treated as
    unconstrained (always match).

    Args:
        condition: Dict of field → value from rule metadata.
        context: Repository-level validation context.
        api_context: Per-API context, or ``None`` for repo-level findings.

    Returns:
        ``True`` if all conditions match, ``False`` otherwise.
    """
    for field, expected in condition.items():
        if not _evaluate_single_field(field, expected, context, api_context):
            return False
    return True


def _evaluate_single_field(
    field: str,
    expected: object,
    context: ValidationContext,
    api_context: Optional[ApiContext],
) -> bool:
    """Evaluate one condition field against the context."""

    # --- Per-API array fields ---
    if field in _API_CONTEXT_FIELDS:
        if api_context is None:
            # Repo-level finding — per-API conditions are unconstrained
            return True
        actual = getattr(api_context, field, None)
        if not isinstance(expected, list):
            return actual == expected
        return actual in expected

    # --- commonalities_release: range expression ---
    if field == "commonalities_release":
        return evaluate_version_range(str(expected), context.commonalities_release)

    # --- Boolean fields ---
    if field in ("is_release_review_pr", "release_plan_changed"):
        actual = getattr(context, field, None)
        return actual == expected

    # --- Repository-level array fields ---
    # branch_types, trigger_types, target_release_type
    _FIELD_TO_ATTR = {
        "branch_types": "branch_type",
        "trigger_types": "trigger_type",
        "target_release_type": "target_release_type",
    }
    attr_name = _FIELD_TO_ATTR.get(field)
    if attr_name is not None:
        actual = getattr(context, attr_name, None)
        if not isinstance(expected, list):
            return actual == expected
        return actual in expected

    # Unknown field — treat as non-matching to be safe
    logger.warning("Unknown condition field: %r", field)
    return False


def is_applicable(
    applicability: dict,
    context: ValidationContext,
    api_context: Optional[ApiContext],
) -> bool:
    """Check whether a rule is applicable in the current context.

    Returns ``True`` if *applicability* is empty (unconstrained) or all
    conditions match.
    """
    if not applicability:
        return True
    return evaluate_condition(applicability, context, api_context)
