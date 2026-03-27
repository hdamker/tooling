"""gherkin-lint engine adapter for the CAMARA validation framework.

Invokes gherkin-lint on BDD feature files, parses the JSON output,
and normalizes findings into the common findings model.

Design doc references:
  - Section 8.1 step 7: full validation (gherkin-lint invocation)
  - Section 2.2: check areas (gherkin-lint coverage)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGINE_NAME = "gherkin"

# gherkin-lint has no per-finding severity — all are reported identically.
# Default to "warn" so findings don't block in standard profile; post-filter
# rule metadata can elevate specific rules to "error".
DEFAULT_LEVEL = "warn"

DEFAULT_TEST_GLOB = "code/Test_definitions/**/*.feature"

# Sentinel rule name for adapter-level errors.
_EXECUTION_ERROR_RULE = "gherkin-execution-error"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def derive_api_name(file_path: str) -> Optional[str]:
    """Extract the API name from a test file path.

    Expects paths like ``code/Test_definitions/quality-on-demand.feature``.
    Returns the file stem, or ``None`` for paths outside
    ``Test_definitions``.
    """
    if not file_path:
        return None
    parts = PurePosixPath(file_path).parts
    try:
        idx = parts.index("Test_definitions")
    except ValueError:
        return None
    if idx + 1 < len(parts):
        return PurePosixPath(parts[idx + 1]).stem
    return None


def normalize_file_errors(file_entry: dict, cwd: str) -> List[dict]:
    """Convert one gherkin-lint file entry into normalised findings.

    gherkin-lint JSON format per file::

        {"filePath": "/absolute/path/to/file.feature",
         "errors": [{"message": "...", "rule": "...", "line": N}, ...]}

    ``filePath`` is absolute and must be made relative to *cwd*.
    Each error becomes a finding with ``engine="gherkin"`` and
    ``level=DEFAULT_LEVEL``.
    """
    abs_path = file_entry.get("filePath", "")

    # Relativize: strip cwd prefix to get repo-relative path.
    try:
        rel_path = os.path.relpath(abs_path, cwd)
    except ValueError:
        # On Windows, relpath raises ValueError for different drives.
        rel_path = abs_path

    errors = file_entry.get("errors", [])
    findings = []
    for err in errors:
        finding: dict = {
            "engine": ENGINE_NAME,
            "engine_rule": err.get("rule", "unknown"),
            "level": DEFAULT_LEVEL,
            "message": err.get("message", ""),
            "path": rel_path,
            "line": err.get("line", 1),
            "api_name": derive_api_name(rel_path),
        }
        findings.append(finding)
    return findings


def parse_gherkin_output(raw_json: str, cwd: str) -> List[dict]:
    """Parse gherkin-lint ``--format json`` stdout into normalised findings.

    gherkin-lint outputs a JSON array of file entries.  Files with no
    errors (empty ``errors`` array) are skipped.

    Args:
        raw_json: Raw JSON string from gherkin-lint stdout.
        cwd: Repo root path for relativizing absolute file paths.

    Returns:
        List of findings conforming to the common findings model.
    """
    if not raw_json.strip():
        return []

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse gherkin-lint JSON output: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning("gherkin-lint output is not a JSON array")
        return []

    findings = []
    for file_entry in data:
        if file_entry.get("errors"):
            findings.extend(normalize_file_errors(file_entry, cwd))
    return findings


# ---------------------------------------------------------------------------
# I/O wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GherkinResult:
    """Result of a gherkin-lint CLI invocation."""

    findings: List[dict]
    success: bool
    error_message: str = ""


def _expand_globs(patterns: Sequence[str], cwd: Path) -> List[str]:
    """Expand glob patterns relative to *cwd* into concrete file paths.

    ``subprocess.run()`` without ``shell=True`` does not expand globs,
    and gherkin-lint's internal feature-finder mangles ``**`` patterns
    (appends ``/**.feature`` to any pattern containing ``/**``).
    Expanding in Python avoids both issues.

    Returns repo-relative POSIX path strings.
    """
    expanded: List[str] = []
    for pattern in patterns:
        matches = sorted(cwd.glob(pattern))
        expanded.extend(str(m.relative_to(cwd)) for m in matches)
    return expanded


def run_gherkin_lint(
    config_path: Path,
    file_patterns: List[str],
    cwd: Path,
) -> GherkinResult:
    """Invoke gherkin-lint via npx and capture structured output.

    Uses ``--format json`` for machine-readable output.

    Args:
        config_path: Path to the ``.gherkin-lintrc`` configuration file.
        file_patterns: Glob patterns for input feature files.
        cwd: Working directory (repo root).

    Returns:
        :class:`GherkinResult` with parsed findings and status.
    """
    # Expand globs in Python — gherkin-lint's feature-finder mangles
    # ** patterns (turns "dir/**/*.feature" into "dir/**/*.feature/**.feature").
    files = _expand_globs(file_patterns, cwd)
    if not files:
        logger.info("No files matched patterns: %s", file_patterns)
        return GherkinResult(findings=[], success=True)

    cmd = [
        "gherkin-lint",
        "--format", "json",
        "--config", str(config_path),
        *files,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=120,
        )
    except FileNotFoundError:
        return GherkinResult(
            findings=[],
            success=False,
            error_message="gherkin-lint not found — is it installed and on PATH?",
        )
    except subprocess.TimeoutExpired:
        return GherkinResult(
            findings=[],
            success=False,
            error_message="gherkin-lint timed out after 120 seconds",
        )

    # Exit 0 = clean, exit 1 = findings found.  Both produce valid JSON.
    if result.returncode in (0, 1):
        findings = parse_gherkin_output(result.stdout, str(cwd))
        return GherkinResult(findings=findings, success=True)

    # Other exit codes: check for config-not-found or other runtime errors.
    stderr = result.stderr.strip() if result.stderr else ""
    stdout = result.stdout.strip() if result.stdout else ""
    error_detail = stderr or stdout or "unknown error"
    return GherkinResult(
        findings=[],
        success=False,
        error_message=f"gherkin-lint exited with code {result.returncode}: {error_detail}",
    )


def _make_error_finding(message: str) -> dict:
    """Create an error finding for adapter-level failures."""
    return {
        "engine": ENGINE_NAME,
        "engine_rule": _EXECUTION_ERROR_RULE,
        "level": "error",
        "message": message,
        "path": "",
        "line": 1,
        "api_name": None,
    }


def run_gherkin_engine(
    repo_path: Path,
    config_path: Path,
    file_patterns: Optional[List[str]] = None,
) -> List[dict]:
    """Top-level entry point for the orchestrator.

    Args:
        repo_path: Root of the repository being validated.
        config_path: Path to the gherkin-lint configuration file.
        file_patterns: Override glob patterns (default:
            ``["code/Test_definitions/**/*.feature"]``).

    Returns:
        List of finding dicts conforming to ``findings-schema.yaml``.
    """
    if file_patterns is None:
        file_patterns = [DEFAULT_TEST_GLOB]

    logger.info("Running gherkin-lint with config: %s", config_path)

    result = run_gherkin_lint(config_path, file_patterns, cwd=repo_path)

    if not result.success:
        logger.error("gherkin-lint engine error: %s", result.error_message)
        return [_make_error_finding(result.error_message)]

    logger.info("gherkin-lint produced %d finding(s)", len(result.findings))
    return result.findings
