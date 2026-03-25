"""yamllint engine adapter for the CAMARA validation framework.

Invokes yamllint on YAML spec files, parses the parsable-format output,
and normalizes findings into the common findings model.

Design doc references:
  - Section 8.1 step 5: pre-bundling validation (YAML syntax check)
  - Section 2.2: check areas (yamllint coverage)

yamllint errors block downstream steps (Spectral, bundling).  That
blocking decision is made by the orchestrator — this adapter simply
produces findings with the correct severity levels.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGINE_NAME = "yamllint"

# yamllint level -> framework level.
SEVERITY_MAP: dict[str, str] = {
    "error": "error",
    "warning": "warn",
}

DEFAULT_SPEC_GLOB = "code/API_definitions/*.yaml"

# Regex for yamllint parsable-format lines:
#   file:line:col: [level] message (rule)
# The rule suffix is optional (syntax errors may omit it).
# The rule is always the last parenthesised group on the line.
_PARSABLE_RE = re.compile(
    r"^(.+?):(\d+):(\d+): \[(error|warning)\] (.+?)(?:\s+\(([^)]+)\))?$"
)

# Sentinel rule name for adapter-level errors.
_EXECUTION_ERROR_RULE = "yamllint-execution-error"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def map_severity(yamllint_level: str) -> str:
    """Map a yamllint level string to a framework level.

    Args:
        yamllint_level: ``"error"`` or ``"warning"``.

    Returns:
        Framework level: ``"error"`` or ``"warn"``.

    Raises:
        KeyError: If *yamllint_level* is not recognised.
    """
    return SEVERITY_MAP[yamllint_level]


def derive_api_name(file_path: str) -> Optional[str]:
    """Extract the API name from a spec file path.

    Expects paths like ``code/API_definitions/quality-on-demand.yaml``.
    Returns the file stem, or ``None`` for paths outside
    ``API_definitions``.
    """
    if not file_path:
        return None
    parts = PurePosixPath(file_path).parts
    try:
        idx = parts.index("API_definitions")
    except ValueError:
        return None
    if idx + 1 < len(parts):
        return PurePosixPath(parts[idx + 1]).stem
    return None


def parse_parsable_line(line: str) -> Optional[dict]:
    """Parse one yamllint parsable-format line into a finding dict.

    Format: ``file:line:col: [level] message (rule)``

    yamllint line and column numbers are already 1-indexed.

    Returns:
        A finding dict, or ``None`` if the line does not match.
    """
    match = _PARSABLE_RE.match(line.strip())
    if not match:
        return None

    file_path, line_no, col_no, level, message, rule = match.groups()

    finding: dict = {
        "engine": ENGINE_NAME,
        "engine_rule": rule or "syntax-error",
        "level": map_severity(level),
        "message": message.strip(),
        "path": file_path,
        "line": int(line_no),
        "column": int(col_no),
        "api_name": derive_api_name(file_path),
    }
    return finding


def parse_yamllint_output(raw: str) -> List[dict]:
    """Parse yamllint ``--format parsable`` stdout into normalised findings.

    Blank lines and lines that don't match the parsable format are skipped.

    Returns:
        List of findings conforming to the common findings model.
    """
    findings = []
    for line in raw.splitlines():
        finding = parse_parsable_line(line)
        if finding is not None:
            findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# I/O wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YamllintResult:
    """Result of a yamllint CLI invocation."""

    findings: List[dict]
    success: bool
    error_message: str = ""


def run_yamllint(
    config_path: Path,
    file_patterns: List[str],
    cwd: Path,
) -> YamllintResult:
    """Invoke yamllint and capture structured output.

    Uses ``python3 -m yamllint`` for reliable module execution and
    ``--format parsable`` for machine-readable output.

    Args:
        config_path: Path to the ``.yamllint.yaml`` configuration file.
        file_patterns: Glob patterns for input files.
        cwd: Working directory (repo root).

    Returns:
        :class:`YamllintResult` with parsed findings and status.
    """
    cmd = [
        sys.executable, "-m", "yamllint",
        "--format", "parsable",
        "--config-file", str(config_path),
        *file_patterns,
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
        return YamllintResult(
            findings=[],
            success=False,
            error_message="yamllint not found — is it installed?",
        )
    except subprocess.TimeoutExpired:
        return YamllintResult(
            findings=[],
            success=False,
            error_message="yamllint timed out after 120 seconds",
        )

    # Exit 0 = clean, exit 1 = findings found.  Both are normal.
    if result.returncode in (0, 1):
        findings = parse_yamllint_output(result.stdout)
        return YamllintResult(findings=findings, success=True)

    # Other exit codes indicate a runtime error.
    stderr = result.stderr.strip() if result.stderr else "unknown error"
    return YamllintResult(
        findings=[],
        success=False,
        error_message=f"yamllint exited with code {result.returncode}: {stderr}",
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


def run_yamllint_engine(
    repo_path: Path,
    config_path: Path,
    file_patterns: Optional[List[str]] = None,
) -> List[dict]:
    """Top-level entry point for the orchestrator.

    Args:
        repo_path: Root of the repository being validated.
        config_path: Path to the yamllint configuration file.
        file_patterns: Override glob patterns (default:
            ``["code/API_definitions/*.yaml"]``).

    Returns:
        List of finding dicts conforming to ``findings-schema.yaml``.
    """
    if file_patterns is None:
        file_patterns = [DEFAULT_SPEC_GLOB]

    logger.info("Running yamllint with config: %s", config_path)

    result = run_yamllint(config_path, file_patterns, cwd=repo_path)

    if not result.success:
        logger.error("yamllint engine error: %s", result.error_message)
        return [_make_error_finding(result.error_message)]

    logger.info("yamllint produced %d finding(s)", len(result.findings))
    return result.findings
