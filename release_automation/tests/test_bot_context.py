"""Tests for bot_context.py and context_builder.py."""

import pytest

from release_automation.scripts.bot_context import BotContext
from release_automation.scripts.context_builder import build_context


class TestBotContext:
    """Tests for the BotContext dataclass."""

    def test_default_values(self):
        """All fields have correct defaults."""
        ctx = BotContext()

        # String fields default to empty string
        assert ctx.command == ""
        assert ctx.command_args == ""
        assert ctx.user == ""
        assert ctx.trigger_pr_number == ""
        assert ctx.trigger_type == ""
        assert ctx.trigger_pr_url == ""
        assert ctx.closed_issue_number == ""
        assert ctx.closed_issue_url == ""
        assert ctx.release_plan_url == ""
        assert ctx.release_tag == ""
        assert ctx.state == ""
        assert ctx.release_type == ""
        assert ctx.meta_release == ""
        assert ctx.short_type == ""
        assert ctx.snapshot_id == ""
        assert ctx.snapshot_branch == ""
        assert ctx.release_review_branch == ""
        assert ctx.src_commit_sha == ""
        assert ctx.release_pr_number == ""
        assert ctx.release_pr_url == ""
        assert ctx.commonalities_release == ""
        assert ctx.identity_consent_management_release == ""
        assert ctx.error_message == ""
        assert ctx.error_type == ""
        assert ctx.workflow_run_url == ""
        assert ctx.draft_release_url == ""
        assert ctx.reason == ""

        # Publication fields default to empty string
        assert ctx.release_url == ""
        assert ctx.reference_tag == ""
        assert ctx.reference_tag_url == ""
        assert ctx.sync_pr_number == ""
        assert ctx.sync_pr_url == ""
        assert ctx.src_commit_sha_short == ""
        assert ctx.confirm_tag == ""

        # List field defaults to empty list
        assert ctx.apis == []

        # Boolean flags default to False
        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is False
        assert ctx.is_missing_field is False
        assert ctx.state_snapshot_active is False
        assert ctx.state_draft_ready is False
        assert ctx.state_published is False
        assert ctx.trigger_workflow_dispatch is False
        assert ctx.trigger_issue_close is False
        assert ctx.trigger_release_plan_change is False
        assert ctx.has_meta_release is False
        assert ctx.has_reason is False

    def test_derive_flags_missing_file(self):
        """error_type 'missing_file' sets is_missing_file flag."""
        ctx = BotContext(error_type="missing_file")
        ctx.derive_flags()

        assert ctx.is_missing_file is True
        assert ctx.is_malformed_yaml is False
        assert ctx.is_missing_field is False

    def test_derive_flags_malformed_yaml(self):
        """error_type 'malformed_yaml' sets is_malformed_yaml flag."""
        ctx = BotContext(error_type="malformed_yaml")
        ctx.derive_flags()

        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is True
        assert ctx.is_missing_field is False

    def test_derive_flags_missing_field(self):
        """error_type 'missing_field' sets is_missing_field flag."""
        ctx = BotContext(error_type="missing_field")
        ctx.derive_flags()

        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is False
        assert ctx.is_missing_field is True

    def test_derive_flags_snapshot_active(self):
        """state 'snapshot-active' sets state_snapshot_active flag."""
        ctx = BotContext(state="snapshot-active")
        ctx.derive_flags()

        assert ctx.state_snapshot_active is True
        assert ctx.state_draft_ready is False

    def test_derive_flags_draft_ready(self):
        """state 'draft-ready' sets state_draft_ready flag."""
        ctx = BotContext(state="draft-ready")
        ctx.derive_flags()

        assert ctx.state_snapshot_active is False
        assert ctx.state_draft_ready is True

    def test_derive_flags_planned_state(self):
        """state 'planned' sets no state flags."""
        ctx = BotContext(state="planned")
        ctx.derive_flags()

        assert ctx.state_snapshot_active is False
        assert ctx.state_draft_ready is False
        assert ctx.state_published is False

    def test_derive_flags_published(self):
        """state 'published' sets state_published flag."""
        ctx = BotContext(state="published")
        ctx.derive_flags()

        assert ctx.state_snapshot_active is False
        assert ctx.state_draft_ready is False
        assert ctx.state_published is True

    def test_derive_flags_empty_error_type(self):
        """Empty error_type sets no error flags."""
        ctx = BotContext(error_type="")
        ctx.derive_flags()

        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is False
        assert ctx.is_missing_field is False

    def test_derive_flags_clears_stale_flags(self):
        """Changing error_type and re-deriving clears old flags."""
        ctx = BotContext(error_type="missing_file")
        ctx.derive_flags()
        assert ctx.is_missing_file is True

        ctx.error_type = "malformed_yaml"
        ctx.derive_flags()
        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is True

    def test_to_dict_returns_all_keys(self):
        """to_dict() returns a dict with all BotContext fields."""
        ctx = BotContext()
        d = ctx.to_dict()

        expected_keys = {
            "command", "command_args", "user", "trigger_pr_number",
            "trigger_type", "trigger_pr_url",
            "closed_issue_number", "closed_issue_url", "release_plan_url",
            "release_tag", "state", "release_type", "meta_release", "short_type",
            "snapshot_id", "snapshot_branch", "snapshot_branch_url",
            "release_review_branch", "release_review_branch_url",
            "src_commit_sha", "release_pr_number", "release_pr_url",
            "apis",
            "commonalities_release", "identity_consent_management_release",
            "error_message", "error_type",
            "is_missing_file", "is_malformed_yaml", "is_missing_field",
            "state_snapshot_active", "state_draft_ready", "state_published",
            "trigger_workflow_dispatch", "trigger_issue_close",
            "trigger_release_plan_change",
            "has_meta_release", "has_reason",
            "workflow_run_url", "draft_release_url", "reason",
            # Publication fields
            "release_url", "reference_tag", "reference_tag_url",
            "sync_pr_number", "sync_pr_url",
            "src_commit_sha_short", "confirm_tag",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_no_none_values(self):
        """No None values in to_dict() output."""
        ctx = BotContext()
        d = ctx.to_dict()

        for key, value in d.items():
            assert value is not None, f"Key '{key}' has None value"

    def test_to_dict_apis_list(self):
        """apis list entries are preserved as dicts in to_dict()."""
        apis = [
            {"api_name": "QoD", "api_version": "1.0.0-rc.1", "api_title": "Quality on Demand",
             "target_api_version": "1.0.0", "target_api_status": "rc"},
        ]
        ctx = BotContext(apis=apis)
        d = ctx.to_dict()

        assert d["apis"] == apis
        assert d["apis"][0]["api_name"] == "QoD"

    def test_to_dict_with_populated_fields(self):
        """to_dict() preserves populated field values."""
        ctx = BotContext(
            release_tag="r4.1",
            state="snapshot-active",
            snapshot_id="r4.1-abc1234",
        )
        ctx.derive_flags()
        d = ctx.to_dict()

        assert d["release_tag"] == "r4.1"
        assert d["state"] == "snapshot-active"
        assert d["snapshot_id"] == "r4.1-abc1234"
        assert d["state_snapshot_active"] is True

    def test_to_dict_booleans_for_pystache(self):
        """Boolean True/False are preserved (pystache uses truthiness)."""
        ctx = BotContext(error_type="missing_file")
        ctx.derive_flags()
        d = ctx.to_dict()

        assert d["is_missing_file"] is True
        assert d["is_malformed_yaml"] is False
        assert isinstance(d["is_missing_file"], bool)
        assert isinstance(d["is_malformed_yaml"], bool)


class TestBuildContext:
    """Tests for the build_context() function."""

    def test_returns_complete_dict(self):
        """build_context() returns dict with all schema keys."""
        result = build_context()

        expected_keys = {
            "command", "command_args", "user", "trigger_pr_number",
            "trigger_type", "trigger_pr_url",
            "closed_issue_number", "closed_issue_url", "release_plan_url",
            "release_tag", "state", "release_type", "meta_release", "short_type",
            "snapshot_id", "snapshot_branch", "snapshot_branch_url",
            "release_review_branch", "release_review_branch_url",
            "src_commit_sha", "release_pr_number", "release_pr_url",
            "apis",
            "commonalities_release", "identity_consent_management_release",
            "error_message", "error_type",
            "is_missing_file", "is_malformed_yaml", "is_missing_field",
            "state_snapshot_active", "state_draft_ready", "state_published",
            "trigger_workflow_dispatch", "trigger_issue_close",
            "trigger_release_plan_change",
            "has_meta_release", "has_reason",
            "workflow_run_url", "draft_release_url", "reason",
            # Publication fields
            "release_url", "reference_tag", "reference_tag_url",
            "sync_pr_number", "sync_pr_url",
            "src_commit_sha_short", "confirm_tag",
        }
        assert set(result.keys()) == expected_keys

    def test_with_kwargs(self):
        """build_context() sets fields from kwargs."""
        result = build_context(
            release_tag="r4.1",
            state="snapshot-active",
            user="testuser",
        )

        assert result["release_tag"] == "r4.1"
        assert result["state"] == "snapshot-active"
        assert result["user"] == "testuser"

    def test_derives_flags_automatically(self):
        """build_context() derives flags from string fields."""
        result = build_context(error_type="missing_file")
        assert result["is_missing_file"] is True
        assert result["is_malformed_yaml"] is False

        result = build_context(state="draft-ready")
        assert result["state_draft_ready"] is True
        assert result["state_snapshot_active"] is False

    def test_ignores_unknown_kwargs(self):
        """Unknown kwargs are silently ignored."""
        result = build_context(
            release_tag="r4.1",
            unknown_field="should be ignored",
            another_unknown=42,
        )
        assert result["release_tag"] == "r4.1"
        assert "unknown_field" not in result
        assert "another_unknown" not in result

    def test_empty_call(self):
        """build_context() with no args returns all defaults."""
        result = build_context()

        assert result["release_tag"] == ""
        assert result["state"] == ""
        assert result["apis"] == []
        assert result["is_missing_file"] is False

    def test_no_none_values(self):
        """build_context() output has no None values."""
        result = build_context()
        for key, value in result.items():
            assert value is not None, f"Key '{key}' has None value"

    def test_apis_list(self):
        """build_context() preserves apis list entries."""
        apis = [
            {
                "api_name": "QualityOnDemand",
                "target_api_version": "1.0.0",
                "target_api_status": "rc",
                "api_version": "1.0.0-rc.1",
                "api_title": "Quality on Demand",
            },
            {
                "api_name": "QoSBooking",
                "target_api_version": "0.2.0",
                "target_api_status": "alpha",
                "api_version": "0.2.0-alpha.1",
                "api_title": "QoS Booking",
            },
        ]
        result = build_context(apis=apis)

        assert len(result["apis"]) == 2
        assert result["apis"][0]["api_name"] == "QualityOnDemand"
        assert result["apis"][1]["api_version"] == "0.2.0-alpha.1"

    def test_multiple_flags_from_different_fields(self):
        """State and error flags are derived independently."""
        result = build_context(
            state="snapshot-active",
            error_type="missing_file",
        )
        assert result["state_snapshot_active"] is True
        assert result["is_missing_file"] is True
        assert result["state_draft_ready"] is False
        assert result["is_malformed_yaml"] is False


class TestWP49Fields:
    """Tests for bot message context fields."""

    def test_trigger_type_workflow_dispatch(self):
        """trigger_type 'workflow_dispatch' sets correct flag."""
        ctx = BotContext(trigger_type="workflow_dispatch")
        ctx.derive_flags()
        assert ctx.trigger_workflow_dispatch is True
        assert ctx.trigger_issue_close is False
        assert ctx.trigger_release_plan_change is False

    def test_trigger_type_issue_close(self):
        """trigger_type 'issue_close' sets correct flag."""
        ctx = BotContext(trigger_type="issue_close")
        ctx.derive_flags()
        assert ctx.trigger_workflow_dispatch is False
        assert ctx.trigger_issue_close is True
        assert ctx.trigger_release_plan_change is False

    def test_trigger_type_release_plan_change(self):
        """trigger_type 'release_plan_change' sets correct flag."""
        ctx = BotContext(trigger_type="release_plan_change")
        ctx.derive_flags()
        assert ctx.trigger_workflow_dispatch is False
        assert ctx.trigger_issue_close is False
        assert ctx.trigger_release_plan_change is True

    def test_has_meta_release_true(self):
        """has_meta_release is True when meta_release is non-empty."""
        ctx = BotContext(meta_release="Fall 2026")
        ctx.derive_flags()
        assert ctx.has_meta_release is True

    def test_has_meta_release_false(self):
        """has_meta_release is False when meta_release is empty."""
        ctx = BotContext(meta_release="")
        ctx.derive_flags()
        assert ctx.has_meta_release is False

    def test_has_reason_true(self):
        """has_reason is True when reason is non-empty."""
        ctx = BotContext(reason="Found API error")
        ctx.derive_flags()
        assert ctx.has_reason is True

    def test_has_reason_false(self):
        """has_reason is False when reason is empty."""
        ctx = BotContext(reason="")
        ctx.derive_flags()
        assert ctx.has_reason is False

    def test_short_type_alpha(self):
        """short_type derived from pre-release-alpha."""
        ctx = BotContext(release_type="pre-release-alpha")
        ctx.derive_flags()
        assert ctx.short_type == "alpha"

    def test_short_type_rc(self):
        """short_type derived from pre-release-rc."""
        ctx = BotContext(release_type="pre-release-rc")
        ctx.derive_flags()
        assert ctx.short_type == "rc"

    def test_short_type_public(self):
        """short_type derived from public-release."""
        ctx = BotContext(release_type="public-release")
        ctx.derive_flags()
        assert ctx.short_type == "public"

    def test_short_type_maintenance(self):
        """short_type derived from maintenance-release."""
        ctx = BotContext(release_type="maintenance-release")
        ctx.derive_flags()
        assert ctx.short_type == "maintenance"

    def test_short_type_passthrough_unknown(self):
        """Unknown release_type passes through as short_type."""
        ctx = BotContext(release_type="custom-type")
        ctx.derive_flags()
        assert ctx.short_type == "custom-type"

    def test_short_type_not_overwritten_if_set(self):
        """Explicit short_type is not overwritten by derive_flags."""
        ctx = BotContext(release_type="pre-release-alpha", short_type="custom")
        ctx.derive_flags()
        assert ctx.short_type == "custom"

    def test_build_context_derives_short_type(self):
        """build_context derives short_type from release_type."""
        result = build_context(release_type="pre-release-rc")
        assert result["short_type"] == "rc"

    def test_build_context_trigger_flags(self):
        """build_context derives trigger flags."""
        result = build_context(trigger_type="workflow_dispatch")
        assert result["trigger_workflow_dispatch"] is True
        assert result["trigger_issue_close"] is False

    def test_build_context_has_meta_release(self):
        """build_context derives has_meta_release."""
        result = build_context(meta_release="Spring 2026")
        assert result["has_meta_release"] is True

        result = build_context(meta_release="")
        assert result["has_meta_release"] is False

    def test_issue_creation_fields_in_context(self):
        """Issue creation fields are passed through build_context."""
        result = build_context(
            closed_issue_number="42",
            closed_issue_url="https://github.com/org/repo/issues/42",
            release_plan_url="https://github.com/org/repo/blob/main/release-plan.yaml",
        )
        assert result["closed_issue_number"] == "42"
        assert result["closed_issue_url"] == "https://github.com/org/repo/issues/42"
        assert result["release_plan_url"] == "https://github.com/org/repo/blob/main/release-plan.yaml"
