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

    def test_render_collapses_excess_blank_lines(self, temp_template_dir):
        """Collapses 3+ consecutive newlines to at most one blank line."""
        (temp_template_dir / "blanks.md").write_text(
            "Header\n{{#a}}line a\n{{/a}}\n{{#b}}line b\n{{/b}}\n{{#c}}line c\n{{/c}}\nFooter"
        )
        responder = BotResponder(template_dir=temp_template_dir)
        # Only 'a' is true → 'b' and 'c' sections produce empty lines
        result = responder.render("blanks", {"a": True, "b": False, "c": False})
        assert "Header\nline a" in result
        assert "\n\n\n" not in result
        assert "Footer" in result

    def test_render_strips_leading_trailing_whitespace(self, temp_template_dir):
        """Strips leading/trailing whitespace from rendered output."""
        (temp_template_dir / "padded.md").write_text("\n\nContent\n\n")
        responder = BotResponder(template_dir=temp_template_dir)
        result = responder.render("padded", {})
        assert result == "Content"

    def test_render_missing_template(self, temp_template_dir):
        """Raises TemplateNotFoundError for missing template."""
        responder = BotResponder(template_dir=temp_template_dir)
        with pytest.raises(TemplateNotFoundError) as exc_info:
            responder.render("nonexistent", {})
        assert "nonexistent" in str(exc_info.value)

    def test_render_real_template(self, bot_responder):
        """Renders an actual bot message template."""
        from release_automation.scripts.context_builder import build_context
        # Use build_context for proper defaults
        context = build_context(
            command="/create-snapshot",
            user="testuser",
            state="planned"
        )
        result = bot_responder.render("interim_processing", context)
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
            "publish_confirmation",
            "release_published",
            "publish_failed",
            "internal_error",
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
        from release_automation.scripts.context_builder import build_context
        context = build_context(
            release_tag="r4.1",
            meta_release="Spring 2026",
            snapshot_id="r4.1-abc1234",
            state="snapshot-active",
            snapshot_branch="release-snapshot/r4.1-abc1234",
            release_review_branch="release-review/r4.1-abc1234",
            release_pr_url="https://github.com/org/repo/pull/123",
            apis=[
                {"api_name": "quality-on-demand", "api_version": "1.0.0"},
                {"api_name": "qos-profiles", "api_version": "0.11.0-rc.1"},
            ],
        )
        result = bot_responder.render("snapshot_created", context)
        # Template shows snapshot_id and apis, not meta_release
        assert "r4.1-abc1234" in result
        assert "quality-on-demand" in result
        assert "1.0.0" in result
        assert "pull/123" in result

    def test_command_rejected_template(self, bot_responder):
        """command_rejected template renders correctly."""
        from release_automation.scripts.context_builder import build_context
        # Use build_context for state flags
        context = build_context(
            command="/create-snapshot",
            user="developer",
            error_message="A snapshot already exists for this release.",
            release_tag="r4.1",
            state="snapshot-active",
            workflow_run_url="https://github.com/org/repo/actions/runs/123",
        )
        result = bot_responder.render("command_rejected", context)
        assert "/create-snapshot" in result
        assert "snapshot already exists" in result
        # User is not shown in compact format
        assert "snapshot-active" in result

    def test_snapshot_failed_template(self, bot_responder):
        """snapshot_failed template renders with error message."""
        from release_automation.scripts.context_builder import build_context
        context = build_context(
            release_tag="r4.1",
            state="planned",
            error_message="API version mismatch in quality-on-demand",
            workflow_run_url="https://github.com/org/repo/actions/runs/123",
        )
        result = bot_responder.render("snapshot_failed", context)
        # Header uses lowercase "failed"
        assert "failed" in result
        assert "API version mismatch" in result

    def test_snapshot_failed_template_with_error_message(self, bot_responder):
        """snapshot_failed template renders with single error_message."""
        from release_automation.scripts.context_builder import build_context
        context = build_context(
            release_tag="r4.1",
            state="planned",
            error_message="Unexpected error: 'str' object has no attribute 'get'",
            workflow_run_url="https://github.com/org/repo/actions/runs/456",
        )
        result = bot_responder.render("snapshot_failed", context)
        # Header uses lowercase "failed"
        assert "failed" in result
        assert "Unexpected error" in result
        assert "'str' object has no attribute 'get'" in result


