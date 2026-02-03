"""
Unit tests for the CHANGELOG generator.

Tests cover cycle extraction, release type descriptions, API section formatting,
draft generation, and file writing.
"""

import pytest
from pathlib import Path

from release_automation.scripts.changelog_generator import (
    ChangelogGenerator,
    RELEASE_TYPE_MAP,
)


# --- Fixtures ---


@pytest.fixture
def generator():
    """Create a ChangelogGenerator with the actual template directory."""
    return ChangelogGenerator()


@pytest.fixture
def single_api_metadata():
    """Metadata dict with a single API."""
    return {
        "repository": {
            "release_type": "pre-release-rc",
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "api_version": "v1.1.0-rc.1",
                "api_title": "quality-on-demand",
                "api_file_name": "quality-on-demand",
            }
        ],
        "dependencies": {
            "commonalities_release": "v0.6.0 (r3.3)",
            "identity_consent_management_release": "v0.4.0 (r3.3)",
        },
    }


@pytest.fixture
def multi_api_metadata():
    """Metadata dict with multiple APIs."""
    return {
        "repository": {
            "release_type": "public-release",
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "api_version": "v1.1.0",
                "api_title": "quality-on-demand",
                "api_file_name": "quality-on-demand",
            },
            {
                "api_name": "qos-profiles",
                "api_version": "v1.1.0",
                "api_title": "qos-profiles",
                "api_file_name": "qos-profiles",
            },
        ],
        "dependencies": {
            "commonalities_release": "v0.6.0 (r3.3)",
            "identity_consent_management_release": "v0.4.0 (r3.3)",
        },
    }


@pytest.fixture
def sample_changes_body():
    """Sample candidate changes body from GitHub generate-notes API."""
    return (
        "## What's Changed\n"
        "* Add feature X by @user1 in https://github.com/camaraproject/QualityOnDemand/pull/100\n"
        "* Fix bug Y by @user2 in https://github.com/camaraproject/QualityOnDemand/pull/101\n"
        "\n"
        "**Full Changelog**: https://github.com/camaraproject/QualityOnDemand/compare/r3.2...r4.1\n"
    )


# --- Cycle Extraction ---


class TestCycleExtraction:
    """Tests for _get_cycle()."""

    def test_r4_1_returns_4(self, generator):
        assert generator._get_cycle("r4.1") == "4"

    def test_r3_2_returns_3(self, generator):
        assert generator._get_cycle("r3.2") == "3"

    def test_r10_1_returns_10(self, generator):
        assert generator._get_cycle("r10.1") == "10"

    def test_invalid_tag_raises_error(self, generator):
        with pytest.raises(ValueError, match="Cannot extract cycle"):
            generator._get_cycle("v1.0.0")


# --- Release Type Description ---


class TestReleaseTypeDescription:
    """Tests for _get_release_type_description()."""

    def test_pre_release_alpha_returns_prerelease(self, generator):
        assert generator._get_release_type_description("pre-release-alpha") == "pre-release"

    def test_pre_release_rc_returns_release_candidate(self, generator):
        assert generator._get_release_type_description("pre-release-rc") == "release candidate"

    def test_public_release_returns_public_release(self, generator):
        assert generator._get_release_type_description("public-release") == "public release"

    def test_unknown_returns_as_is(self, generator):
        assert generator._get_release_type_description("custom") == "custom"


# --- API Section Formatting ---


