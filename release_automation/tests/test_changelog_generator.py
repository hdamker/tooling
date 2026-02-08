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
    TOC_START_MARKER,
    TOC_END_MARKER,
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


# --- Table of Contents ---


class TestTocGeneration:
    """Tests for Table of Contents generation."""

    # --- Anchor conversion ---

    def test_anchor_simple_release_tag(self):
        assert ChangelogGenerator._heading_to_anchor("r3.2") == "r32"

    def test_anchor_double_digit_cycle(self):
        assert ChangelogGenerator._heading_to_anchor("r10.1") == "r101"

    def test_anchor_preserves_hyphens(self):
        assert ChangelogGenerator._heading_to_anchor("v0.10.0-rc2") == "v0100-rc2"

    # --- Entry extraction ---

    def test_extract_entries_finds_all_headings(self):
        content = (
            "# Changelog Repo\n\n"
            "Preamble text\n\n"
            "# r4.2\n\n## Release Notes\n\nThis pre-release contains\n\n"
            "# r4.1\n\n## Release Notes\n\nThis pre-release contains\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert len(entries) == 2
        assert entries[0]["heading"] == "r4.2"
        assert entries[1]["heading"] == "r4.1"

    def test_extract_entries_detects_public_release(self):
        content = (
            "# r4.2\n\n## Release Notes\n\n"
            "This public release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert entries[0]["is_public"] is True

    def test_extract_entries_detects_maintenance_release(self):
        content = (
            "# r4.2\n\n## Release Notes\n\n"
            "This maintenance release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert entries[0]["is_public"] is True

    def test_extract_entries_pre_release_not_public(self):
        content = (
            "# r4.1\n\n## Release Notes\n\n"
            "This pre-release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert entries[0]["is_public"] is False

    # --- TOC formatting ---

    def test_format_toc_empty_entries(self):
        assert ChangelogGenerator._format_toc([]) == ""

    def test_format_toc_public_entry_is_bold(self):
        entries = [{"heading": "r4.2", "is_public": True}]
        result = ChangelogGenerator._format_toc(entries)
        assert "## Table of Contents" in result
        assert "- **[r4.2](#r42)**" in result

    def test_format_toc_mixed_entries_order(self):
        entries = [
            {"heading": "r4.2", "is_public": True},
            {"heading": "r4.1", "is_public": False},
        ]
        result = ChangelogGenerator._format_toc(entries)
        assert "- **[r4.2](#r42)**" in result
        assert "- [r4.1](#r41)" in result
        assert result.index("r4.2") < result.index("r4.1")

    # --- File integration ---

    def test_new_file_contains_toc(self, generator, tmp_path):
        content = "# r4.1\n\n## Release Notes\n\nThis pre-release contains the definition\n"
        generator.write_changelog(str(tmp_path), content, "r4.1", "TestRepo")
        filepath = tmp_path / "CHANGELOG" / "CHANGELOG-r4.md"
        file_content = filepath.read_text()
        assert TOC_START_MARKER in file_content
        assert TOC_END_MARKER in file_content
        assert "## Table of Contents" in file_content
        assert "- [r4.1](#r41)" in file_content

    def test_prepend_updates_toc(self, generator, tmp_path):
        # Write first release (pre-release)
        content1 = "# r4.1\n\n## Release Notes\n\nThis pre-release contains the definition\n"
        generator.write_changelog(str(tmp_path), content1, "r4.1", "TestRepo")

        # Write second release (public)
        content2 = "# r4.2\n\n## Release Notes\n\nThis public release contains the definition\n"
        generator.write_changelog(str(tmp_path), content2, "r4.2", "TestRepo")

        filepath = tmp_path / "CHANGELOG" / "CHANGELOG-r4.md"
        file_content = filepath.read_text()
        # Both entries should be in TOC
        assert "- **[r4.2](#r42)**" in file_content  # public = bold
        assert "- [r4.1](#r41)" in file_content       # pre-release = plain
        # r4.2 should be listed before r4.1 in TOC
        toc_start = file_content.index(TOC_START_MARKER)
        toc_end = file_content.index(TOC_END_MARKER)
        toc_section = file_content[toc_start:toc_end]
        assert toc_section.index("r4.2") < toc_section.index("r4.1")

    def test_fallback_for_file_without_markers(self, generator, tmp_path):
        """Legacy files created before TOC feature get markers inserted."""
        changelog_dir = tmp_path / "CHANGELOG"
        changelog_dir.mkdir()
        existing_file = changelog_dir / "CHANGELOG-r4.md"
        # Write a legacy file without TOC markers
        legacy_content = (
            "# Changelog TestRepo\n\n"
            "**Please be aware...**\n\n"
            "# r4.1\n\n## Release Notes\n\nThis pre-release contains the definition\n"
        )
        existing_file.write_text(legacy_content)

        # Add new release section
        new_content = "# r4.2\n\n## Release Notes\n\nThis public release contains the definition\n"
        generator.write_changelog(str(tmp_path), new_content, "r4.2", "TestRepo")

        file_content = existing_file.read_text()
        assert TOC_START_MARKER in file_content
        assert TOC_END_MARKER in file_content
        assert "## Table of Contents" in file_content
        assert "- **[r4.2](#r42)**" in file_content
        assert "- [r4.1](#r41)" in file_content

    def test_header_contains_toc_markers(self, generator):
        """New headers include empty TOC markers between title and preamble."""
        header = generator._generate_header("TestRepo")
        assert TOC_START_MARKER in header
        assert TOC_END_MARKER in header
        assert header.index(TOC_START_MARKER) < header.index("Please be aware")
