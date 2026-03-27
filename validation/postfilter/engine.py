"""Post-filter engine — main orchestration entry point.

Processes raw engine findings through rule metadata lookup, applicability
evaluation, conditional severity resolution, and profile-based blocking
to produce a structured result with an overall pass/fail/error verdict.

Design doc references:
  - Section 8.4: post-filter pipeline
  - Section 8.1 step 8: post-filter in end-to-end flow
  - Section 2.1: overall result computation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from validation.context import ApiContext, ValidationContext

from .condition_evaluator import is_applicable
from .level_resolver import apply_profile_blocking, resolve_level
from .metadata_loader import RuleMetadata, build_lookup_index, load_all_rules

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostFilterResult:
    """Result of post-filter processing.

    Attributes:
        findings: Processed findings with resolved level, optional hint, blocks.
        result: Overall verdict — ``"pass"``, ``"fail"``, or ``"error"``.
        summary: Human-readable one-line summary.
    """

    findings: List[dict]
    result: str
    summary: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_engine_error_finding(finding: dict) -> bool:
    """Check if a finding represents an engine execution error.

    Engine adapters emit these with ``engine_rule`` ending in
    ``-execution-error`` (e.g. ``spectral-execution-error``).
    """
    return finding.get("engine_rule", "").endswith("-execution-error")


def _resolve_api_context(
    finding: dict,
    context: ValidationContext,
) -> Optional[ApiContext]:
    """Look up the ``ApiContext`` for a finding by matching ``api_name``.

    Returns ``None`` for repo-level findings or when no matching API
    exists in the context.
    """
    api_name = finding.get("api_name")
    if not api_name:
        return None
    for api in context.apis:
        if api.api_name == api_name:
            return api
    return None


def _enrich_finding(
    finding: dict,
    rule: RuleMetadata,
    resolved_level: Optional[str] = None,
) -> dict:
    """Create an enriched copy of a finding with metadata applied.

    When *resolved_level* is ``None`` (identity-only entry without
    ``conditional_level``), the engine's original level is preserved.
    When *message_override* is set, the finding's message is replaced.
    When *hint* is set, it is added to the finding as additional guidance.
    When neither is set, the engine's original message is preserved and
    no hint is added.
    """
    enriched = dict(finding)
    enriched["rule_id"] = rule.id
    if resolved_level is not None:
        enriched["level"] = resolved_level
    if rule.message_override is not None:
        enriched["message"] = rule.message_override
    if rule.hint is not None:
        enriched["hint"] = rule.hint
    return enriched


def _passthrough_finding(finding: dict) -> dict:
    """Create a pass-through copy: keep engine level, no hint added."""
    return dict(finding)


def compute_overall_result(
    findings: List[dict],
    had_engine_error: bool,
    profile: str = "",
) -> str:
    """Compute the overall result from processed findings.

    Priority: ``"error"`` > ``"fail"`` > ``"advisory"`` > ``"pass"``.

    Args:
        findings: Post-filtered findings with ``blocks`` field set.
        had_engine_error: Whether any engine execution error occurred.
        profile: Validation profile (advisory/standard/strict).

    Returns:
        ``"error"`` if evaluation was incomplete (engine failure),
        ``"fail"`` if any finding has ``blocks=True``,
        ``"advisory"`` if profile is advisory and findings exist,
        ``"pass"`` otherwise.
    """
    if had_engine_error:
        return "error"
    if any(f.get("blocks") for f in findings):
        return "fail"
    if profile == "advisory" and findings:
        return "advisory"
    return "pass"


def _build_summary(result: str, findings: List[dict]) -> str:
    """Build a human-readable one-line summary."""
    total = len(findings)
    blocking = sum(1 for f in findings if f.get("blocks"))
    errors = sum(1 for f in findings if f.get("level") == "error")
    warnings = sum(1 for f in findings if f.get("level") == "warn")
    hints = sum(1 for f in findings if f.get("level") == "hint")

    if result == "error":
        return (
            f"Incomplete evaluation: {total} findings "
            f"({errors} errors, {warnings} warnings, {hints} hints)"
        )
    if result == "fail":
        return (
            f"Failed: {blocking} blocking out of {total} findings "
            f"({errors} errors, {warnings} warnings, {hints} hints)"
        )
    if result == "advisory":
        return (
            f"Advisory: {total} findings "
            f"({errors} errors, {warnings} warnings, {hints} hints)"
        )
    if total == 0:
        return "Passed: no findings"
    return (
        f"Passed: {total} findings "
        f"({errors} errors, {warnings} warnings, {hints} hints)"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_post_filter(
    findings: List[dict],
    context: ValidationContext,
    rules_dir: Path,
) -> PostFilterResult:
    """Process all findings through the post-filter pipeline.

    Algorithm per finding:

    1. Engine execution errors pass through unchanged, flag
       ``had_engine_error``.
    2. Look up ``(engine, engine_rule)`` in the metadata index.
    3. **Mapped rule**: evaluate applicability (remove if not applicable),
       resolve conditional level (remove if ``"muted"``), enrich with
       ``rule_id``, optional ``message_override``/``hint``, and
       adjusted ``level``.
    4. **Unmapped rule** (pass-through): keep engine severity and
       message, no hint added.
    5. Apply profile blocking to all surviving findings.
    6. Compute overall result.

    Args:
        findings: Raw findings from all engine adapters.
        context: Unified validation context.
        rules_dir: Path to the ``validation/rules/`` directory.

    Returns:
        :class:`PostFilterResult` with processed findings and verdict.
    """
    # Load rule metadata and build lookup index
    all_rules = load_all_rules(rules_dir)
    index = build_lookup_index(all_rules)

    logger.info(
        "Post-filter: %d findings, %d rules loaded, profile=%s",
        len(findings),
        len(all_rules),
        context.profile,
    )

    processed: list[dict] = []
    had_engine_error = False

    for finding in findings:
        # Step 1: Engine execution errors pass through
        if _is_engine_error_finding(finding):
            had_engine_error = True
            enriched = _passthrough_finding(finding)
            enriched["blocks"] = True
            processed.append(enriched)
            continue

        # Step 2: Metadata lookup
        key = (finding.get("engine", ""), finding.get("engine_rule", ""))
        rule = index.get(key)

        if rule is not None:
            # Step 3: Mapped rule
            api_ctx = _resolve_api_context(finding, context)

            # Applicability check — remove if not applicable
            if not is_applicable(rule.applicability, context, api_ctx):
                continue

            # Conditional level resolution (skip for identity-only entries)
            if rule.conditional_level is not None:
                resolved_level = resolve_level(rule, context, api_ctx)
                if resolved_level == "muted":
                    continue
                enriched = _enrich_finding(finding, rule, resolved_level)
            else:
                # Identity-only: assign rule_id, keep engine level
                enriched = _enrich_finding(finding, rule)
        else:
            # Step 4: Unmapped rule — pass-through
            enriched = _passthrough_finding(finding)

        # Step 5: Profile blocking
        enriched["blocks"] = apply_profile_blocking(
            enriched["level"], context.profile
        )
        processed.append(enriched)

    # Step 6: Overall result
    result = compute_overall_result(processed, had_engine_error, context.profile)
    summary = _build_summary(result, processed)

    logger.info("Post-filter result: %s — %s", result, summary)

    return PostFilterResult(
        findings=processed,
        result=result,
        summary=summary,
    )
