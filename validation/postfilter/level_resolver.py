"""Conditional level resolution and profile-based blocking.

Pure functions that resolve the effective severity for a finding and
determine whether it blocks under the active profile.

Design doc references:
  - Section 8.4: conditional level overrides (first match wins)
  - Section 2.1: validation profiles (advisory / standard / strict)
"""

from __future__ import annotations

from typing import Optional

from validation.context import ApiContext, ValidationContext
from validation.context.context_builder import (
    PROFILE_ADVISORY,
    PROFILE_STANDARD,
    PROFILE_STRICT,
)

from .condition_evaluator import evaluate_condition
from .metadata_loader import RuleMetadata


# ---------------------------------------------------------------------------
# Level resolution
# ---------------------------------------------------------------------------


def resolve_level(
    rule: RuleMetadata,
    context: ValidationContext,
    api_context: Optional[ApiContext],
) -> str:
    """Resolve the effective severity level for a finding.

    Walks ``conditional_level.overrides`` in declaration order.  The
    first override whose condition matches the context wins.  If no
    override matches, the default level is returned.

    Args:
        rule: Rule metadata containing the conditional level spec.
        context: Repository-level validation context.
        api_context: Per-API context, or ``None`` for repo-level findings.

    Returns:
        Resolved level: ``"error"``, ``"warn"``, ``"hint"``, or ``"muted"``.
    """
    for override in rule.conditional_level.overrides:
        if evaluate_condition(override.condition, context, api_context):
            return override.level
    return rule.conditional_level.default


# ---------------------------------------------------------------------------
# Profile blocking
# ---------------------------------------------------------------------------


def apply_profile_blocking(level: str, profile: str) -> bool:
    """Determine whether a finding at *level* blocks under *profile*.

    Profile semantics:
        - **advisory**: nothing blocks (always ``False``)
        - **standard**: errors block
        - **strict**: errors and warnings block

    Args:
        level: Resolved finding level (``"error"``, ``"warn"``, ``"hint"``).
        profile: Active validation profile.

    Returns:
        ``True`` if the finding should block.
    """
    if profile == PROFILE_ADVISORY:
        return False
    if profile == PROFILE_STANDARD:
        return level == "error"
    if profile == PROFILE_STRICT:
        return level in ("error", "warn")
    return False