class TestContextIntegration:
    """Tests simulating the post-bot-comment action's context flow.

    These tests verify that partial context (as each workflow job passes)
    produces complete, crash-free template rendering via build_context().
    """

    def test_config_error_partial_context(self, bot_responder):
        """handle-config-error job's partial context renders config_error."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "error_type": "missing_file",
            "error_message": "release-plan.yaml not found",
            "command": "/create-snapshot",
            "user": "developer",
            "workflow_run_url": "https://github.com/org/repo/actions/runs/1",
        }
        context = build_context(**raw)
        result = bot_responder.render("config_error", context)
        assert "missing_file" in result or "release-plan.yaml" in result

    def test_config_error_derives_boolean_flags(self, bot_responder):
        """Boolean flags are derived from error_type without explicit passing."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "error_type": "malformed_yaml",
            "error_message": "YAML syntax error on line 5",
            "command": "/create-snapshot",
            "user": "developer",
            "workflow_run_url": "https://github.com/org/repo/actions/runs/1",
        }
        context = build_context(**raw)
        assert context["is_malformed_yaml"] is True
        assert context["is_missing_file"] is False
        assert context["is_missing_field"] is False

    def test_post_result_renders_snapshot_created(self, bot_responder):
        """post-result job's context renders snapshot_created template."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "command": "create-snapshot",
            "user": "developer",
            "release_tag": "r4.1",
            "state": "snapshot-active",
            "snapshot_id": "r4.1-abc1234",
            "snapshot_branch": "release-snapshot/r4.1-abc1234",
            "release_review_branch": "release-review/r4.1-abc1234",
            "release_pr_url": "https://github.com/org/repo/pull/42",
            "release_pr_number": "42",
            "workflow_run_url": "https://github.com/org/repo/actions/runs/1",
            "apis": [{"api_name": "QoD", "api_version": "1.0.0-rc.1"}],
        }
        context = build_context(**raw)
        result = bot_responder.render("snapshot_created", context)
        assert "r4.1-abc1234" in result
        assert "QoD" in result
        assert "1.0.0-rc.1" in result
        assert "pull/42" in result

    def test_issue_reopened_partial_context(self, bot_responder):
        """handle-issue-event's minimal context renders issue_reopened."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "release_tag": "r4.1",
            "state": "snapshot-active",
            "snapshot_id": "r4.1-abc1234",
            "reason": "Cannot close Release Issue while release is in progress",
        }
        context = build_context(**raw)
        assert context["state_snapshot_active"] is True
        assert context["state_draft_ready"] is False
        result = bot_responder.render("issue_reopened", context)
        # Template shows state, not release_tag
        assert "snapshot-active" in result
        assert "reopened" in result

    def test_apis_json_string_to_list_conversion(self):
        """apis_json string is correctly converted to apis list."""
        import json
        from release_automation.scripts.context_builder import build_context

        raw = {
            "release_tag": "r4.1",
            "apis_json": json.dumps([
                {"api_name": "QoD", "api_version": "1.0.0"},
                {"api_name": "qos-profiles", "api_version": "0.11.0-rc.1"},
            ]),
        }
        # Simulate the conversion done in post-bot-comment action
        if "apis_json" in raw and isinstance(raw["apis_json"], str):
            raw["apis"] = json.loads(raw["apis_json"])
            del raw["apis_json"]
        context = build_context(**raw)
        assert len(context["apis"]) == 2
        assert context["apis"][0]["api_name"] == "QoD"
        assert context["apis"][1]["api_version"] == "0.11.0-rc.1"

    def test_interim_processing_minimal_context(self, bot_responder):
        """post-interim's minimal context renders interim_processing."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "command": "/create-snapshot",
            "user": "developer",
            "workflow_run_url": "https://github.com/org/repo/actions/runs/1",
        }
        context = build_context(**raw)
        result = bot_responder.render("interim_processing", context)
        assert "/create-snapshot" in result
        assert "developer" in result

    def test_rejection_partial_context(self, bot_responder):
        """post-rejection job's context renders command_rejected."""
        from release_automation.scripts.context_builder import build_context

        raw = {
            "command": "/create-snapshot",
            "user": "developer",
            "state": "snapshot-active",
            "release_tag": "r4.1",
            "error_message": "Command /create-snapshot not allowed in state 'snapshot-active'",
            "workflow_run_url": "https://github.com/org/repo/actions/runs/1",
        }
        context = build_context(**raw)
        result = bot_responder.render("command_rejected", context)
        assert "not allowed" in result
        # Template shows state and command, not user
        assert "snapshot-active" in result
        assert "create-snapshot" in result


