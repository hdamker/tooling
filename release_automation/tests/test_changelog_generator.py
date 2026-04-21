"""
Unit tests for the CHANGELOG generator.

Tests cover cycle extraction, release type descriptions, API section formatting,
draft generation, and file writing.
"""

import pytest
from pathlib import Path

from release_automation.scripts.changelog_generator import (
    CANDIDATE_CHANGES_END_MARKER,
    CANDIDATE_CHANGES_START_MARKER,
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

    def test_format_api_section_uses_api_name_not_title(self):
        """Heading must use kebab-case api_name, not the OpenAPI info.title."""
        api = {
            "api_name": "quality-on-demand",
            "api_version": "v1.0.0",
            "api_title": "CAMARA Quality On Demand",
            "api_file_name": "quality-on-demand",
        }
        result = ChangelogGenerator.format_api_section(api, "r1.1", "TestRepo")
        assert "## quality-on-demand v1.0.0" in result
        assert "**quality-on-demand v1.0.0 is ...**" in result
        assert "CAMARA" not in result

    def test_format_api_section_without_title(self):
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

    def test_generate_draft_allows_commonalities_version_only(
        self, generator, single_api_metadata
    ):
        single_api_metadata["dependencies"]["commonalities_release"] = "0.7.0-rc.1"
        single_api_metadata["dependencies"][
            "identity_consent_management_release"
        ] = "0.5.0-rc.1"

        result = generator.generate_draft(
            release_tag="r4.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
        )

        assert "Commonalities 0.7.0-rc.1" in result
        assert "Identity and Consent Management 0.5.0-rc.1" in result

    def test_generate_draft_with_candidate_changes(
        self, generator, single_api_metadata, sample_changes_body
    ):
        result = generator.generate_draft(
            release_tag="r4.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
            candidate_changes=sample_changes_body,
        )
        # PR entries present inside candidate changes block
        assert "Add feature X" in result
        assert "@user1" in result
        assert "Fix bug Y" in result
        # Markers wrap the candidate changes block
        assert CANDIDATE_CHANGES_START_MARKER in result
        assert CANDIDATE_CHANGES_END_MARKER in result
        # Instruction text visible (not collapsed)
        assert "auto-removed on merge" in result
        # Full Changelog link at end, outside markers
        assert "compare/r3.2...r4.1" in result
        end_marker_pos = result.index(CANDIDATE_CHANGES_END_MARKER)
        full_changelog_pos = result.index("compare/r3.2...r4.1")
        assert full_changelog_pos > end_marker_pos

    def test_generate_draft_with_candidate_changes_position(
        self, generator, single_api_metadata, sample_changes_body
    ):
        """Candidate changes block appears BEFORE API sections."""
        result = generator.generate_draft(
            release_tag="r4.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
            candidate_changes=sample_changes_body,
        )
        start_marker_pos = result.index(CANDIDATE_CHANGES_START_MARKER)
        api_section_pos = result.index("### Added")
        assert start_marker_pos < api_section_pos

    def test_generate_draft_no_candidate_changes(self, generator, single_api_metadata):
        result = generator.generate_draft(
            release_tag="r1.1",
            metadata=single_api_metadata,
            repo_name="QualityOnDemand",
            candidate_changes=None,
        )
        assert "# r1.1" in result
        # No markers or working area when no candidate changes
        assert CANDIDATE_CHANGES_START_MARKER not in result
        assert CANDIDATE_CHANGES_END_MARKER not in result
        assert "Working area" not in result
        # API sections still present
        assert "### Added" in result

    def test_generate_draft_multiple_apis(self, generator, multi_api_metadata):
        result = generator.generate_draft(
            release_tag="r3.2",
            metadata=multi_api_metadata,
            repo_name="QualityOnDemand",
        )
        assert "quality-on-demand v1.1.0" in result
        assert "qos-profiles v1.1.0" in result
        assert "public release" in result

    def test_generate_draft_uses_api_name_not_title_in_summary(self, generator):
        """Release notes summary list must use api_name, not api_title."""
        metadata = {
            "repository": {"release_type": "pre-release-alpha"},
            "apis": [
                {
                    "api_name": "quality-on-demand",
                    "api_version": "v1.0.0-alpha.1",
                    "api_title": "CAMARA Quality On Demand",
                    "api_file_name": "quality-on-demand",
                }
            ],
            "dependencies": {
                "commonalities_release": "v0.6.0 (r3.3)",
                "identity_consent_management_release": "v0.4.0 (r3.3)",
            },
        }
        result = generator.generate_draft(
            release_tag="r1.1", metadata=metadata, repo_name="TestRepo"
        )
        assert "* quality-on-demand v1.0.0-alpha.1" in result
        assert "CAMARA Quality On Demand" not in result


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


# --- File Writing: Dual-Mode (flat vs per-cycle) ---


class TestFileWritingFlatMode:
    """Flat-mode (CHANGELOG.md at repo root) activates only for maintenance
    releases when no per-cycle file exists yet. Every other release type
    stays on per-cycle even if a legacy flat CHANGELOG.md is present."""

    def test_maintenance_release_with_no_cycle_file_writes_flat(self, generator, tmp_path):
        content = "# r2.3\n\n## Release Notes\n\nMaintenance patch\n"
        path = generator.write_changelog(
            str(tmp_path),
            content,
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )
        assert path == "CHANGELOG.md"
        flat = tmp_path / "CHANGELOG.md"
        assert flat.exists()
        assert "# r2.3" in flat.read_text()
        # No per-cycle directory should be created when writing flat
        assert not (tmp_path / "CHANGELOG" / "CHANGELOG-r2.md").exists()

    def test_maintenance_release_with_existing_cycle_file_uses_per_cycle(
        self, generator, tmp_path
    ):
        # Pre-seed the per-cycle file
        (tmp_path / "CHANGELOG").mkdir()
        per_cycle = tmp_path / "CHANGELOG" / "CHANGELOG-r2.md"
        per_cycle.write_text(
            "# Changelog SimpleEdgeDiscovery\n\n"
            "Recording rules...\n\n"
            "# r2.2\n\n## Release Notes\n\nPrior public\n"
        )
        flat_before = "legacy content\n"
        (tmp_path / "CHANGELOG.md").write_text(flat_before)

        new_section = "# r2.3\n\n## Release Notes\n\nMaintenance patch\n"
        path = generator.write_changelog(
            str(tmp_path),
            new_section,
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )
        assert path == "CHANGELOG/CHANGELOG-r2.md"
        # Per-cycle file was updated (r2.3 prepended), flat file untouched
        assert "# r2.3" in per_cycle.read_text()
        assert (tmp_path / "CHANGELOG.md").read_text() == flat_before

    def test_public_release_always_uses_per_cycle(self, generator, tmp_path):
        # Flat CHANGELOG.md present, no CHANGELOG/ directory
        (tmp_path / "CHANGELOG.md").write_text("legacy content\n")

        content = "# r4.2\n\n## Release Notes\n\nPublic\n"
        path = generator.write_changelog(
            str(tmp_path),
            content,
            "r4.2",
            "QualityOnDemand",
            release_type="public-release",
        )
        assert path == "CHANGELOG/CHANGELOG-r4.md"
        assert (tmp_path / "CHANGELOG" / "CHANGELOG-r4.md").exists()

    def test_pre_release_rc_always_uses_per_cycle(self, generator, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text("legacy content\n")

        content = "# r4.1\n\n## Release Notes\n\nRC\n"
        path = generator.write_changelog(
            str(tmp_path),
            content,
            "r4.1",
            "QualityOnDemand",
            release_type="pre-release-rc",
        )
        assert path == "CHANGELOG/CHANGELOG-r4.md"

    def test_empty_release_type_defaults_to_per_cycle(self, generator, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text("legacy content\n")

        content = "# r4.1\n\n## Release Notes\n\nNo type\n"
        path = generator.write_changelog(
            str(tmp_path), content, "r4.1", "QualityOnDemand"
        )
        assert path == "CHANGELOG/CHANGELOG-r4.md"

    def test_flat_write_prepends_before_first_release_heading(self, generator, tmp_path):
        # Shape mirrors SimpleEdgeDiscovery's CHANGELOG.md:
        # title + manual TOC + NOTE + preamble + release sections
        legacy = (
            "# Changelog Simple Edge Discovery\n\n"
            "NOTE: \n\n"
            "## Table of contents\n\n"
            "- [r2.2](#r22)\n"
            "- [r2.1 - rc](#r21---rc)\n\n"
            "**Please use the latest published release.**\n\n"
            "# r2.2 - Fall25 public release\n\n"
            "Prior public release content\n"
        )
        (tmp_path / "CHANGELOG.md").write_text(legacy)

        new_section = "# r2.3\n\n## Release Notes\n\nMaintenance patch\n"
        generator.write_changelog(
            str(tmp_path),
            new_section,
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )

        result = (tmp_path / "CHANGELOG.md").read_text()
        r23 = result.index("# r2.3")
        r22 = result.index("# r2.2")
        assert r23 < r22

    def test_flat_write_injects_toc_markers_on_first_run(self, generator, tmp_path):
        # Legacy CHANGELOG.md has no automation TOC markers
        legacy = (
            "# Changelog Simple Edge Discovery\n\n"
            "## Table of contents\n\n"
            "- [r2.2](#r22)\n\n"
            "# r2.2\n\nPrior content\n"
        )
        (tmp_path / "CHANGELOG.md").write_text(legacy)

        new_section = "# r2.3\n\nThis maintenance release contains something\n"
        generator.write_changelog(
            str(tmp_path),
            new_section,
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )

        result = (tmp_path / "CHANGELOG.md").read_text()
        assert TOC_START_MARKER in result
        assert TOC_END_MARKER in result

    def test_flat_write_updates_toc_idempotently(self, generator, tmp_path):
        # First maintenance write inserts markers
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog Simple Edge Discovery\n\n"
            "# r2.2\n\nPrior content\n"
        )
        generator.write_changelog(
            str(tmp_path),
            "# r2.3\n\nThis maintenance release contains A\n",
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )
        # Second maintenance write (hypothetical r2.4 still before migration)
        generator.write_changelog(
            str(tmp_path),
            "# r2.4\n\nThis maintenance release contains B\n",
            "r2.4",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )

        result = (tmp_path / "CHANGELOG.md").read_text()
        assert result.count(TOC_START_MARKER) == 1
        assert result.count(TOC_END_MARKER) == 1
        # Both release entries present in TOC
        assert "[r2.4](#r24)" in result
        assert "[r2.3](#r23)" in result

    def test_flat_write_end_to_end_sed_style_headings(self, generator, tmp_path):
        """End-to-end: a repo with SED-style suffixed headings
        (``# r2.2 - Fall25 public release``) gets a new maintenance
        section prepended. The regenerated TOC lists every legacy
        heading with the anchor GitHub actually renders for the full
        heading text, not the short-tag anchor."""
        # Simulate SimpleEdgeDiscovery's legacy CHANGELOG.md: mixed heading
        # styles, one with a trailing descriptor, one without.
        legacy = (
            "# Changelog Simple Edge Discovery\n\n"
            "# r2.2 - Fall25 public release\n\n"
            "This public release contains the definition and documentation of\n"
            "* simple-edge-discovery v2.0.0\n\n"
            "# r2.1 - rc\n\n"
            "This pre-release contains the definition\n\n"
            "# r1.3\n\n"
            "This public release contains the definition\n"
        )
        (tmp_path / "CHANGELOG.md").write_text(legacy)

        new_section = (
            "# r2.3\n\n## Release Notes\n\n"
            "This maintenance release contains patches\n"
        )
        generator.write_changelog(
            str(tmp_path),
            new_section,
            "r2.3",
            "SimpleEdgeDiscovery",
            release_type="maintenance-release",
        )

        result = (tmp_path / "CHANGELOG.md").read_text()

        # New section lands before the first legacy section
        assert result.index("# r2.3") < result.index("# r2.2 - Fall25")

        # TOC contains an entry for every release-tag heading, with
        # link text and anchor both derived from the full heading text
        # so anchors match GitHub's rendering and link labels match the
        # underlying headings verbatim.
        assert "[r2.3](#r23)" in result
        assert "[r2.2 - Fall25 public release](#r22---fall25-public-release)" in result
        assert "[r2.1 - rc](#r21---rc)" in result
        assert "[r1.3](#r13)" in result

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

    def test_extract_entries_matches_heading_with_suffix(self):
        """Legacy headings may carry trailing descriptor text such as
        ``# r2.2 - Fall25 public release``. The full heading text is
        captured so both link label and anchor track what the heading
        actually says."""
        content = (
            "# r2.2 - Fall25 public release\n\n"
            "## Release Notes\n\n"
            "This public release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert len(entries) == 1
        assert entries[0]["heading"] == "r2.2 - Fall25 public release"
        assert entries[0]["is_public"] is True

    def test_extract_entries_mixed_plain_and_suffixed(self):
        """Mixed heading styles each get their full heading text in
        the entry's ``heading`` field."""
        content = (
            "# r2.2 - Fall25 public release\n\n"
            "This public release contains the definition\n\n"
            "# r2.1 - rc\n\n"
            "This pre-release contains the definition\n\n"
            "# r1.3\n\n"
            "This public release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert [e["heading"] for e in entries] == [
            "r2.2 - Fall25 public release",
            "r2.1 - rc",
            "r1.3",
        ]

    def test_extract_entries_matches_three_part_legacy_tag(self):
        """Pre-standardization repos have three-part tags like
        ``# r0.9.3 - rc``. The full heading text is captured verbatim."""
        content = (
            "# r0.9.3 - rc\n\n"
            "This pre-release contains the definition\n"
        )
        entries = ChangelogGenerator._extract_toc_entries(content)
        assert entries[0]["heading"] == "r0.9.3 - rc"

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

    def test_format_toc_suffixed_heading_uses_full_text(self):
        """Legacy suffixed headings render with both link text and anchor
        derived from the full heading text — matching GitHub's rendered
        anchor for that heading."""
        entries = [
            {"heading": "r2.2 - Fall25 public release", "is_public": True}
        ]
        result = ChangelogGenerator._format_toc(entries)
        assert (
            "- **[r2.2 - Fall25 public release](#r22---fall25-public-release)**"
            in result
        )

    def test_format_toc_three_part_tag_preserved(self):
        """Three-part legacy tags keep the full tag in both link text and
        anchor, so SED-style ``r0.9.3 - rc`` renders faithfully."""
        entries = [{"heading": "r0.9.3 - rc", "is_public": False}]
        result = ChangelogGenerator._format_toc(entries)
        assert "- [r0.9.3 - rc](#r093---rc)" in result

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


# --- Candidate Changes Splitting ---


class TestSplitCandidateChanges:
    """Tests for _split_candidate_changes()."""

    def test_extracts_full_changelog_url(self):
        raw = (
            "## What's Changed\n"
            "* Add feature by @user in https://github.com/org/repo/pull/1\n"
            "\n"
            "**Full Changelog**: https://github.com/org/repo/compare/r3.2...r4.1\n"
        )
        body, url = ChangelogGenerator._split_candidate_changes(raw)
        assert url == "https://github.com/org/repo/compare/r3.2...r4.1"
        assert "Add feature" in body
        assert "**Full Changelog**" not in body

    def test_no_full_changelog_line(self):
        raw = (
            "## What's Changed\n"
            "* Add feature by @user in https://github.com/org/repo/pull/1\n"
        )
        body, url = ChangelogGenerator._split_candidate_changes(raw)
        assert url is None
        assert "Add feature" in body

    def test_empty_string(self):
        body, url = ChangelogGenerator._split_candidate_changes("")
        assert body == ""
        assert url is None

    def test_only_full_changelog_line(self):
        raw = "**Full Changelog**: https://github.com/org/repo/compare/r1.1...r1.2\n"
        body, url = ChangelogGenerator._split_candidate_changes(raw)
        assert url == "https://github.com/org/repo/compare/r1.1...r1.2"
        assert body == ""

    def test_preserves_pr_list_formatting(self):
        raw = (
            "## What's Changed\n"
            "* First PR by @a in https://github.com/org/repo/pull/10\n"
            "* Second PR by @b in https://github.com/org/repo/pull/11\n"
            "* Third PR by @c in https://github.com/org/repo/pull/12\n"
            "\n"
            "**Full Changelog**: https://github.com/org/repo/compare/r3.2...r4.1\n"
        )
        body, url = ChangelogGenerator._split_candidate_changes(raw)
        assert "First PR" in body
        assert "Second PR" in body
        assert "Third PR" in body
        assert "## What's Changed" in body


# --- Candidate Changes Markers ---


class TestCandidateChangesMarkers:
    """Tests for marker format stability."""

    def test_markers_use_html_comment_format(self):
        assert CANDIDATE_CHANGES_START_MARKER.startswith("<!--")
        assert CANDIDATE_CHANGES_START_MARKER.endswith("-->")
        assert CANDIDATE_CHANGES_END_MARKER.startswith("<!--")
        assert CANDIDATE_CHANGES_END_MARKER.endswith("-->")

    def test_markers_contain_autogenerated_keyword(self):
        assert "AUTOGENERATED:CANDIDATE_CHANGES" in CANDIDATE_CHANGES_START_MARKER
        assert "AUTOGENERATED:CANDIDATE_CHANGES" in CANDIDATE_CHANGES_END_MARKER

    def test_begin_end_convention(self):
        assert "BEGIN:" in CANDIDATE_CHANGES_START_MARKER
        assert "END:" in CANDIDATE_CHANGES_END_MARKER
