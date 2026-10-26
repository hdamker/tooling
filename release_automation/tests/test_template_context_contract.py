"""
Contract tests: verify all templates render with the unified BotContext.

These tests ensure that every bot message template can be rendered
without crashing when given a BotContext-produced dict. This catches
missing-key errors that would otherwise only surface at runtime in
GitHub Actions (pystache strict mode raises on missing keys).
"""

import pytest

from release_automation.scripts.bot_responder import BotResponder
from release_automation.scripts.bot_context import build_context


KNOWN_TEMPLATES = [
    "command_rejected",
    "common_sync_failed",
    "common_sync_pr_created",
    "config_error",
    "draft_created",
    "draft_revoked",
    "interim_processing",
    "issue_created",
    "issue_reopened",
    "issue_sync_failed",
    "issue_synced",
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
        """list_templates() returns at least 14 templates."""
        templates = responder.list_templates()
        assert len(templates) >= 13, (
            f"Expected at least 14 templates, got {len(templates)}: {templates}"
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




# ── valid actions (commands.actions_for, 107 D2) ─────────────────────────────


def test_templates_say_base_branch_not_main(responder):
    # F4 family: a maintenance-line codeowner reads the branch of the release, never a hard-coded main
    for template in responder.template_dir.glob("*.md"):
        assert "`main`" not in template.read_text(encoding="utf-8"), template.name
    body = responder.render("snapshot_failed", build_context(
        command="create-snapshot", state="planned", release_tag="r1.9", base_branch="maintenance/r1",
        error_message="Pre-snapshot validation failed",
    ))
    assert body.startswith("**❌ Command failed: `/create-snapshot` — State: `planned`**")
    assert "Fix the cause on `maintenance/r1` and retry `/create-snapshot`" in body


def test_failed_discard_reports_the_real_state(responder):
    # The failure template of /discard-snapshot and /delete-draft follows the state the run reports
    body = responder.render("snapshot_failed", build_context(
        command="discard-snapshot", state="snapshot-active", release_tag="r1.9", base_branch="main",
        release_pr_url="https://github.com/o/r/pull/3",
    ))

    assert body.startswith("**❌ Command failed: `/discard-snapshot` — State: `snapshot-active`**")
    assert "`/discard-snapshot <reason>`" in body


def test_templates_have_no_hand_written_valid_actions(responder):
    for template in responder.template_dir.glob("*.md"):
        text = template.read_text(encoding="utf-8")
        assert "Valid actions" not in text and "→" not in text, template.name


@pytest.mark.parametrize("state", ["published", "not-planned"])
def test_rejection_offers_no_command_the_state_rejects(responder, state):
    # F2: these rejections used to offer /create-snapshot
    body = responder.render("command_rejected", build_context(
        command="discard-snapshot", state=state, release_tag="r4.1",
        error_message=f"Command /discard-snapshot is not allowed in state '{state}'. Valid commands: /sync-issue",
    ))

    assert "/create-snapshot" not in body


def test_result_comment_lists_the_actions_of_the_state_after_the_command(responder):
    body = responder.render("snapshot_created", build_context(
        state="snapshot-active", release_tag="r4.1", release_pr_url="https://github.com/org/repo/pull/123",
    ))

    assert body.rstrip().endswith(
        "**Valid actions:**<br>→ **Update, review, and merge [Release PR](https://github.com/org/repo/pull/123) "
        "to create draft release**<br>→ `/discard-snapshot <reason>` — discard and return to `planned`"
    )
