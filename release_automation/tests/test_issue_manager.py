"""
Unit tests for issue_manager.py

Tests the IssueManager class which handles Release Issue content management.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from release_automation.scripts.issue_manager import (
    IssueManager,
    SnapshotHistoryEntry,
)


class TestSnapshotHistoryEntry:
    """Tests for SnapshotHistoryEntry dataclass."""

    def test_create_current_entry(self):
        """Test creating an entry for a current snapshot."""
        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-abc1234",
            status="Current",
            created_at="2026-01-30 10:00",
            release_review_branch="release-review/r4.1-abc1234"
        )

        assert entry.snapshot_id == "r4.1-abc1234"
        assert entry.status == "Current"
        assert entry.discarded_at is None
        assert entry.reason is None

    def test_create_discarded_entry(self):
        """Test creating an entry for a discarded snapshot."""
        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-abc1234",
            status="Discarded",
            created_at="2026-01-30 10:00",
            discarded_at="2026-01-30 12:00",
            reason="API validation failed",
            release_review_branch="release-review/r4.1-abc1234"
        )

        assert entry.status == "Discarded"
        assert entry.discarded_at == "2026-01-30 12:00"
        assert entry.reason == "API validation failed"


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


class TestIssueManagerAppendToHistory:
    """Tests for append_to_history method."""

    def test_append_first_entry(self):
        """Test appending the first entry to an empty history table."""
        manager = IssueManager()

        body = """<!-- BEGIN:HISTORY -->
| Snapshot | Status | Created | Discarded | Reason | Review Branch |
|----------|--------|---------|-----------|--------|---------------|
<!-- END:HISTORY -->"""

        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-abc1234",
            status="Current",
            created_at="2026-01-30 10:00",
            release_review_branch="release-review/r4.1-abc1234"
        )

        result = manager.append_to_history(body, entry)

        assert "`r4.1-abc1234`" in result
        assert "**Current**" in result
        assert "2026-01-30 10:00" in result
        assert "`release-review/r4.1-abc1234`" in result

    def test_append_second_entry(self):
        """Test appending a second entry (newest at top)."""
        manager = IssueManager()

        body = """<!-- BEGIN:HISTORY -->
| Snapshot | Status | Created | Discarded | Reason | Review Branch |
|----------|--------|---------|-----------|--------|---------------|
| `r4.1-abc1234` | Discarded | 2026-01-29 10:00 | 2026-01-29 12:00 | Failed | `release-review/r4.1-abc1234` |
<!-- END:HISTORY -->"""

        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-def5678",
            status="Current",
            created_at="2026-01-30 10:00",
            release_review_branch="release-review/r4.1-def5678"
        )

        result = manager.append_to_history(body, entry)

        # New entry should be present
        assert "`r4.1-def5678`" in result
        # Old entry should still be present
        assert "`r4.1-abc1234`" in result
        # New entry should appear before old entry
        new_pos = result.find("r4.1-def5678")
        old_pos = result.find("r4.1-abc1234")
        assert new_pos < old_pos

    def test_append_with_defaults_for_optional_fields(self):
        """Test that optional fields default to em-dash."""
        manager = IssueManager()

        body = """<!-- BEGIN:HISTORY -->
