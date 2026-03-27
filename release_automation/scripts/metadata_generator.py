"""
Metadata generator for CAMARA release automation.

This module generates release-metadata.yaml content for snapshot branches.
The output conforms to the release-metadata-schema.yaml specification.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ApiMetadata:
    """Metadata for a single API in the release."""

    api_name: str
    api_version: str
    api_title: str

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for YAML serialization."""
        return {
            "api_name": self.api_name,
            "api_version": self.api_version,
            "api_title": self.api_title,
        }


@dataclass
class ReleaseMetadata:
    """
    Complete release metadata structure.

    Matches the release-metadata-schema.yaml specification.
    """

    repository_name: str
    release_tag: str
    release_type: str
    src_commit_sha: Optional[str]
    apis: List[ApiMetadata] = field(default_factory=list)
    release_date: Optional[str] = None
    release_notes: Optional[str] = None
    commonalities_release: Optional[str] = None
    identity_consent_management_release: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary suitable for YAML serialization.

        Returns:
            Dict matching release-metadata-schema.yaml structure
        """
        result: Dict[str, Any] = {
            "repository": {
                "repository_name": self.repository_name,
                "release_tag": self.release_tag,
                "release_type": self.release_type,
                "release_date": self.release_date,
                "src_commit_sha": self.src_commit_sha,
            },
            "apis": [api.to_dict() for api in self.apis],
        }

        # Add optional release_notes if provided
        if self.release_notes:
            result["repository"]["release_notes"] = self.release_notes

        # Add dependencies section if any dependencies are specified
        dependencies = {}
        if self.commonalities_release:
            dependencies["commonalities_release"] = self.commonalities_release
        if self.identity_consent_management_release:
            dependencies["identity_consent_management_release"] = (
                self.identity_consent_management_release
            )

        if dependencies:
            result["dependencies"] = dependencies

        return result


class MetadataGenerator:
    """
    Generate release-metadata.yaml content for snapshot branches.

    Takes release plan information and calculated API versions to produce
    a complete metadata structure ready for YAML serialization.
    """

    # Valid long-form release type values (from release-plan.yaml)
    VALID_RELEASE_TYPES = {
        "pre-release-alpha",
        "pre-release-rc",
        "public-release",
        "maintenance-release",
    }

    def generate(
        self,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        src_commit_sha: Optional[str],
        api_titles: Dict[str, str],
        repo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate release metadata from release plan and calculated versions.

        Args:
            release_plan: Parsed release-plan.yaml content
            api_versions: Dict mapping api_name to calculated version string
            src_commit_sha: SHA of the source commit (snapshot was created from)
            api_titles: Dict mapping api_name to human-readable title
            repo: Full repository path (e.g., "owner/name") — name is extracted

        Returns:
            Dict suitable for YAML serialization as release-metadata.yaml
        """
        repo_section = release_plan.get("repository", {})

        # Derive repository name from repo path, fall back to release plan
        repository_name = repo.split("/")[-1] if repo else self._extract_repo_name(release_plan)

        # Get release tag and type
        release_tag = repo_section.get("target_release_tag", "")
        release_type = self._validate_release_type(
            repo_section.get("target_release_type", "")
        )

        # Build API list
        apis = self._build_api_list(release_plan, api_versions, api_titles)

        # Format dependencies
        dependencies_section = release_plan.get("dependencies", {})
        commonalities = self._format_dependency(
            dependencies_section.get("commonalities_release")
        )
        icm = self._format_dependency(
            dependencies_section.get("identity_consent_management_release")
        )

        # Get optional release notes
        release_notes = repo_section.get("release_notes")

        # Build metadata object
        metadata = ReleaseMetadata(
            repository_name=repository_name,
            release_tag=release_tag,
            release_type=release_type,
            src_commit_sha=src_commit_sha,
            apis=apis,
            release_date=None,  # Set during publication
            release_notes=release_notes,
            commonalities_release=commonalities,
            identity_consent_management_release=icm,
        )

        return metadata.to_dict()

    def _extract_repo_name(self, release_plan: Dict[str, Any]) -> str:
        """
        Extract repository name from release plan.

        Args:
            release_plan: Parsed release-plan.yaml content

        Returns:
            Repository name string
        """
        repo_section = release_plan.get("repository", {})
        return repo_section.get("repository_name", "")

    def _validate_release_type(self, release_type: str) -> str:
        """
        Validate release type is a known long-form value.

        Args:
            release_type: Type from release-plan.yaml
                (e.g., "pre-release-alpha", "public-release")

        Returns:
            The validated release type string (unchanged)

        Raises:
            ValueError: If release_type is not a known value
        """
        if release_type not in self.VALID_RELEASE_TYPES:
            raise ValueError(
                f"Unknown release type: '{release_type}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_RELEASE_TYPES))}"
            )
        return release_type

    def _format_dependency(
        self,
        dependency: Optional[Any],
    ) -> Optional[str]:
        """
        Format a dependency as "rX.Y (version)" string.

        Handles two formats in release-plan.yaml:
        1. Simple string: "r3.4" -> returns "r3.4"
        2. Dict with details: {release_tag: "r3.4", version: "1.2.0"} -> "r3.4 (1.2.0)"

        Args:
            dependency: String release tag or dict with release_tag and optional version

        Returns:
            Formatted string like "r4.2 (1.2.0-rc.1)" or None if no dependency
        """
        if not dependency:
            return None

        # Handle string format (simple release tag)
        if isinstance(dependency, str):
            return dependency

        # Handle dict format with release_tag and optional version
        release_tag = dependency.get("release_tag")
        version = dependency.get("version")

        if not release_tag:
            return None

        if version:
            return f"{release_tag} ({version})"
        else:
            return release_tag

    def _build_api_list(
        self,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        api_titles: Dict[str, str],
    ) -> List[ApiMetadata]:
        """
        Build list of API metadata from plan and calculated versions.

        Args:
            release_plan: Parsed release-plan.yaml content
            api_versions: Dict mapping api_name to calculated version string
            api_titles: Dict mapping api_name to human-readable title

        Returns:
            List of ApiMetadata objects
        """
        apis = []

        for api in release_plan.get("apis", []):
            api_name = api.get("api_name")
            if not api_name:
                continue

            # Get calculated version (with extension) or fall back to target
            version = api_versions.get(api_name, api.get("target_api_version", ""))

            # Get title from provided titles or use api_name as fallback
            title = api_titles.get(api_name, api_name)

            apis.append(
                ApiMetadata(
                    api_name=api_name,
                    api_version=version,
                    api_title=title,
                )
            )

        return apis
