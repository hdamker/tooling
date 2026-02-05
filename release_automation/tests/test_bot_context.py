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
        assert ctx.release_tag == ""
        assert ctx.state == ""
        assert ctx.release_type == ""
        assert ctx.meta_release == ""
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

        # List field defaults to empty list
        assert ctx.apis == []

        # Boolean flags default to False
        assert ctx.is_missing_file is False
        assert ctx.is_malformed_yaml is False
        assert ctx.is_missing_field is False
        assert ctx.state_snapshot_active is False
        assert ctx.state_draft_ready is False

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
            "release_tag", "state", "release_type", "meta_release",
            "snapshot_id", "snapshot_branch", "snapshot_branch_url",
            "release_review_branch", "release_review_branch_url",
            "src_commit_sha", "release_pr_number", "release_pr_url",
            "apis",
            "commonalities_release", "identity_consent_management_release",
            "error_message", "error_type",
            "is_missing_file", "is_malformed_yaml", "is_missing_field",
            "state_snapshot_active", "state_draft_ready",
            "workflow_run_url", "draft_release_url", "reason",
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
            "release_tag", "state", "release_type", "meta_release",
            "snapshot_id", "snapshot_branch", "snapshot_branch_url",
            "release_review_branch", "release_review_branch_url",
            "src_commit_sha", "release_pr_number", "release_pr_url",
            "apis",
            "commonalities_release", "identity_consent_management_release",
            "error_message", "error_type",
            "is_missing_file", "is_malformed_yaml", "is_missing_field",
            "state_snapshot_active", "state_draft_ready",
            "workflow_run_url", "draft_release_url", "reason",
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
