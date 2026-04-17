"""
Unit tests for issue_manager.py

Tests the IssueManager class which handles Release Issue content management.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from release_automation.scripts.issue_manager import IssueManager


class TestIssueManagerUpdateSection:
    """Tests for update_section method."""

    def test_update_state_section(self):
        """Test updating the STATE section."""
        manager = IssueManager()

        body = """Some content before

<!-- BEGIN:STATE -->
**State**: PLANNED
**Last Updated**: 2026-01-29T10:00:00Z
<!-- END:STATE -->

Some content after"""

        new_content = "**State**: SNAPSHOT_ACTIVE\n**Last Updated**: 2026-01-30T10:00:00Z"
        result = manager.update_section(body, "STATE", new_content)

        assert "**State**: SNAPSHOT_ACTIVE" in result
        assert "2026-01-30T10:00:00Z" in result
        assert "Some content before" in result
        assert "Some content after" in result
        # Old content should be gone
        assert "PLANNED" not in result

    def test_update_preserves_other_sections(self):
        """Test that updating one section preserves others."""
        manager = IssueManager()

        body = """<!-- BEGIN:STATE -->
old state
<!-- END:STATE -->

<!-- BEGIN:CONFIG -->
old config
<!-- END:CONFIG -->"""

        result = manager.update_section(body, "STATE", "new state")

        assert "new state" in result
        assert "old config" in result
        assert "old state" not in result

    def test_update_nonexistent_section_returns_original(self):
        """Test that updating a missing section returns the original body."""
        manager = IssueManager()

        body = "No sections here"
        result = manager.update_section(body, "STATE", "new content")

        assert result == body

    def test_update_section_with_multiline_content(self):
        """Test updating section with multiline content."""
        manager = IssueManager()

        body = """<!-- BEGIN:CONFIG -->
old
<!-- END:CONFIG -->"""

        new_content = """Line 1
Line 2
Line 3"""

        result = manager.update_section(body, "CONFIG", new_content)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


class TestIssueManagerGetSectionContent:
    """Tests for get_section_content method."""

    def test_get_existing_section(self):
        """Test getting content from an existing section."""
        manager = IssueManager()

        body = """<!-- BEGIN:STATE -->
**State**: PLANNED
**Last Updated**: 2026-01-29
<!-- END:STATE -->"""

        content = manager.get_section_content(body, "STATE")

        assert content is not None
        assert "**State**: PLANNED" in content

    def test_get_nonexistent_section_returns_none(self):
        """Test that getting a missing section returns None."""
        manager = IssueManager()

        body = "No sections"
        content = manager.get_section_content(body, "STATE")

        assert content is None


class TestIssueManagerGenerateTitle:
    """Tests for generate_title method."""

    def test_generate_rc_title(self):
        """Test generating title for RC release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.1",
            release_type="pre-release-rc",
            meta_release="Sync26"
        )

        assert title == "Release r4.1 (RC) — Sync26"

    def test_generate_alpha_title(self):
        """Test generating title for alpha release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.2",
            release_type="pre-release-alpha"
        )

        assert title == "Release r4.2 (alpha)"

    def test_generate_public_title(self):
        """Test generating title for public release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.0",
            release_type="public-release",
            meta_release="Spring26"
        )

        assert title == "Release r4.0 (public) — Spring26"

    def test_generate_title_without_meta_release(self):
        """Test generating title without meta-release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.1",
            release_type="pre-release-rc"
        )

        assert title == "Release r4.1 (RC)"
        assert "—" not in title

    def test_generate_title_maintenance(self):
        """Test generating title for maintenance release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.0.1",
            release_type="maintenance-release"
        )

        assert title == "Release r4.0.1 (maintenance)"


class TestIssueManagerShouldUpdateTitle:
    """Tests for should_update_title method."""

    def test_title_matches_no_update_needed(self):
        """Test when current title matches expected."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Sync26"
            }
        }

        current_title = "Release r4.1 (RC) — Sync26"

        assert manager.should_update_title(current_title, release_plan) is False

    def test_title_differs_update_needed(self):
        """Test when current title differs from expected."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Sync26"
            }
        }

        # Outdated title
        current_title = "Release r4.1 (alpha)"

        assert manager.should_update_title(current_title, release_plan) is True


class TestIssueManagerGenerateStateSection:
    """Tests for generate_state_section method."""

    @patch('release_automation.scripts.issue_manager.datetime')
    def test_generate_state_section(self, mock_datetime):
        """Test generating state section content."""
        mock_datetime.now.return_value = datetime(2026, 1, 30, 10, 0, 0, tzinfo=timezone.utc)

        manager = IssueManager()

        content = manager.generate_state_section("snapshot_active")

        assert "**State:** `snapshot-active`" in content
        assert "**Last Updated:** 2026-01-30T10:00:00Z" in content


