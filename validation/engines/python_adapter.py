"""Python check engine adapter for the CAMARA validation framework.

Runs native Python check functions against the repository, producing
findings conforming to the common findings model.  Unlike the other
engine adapters (Spectral, yamllint, gherkin-lint), Python checks run
in-process — no subprocess invocation.

Design doc references:
  - Section 8.1 step 7: full validation (Python checks invocation)
  - Section 2.2: check areas (Python check coverage)
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from .python_checks import CHECKS, CheckScope

logger = logging.getLogger(__name__)

ENGINE_NAME = "python"

# Sentinel rule name for adapter-level errors.
_EXECUTION_ERROR_RULE = "python-execution-error"


# ---------------------------------------------------------------------------
# Error finding builder
# ---------------------------------------------------------------------------


def _make_error_finding(message: str, check_name: str = "") -> dict:
    """Create an error finding for adapter-level or check-level failures."""
    return {
        "engine": ENGINE_NAME,
        "engine_rule": check_name or _EXECUTION_ERROR_RULE,
        "level": "error",
        "message": message,
        "path": "",
        "line": 1,
        "api_name": None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_python_engine(
    repo_path: Path,
    context: ValidationContext,
) -> List[dict]:
    """Top-level entry point for the orchestrator.

    Executes all registered Python checks and collects their findings.
    Each check is isolated: if a check raises an exception, an error
    finding is emitted for that check and execution continues with the
    next check.

    Args:
        repo_path: Root of the repository being validated.
        context: Unified validation context.

    Returns:
        List of finding dicts conforming to ``findings-schema.yaml``.
    """
    all_findings: List[dict] = []

    for descriptor in CHECKS:
        try:
            if descriptor.scope == CheckScope.REPO:
                findings = descriptor.fn(repo_path, context)
                all_findings.extend(findings)
            elif descriptor.scope == CheckScope.API:
                for api_ctx in context.apis:
                    single_api_context = dataclasses.replace(
                        context, apis=(api_ctx,)
                    )
                    findings = descriptor.fn(repo_path, single_api_context)
                    all_findings.extend(findings)
        except Exception as exc:
            logger.exception(
                "Python check %s raised an exception", descriptor.name
            )
            all_findings.append(
                _make_error_finding(
                    f"Check {descriptor.name!r} failed: {exc}",
                    check_name=descriptor.name,
                )
            )

    logger.info("Python checks produced %d finding(s)", len(all_findings))
    return all_findings
