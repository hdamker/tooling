"""Spectral engine adapter for the CAMARA validation framework.

Invokes Spectral CLI on OpenAPI spec files, parses the JSON output, and
normalizes findings into the common findings model.

Design doc references:
  - Section 8.1 step 7: full validation (Spectral invocation)
  - Section 7.5: Spectral pre-selection (version-specific rulesets)
  - Section 2.2: check areas (Spectral coverage)
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGINE_NAME = "spectral"

# Spectral severity (integer) -> framework level (string).
# Spectral: 0=error, 1=warn, 2=info, 3=hint.
# Framework collapses info and hint into "hint".
SEVERITY_MAP: dict[int, str] = {
    0: "error",
    1: "warn",
    2: "hint",
    3: "hint",
}

DEFAULT_SPEC_GLOB = "code/API_definitions/*.yaml"

# Fallback ruleset when version-specific file is not found.
DEFAULT_RULESET = ".spectral.yaml"

# Version-line prefix -> ruleset filename.
_VERSION_RULESET_MAP: dict[str, str] = {
    "r3": ".spectral-r3.4.yaml",
    "r4": ".spectral-r4.yaml",
}

# Latest version line used when commonalities_release is absent.
_LATEST_VERSION_LINE = "r4"

# Sentinel rule name for adapter-level errors.
_EXECUTION_ERROR_RULE = "spectral-execution-error"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def map_severity(spectral_severity: int) -> str:
    """Map a Spectral severity integer to a framework level string.

    Args:
        spectral_severity: Spectral severity (0=error, 1=warn, 2=info, 3=hint).

    Returns:
        Framework level: "error", "warn", or "hint".

    Raises:
        KeyError: If *spectral_severity* is not in the range 0-3.
    """
    return SEVERITY_MAP[spectral_severity]


def derive_api_name(file_path: str) -> Optional[str]:
    """Extract the API name from a spec file path.

    Expects paths like ``code/API_definitions/quality-on-demand.yaml``.
    Returns the file stem (without extension) as the API name, or ``None``
    for paths that are not under ``API_definitions``.
    """
    if not file_path:
        return None
    parts = PurePosixPath(file_path).parts
    try:
        idx = parts.index("API_definitions")
    except ValueError:
        return None
    # The file name should follow immediately after API_definitions.
    if idx + 1 < len(parts):
        return PurePosixPath(parts[idx + 1]).stem
    return None


def select_ruleset_path(
    commonalities_release: Optional[str],
    config_dir: Path,
) -> Path:
    """Select the Spectral ruleset based on the Commonalities release version.

    Resolution order:
    1. Map *commonalities_release* prefix to a version-specific filename
       (e.g. ``r4.1`` -> ``.spectral-r4.yaml``).
    2. If *commonalities_release* is absent or unrecognised, default to the
       latest version line (currently r4).
    3. If the version-specific file does not exist on disk, fall back to
       ``.spectral.yaml``.

    Args:
        commonalities_release: Version string from release-plan.yaml
            (e.g. "r4.1", "r3.4") or ``None``.
        config_dir: Directory containing Spectral ruleset files.

    Returns:
        Absolute path to the selected ruleset file.
    """
    # Determine target version line.
    version_line = _LATEST_VERSION_LINE
    if commonalities_release:
        for prefix in _VERSION_RULESET_MAP:
            if commonalities_release.startswith(prefix):
                version_line = prefix
                break

    # Try version-specific ruleset.
    ruleset_name = _VERSION_RULESET_MAP[version_line]
    candidate = config_dir / ruleset_name
    if candidate.is_file():
        return candidate

    # Fallback to default.
    fallback = config_dir / DEFAULT_RULESET
    logger.info(
        "Version-specific ruleset %s not found; falling back to %s",
        ruleset_name,
        DEFAULT_RULESET,
    )
    return fallback


def normalize_finding(raw: dict) -> dict:
    """Convert one Spectral JSON finding to the common findings model.

    Critical field mapping:
    - ``raw["source"]`` -> ``finding["path"]`` (file path, NOT ``raw["path"]``
      which is the JSONPath within the document).
    - ``raw["range"]["start"]["line"]`` is 0-indexed; add 1 for the framework.
    - ``raw["range"]["start"]["character"]`` is 0-indexed; add 1.
    """
    source = raw.get("source", "")
    start = raw.get("range", {}).get("start", {})

    line = start.get("line", 0) + 1
    character = start.get("character")
    column = (character + 1) if character is not None else None

    finding: dict = {
        "engine": ENGINE_NAME,
        "engine_rule": raw.get("code", "unknown"),
        "level": map_severity(raw.get("severity", 1)),
        "message": raw.get("message", ""),
        "path": source,
        "line": line,
        "api_name": derive_api_name(source),
    }

    if column is not None:
        finding["column"] = column

    return finding


def parse_spectral_output(raw_json: str) -> List[dict]:
    """Parse Spectral ``--format json`` stdout into normalised findings.

    Args:
        raw_json: Raw JSON string from Spectral stdout.

    Returns:
        List of findings conforming to the common findings model.
        Returns an empty list if *raw_json* is empty or not valid JSON.
    """
    if not raw_json.strip():
        return []

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Spectral JSON output: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning("Spectral output is not a JSON array")
        return []

    findings = []
    for item in data:
        try:
            findings.append(normalize_finding(item))
        except (KeyError, TypeError) as exc:
            logger.warning("Skipping malformed Spectral finding: %s", exc)
    return findings


# ---------------------------------------------------------------------------
# I/O wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpectralResult:
    """Result of a Spectral CLI invocation."""

    findings: List[dict]
    success: bool
    error_message: str = ""


def run_spectral(
    ruleset_path: Path,
    spec_patterns: List[str],
    cwd: Path,
) -> SpectralResult:
    """Invoke Spectral CLI and capture structured output.

    Uses ``--format json`` for machine-readable output.  The default
    ``--fail-severity error`` means exit 0 for warnings-only and exit 1
    when errors are present — both are normal operation with valid JSON
    on stdout.

    Args:
        ruleset_path: Path to the Spectral ruleset file.
        spec_patterns: Glob patterns for input files (e.g.
            ``["code/API_definitions/*.yaml"]``).
        cwd: Working directory for the subprocess (normally the repo root
            so that ``source`` paths in the output are repo-relative).

    Returns:
        :class:`SpectralResult` with parsed findings and status.
    """
    cmd = [
        "spectral",
        "lint",
        "--format", "json",
        "--ruleset", str(ruleset_path),
        *spec_patterns,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=300,
        )
    except FileNotFoundError:
        return SpectralResult(
            findings=[],
            success=False,
            error_message="Spectral CLI not found — is @stoplight/spectral-cli installed?",
        )
    except subprocess.TimeoutExpired:
        return SpectralResult(
            findings=[],
            success=False,
            error_message="Spectral timed out after 300 seconds",
        )

    # Exit 0 or 1: normal operation (findings may or may not exist).
    if result.returncode in (0, 1):
        findings = parse_spectral_output(result.stdout)
        return SpectralResult(findings=findings, success=True)

    # Exit 2+: Spectral runtime error.
    stderr = result.stderr.strip() if result.stderr else "unknown error"
    return SpectralResult(
        findings=[],
        success=False,
        error_message=f"Spectral exited with code {result.returncode}: {stderr}",
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


def run_spectral_engine(
    repo_path: Path,
    config_dir: Path,
    commonalities_release: Optional[str] = None,
    spec_patterns: Optional[List[str]] = None,
) -> List[dict]:
    """Top-level entry point for the orchestrator.

    Selects the appropriate ruleset, invokes Spectral, and returns a list
    of findings conforming to the common findings model.  On adapter-level
    errors (Spectral not installed, runtime error) a single error finding
    is returned instead of raising.

    Args:
        repo_path: Root of the repository being validated.
        config_dir: Directory containing Spectral ruleset files.
        commonalities_release: Version string for ruleset selection.
        spec_patterns: Override glob patterns (default:
            ``["code/API_definitions/*.yaml"]``).

    Returns:
        List of finding dicts conforming to ``findings-schema.yaml``.
    """
    if spec_patterns is None:
        spec_patterns = [DEFAULT_SPEC_GLOB]

    ruleset = select_ruleset_path(commonalities_release, config_dir)
    logger.info("Using Spectral ruleset: %s", ruleset)

    result = run_spectral(ruleset, spec_patterns, cwd=repo_path)

    if not result.success:
        logger.error("Spectral engine error: %s", result.error_message)
        return [_make_error_finding(result.error_message)]

    logger.info("Spectral produced %d finding(s)", len(result.findings))
    return result.findings
