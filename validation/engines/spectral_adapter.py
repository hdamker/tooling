"""Spectral engine adapter for the CAMARA validation framework.

Invokes Spectral CLI on OpenAPI spec files, parses the JSON output, and
normalizes findings into the common findings model.

Design doc references:
  - Section 8.1 step 7: full validation (Spectral invocation)
  - Section 7.5: Spectral pre-selection (version-specific rulesets)
  - Section 2.2: check areas (Spectral coverage)
"""

from __future__ import annotations

import glob as glob_mod
import json
import logging
import os
import subprocess
import tempfile
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

# When commonalities_release is absent (no release-plan.yaml), default to the
# oldest supported version line — conservative choice for repos that haven't
# declared a Commonalities dependency yet.
_DEFAULT_VERSION_LINE = "r3"

# When commonalities_release is present but unrecognised (likely a newer version
# than what we support), default to the latest available version line.
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
    2. If *commonalities_release* is ``None`` (no release-plan.yaml),
       default to the oldest supported version line (currently r3 —
       conservative choice for repos without a Commonalities dependency).
    3. If *commonalities_release* is present but unrecognised (likely
       newer than supported), default to the latest version line
       (currently r4).
    4. If the version-specific file does not exist on disk, fall back to
       ``.spectral.yaml``.

    Args:
        commonalities_release: Version string from release-plan.yaml
            (e.g. "r4.1", "r3.4") or ``None``.
        config_dir: Directory containing Spectral ruleset files.

    Returns:
        Absolute path to the selected ruleset file.
    """
    # Determine target version line.
    if commonalities_release is None:
        # No release-plan.yaml or no commonalities dependency declared.
        version_line = _DEFAULT_VERSION_LINE
    else:
        # Start with latest; override if a known prefix matches.
        version_line = _LATEST_VERSION_LINE
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


def _normalize_path(source: str, repo_root: Optional[str] = None) -> str:
    """Strip repo-root prefix from an absolute path to make it repo-relative.

    Spectral may emit absolute runner paths (e.g.
    ``/home/runner/work/Repo/Repo/code/API_definitions/api.yaml``) depending
    on how the shell resolves the glob.  Normalising at finding-creation time
    ensures every downstream consumer (annotations, diagnostics, PR comment)
    sees clean repo-relative paths.
    """
    if not source or not repo_root:
        return source
    root = repo_root.rstrip("/") + "/"
    if source.startswith(root):
        return source[len(root):]
    return source


def normalize_finding(raw: dict, repo_root: Optional[str] = None) -> dict:
    """Convert one Spectral JSON finding to the common findings model.

    Critical field mapping:
    - ``raw["source"]`` -> ``finding["path"]`` (file path, NOT ``raw["path"]``
      which is the JSONPath within the document).
    - ``raw["range"]["start"]["line"]`` is 0-indexed; add 1 for the framework.
    - ``raw["range"]["start"]["character"]`` is 0-indexed; add 1.

    Findings on external files (e.g. ``code/common/CAMARA_common.yaml``)
    that Spectral followed via ``$ref`` are downgraded to ``hint`` level
    since they are not directly actionable by the API developer.

    Args:
        raw: Single finding dict from Spectral JSON output.
        repo_root: Absolute path to the repository root.  When provided,
            absolute ``source`` paths are normalised to repo-relative.
    """
    source = _normalize_path(raw.get("source", ""), repo_root)

    # Findings from external files that Spectral followed via $ref
    # (e.g. code/common/CAMARA_common.yaml) are downgraded to hint —
    # they are not directly actionable by the API developer.
    from_external = bool(source and "API_definitions" not in source)

    start = raw.get("range", {}).get("start", {})

    line = start.get("line", 0) + 1
    character = start.get("character")
    column = (character + 1) if character is not None else None

    level = "hint" if from_external else map_severity(raw.get("severity", 1))

    finding: dict = {
        "engine": ENGINE_NAME,
        "engine_rule": raw.get("code", "unknown"),
        "level": level,
        "message": raw.get("message", ""),
        "path": source,
        "line": line,
        "api_name": derive_api_name(source),
    }

    if column is not None:
        finding["column"] = column

    return finding


def parse_spectral_output(
    raw_json: str,
    repo_root: Optional[str] = None,
) -> List[dict]:
    """Parse Spectral ``--format json`` stdout into normalised findings.

    Args:
        raw_json: Raw JSON string from Spectral stdout.
        repo_root: Repository root path passed to :func:`normalize_finding`
            for path normalisation.

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
            findings.append(normalize_finding(item, repo_root=repo_root))
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

    Uses ``--format json`` for machine-readable output.  Output is written
    to a temporary file via Spectral's ``--output`` flag to avoid Node.js
    stdout pipe truncation on large result sets (>64 KB).

    The default ``--fail-severity error`` means exit 0 for warnings-only
    and exit 1 when errors are present — both are normal operation with
    valid JSON in the output file.

    Args:
        ruleset_path: Path to the Spectral ruleset file.
        spec_patterns: Glob patterns for input files (e.g.
            ``["code/API_definitions/*.yaml"]``).
        cwd: Working directory for the subprocess (normally the repo root
            so that ``source`` paths in the output are repo-relative).

    Returns:
        :class:`SpectralResult` with parsed findings and status.
    """
    # Create a temp file for Spectral JSON output.  Placed in cwd to stay
    # on the same filesystem.  delete=False so we control cleanup.
    fd, output_path = tempfile.mkstemp(suffix=".json", dir=str(cwd))
    output_file = Path(output_path)
    try:
        # Close the fd immediately — Spectral will open the file by name.
        os.close(fd)

        cmd = [
            "spectral",
            "lint",
            "--format", "json",
            "--quiet",
            "--output", str(output_file),
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
            if output_file.exists() and output_file.stat().st_size > 0:
                json_text = output_file.read_text(encoding="utf-8")
            else:
                logger.warning(
                    "Spectral output file is empty or missing (exit %d)",
                    result.returncode,
                )
                json_text = ""
            findings = parse_spectral_output(json_text, repo_root=str(cwd))
            return SpectralResult(findings=findings, success=True)

        # Exit 2+: Spectral runtime error.
        stderr = result.stderr.strip() if result.stderr else "unknown error"
        return SpectralResult(
            findings=[],
            success=False,
            error_message=f"Spectral exited with code {result.returncode}: {stderr}",
        )
    finally:
        output_file.unlink(missing_ok=True)


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


def _resolve_spec_files(patterns: List[str], cwd: Path) -> List[str]:
    """Resolve glob patterns to individual file paths (relative to *cwd*).

    Returns a sorted, deduplicated list of relative POSIX-style paths.
    """
    files: List[str] = []
    for pattern in patterns:
        matched = sorted(glob_mod.glob(str(cwd / pattern)))
        for abspath in matched:
            rel = str(PurePosixPath(Path(abspath).relative_to(cwd)))
            if rel not in files:
                files.append(rel)
    return files


def _deduplicate_findings(findings: List[dict]) -> List[dict]:
    """Drop duplicate findings from per-file Spectral runs.

    When the same external schema is resolved independently by multiple
    input files, identical findings appear once per invocation.  Keep
    only the first occurrence based on ``(path, line, engine_rule)``.
    """
    seen: set[tuple] = set()
    result: List[dict] = []
    for f in findings:
        key = (f.get("path", ""), f.get("line", 0), f.get("engine_rule", ""))
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def run_spectral_engine(
    repo_path: Path,
    config_dir: Path,
    commonalities_release: Optional[str] = None,
    spec_patterns: Optional[List[str]] = None,
) -> List[dict]:
    """Top-level entry point for the orchestrator.

    Selects the appropriate ruleset, invokes Spectral **per file**, and
    returns a deduplicated list of findings conforming to the common
    findings model.

    Per-file invocation works around a Spectral document-inventory caching
    bug (`stoplightio/spectral#2640
    <https://github.com/stoplightio/spectral/issues/2640>`_) that causes
    source attribution loss when multiple input files share external
    ``$ref`` targets.

    On adapter-level errors (Spectral not installed, runtime error) an
    error finding is emitted for the affected file and processing
    continues with the remaining files.

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

    spec_files = _resolve_spec_files(spec_patterns, repo_path)
    if not spec_files:
        logger.warning("No spec files matched patterns: %s", spec_patterns)
        return []

    all_findings: List[dict] = []
    for spec_file in spec_files:
        result = run_spectral(ruleset, [spec_file], cwd=repo_path)
        if not result.success:
            logger.error("Spectral error on %s: %s", spec_file, result.error_message)
            all_findings.append(_make_error_finding(
                f"{result.error_message} ({spec_file})"
            ))
            continue
        logger.info("Spectral: %s — %d finding(s)", spec_file, len(result.findings))
        all_findings.extend(result.findings)

    deduped = _deduplicate_findings(all_findings)
    if len(deduped) < len(all_findings):
        logger.info(
            "Spectral dedup: %d → %d finding(s) (dropped %d cross-file duplicates)",
            len(all_findings), len(deduped), len(all_findings) - len(deduped),
        )
    logger.info("Spectral produced %d finding(s) across %d file(s)",
                len(deduped), len(spec_files))
    return deduped
