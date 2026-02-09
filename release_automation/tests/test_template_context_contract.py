"""
Contract tests: verify all templates render with the unified BotContext.

These tests ensure that every bot message template can be rendered
without crashing when given a BotContext-produced dict. This catches
missing-key errors that would otherwise only surface at runtime in
GitHub Actions (pystache strict mode raises on missing keys).
"""

import pytest

from release_automation.scripts.bot_responder import BotResponder
from release_automation.scripts.context_builder import build_context


KNOWN_TEMPLATES = [
    "command_rejected",
    "config_drift_warning",
    "config_error",
    "draft_created",
    "draft_revoked",
    "interim_processing",
    "issue_created",
    "issue_reopened",
    "publish_confirmation",
    "snapshot_created",
    "snapshot_discarded",
    "snapshot_failed",
]


@pytest.fixture
def responder():
    """BotResponder using the real template directory."""
    return BotResponder()


class TestTemplateContextContract:
    """Contract tests for template/context alignment."""

    def test_all_templates_render_with_default_context(self, responder):
        """All templates render with empty defaults (no crash).

        This is the core contract test: build_context() with no arguments
        produces a dict with all keys that pystache strict mode requires.
        Every template must render without raising a MissingTags error.
        """
        context = build_context()
        templates = responder.list_templates()

        for template_name in templates:
            result = responder.render(template_name, context)
            assert isinstance(result, str), (
                f"Template '{template_name}' did not return a string"
            )

    def test_all_templates_render_with_full_context(self, responder):
        """All templates render with all fields populated."""
        context = build_context(
            # Trigger fields
            command="/create-snapshot",
            command_args="",
            user="testuser",
            trigger_pr_number="42",
            # State fields
            release_tag="r4.1",
            state="snapshot-active",
            release_type="initial",
            meta_release="Fall25",
            # Snapshot fields
            snapshot_id="r4.1-abc1234",
            snapshot_branch="release-snapshot/r4.1-abc1234",
            release_review_branch="release-review/r4.1-abc1234",
            src_commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            release_pr_number="123",
            release_pr_url="https://github.com/org/repo/pull/123",
            # API fields
            apis=[
                {
                    "api_name": "QualityOnDemand",
                    "target_api_version": "1.0.0",
                    "target_api_status": "rc",
                    "api_version": "1.0.0-rc.1",
                    "api_title": "Quality on Demand",
                },
            ],
            # Dependency fields
            commonalities_release="r0.5",
            identity_consent_management_release="r0.3",
            # Error fields
            error_message="Test error message",
            error_type="missing_file",
            # Display fields
            workflow_run_url="https://github.com/org/repo/actions/runs/123",
            draft_release_url="https://github.com/org/repo/releases/tag/r4.1",
            reason="Testing discard",
        )
        templates = responder.list_templates()

        for template_name in templates:
            result = responder.render(template_name, context)
            assert isinstance(result, str), (
                f"Template '{template_name}' did not return a string"
            )
            assert len(result) > 0, (
                f"Template '{template_name}' rendered to empty string"
            )

    def test_all_known_templates_exist(self, responder):
        """All 12 known templates are present in the template directory."""
        templates = responder.list_templates()

        for name in KNOWN_TEMPLATES:
            assert name in templates, (
                f"Expected template '{name}' not found in template directory"
            )

    def test_list_templates_returns_expected_count(self, responder):
        """list_templates() returns at least 12 templates."""
        templates = responder.list_templates()
        assert len(templates) >= 12, (
            f"Expected at least 12 templates, got {len(templates)}: {templates}"
        )

    def test_build_context_no_none_values(self):
        """build_context() output has no None values at any level."""
        context = build_context()
        for key, value in context.items():
            assert value is not None, (
                f"Key '{key}' has None value in default context"
            )

    def test_snapshot_created_renders_with_apis(self, responder):
        """snapshot_created template renders correctly with apis list."""
        context = build_context(
            release_tag="r4.1",
            meta_release="Fall25",
            snapshot_id="r4.1-abc1234",
            state="snapshot-active",
            snapshot_branch="release-snapshot/r4.1-abc1234",
            release_review_branch="release-review/r4.1-abc1234",
            release_pr_url="https://github.com/org/repo/pull/123",
            apis=[
                {
                    "api_name": "QualityOnDemand",
                    "api_version": "1.0.0-rc.1",
                    "api_title": "Quality on Demand",
                    "target_api_version": "1.0.0",
                    "target_api_status": "rc",
                },
            ],
        )
        result = responder.render("snapshot_created", context)
        assert "QualityOnDemand" in result
        assert "1.0.0-rc.1" in result

    def test_config_error_renders_each_error_type(self, responder):
        """config_error template renders for each error type without crash."""
        for error_type in ["missing_file", "malformed_yaml", "missing_field"]:
            context = build_context(
                command="/create-snapshot",
                user="testuser",
                error_type=error_type,
                error_message=f"Test {error_type} error",
                workflow_run_url="https://github.com/org/repo/actions/runs/1",
            )
            result = responder.render("config_error", context)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_issue_reopened_renders_each_state(self, responder):
        """issue_reopened template renders for each relevant state."""
        for state in ["snapshot-active", "draft-ready"]:
            context = build_context(
                release_tag="r4.1",
                state=state,
            )
            result = responder.render("issue_reopened", context)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_config_drift_warning_renders_for_snapshot_active(self, responder):
        """config_drift_warning renders for snapshot-active state."""
        context = build_context(
            release_tag="r4.1",
            state="snapshot-active",
            trigger_type="release_plan_change",
            trigger_pr_number="55",
            trigger_pr_url="https://github.com/org/repo/pull/55",
            release_pr_url="https://github.com/org/repo/pull/123",
            release_plan_url="https://github.com/org/repo/blob/main/release-plan.yaml",
            apis=[
                {
                    "api_name": "QualityOnDemand",
                    "api_version": "1.0.0-rc.1",
                },
            ],
        )
        result = responder.render("config_drift_warning", context)
        assert "Configuration drift" in result
        assert "#55" in result
        assert "/discard-snapshot" in result
        assert "Snapshot Configuration" in result

    def test_config_drift_warning_renders_for_draft_ready(self, responder):
        """config_drift_warning renders for draft-ready state."""
        context = build_context(
            release_tag="r4.1",
            state="draft-ready",
            trigger_type="release_plan_change",
            trigger_pr_number="55",
            trigger_pr_url="https://github.com/org/repo/pull/55",
            release_plan_url="https://github.com/org/repo/blob/main/release-plan.yaml",
            apis=[
                {
                    "api_name": "QualityOnDemand",
                    "api_version": "1.0.0-rc.1",
                },
            ],
        )
        result = responder.render("config_drift_warning", context)
        assert "Configuration drift" in result
        assert "/delete-draft" in result
        assert "/publish-release" in result
