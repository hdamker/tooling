"""
Unit tests for the metadata generator.

These tests verify release-metadata.yaml generation for all scenarios:
- Complete metadata generation
- Missing dependencies handling
- Empty API list
- Optional fields (release_notes)
- Release type mapping
"""

import pytest

from release_automation.scripts.metadata_generator import (
    ApiMetadata,
    MetadataGenerator,
    ReleaseMetadata,
)


@pytest.fixture
def generator():
    """Create a MetadataGenerator instance."""
    return MetadataGenerator()


@pytest.fixture
def sample_release_plan():
    """Create a sample release plan for testing."""
    return {
        "repository": {
            "repository_name": "QualityOnDemand",
            "target_release_tag": "r4.2",
            "target_release_type": "pre-release-rc",
            "release_notes": "Pre-release for CAMARA Sync26 meta-release.",
        },
        "dependencies": {
            "commonalities_release": {
                "release_tag": "r4.2",
                "version": "1.2.0-rc.1",
            },
            "identity_consent_management_release": {
                "release_tag": "r4.3",
                "version": "1.1.0",
            },
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "target_api_version": "3.2.0",
                "target_api_status": "rc",
            },
            {
                "api_name": "qos-profiles",
                "target_api_version": "1.0.0",
                "target_api_status": "public",
            },
        ],
    }


@pytest.fixture
def sample_api_versions():
    """Sample calculated API versions."""
    return {
        "quality-on-demand": "3.2.0-rc.2",
        "qos-profiles": "1.0.0",
    }


@pytest.fixture
def sample_api_titles():
    """Sample API titles."""
    return {
        "quality-on-demand": "Quality On Demand",
        "qos-profiles": "QoS Profiles",
    }


class TestApiMetadata:
    """Tests for ApiMetadata dataclass."""

    def test_to_dict(self):
        """ApiMetadata.to_dict returns correct structure."""
        api = ApiMetadata(
            api_name="location-verification",
            api_version="3.2.0-rc.1",
            api_title="Location Verification",
        )

        result = api.to_dict()

        assert result == {
            "api_name": "location-verification",
            "api_version": "3.2.0-rc.1",
            "api_title": "Location Verification",
        }


class TestReleaseMetadata:
    """Tests for ReleaseMetadata dataclass."""

    def test_to_dict_complete(self):
        """ReleaseMetadata.to_dict includes all fields when present."""
        metadata = ReleaseMetadata(
            repository_name="QualityOnDemand",
            release_tag="r4.2",
            release_type="pre-release-rc",
            src_commit_sha="abc123def456",
            apis=[
                ApiMetadata(
                    api_name="quality-on-demand",
                    api_version="3.2.0-rc.1",
                    api_title="Quality On Demand",
                )
            ],
            release_date=None,
            release_notes="Test release notes",
            commonalities_release="r4.2 (1.2.0-rc.1)",
            identity_consent_management_release="r4.3 (1.1.0)",
        )

        result = metadata.to_dict()

        assert result["repository"]["repository_name"] == "QualityOnDemand"
        assert result["repository"]["release_tag"] == "r4.2"
        assert result["repository"]["release_type"] == "pre-release-rc"
        assert result["repository"]["src_commit_sha"] == "abc123def456"
        assert result["repository"]["release_date"] is None
        assert result["repository"]["release_notes"] == "Test release notes"
        assert result["dependencies"]["commonalities_release"] == "r4.2 (1.2.0-rc.1)"
        assert (
            result["dependencies"]["identity_consent_management_release"]
            == "r4.3 (1.1.0)"
        )
        assert len(result["apis"]) == 1
        assert result["apis"][0]["api_name"] == "quality-on-demand"

    def test_to_dict_minimal(self):
        """ReleaseMetadata.to_dict excludes optional fields when empty."""
        metadata = ReleaseMetadata(
            repository_name="TestRepo",
            release_tag="r1.0",
            release_type="pre-release-alpha",
            src_commit_sha=None,
            apis=[],
        )

        result = metadata.to_dict()

        assert "dependencies" not in result
        assert "release_notes" not in result["repository"]
        assert result["repository"]["src_commit_sha"] is None

    def test_to_dict_partial_dependencies(self):
        """ReleaseMetadata.to_dict handles partial dependencies."""
        metadata = ReleaseMetadata(
            repository_name="TestRepo",
            release_tag="r1.0",
            release_type="pre-release-alpha",
            src_commit_sha=None,
            apis=[],
            commonalities_release="r4.2 (1.0.0)",
            # No ICM dependency
        )

        result = metadata.to_dict()

        assert "dependencies" in result
        assert result["dependencies"]["commonalities_release"] == "r4.2 (1.0.0)"
        assert "identity_consent_management_release" not in result["dependencies"]


