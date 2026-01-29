"""
Unit tests for the bot responder.

These tests verify template rendering, marker handling, and error cases.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from release_automation.scripts.bot_responder import (
    BotResponder,
    BotResponderError,
    TemplateNotFoundError,
)


@pytest.fixture
def bot_responder():
    """Create a BotResponder with the actual template directory."""
    return BotResponder()


@pytest.fixture
def temp_template_dir(tmp_path):
    """Create a temporary template directory with test templates."""
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    # Create a simple test template
    (template_dir / "simple.md").write_text("Hello, {{name}}!")

    # Create a template with conditionals
    (template_dir / "conditional.md").write_text(
        "{{#show_section}}Visible{{/show_section}}{{^show_section}}Hidden{{/show_section}}"
    )

    # Create a template with lists
    (template_dir / "list.md").write_text(
        "Items:{{#items}}\n- {{.}}{{/items}}"
    )

    return template_dir


class TestBotResponderInit:
    """Tests for BotResponder initialization."""

    def test_default_template_dir(self, bot_responder):
        """Default template directory is set correctly."""
        assert bot_responder.template_dir.name == "bot_messages"
        assert "templates" in str(bot_responder.template_dir)

    def test_custom_template_dir(self, temp_template_dir):
        """Custom template directory can be specified."""
        responder = BotResponder(template_dir=temp_template_dir)
        assert responder.template_dir == temp_template_dir


class TestRender:
    """Tests for the render method."""

    def test_render_simple_template(self, temp_template_dir):
        """Renders simple variable substitution."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render("simple", {"name": "World"})
        assert result == "Hello, World!"

    def test_render_conditional_true(self, temp_template_dir):
        """Renders conditional section when value is truthy."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render("conditional", {"show_section": True})
        assert result == "Visible"

    def test_render_conditional_false(self, temp_template_dir):
        """Renders inverted section when value is falsy."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render("conditional", {"show_section": False})
        assert result == "Hidden"

    def test_render_list(self, temp_template_dir):
        """Renders list iteration."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render("list", {"items": ["one", "two", "three"]})
        assert "- one" in result
        assert "- two" in result
        assert "- three" in result

    def test_render_missing_template(self, temp_template_dir):
        """Raises TemplateNotFoundError for missing template."""
        responder = BotResponder(template_dir=temp_template_dir)
        with pytest.raises(TemplateNotFoundError) as exc_info:
            responder.render("nonexistent", {})
        assert "nonexistent" in str(exc_info.value)

    def test_render_real_template(self, bot_responder):
        """Renders an actual bot message template."""
        result = bot_responder.render("interim_processing", {
            "command": "/create-snapshot",
            "user": "testuser"
        })
        assert "/create-snapshot" in result
        assert "@testuser" in result
        assert "Processing" in result


class TestRenderWithMarker:
    """Tests for the render_with_marker method."""

    def test_adds_marker_to_output(self, temp_template_dir):
        """Marker is prepended to rendered content."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render_with_marker(
            "simple",
            {"name": "World"},
            "r4.1"
        )
        assert result.startswith("<!-- release-bot:r4.1 -->")
        assert "Hello, World!" in result

    def test_marker_format(self, temp_template_dir):
        """Marker uses correct format."""
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render_with_marker(
            "simple",
            {"name": "Test"},
            "r5.0-rc.1"
        )
        assert "<!-- release-bot:r5.0-rc.1 -->" in result


class TestListTemplates:
    """Tests for the list_templates method."""

    def test_lists_available_templates(self, temp_template_dir):
        """Returns list of template names."""
        responder = BotResponder(template_dir=temp_template_dir)
        templates = responder.list_templates()
        assert "simple" in templates
        assert "conditional" in templates
        assert "list" in templates

    def test_lists_real_templates(self, bot_responder):
        """Lists actual bot message templates."""
        templates = bot_responder.list_templates()
        expected = [
            "interim_processing",
            "snapshot_created",
            "snapshot_failed",
            "snapshot_discarded",
            "draft_created",
            "draft_revoked",
            "command_rejected",
            "issue_reopened",
        ]
        for name in expected:
            assert name in templates, f"Missing template: {name}"

    def test_empty_for_nonexistent_dir(self, tmp_path):
        """Returns empty list for nonexistent directory."""
        responder = BotResponder(template_dir=tmp_path / "nonexistent")
        assert responder.list_templates() == []


class TestExtractMarkerTag:
    """Tests for the extract_marker_tag static method."""

    def test_extracts_simple_tag(self):
        """Extracts tag from valid marker."""
        content = "<!-- release-bot:r4.1 -->\nSome content"
        tag = BotResponder.extract_marker_tag(content)
        assert tag == "r4.1"

    def test_extracts_complex_tag(self):
        """Extracts tag with dots and dashes."""
        content = "<!-- release-bot:r5.0-rc.2 -->\nContent"
        tag = BotResponder.extract_marker_tag(content)
        assert tag == "r5.0-rc.2"

    def test_returns_none_for_no_marker(self):
        """Returns None when no marker present."""
        content = "Just some regular content"
        tag = BotResponder.extract_marker_tag(content)
        assert tag is None

    def test_finds_marker_anywhere_in_content(self):
        """Finds marker even if not at start."""
        content = "Header\n<!-- release-bot:r4.1 -->\nContent"
        tag = BotResponder.extract_marker_tag(content)
        assert tag == "r4.1"


class TestRealTemplates:
    """Integration tests for real bot message templates."""

    def test_snapshot_created_template(self, bot_responder):
        """snapshot_created template renders correctly."""
        result = bot_responder.render("snapshot_created", {
            "release_tag": "r4.1",
            "meta_release": "Spring 2026",
            "snapshot_id": "r4.1-abc1234",
            "state": "snapshot-active",
            "snapshot_branch": "release-snapshot/r4.1-abc1234",
            "release_review_branch": "release-review/r4.1-abc1234",
            "release_pr_url": "https://github.com/org/repo/pull/123",
            "apis": [
                {"name": "quality-on-demand", "version": "1.0.0"},
                {"name": "qos-profiles", "version": "0.11.0-rc.1"},
            ],
        })
        assert "r4.1" in result
        assert "Spring 2026" in result
        assert "r4.1-abc1234" in result
        assert "quality-on-demand" in result
        assert "1.0.0" in result

    def test_command_rejected_template(self, bot_responder):
        """command_rejected template renders correctly."""
        result = bot_responder.render("command_rejected", {
            "command": "/create-snapshot",
            "user": "developer",
            "reason": "A snapshot already exists for this release.",
            "release_tag": "r4.1",
            "state": "snapshot-active",
            "valid_actions": ["/discard-snapshot", "/delete-draft"],
        })
        assert "/create-snapshot" in result
        assert "snapshot already exists" in result
        assert "/discard-snapshot" in result

    def test_snapshot_failed_template(self, bot_responder):
        """snapshot_failed template renders with errors."""
        result = bot_responder.render("snapshot_failed", {
            "release_tag": "r4.1",
            "state": "planned",
            "release_type": "initial",
            "errors": [
                "API version mismatch in quality-on-demand",
                "Missing required field: x-]]",
            ],
            "warnings": [
                "Deprecated field found",
            ],
        })
        assert "Failed" in result
        assert "API version mismatch" in result
        assert "Deprecated field" in result
