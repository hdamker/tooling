"""
Version calculator for CAMARA release automation.

This module calculates API version extensions based on release history.
It ensures each pre-release version has a unique extension number.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from .github_client import GitHubClient


def calculate_url_version(api_version: str) -> str:
    """
    Calculate the URL version component per CAMARA API Design Guide rules.

    Rules from CAMARA API Design Guide section 7.2:
    - Initial public (0.y.z): v0.y
    - Stable public (x.y.z where x>0): vx
    - Initial alpha (0.y.z-alpha.m): v0.yalpham
    - Initial rc (0.y.z-rc.n): v0.yrcn
    - Stable alpha (x.y.z-alpha.m where x>0): vxalpham
    - Stable rc (x.y.z-rc.n where x>0): vxrcn
    - Work-in-progress: vwip

    Args:
        api_version: Full API version string (e.g., "1.2.0-rc.3", "0.3.0-alpha.1")

    Returns:
        URL version string (e.g., "v1rc3", "v0.3alpha1", "v1", "v0.3")

    Examples:
        >>> calculate_url_version("0.3.0-alpha.1")
        'v0.3alpha1'
        >>> calculate_url_version("1.2.0-alpha.2")
        'v1alpha2'
        >>> calculate_url_version("1.2.0-rc.3")
        'v1rc3'
        >>> calculate_url_version("0.3.0")
        'v0.3'
        >>> calculate_url_version("1.0.0")
        'v1'
        >>> calculate_url_version("wip")
        'vwip'
    """
    if api_version == "wip":
        return "vwip"

    # Parse version: x.y.z or x.y.z-status.n
    pattern = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.(\d+))?$')
    match = pattern.match(api_version)
    if not match:
        # Fallback for invalid versions
        return "vwip"

    major, minor, _patch, status, extension = match.groups()
    major = int(major)

    # Build URL version base
    if major == 0:
        # Initial version: include minor
        base = f"v0.{minor}"
    else:
        # Stable version: major only
        base = f"v{major}"

    # Add pre-release suffix if present
    if status and extension:
        return f"{base}{status}{extension}"

    return base


@dataclass
class VersionInfo:
    """Information about a released API version."""
    api_name: str
    api_version: str
    release_tag: str


class VersionCalculator:
    """
    Calculate API version extensions based on release history.

    For pre-release versions (alpha, rc), the calculator scans existing
    releases to determine the next extension number. Public releases
    use the base version without extension.

    Example:
        - First rc release: 3.2.0-rc.1
        - Second rc release: 3.2.0-rc.2
        - Public release: 3.2.0
    """

    # Pattern to parse version with extension: 1.2.3-rc.4
    VERSION_PATTERN = re.compile(
        r'^(\d+\.\d+\.\d+)-([a-z]+)\.(\d+)$'
    )

    def __init__(self, github_client: GitHubClient):
        """
        Initialize the version calculator.

        Args:
            github_client: GitHubClient instance for repository operations
        """
        self.gh = github_client

    def calculate_version(
        self,
        api_name: str,
        target_version: str,
        target_status: str,
        seed_version: Optional[str] = None
    ) -> str:
        """
        Calculate the full version string with extension.

        For public releases, returns the target version unchanged.
        For pre-releases, finds existing extensions and returns the next one.

        Args:
            api_name: Name of the API (e.g., "location-verification")
            target_version: Base version (e.g., "3.2.0")
            target_status: Release status ("alpha", "rc", or "public")
            seed_version: Optional predecessor-repository pre-release version
                (from release-plan.yaml's seeded_from) to fold in alongside
                this repository's own history, for repo-split continuity

        Returns:
            Full version string (e.g., "3.2.0-rc.2")
        """
        # Public releases don't have extensions
        if target_status == "public":
            return target_version

        # Find existing extensions for this version/status combination
        existing = self.find_existing_extensions(
            api_name, target_version, target_status, seed_version=seed_version
        )

        # Calculate next extension number
        if existing:
            # Get the highest existing extension
            max_ext = max(existing)
            next_ext = max_ext + 1
        else:
            next_ext = 1

        return f"{target_version}-{target_status}.{next_ext}"

    def find_existing_extensions(
        self,
        api_name: str,
        target_version: str,
        target_status: str,
        seed_version: Optional[str] = None
    ) -> List[int]:
        """
        Find all existing extension numbers for a version/status combination.

        Scans all published releases and reads their release-metadata.yaml
        to find matching API versions.

        Args:
            api_name: Name of the API
            target_version: Base version (e.g., "3.2.0")
            target_status: Release status ("alpha", "rc")
            seed_version: Optional predecessor-repository pre-release version
                to fold in as one virtual entry, for repo-split continuity

        Returns:
            List of extension numbers found (e.g., [1, 2, 3])
        """
        extensions = []

        # Get all published releases
        releases = self.gh.get_releases(include_drafts=False)

        for release in releases:
            # Read release-metadata.yaml from the tag
            metadata = self.gh.get_release_metadata(release.tag_name)
            if not metadata:
                continue

            # Check each API in the release
            apis = metadata.get("apis", [])
            for api in apis:
                if api.get("api_name") != api_name:
                    continue

                api_version = api.get("api_version", "")
                ext = self._parse_extension(
                    api_version, target_version, target_status
                )
                if ext is not None:
                    extensions.append(ext)

        # Fold in the seeded_from predecessor-repository fact, if any, using
        # the same URL-namespace matching as self-history entries above.
        if seed_version:
            ext = self._parse_extension(
                seed_version, target_version, target_status
            )
            if ext is not None:
                extensions.append(ext)

        return extensions

    def calculate_versions_for_plan(
        self,
        release_plan: dict
    ) -> dict:
        """
        Calculate versions for all APIs in a release plan.

        Reads release_plan['seeded_from']['apis'] when present (a repo-split
        continuity fact - see release-plan-schema.yaml) and folds each API's
        declared last_rc_api_version / last_alpha_api_version into the
        matching status's extension calculation.

        Args:
            release_plan: Parsed release-plan.yaml content

        Returns:
            Dict mapping api_name to calculated version
        """
        versions = {}
        seed_versions = self._extract_seed_versions(release_plan)

        apis = release_plan.get("apis", [])
        for api in apis:
            api_name = api.get("api_name")
            target_version = api.get("target_api_version")
            target_status = api.get("target_api_status", "public")

            if api_name and target_version:
                seed_version = seed_versions.get(api_name, {}).get(target_status)
                versions[api_name] = self.calculate_version(
                    api_name, target_version, target_status,
                    seed_version=seed_version
                )

        return versions

    @staticmethod
    def _extract_seed_versions(release_plan: dict) -> dict:
        """
        Build a {api_name: {status: version}} map from release_plan['seeded_from'].

        Only last_rc_api_version / last_alpha_api_version are read;
        seeded_api_version is documentation-only provenance and is ignored.
        """
        seeded_from = release_plan.get("seeded_from")
        if not isinstance(seeded_from, dict):
            return {}

        seed_versions: dict = {}
        for api in seeded_from.get("apis", []):
            if not isinstance(api, dict):
                continue
            api_name = api.get("api_name")
            if not api_name:
                continue

            by_status = {}
            for status, field in (
                ("rc", "last_rc_api_version"),
                ("alpha", "last_alpha_api_version"),
            ):
                value = api.get(field)
                if isinstance(value, str) and value:
                    by_status[status] = value

            if by_status:
                seed_versions[api_name] = by_status

        return seed_versions

    def _parse_extension(
        self,
        version: str,
        target_version: str,
        target_status: str
    ) -> Optional[int]:
        """
        Parse extension number from a version string.

        Returns the extension number if the version produces the same URL
        version as the target (i.e., would collide), otherwise None.

        URL versioning rules (CAMARA API Design Guide 7.2):
        - Stable (major >= 1): URL uses major only (vX), so all x.*.* share
          the same extension namespace
        - Initial (major == 0): URL uses major.minor (v0.Y), so only 0.y.*
          share the same extension namespace

        Args:
            version: Version string to parse (e.g., "3.2.0-rc.2")
            target_version: Base version to match (e.g., "3.2.0")
            target_status: Status to match (e.g., "rc")

        Returns:
            Extension number or None if no match
        """
        match = self.VERSION_PATTERN.match(version)
        if not match:
            return None

        base_version, status, extension = match.groups()

        if status != target_status:
            return None

        # Two versions collide if they produce the same URL version prefix.
        # Reuse calculate_url_version with dummy extension to compare.
        existing_url = calculate_url_version(f"{base_version}-{status}.1")
        target_url = calculate_url_version(f"{target_version}-{status}.1")

        if existing_url == target_url:
            return int(extension)

        return None