class TestMetadataGenerator:
    """Tests for MetadataGenerator class."""

    def test_generate_complete_metadata(
        self, generator, sample_release_plan, sample_api_versions, sample_api_titles
    ):
        """Generate complete metadata from release plan."""
        result = generator.generate(
            release_plan=sample_release_plan,
            api_versions=sample_api_versions,
            src_commit_sha="abcd1234efgh5678",
            api_titles=sample_api_titles,
        )

        # Check repository section
        assert result["repository"]["repository_name"] == "QualityOnDemand"
        assert result["repository"]["release_tag"] == "r4.2"
        assert result["repository"]["release_type"] == "pre-release-rc"
        assert result["repository"]["src_commit_sha"] == "abcd1234efgh5678"
        assert result["repository"]["release_date"] is None
        assert (
            result["repository"]["release_notes"]
            == "Pre-release for CAMARA Sync26 meta-release."
        )

        # Check dependencies
        assert result["dependencies"]["commonalities_release"] == "r4.2 (1.2.0-rc.1)"
        assert (
            result["dependencies"]["identity_consent_management_release"]
            == "r4.3 (1.1.0)"
        )

        # Check APIs - should use calculated versions
        assert len(result["apis"]) == 2
        assert result["apis"][0]["api_name"] == "quality-on-demand"
        assert result["apis"][0]["api_version"] == "3.2.0-rc.2"
        assert result["apis"][0]["api_title"] == "Quality On Demand"
        assert result["apis"][1]["api_name"] == "qos-profiles"
        assert result["apis"][1]["api_version"] == "1.0.0"

    def test_generate_without_dependencies(self, generator):
        """Generate metadata without dependencies section."""
        release_plan = {
            "repository": {
                "repository_name": "SimpleAPI",
                "target_release_tag": "r1.0",
                "target_release_type": "pre-release-alpha",
            },
            "apis": [
                {
                    "api_name": "simple-api",
                    "target_api_version": "0.1.0",
                    "target_api_status": "alpha",
                }
            ],
        }

        result = generator.generate(
            release_plan=release_plan,
            api_versions={"simple-api": "0.1.0-alpha.1"},
            src_commit_sha="abc123",
            api_titles={"simple-api": "Simple API"},
        )

        assert "dependencies" not in result
        assert result["apis"][0]["api_version"] == "0.1.0-alpha.1"

    def test_generate_with_empty_api_list(self, generator):
        """Generate metadata with no APIs."""
        release_plan = {
            "repository": {
                "repository_name": "EmptyRepo",
                "target_release_tag": "r1.0",
                "target_release_type": "pre-release-alpha",
            },
            "apis": [],
        }

        result = generator.generate(
            release_plan=release_plan,
            api_versions={},
            src_commit_sha=None,
            api_titles={},
        )

        assert result["apis"] == []
        assert result["repository"]["release_type"] == "pre-release-alpha"

    def test_generate_with_null_commit_sha(self, generator):
        """Generate metadata with null commit SHA."""
        release_plan = {
            "repository": {
                "repository_name": "TestRepo",
                "target_release_tag": "r2.0",
                "target_release_type": "public-release",
            },
            "apis": [],
        }

        result = generator.generate(
            release_plan=release_plan,
            api_versions={},
            src_commit_sha=None,
            api_titles={},
        )

        assert result["repository"]["src_commit_sha"] is None

    def test_generate_derives_repository_name_from_repo_param(self, generator):
        """repository_name derived from repo parameter, not release plan."""
        release_plan = {
            "repository": {
                "target_release_tag": "r1.0",
                "target_release_type": "pre-release-alpha",
            },
            "apis": [],
        }

        result = generator.generate(
            release_plan=release_plan,
            api_versions={},
            src_commit_sha=None,
            api_titles={},
            repo="hdamker/TestRepo-QoD",
        )

        assert result["repository"]["repository_name"] == "TestRepo-QoD"

    def test_generate_falls_back_to_plan_without_repo_param(self, generator):
        """Falls back to release plan repository_name when repo not provided."""
        release_plan = {
            "repository": {
                "repository_name": "QualityOnDemand",
                "target_release_tag": "r1.0",
                "target_release_type": "pre-release-alpha",
            },
            "apis": [],
        }

        result = generator.generate(
            release_plan=release_plan,
            api_versions={},
            src_commit_sha=None,
            api_titles={},
        )

        assert result["repository"]["repository_name"] == "QualityOnDemand"