class TestApiSectionFormatting:
    """Tests for format_api_section static method."""

    def test_format_single_api_section(self):
        api = {
            "api_name": "quality-on-demand",
            "api_version": "v1.1.0",
            "api_title": "quality-on-demand",
            "api_file_name": "quality-on-demand",
        }
        result = ChangelogGenerator.format_api_section(api, "r3.2", "QualityOnDemand")
        assert "## quality-on-demand v1.1.0" in result
        assert "View it on ReDoc" in result
        assert "View it on Swagger Editor" in result
        assert "YAML spec file" in result
        assert "### Added" in result
        assert "### Changed" in result
        assert "### Fixed" in result
        assert "### Removed" in result
        assert "_To be filled during release review_" in result

    def test_format_api_section_url_patterns(self):
        api = {
            "api_name": "my-api",
            "api_version": "v1.0.0",
            "api_title": "my-api",
            "api_file_name": "my-api",
        }
        result = ChangelogGenerator.format_api_section(api, "r4.1", "TestRepo", org="myorg")
        assert "https://raw.githubusercontent.com/myorg/TestRepo/r4.1/code/API_definitions/my-api.yaml" in result
        assert "https://github.com/myorg/TestRepo/blob/r4.1/code/API_definitions/my-api.yaml" in result
        assert "redocly.github.io/redoc" in result
        assert "camaraproject.github.io/swagger-ui" in result

    def test_format_api_section_uses_api_name_as_fallback(self):
        api = {
            "api_name": "fallback-api",
            "api_version": "v1.0.0",
        }
        result = ChangelogGenerator.format_api_section(api, "r1.1", "TestRepo")
        assert "## fallback-api v1.0.0" in result


# --- Draft Generation ---


class TestDraftGeneration:
    """Tests for generate_draft()."""

    def test_generate_draft_single_api(self, generator, single_api_metadata):
        result = generator.generate_draft(
            release_tag="r4.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
        )
        assert "# r4.1" in result
        assert "release candidate" in result
        assert "quality-on-demand v1.1.0-rc.1" in result
        assert "Commonalities v0.6.0 (r3.3)" in result

    def test_generate_draft_with_candidate_changes(
        self, generator, single_api_metadata, sample_changes_body
    ):
        result = generator.generate_draft(
            release_tag="r4.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
            candidate_changes=sample_changes_body,
        )
        assert "Add feature X" in result
        assert "@user1" in result
        assert "Fix bug Y" in result
        assert "Full Changelog" in result
        assert "compare/r3.2...r4.1" in result

    def test_generate_draft_no_candidate_changes(self, generator, single_api_metadata):
        result = generator.generate_draft(
            release_tag="r1.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
            candidate_changes=None,
        )
        assert "# r1.1" in result
        assert "No candidate changes available" in result

    def test_generate_draft_multiple_apis(self, generator, multi_api_metadata):
        result = generator.generate_draft(
            release_tag="r3.2",
            metadata=multi_api_metadata,
            repo_name="QualityOnDemand",
        )
        assert "quality-on-demand v1.1.0" in result
        assert "qos-profiles v1.1.0" in result
        assert "public release" in result


# --- File Writing ---


class TestFileWriting:
    """Tests for write_changelog()."""

    def test_write_new_changelog_creates_dir_and_file(self, generator, tmp_path):
        content = "# r4.1\n\n## Release Notes\n\nTest content\n"
        path = generator.write_changelog(str(tmp_path), content, "r4.1", "QualityOnDemand")
        assert path == "CHANGELOG/CHANGELOG-r4.md"
        filepath = tmp_path / "CHANGELOG" / "CHANGELOG-r4.md"
        assert filepath.exists()
        file_content = filepath.read_text()
        assert "# Changelog QualityOnDemand" in file_content
        assert "# r4.1" in file_content

    def test_write_existing_changelog_prepends_section(self, generator, tmp_path):
        # Create existing file with one release
        changelog_dir = tmp_path / "CHANGELOG"
        changelog_dir.mkdir()
        existing_file = changelog_dir / "CHANGELOG-r4.md"
        existing_content = (
            "# Changelog QualityOnDemand\n\n"
            "Recording rules...\n\n"
            "# r4.1\n\n## Release Notes\n\nFirst release content\n"
        )
        existing_file.write_text(existing_content)

        # Add new release section
        new_content = "# r4.2\n\n## Release Notes\n\nSecond release content\n"
        generator.write_changelog(str(tmp_path), new_content, "r4.2", "QualityOnDemand")

        result = existing_file.read_text()
        # New section should come before old section
        r42_pos = result.index("# r4.2")
        r41_pos = result.index("# r4.1")
        assert r42_pos < r41_pos

    def test_header_generation_contains_repo_name(self, generator):
        header = generator._generate_header("QualityOnDemand")
        assert "# Changelog QualityOnDemand" in header
        assert "best results, use the latest published release" in header
