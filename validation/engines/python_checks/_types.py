"""Shared types and helpers for Python check modules.

Provides the check descriptor, scope enum, finding builder, and common
utilities used across all check modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Callable, List, Optional

import yaml

logger = logging.getLogger(__name__)

ENGINE_NAME = "python"


# ---------------------------------------------------------------------------
# Check scope and descriptor
# ---------------------------------------------------------------------------


class CheckScope(Enum):
    """Whether a check runs once per repository or once per API."""

    REPO = "repo"
    API = "api"


@dataclass(frozen=True)
class CheckDescriptor:
    """Registry entry for one Python check.

    Attributes:
        name: Kebab-case identifier used as ``engine_rule`` in findings.
        scope: REPO (called once) or API (called per API in context).
        fn: The check function — ``(repo_path, context) -> List[dict]``.
    """

    name: str
    scope: CheckScope
    fn: Callable[..., List[dict]]


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------


def make_finding(
    engine_rule: str,
    level: str,
    message: str,
    path: str = "",
    line: int = 1,
    api_name: Optional[str] = None,
    **extra: object,
) -> dict:
    """Build a finding dict conforming to findings-schema.yaml.

    Args:
        engine_rule: Kebab-case check name (matches CheckDescriptor.name).
        level: ``"error"``, ``"warn"``, or ``"hint"``.
        message: Human-readable description of the issue.
        path: File path relative to the repository root.
        line: 1-indexed line number.
        api_name: API this finding belongs to, or ``None`` for repo-level.
        **extra: Additional fields (e.g. ``column``).

    Returns:
        Dict with all required finding fields.
    """
    finding: dict = {
        "engine": ENGINE_NAME,
        "engine_rule": engine_rule,
        "level": level,
        "message": message,
        "path": path,
        "line": line,
        "api_name": api_name,
    }
    if extra:
        finding.update(extra)
    return finding


# ---------------------------------------------------------------------------
# Common utilities
# ---------------------------------------------------------------------------


def load_yaml_safe(file_path: Path) -> Optional[dict]:
    """Load a YAML file, returning ``None`` on any error.

    Returns ``None`` when the file does not exist, is empty, contains
    non-dict content, or has a YAML syntax error.
    """
    if not file_path.is_file():
        return None
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def derive_api_name(file_path: str) -> Optional[str]:
    """Extract the API name from a spec file path.

    Expects paths like ``code/API_definitions/quality-on-demand.yaml``.
    Returns the file stem (without extension) or ``None`` for paths
    that are not under ``API_definitions``.
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