class TestIssueManagerGenerateConfigSection:
    """Tests for generate_config_section method."""

    def test_generate_config_with_apis(self):
        """Test generating config section with APIs, status column, and release type."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Sync26"
            },
            "apis": [
                {"api_name": "location-verification", "target_api_version": "3.2.0", "target_api_status": "rc"},
                {"api_name": "location-retrieval", "target_api_version": "0.5.0", "target_api_status": "rc"}
            ]
        }

        api_versions = {
            "location-verification": "3.2.0-rc.1",
            "location-retrieval": "0.5.0-rc.1"
        }

        content = manager.generate_config_section(release_plan, api_versions)

        assert "**Release type:** rc" in content
        assert "| API | Status | Target | Calculated |" in content
        assert "| location-verification | rc | 3.2.0 | `3.2.0-rc.1` |" in content
        assert "| location-retrieval | rc | 0.5.0 | `0.5.0-rc.1` |" in content

    def test_generate_config_no_readiness_details(self):
        """Test that config section does not include readiness details (moved to static body)."""
        manager = IssueManager()

        release_plan = {
            "apis": [
                {"api_name": "test-api", "target_api_version": "1.0.0", "target_api_status": "public"}
            ]
        }

        content = manager.generate_config_section(release_plan, {"test-api": "1.0.0"})

        assert "<details>" not in content
        assert "Required assets per API status" not in content

    def test_generate_config_without_status(self):
        """Test that missing target_api_status shows dash."""
        manager = IssueManager()

        release_plan = {
            "apis": [
                {"api_name": "test-api", "target_api_version": "1.0.0"}
            ]
        }

        content = manager.generate_config_section(release_plan, {"test-api": "1.0.0"})

        assert "| test-api | — | 1.0.0 |" in content

    def test_generate_config_without_apis(self):
        """Test generating config section without APIs shows placeholder."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-alpha"
            },
            "apis": []
        }

        content = manager.generate_config_section(release_plan, {})

        assert "_No APIs or dependencies configured_" in content


class TestIssueManagerGenerateIssueBodyTemplate:
    """Tests for generate_issue_body_template method."""

    def test_generate_complete_template(self):
        """Test generating a complete issue body template."""
        manager = IssueManager()

        body = manager.generate_issue_body_template(
            release_tag="r4.1",
            release_type="pre-release-rc",
            meta_release="Sync26"
        )

        # No redundant heading — title carries release info
        assert "## Release:" not in body

        # Check sections exist with reduced heading levels
        assert "<!-- BEGIN:STATE -->" in body
        assert "<!-- END:STATE -->" in body
        assert "<!-- BEGIN:CONFIG -->" in body
        assert "<!-- END:CONFIG -->" in body
        assert "<!-- BEGIN:ACTIONS -->" in body
        assert "<!-- END:ACTIONS -->" in body

        assert "**State:** `planned`" in body

        assert "`/create-snapshot`" in body

        # Check preparation section
        assert "### Preparing the release content" in body
        assert "release-plan.yaml" in body
        assert "Commonalities and ICM dependency versions" in body
        assert "CI checks are green" in body
        assert "All intended implementation PRs are merged" in body
        assert "SemVer is correct" in body

        # Check readiness details block in static body
        assert "<details>" in body
        assert "Required release assets per API status" in body
        assert "full documentation" in body  # convenience copy label
        assert "| 1 | Release Plan | M | M | M | M |" in body
        assert "api-readiness-checklist.md" in body
        assert "</details>" in body

    def test_generate_template_without_meta_release(self):
        """Test generating template without meta-release."""
        manager = IssueManager()

        body = manager.generate_issue_body_template(
            release_tag="r4.1",
            release_type="pre-release-alpha"
        )

        # No redundant heading
        assert "## Release:" not in body
        # Optional scope placeholder sits above the automation-managed markers
        assert "_Optional: use this space to describe" in body
        # Remaining section headings should stay at ###
        assert "### Preparing the release content" in body
        assert "### Release Status" in body


class TestIssueManagerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_update_section_with_special_chars_in_content(self):
        """Test updating section with regex special characters."""
        manager = IssueManager()

        body = """<!-- BEGIN:STATE -->
old
<!-- END:STATE -->"""

        new_content = "Contains $special (chars) [and] {braces} | pipes"
        result = manager.update_section(body, "STATE", new_content)

        assert new_content in result

    def test_get_section_with_nested_comments(self):
        """Test getting section that might have nested HTML comments."""
        manager = IssueManager()

        # This shouldn't happen in practice but let's be robust
        body = """<!-- BEGIN:STATE -->
Content with <!-- inner comment -->
<!-- END:STATE -->"""

        content = manager.get_section_content(body, "STATE")
        assert content is not None
        assert "inner comment" in content


class TestIssueManagerPublishedSections:
    """Tests for published state section generators."""

    def test_generate_published_state_section_basic(self):
        """Test generating published state section."""
        manager = IssueManager()

        content = manager.generate_published_state_section(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="source/r4.1"
        )

        assert "**State:** `published`" in content
        assert "**Release:** [r4.1](https://github.com/test/releases/tag/r4.1)" in content
        assert "**Reference tag:** `source/r4.1`" in content
        # No sync PR line when not provided
        assert "Sync PR" not in content

    def test_generate_published_state_section_with_sync_pr(self):
        """Test published state with sync PR URL."""
        manager = IssueManager()

        content = manager.generate_published_state_section(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="source/r4.1",
            sync_pr_url="https://github.com/test/pull/123"
        )

        assert "**Sync PR:** https://github.com/test/pull/123" in content

    def test_generate_published_state_section_has_timestamp(self):
        """Test that published state includes timestamp."""
        manager = IssueManager()

        content = manager.generate_published_state_section(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="source/r4.1"
        )

        # Should contain a timestamp in ISO format
        assert "**Last Updated:**" in content
        assert "202" in content  # Year starts with 202x

    def test_generate_published_actions_section(self):
        """Test generating published actions section."""
        manager = IssueManager()

        content = manager.generate_published_actions_section()

        assert "No further actions available" in content
        assert "release is published" in content
