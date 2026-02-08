"""
Version calculator for CAMARA release automation.

This module calculates API version extensions based on release history.
It ensures each pre-release version has a unique extension number.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import yaml

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
        target_status: str
    ) -> str:
        """
        Calculate the full version string with extension.

        For public releases, returns the target version unchanged.
        For pre-releases, finds existing extensions and returns the next one.

        Args:
            api_name: Name of the API (e.g., "location-verification")
            target_version: Base version (e.g., "3.2.0")
            target_status: Release status ("alpha", "rc", or "public")

        Returns:
            Full version string (e.g., "3.2.0-rc.2")
        """
        # Public releases don't have extensions
        if target_status == "public":
            return target_version

        # Find existing extensions for this version/status combination
        existing = self.find_existing_extensions(
            api_name, target_version, target_status
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
        target_status: str
    ) -> List[int]:
        """
        Find all existing extension numbers for a version/status combination.

        Scans all published releases and reads their release-metadata.yaml
        to find matching API versions.

        Args:
            api_name: Name of the API
            target_version: Base version (e.g., "3.2.0")
            target_status: Release status ("alpha", "rc")

        Returns:
            List of extension numbers found (e.g., [1, 2, 3])
        """
        extensions = []

        # Get all published releases
        releases = self.gh.get_releases(include_drafts=False)

        for release in releases:
            # Read release-metadata.yaml from the tag
            metadata = self._read_release_metadata(release.tag_name)
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

        return extensions

    def calculate_versions_for_plan(
        self,
        release_plan: dict
    ) -> dict:
        """
        Calculate versions for all APIs in a release plan.

        Args:
            release_plan: Parsed release-plan.yaml content

        Returns:
            Dict mapping api_name to calculated version
        """
        versions = {}

        apis = release_plan.get("apis", [])
        for api in apis:
            api_name = api.get("api_name")
            target_version = api.get("target_api_version")
            target_status = api.get("target_api_status", "public")

            if api_name and target_version:
                versions[api_name] = self.calculate_version(
                    api_name, target_version, target_status
                )

        return versions

    def _read_release_metadata(self, tag: str) -> Optional[dict]:
        """
        Read release-metadata.yaml from a release tag.

        Args:
            tag: Release tag name (e.g., "r4.1")

        Returns:
            Parsed YAML content or None if not found
        """
        content = self.gh.get_file_content("release-metadata.yaml", tag)
        if not content:
            return None

        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse release-metadata.yaml from {tag}: {e}")
            return None

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
