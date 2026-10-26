"""Published release-history snapshot parser for validation.

The workflow layer resolves GitHub release metadata and writes a compact JSON
snapshot.  The Python orchestrator consumes that file offline; it never calls
GitHub while evaluating validation rules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

TERMINAL_RELEASE_TYPES = {"public-release", "maintenance-release"}


@dataclass(frozen=True, order=True)
class ReleaseTag:
    """Sortable CAMARA repository release tag, e.g. ``r4.3``."""

    major: int
    minor: int


@dataclass(frozen=True)
class PublishedReleaseApi:
    """API entry from a published release metadata snapshot."""

    api_name: str
    api_version: str
    api_file_name: str = ""

    @property
    def base_version(self) -> str:
        return normalize_api_version_base(self.api_version)

    @property
    def status(self) -> str:
        if "-alpha." in self.api_version:
            return "alpha"
        if "-rc." in self.api_version:
            return "rc"
        return "public"


@dataclass(frozen=True)
class PublishedRelease:
    """Published repository release plus release-metadata summary."""

    tag: str
    release_type: str
    prerelease: bool
    published_at: str
    src_commit_sha: str
    metadata_available: bool
    apis: Tuple[PublishedReleaseApi, ...]
    commonalities_release: str = ""
    icm_release: str = ""

    @property
    def parsed_tag(self) -> Optional[ReleaseTag]:
        return parse_release_tag(self.tag)


@dataclass(frozen=True)
class ReleaseHistorySnapshot:
    """Workflow-resolved release history consumed by history-aware rules."""

    schema_version: int
    repository: str
    base_ref: str
    lookup_status: str
    published_releases: Tuple[PublishedRelease, ...]
    # None means the branch lookup did not run or failed; rules that need it skip.
    maintenance_branches: Optional[Tuple[str, ...]] = None

    def release_tags_available(self) -> bool:
        """Return True when repository release tags are known enough to compare."""
        return self.lookup_status == "complete" or bool(self.published_releases)

    def latest_release(self, cycle: Optional[int] = None) -> Optional[PublishedRelease]:
        """Return the highest release tag, optionally within one release cycle."""
        releases = [
            release
            for release in self.published_releases
            if release.parsed_tag is not None
            and (cycle is None or release.parsed_tag.major == cycle)
        ]
        if not releases:
            return None
        return max(releases, key=lambda release: release.parsed_tag)

    def is_maintenance_line(self, cycle: int) -> bool:
        """Return True when cycle ``rX`` already contains a terminal release.

        Only releases with metadata count, so legacy releases without
        release-metadata.yaml never turn a cycle into a maintenance line.
        """
        return any(
            release.parsed_tag is not None
            and release.parsed_tag.major == cycle
            and release.metadata_available
            and release.release_type in TERMINAL_RELEASE_TYPES
            for release in self.published_releases
        )

    def patched_release(self, cycle: int) -> Optional[PublishedRelease]:
        """Return the newest terminal release of a maintenance line.

        rc pre-releases are skipped.  Returns None when a newer non-prerelease
        release of the cycle has no metadata, because it could be the real
        patched release.
        """
        candidates = [
            release
            for release in self.published_releases
            if release.parsed_tag is not None
            and release.parsed_tag.major == cycle
            and not release.prerelease
        ]
        if not candidates:
            return None
        newest = max(candidates, key=lambda release: release.parsed_tag)
        if (
            not newest.metadata_available
            or newest.release_type not in TERMINAL_RELEASE_TYPES
        ):
            return None
        return newest

    def later_cycle_releases(self, cycle: int) -> list[PublishedRelease]:
        """Return releases of any type tagged in a cycle after ``cycle``."""
        return [
            release
            for release in self.published_releases
            if release.parsed_tag is not None and release.parsed_tag.major > cycle
        ]

    def has_maintenance_branch(self, cycle: int) -> Optional[bool]:
        """Return whether ``maintenance/rX`` exists; None when unknown."""
        if self.maintenance_branches is None:
            return None
        return f"maintenance/r{cycle}" in self.maintenance_branches

    def release_by_tag(self, tag: str) -> Optional[PublishedRelease]:
        for release in self.published_releases:
            if release.tag == tag:
                return release
        return None

    def has_cycle(self, major: int) -> bool:
        return any(
            release.parsed_tag is not None and release.parsed_tag.major == major
            for release in self.published_releases
        )

    def terminal_api_version_statuses(self, api_name: str) -> set[tuple[str, str]]:
        versions: set[tuple[str, str]] = set()
        for release in self.published_releases:
            if (
                not release.metadata_available
                or release.release_type not in TERMINAL_RELEASE_TYPES
            ):
                continue
            for api in release.apis:
                if api.api_name == api_name:
                    versions.add((api.base_version, api.status))
        return versions

    def may_have_missing_terminal_metadata(self) -> bool:
        """Return True when unavailable metadata could hide terminal API evidence."""
        return any(
            not release.metadata_available and not release.prerelease
            for release in self.published_releases
        )


_RELEASE_TAG_RE = re.compile(r"^r([1-9]\d*)\.([1-9]\d*)$")
_API_VERSION_BASE_RE = re.compile(r"^(\d+\.\d+\.\d+)(?:-(?:alpha|rc)\.\d+)?$")


def parse_release_tag(tag: str) -> Optional[ReleaseTag]:
    """Parse ``rX.Y`` into a sortable value; return None for invalid tags."""
    match = _RELEASE_TAG_RE.fullmatch(str(tag))
    if not match:
        return None
    return ReleaseTag(major=int(match.group(1)), minor=int(match.group(2)))


def normalize_api_version_base(version: str) -> str:
    """Return the release-plan base version for a metadata API version."""
    match = _API_VERSION_BASE_RE.fullmatch(str(version))
    if not match:
        return str(version)
    return match.group(1)


def _parse_api(raw: Any) -> Optional[PublishedReleaseApi]:
    if not isinstance(raw, dict):
        return None
    api_name = raw.get("api_name")
    api_version = raw.get("api_version")
    if not isinstance(api_name, str) or not isinstance(api_version, str):
        return None
    api_file_name = raw.get("api_file_name")
    return PublishedReleaseApi(
        api_name=api_name,
        api_version=api_version,
        api_file_name=api_file_name if isinstance(api_file_name, str) else "",
    )


def _parse_release(raw: Any) -> Optional[PublishedRelease]:
    if not isinstance(raw, dict):
        return None
    tag = raw.get("tag")
    if not isinstance(tag, str) or not tag:
        return None
    apis = tuple(
        api
        for api in (_parse_api(item) for item in raw.get("apis", []))
        if api is not None
    )
    return PublishedRelease(
        tag=tag,
        release_type=str(raw.get("release_type") or ""),
        prerelease=bool(raw.get("prerelease", False)),
        published_at=str(raw.get("published_at") or ""),
        src_commit_sha=str(raw.get("src_commit_sha") or ""),
        metadata_available=bool(raw.get("metadata_available", False)),
        commonalities_release=str(raw.get("commonalities_release") or ""),
        icm_release=str(raw.get("icm_release") or ""),
        apis=apis,
    )


def parse_release_history(data: Any) -> Optional[ReleaseHistorySnapshot]:
    """Parse release-history JSON data into a tolerant immutable snapshot."""
    if not isinstance(data, dict):
        return None

    releases = tuple(
        release
        for release in (
            _parse_release(item) for item in data.get("published_releases", [])
        )
        if release is not None
    )

    try:
        schema_version = int(data.get("schema_version", 1))
    except (TypeError, ValueError):
        schema_version = 1

    raw_branches = data.get("maintenance_branches")
    maintenance_branches = (
        tuple(
            branch
            for branch in raw_branches
            if isinstance(branch, str) and branch.startswith("maintenance/")
        )
        if isinstance(raw_branches, list)
        else None
    )

    return ReleaseHistorySnapshot(
        schema_version=schema_version,
        repository=str(data.get("repository") or ""),
        base_ref=str(data.get("base_ref") or ""),
        lookup_status=str(data.get("lookup_status") or "missing"),
        published_releases=releases,
        maintenance_branches=maintenance_branches,
    )


def load_release_history(path: Path) -> Optional[ReleaseHistorySnapshot]:
    """Load and parse a workflow-resolved release-history JSON file."""
    if not path.is_file():
        logger.debug("release-history snapshot not found at %s", path)
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load release-history snapshot from %s", path)
        return None

    return parse_release_history(data)