| Snapshot | Status | Created | Discarded | Reason | Review Branch |
|----------|--------|---------|-----------|--------|---------------|
<!-- END:HISTORY -->"""

        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-abc1234",
            status="Current",
            created_at="2026-01-30 10:00",
            release_review_branch="release-review/r4.1-abc1234"
            # discarded_at and reason are None
        )

        result = manager.append_to_history(body, entry)

        # Should have em-dashes for discarded and reason
        assert "| — |" in result


class TestIssueManagerMarkSnapshotDiscarded:
    """Tests for mark_snapshot_discarded method."""

    @patch('release_automation.scripts.issue_manager.datetime')
    def test_mark_discarded(self, mock_datetime):
        """Test marking a snapshot as discarded."""
        mock_datetime.now.return_value = datetime(2026, 1, 30, 12, 0, tzinfo=timezone.utc)

        manager = IssueManager()

        body = """| `r4.1-abc1234` | **Current** | 2026-01-30 10:00 | — | — | `release-review/r4.1-abc1234` |"""

        result = manager.mark_snapshot_discarded(
            body,
            snapshot_id="r4.1-abc1234",
            reason="Validation failed"
        )

        assert "Discarded" in result
        assert "2026-01-30 12:00" in result
        assert "Validation failed" in result
        assert "**Current**" not in result


class TestIssueManagerGenerateTitle:
    """Tests for generate_title method."""

    def test_generate_rc_title(self):
        """Test generating title for RC release."""
        manager = IssueManager()

        title = manager.generate_title(
            release_tag="r4.1",
            release_type="pre-release-rc",
            meta_release="Fall26"
        )

        assert title == "Release r4.1 (RC) — Fall26"

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
                "meta_release": "Fall26"
            }
        }

        current_title = "Release r4.1 (RC) — Fall26"

        assert manager.should_update_title(current_title, release_plan) is False

    def test_title_differs_update_needed(self):
        """Test when current title differs from expected."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Fall26"
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
        """Test generating config section with APIs."""
        manager = IssueManager()

        release_plan = {
            "repository": {
                "target_release_tag": "r4.1",
                "target_release_type": "pre-release-rc",
                "meta_release": "Fall26"
            },
            "apis": [
                {"api_name": "location-verification", "target_api_version": "3.2.0"},
                {"api_name": "location-retrieval", "target_api_version": "0.5.0"}
            ]
        }

        api_versions = {
            "location-verification": "3.2.0-rc.1",
            "location-retrieval": "0.5.0-rc.1"
        }

        content = manager.generate_config_section(release_plan, api_versions)

        assert "| API | Target | Calculated |" in content
        assert "| location-verification | 3.2.0 | `3.2.0-rc.1` |" in content
        assert "| location-retrieval | 0.5.0 | `0.5.0-rc.1` |" in content

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
            meta_release="Fall26"
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

    def test_generate_template_without_meta_release(self):
        """Test generating template without meta-release."""
        manager = IssueManager()

        body = manager.generate_issue_body_template(
            release_tag="r4.1",
            release_type="pre-release-alpha"
        )

        # No redundant heading
        assert "## Release:" not in body
        # Heading levels should be ###
        assert "### Release Highlights" in body
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

    def test_history_without_table_structure(self):
        """Test appending to history when table structure is missing."""
        manager = IssueManager()

        body = """<!-- BEGIN:HISTORY -->
Some malformed content without table
<!-- END:HISTORY -->"""

        entry = SnapshotHistoryEntry(
            snapshot_id="r4.1-abc1234",
            status="Current",
            created_at="2026-01-30 10:00",
            release_review_branch="release-review/r4.1-abc1234"
        )

        # Should not crash, just append
        result = manager.append_to_history(body, entry)
        assert "`r4.1-abc1234`" in result

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
            reference_tag="src/r4.1"
        )

        assert "**State:** `published`" in content
        assert "**Release:** [r4.1](https://github.com/test/releases/tag/r4.1)" in content
        assert "**Reference tag:** `src/r4.1`" in content
        # No sync PR line when not provided
        assert "Sync PR" not in content

    def test_generate_published_state_section_with_sync_pr(self):
        """Test published state with sync PR URL."""
        manager = IssueManager()

        content = manager.generate_published_state_section(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1",
            sync_pr_url="https://github.com/test/pull/123"
        )

        assert "**Sync PR:** https://github.com/test/pull/123" in content

    def test_generate_published_state_section_has_timestamp(self):
        """Test that published state includes timestamp."""
        manager = IssueManager()

        content = manager.generate_published_state_section(
            release_tag="r4.1",
            release_url="https://github.com/test/releases/tag/r4.1",
            reference_tag="src/r4.1"
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