class TestReleaseTypeValidation:
    """Tests for release type validation (DEC-009: long-form values only)."""

    def test_pre_release_alpha_accepted(self, generator):
        """pre-release-alpha is a valid release type."""
        assert generator._validate_release_type("pre-release-alpha") == "pre-release-alpha"

    def test_pre_release_rc_accepted(self, generator):
        """pre-release-rc is a valid release type."""
        assert generator._validate_release_type("pre-release-rc") == "pre-release-rc"

    def test_public_release_accepted(self, generator):
        """public-release is a valid release type."""
        assert generator._validate_release_type("public-release") == "public-release"

    def test_maintenance_release_accepted(self, generator):
        """maintenance-release is a valid release type."""
        assert generator._validate_release_type("maintenance-release") == "maintenance-release"

    def test_short_form_alpha_rejected(self, generator):
        """Short-form 'alpha' is rejected — must use 'pre-release-alpha'."""
        with pytest.raises(ValueError, match="Unknown release type: 'alpha'"):
            generator._validate_release_type("alpha")

    def test_short_form_rc_rejected(self, generator):
        """Short-form 'rc' is rejected — must use 'pre-release-rc'."""
        with pytest.raises(ValueError, match="Unknown release type: 'rc'"):
            generator._validate_release_type("rc")

    def test_short_form_public_rejected(self, generator):
        """Short-form 'public' is rejected — must use 'public-release'."""
        with pytest.raises(ValueError, match="Unknown release type: 'public'"):
            generator._validate_release_type("public")

    def test_none_rejected(self, generator):
        """'none' is rejected — NOT_PLANNED state should not reach metadata generation."""
        with pytest.raises(ValueError, match="Unknown release type: 'none'"):
            generator._validate_release_type("none")

    def test_unknown_rejected(self, generator):
        """Unknown values are rejected with clear error."""
        with pytest.raises(ValueError, match="Unknown release type: 'invalid'"):
            generator._validate_release_type("invalid")

    def test_empty_string_rejected(self, generator):
        """Empty string is rejected."""
        with pytest.raises(ValueError, match="Unknown release type: ''"):
            generator._validate_release_type("")


class TestDependencyFormatting:
    """Tests for dependency formatting."""

    def test_format_dependency_with_version(self, generator):
        """Format dependency with version."""
        dep = {"release_tag": "r4.2", "version": "1.2.0-rc.1"}
        result = generator._format_dependency(dep)
        assert result == "r4.2 (1.2.0-rc.1)"

    def test_format_dependency_without_version(self, generator):
        """Format dependency without version returns just tag."""
        dep = {"release_tag": "r4.2"}
        result = generator._format_dependency(dep)
        assert result == "r4.2"

    def test_format_dependency_none(self, generator):
        """Format None dependency returns None."""
        assert generator._format_dependency(None) is None

    def test_format_dependency_empty_dict(self, generator):
        """Format empty dict returns None."""
        assert generator._format_dependency({}) is None

    def test_format_dependency_no_release_tag(self, generator):
        """Format dependency without release_tag returns None."""
        dep = {"version": "1.0.0"}
        assert generator._format_dependency(dep) is None

    def test_format_dependency_string(self, generator):
        """Format string dependency (simple release tag) returns the string."""
        result = generator._format_dependency("r3.4")
        assert result == "r3.4"

    def test_format_dependency_empty_string(self, generator):
        """Format empty string dependency returns None."""
        result = generator._format_dependency("")
        assert result is None


class TestApiBuildList:
    """Tests for API list building."""

    def test_uses_calculated_versions(self, generator):
        """Build API list uses calculated versions over target versions."""
        release_plan = {
            "apis": [
                {
                    "api_name": "test-api",
                    "target_api_version": "1.0.0",
                }
            ]
        }
        api_versions = {"test-api": "1.0.0-rc.3"}
        api_titles = {"test-api": "Test API"}

        apis = generator._build_api_list(release_plan, api_versions, api_titles)

        assert len(apis) == 1
        assert apis[0].api_version == "1.0.0-rc.3"

    def test_falls_back_to_target_version(self, generator):
        """Build API list falls back to target version if not calculated."""
        release_plan = {
            "apis": [
                {
                    "api_name": "test-api",
                    "target_api_version": "2.0.0",
                }
            ]
        }
        api_versions = {}  # No calculated version
        api_titles = {"test-api": "Test API"}

        apis = generator._build_api_list(release_plan, api_versions, api_titles)

        assert apis[0].api_version == "2.0.0"

    def test_falls_back_to_api_name_for_title(self, generator):
        """Build API list uses api_name as title fallback."""
        release_plan = {
            "apis": [
                {
                    "api_name": "unknown-api",
                    "target_api_version": "1.0.0",
                }
            ]
        }
        api_versions = {}
        api_titles = {}  # No title provided

        apis = generator._build_api_list(release_plan, api_versions, api_titles)

        assert apis[0].api_title == "unknown-api"

    def test_skips_apis_without_name(self, generator):
        """Build API list skips entries without api_name."""
        release_plan = {
            "apis": [
                {"target_api_version": "1.0.0"},  # No api_name
                {"api_name": "valid-api", "target_api_version": "2.0.0"},
            ]
        }

        apis = generator._build_api_list(release_plan, {}, {})

        assert len(apis) == 1
        assert apis[0].api_name == "valid-api"


class TestExtractRepoName:
    """Tests for repository name extraction."""

    def test_extracts_from_repository_section(self, generator):
        """Extract repository name from repository section."""
        release_plan = {
            "repository": {
                "repository_name": "QualityOnDemand",
            }
        }

        result = generator._extract_repo_name(release_plan)

        assert result == "QualityOnDemand"

    def test_returns_empty_if_missing(self, generator):
        """Return empty string if repository_name missing."""
        release_plan = {"repository": {}}

        result = generator._extract_repo_name(release_plan)

        assert result == ""

    def test_returns_empty_if_no_repository_section(self, generator):
        """Return empty string if no repository section."""
        release_plan = {}

        result = generator._extract_repo_name(release_plan)

        assert result == ""
