"""Common-file cache sync status checking.

Verifies that ``code/common/`` files match the expected content declared
in ``.sync-manifest.yaml``.  The manifest is written by the
camara-release-automation sync-common handler and records the source
repository, release tag, and git blob SHA-1 for each synced file.

This module is intentionally VF- and RA-independent: it uses only the
Python standard library plus ``pyyaml``.  Both the validation framework
(P-021 check) and release automation (derive-state ``out_of_sync``
signal) import from here.

See DEC-030 (manifest-based validation) and DEC-031 (tooling_lib).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

__all__ = [
    "SyncStatus",
    "SourceStatus",
    "check_sync_status",
    "git_blob_sha",
    "MANIFEST_FILENAME",
]

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".sync-manifest.yaml"
"""Name of the sync manifest inside ``code/common/``."""

COMMON_DIR = "code/common"
"""Repo-relative path to the common-file cache directory."""


# ---------------------------------------------------------------------------
# Git blob SHA-1
# ---------------------------------------------------------------------------


def git_blob_sha(content: bytes) -> str:
    """Compute the git blob SHA-1 for *content*.

    Produces the same 40-character hex digest as ``git hash-object`` and
    the GitHub Contents API ``.sha`` field::

        sha1("blob {length}\\0" + content)
    """
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SourceStatus:
    """Sync status for a single source repository entry in the manifest."""

    repository: str
    tag_mismatch: Optional[Tuple[str, str]] = None  # (expected, actual)
    missing_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return (
            self.tag_mismatch is None
            and not self.missing_files
            and not self.modified_files
        )


@dataclass
class SyncStatus:
    """Overall sync status for ``code/common/``."""

    no_common_dir: bool = False
    no_manifest: bool = False
    sources: List[SourceStatus] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        if self.no_common_dir or self.no_manifest:
            return False
        return all(s.in_sync for s in self.sources)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _load_manifest(manifest_path: Path) -> Optional[dict]:
    """Load and basic-validate the sync manifest.

    Returns ``None`` if the file does not exist, is not valid YAML, or
    does not contain the expected top-level structure.
    """
    if not manifest_path.is_file():
        return None
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse %s", manifest_path)
        return None
    if not isinstance(data, dict) or "sources" not in data:
        logger.warning("Manifest %s missing 'sources' key", manifest_path)
        return None
    if not isinstance(data["sources"], list):
        logger.warning("Manifest %s 'sources' is not a list", manifest_path)
        return None
    return data


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------


def check_sync_status(
    repo_path: Path,
    expected_releases: Dict[str, str],
) -> SyncStatus:
    """Check whether ``code/common/`` files match the sync manifest.

    Parameters
    ----------
    repo_path:
        Root of the API repository checkout.
    expected_releases:
        Map of source repository name to expected release tag, e.g.
        ``{"Commonalities": "r4.2"}``.  Built by the caller from
        ``release-plan.yaml`` dependencies.

    Returns
    -------
    SyncStatus
        Structured result.  Callers convert this to their own output
        format (VF findings or RA error strings).
    """
    common_dir = repo_path / COMMON_DIR

    if not common_dir.is_dir():
        return SyncStatus(no_common_dir=True)

    manifest_path = common_dir / MANIFEST_FILENAME
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        return SyncStatus(no_manifest=True)

    # Index manifest sources by repository name for O(1) lookup.
    manifest_sources: Dict[str, dict] = {}
    for entry in manifest["sources"]:
        if isinstance(entry, dict) and "repository" in entry:
            manifest_sources[entry["repository"]] = entry

    # Check each expected dependency against the manifest.
    source_statuses: List[SourceStatus] = []
    for repo_name, expected_tag in sorted(expected_releases.items()):
        entry = manifest_sources.get(repo_name)
        if entry is None:
            # Source expected but not in manifest — treat as missing manifest
            # for this specific source.  Produces a tag_mismatch with
            # actual=None signalling "not present".
            source_statuses.append(
                SourceStatus(
                    repository=repo_name,
                    tag_mismatch=(expected_tag, "<not in manifest>"),
                )
            )
            continue

        status = SourceStatus(repository=repo_name)

        # --- Tag match ---
        actual_tag = entry.get("release", "")
        if actual_tag != expected_tag:
            status.tag_mismatch = (expected_tag, actual_tag)

        # --- File integrity ---
        files = entry.get("files", {})
        if isinstance(files, dict):
            for filename, expected_sha in sorted(files.items()):
                file_path = common_dir / filename
                if not file_path.is_file():
                    status.missing_files.append(filename)
                    continue
                actual_sha = git_blob_sha(file_path.read_bytes())
                if actual_sha != expected_sha:
                    status.modified_files.append(filename)

        source_statuses.append(status)

    return SyncStatus(sources=source_statuses)