class TestPublicationTemplates:
    """Tests for publication-related bot message templates."""

    def test_publish_confirmation_template(self, bot_responder):
        """publish_confirmation template renders with draft details."""
        from release_automation.scripts.context_builder import build_context

        context = build_context(
            release_tag="r4.1",
            state="draft-ready",
            draft_release_url="https://github.com/org/repo/releases/tag/untagged-abc123",
            src_commit_sha_short="abc1234",
            apis=[
                {"api_name": "quality-on-demand", "api_version": "1.0.0"},
                {"api_name": "qos-profiles", "api_version": "0.11.0-rc.1"},
            ],
            commonalities_release="0.5.0",
            identity_consent_management_release="0.3.0",
        )
        result = bot_responder.render("publish_confirmation", context)
        assert "Confirmation required" in result
        assert "draft-ready" in result
        assert "r4.1" in result
        assert "abc1234" in result
        assert "/publish-release --confirm r4.1" in result
        assert "quality-on-demand" in result

    def test_release_published_template(self, bot_responder):
        """release_published template renders with release details."""
        from release_automation.scripts.context_builder import build_context

        context = build_context(
            release_tag="r4.1",
            state="published",
            release_type="public-release",
            release_url="https://github.com/org/repo/releases/tag/r4.1",
            sync_pr_number="99",
            sync_pr_url="https://github.com/org/repo/pull/99",
            apis=[
                {"api_name": "quality-on-demand", "api_version": "1.0.0"},
            ],
            commonalities_release="0.5.0",
        )
        result = bot_responder.render("release_published", context)
        assert "Release published" in result
        assert "published" in result
        assert "r4.1" in result
        assert "pull/99" in result
        assert "codeowner merge" in result
        assert "closed automatically" in result

    def test_release_published_template_without_sync_pr(self, bot_responder):
        """release_published template renders without sync PR."""
        from release_automation.scripts.context_builder import build_context

        context = build_context(
            release_tag="r4.1",
            state="published",
            release_type="public-release",
            release_url="https://github.com/org/repo/releases/tag/r4.1",
            apis=[],
        )
        result = bot_responder.render("release_published", context)
        assert "Release published" in result
        # sync_pr_number is empty but always rendered in new template
        assert "codeowner merge" in result

    def test_publish_failed_template(self, bot_responder):
        """publish_failed template renders with error message."""
        from release_automation.scripts.context_builder import build_context

        context = build_context(
            release_tag="r4.1",
            state="draft-ready",
            error_message="Failed to publish release: GitHub API returned 500",
            workflow_run_url="https://github.com/org/repo/actions/runs/12345",
        )
        result = bot_responder.render("publish_failed", context)
        assert "Publication failed" in result
        assert "draft-ready" in result
        assert "GitHub API returned 500" in result
        assert "/publish-release --confirm r4.1" in result
        assert "workflow logs" in result
        assert "/delete-draft" in result

    def test_internal_error_template(self, bot_responder):
        """internal_error template renders with debug info."""
        from release_automation.scripts.context_builder import build_context

        context = build_context(
            command="publish-release",
            state="draft-ready",
            workflow_run_url="https://github.com/org/repo/actions/runs/12345",
        )
        result = bot_responder.render("internal_error", context)
        assert "Internal error" in result
        assert "publish-release" in result
        assert "workflow bug" in result
        assert "View logs" not in result  # New template uses "View workflow logs"
        assert "workflow logs" in result
        assert "actions/runs/12345" in result
