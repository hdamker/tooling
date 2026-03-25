"""Unit tests for validation.context.context_builder."""

from pathlib import Path

import pytest

from validation.context.context_builder import (
    ApiContext,
    ValidationContext,
    derive_api_maturity,
    derive_branch_type,
    derive_target_branch,
    derive_trigger_type,
    is_release_review_pr_check,
    select_profile,
)


# ---------------------------------------------------------------------------
# TestDeriveBranchType
# ---------------------------------------------------------------------------


class TestDeriveBranchType:
    def test_main_branch(self):
        assert derive_branch_type("main") == "main"

    def test_release_snapshot_branch(self):
        assert derive_branch_type("release-snapshot/r4.1") == "release"

    def test_release_snapshot_nested(self):
        assert derive_branch_type("release-snapshot/r4.1/alpha") == "release"

    def test_maintenance_branch(self):
        assert derive_branch_type("maintenance/4.x") == "maintenance"

    def test_feature_branch(self):
        assert derive_branch_type("fix/some-issue") == "feature"

    def test_develop_branch(self):
        assert derive_branch_type("develop") == "feature"

    def test_empty_string(self):
        assert derive_branch_type("") == "feature"


# ---------------------------------------------------------------------------
# TestDeriveTriggerType
# ---------------------------------------------------------------------------


class TestDeriveTriggerType:
    def test_pull_request(self):
        assert derive_trigger_type("pull_request") == "pr"

    def test_workflow_dispatch(self):
        assert derive_trigger_type("workflow_dispatch") == "dispatch"

    def test_pre_snapshot_mode_overrides_event(self):
        assert (
            derive_trigger_type("workflow_dispatch", mode="pre-snapshot")
            == "release-automation"
        )

    def test_unknown_event_fallback(self):
        assert derive_trigger_type("push") == "dispatch"


# ---------------------------------------------------------------------------
# TestSelectProfile
# ---------------------------------------------------------------------------


class TestSelectProfile:
    def test_dispatch_gets_advisory(self):
        assert select_profile("dispatch", "main", False) == "advisory"

    def test_release_automation_gets_strict(self):
        assert select_profile("release-automation", "main", False) == "strict"

    def test_pr_release_review_gets_strict(self):
        assert select_profile("pr", "release", True) == "strict"

    def test_pr_main_gets_standard(self):
        assert select_profile("pr", "main", False) == "standard"

    def test_pr_feature_gets_standard(self):
        assert select_profile("pr", "feature", False) == "standard"

    def test_pr_maintenance_gets_standard(self):
        assert select_profile("pr", "maintenance", False) == "standard"

    def test_profile_override_wins(self):
        assert (
            select_profile("dispatch", "main", False, profile_override="strict")
            == "strict"
        )

    def test_invalid_profile_override_ignored(self):
        assert (
            select_profile("dispatch", "main", False, profile_override="invalid")
            == "advisory"
        )

    def test_local_gets_advisory(self):
        assert select_profile("local", "main", False) == "advisory"


# ---------------------------------------------------------------------------
# TestDeriveApiMaturity
# ---------------------------------------------------------------------------


class TestDeriveApiMaturity:
    def test_zero_major_is_initial(self):
        assert derive_api_maturity("0.5.0") == "initial"

    def test_one_major_is_stable(self):
        assert derive_api_maturity("1.0.0") == "stable"

    def test_high_major_is_stable(self):
        assert derive_api_maturity("3.2.1") == "stable"

    def test_unparseable_defaults_initial(self):
        assert derive_api_maturity("invalid") == "initial"


# ---------------------------------------------------------------------------
# TestIsReleaseReviewPr
# ---------------------------------------------------------------------------


class TestIsReleaseReviewPr:
    def test_release_snapshot_target(self):
        assert is_release_review_pr_check("release-snapshot/r4.1") is True

    def test_main_target(self):
        assert is_release_review_pr_check("main") is False

    def test_empty_base_ref(self):
        assert is_release_review_pr_check("") is False


# ---------------------------------------------------------------------------
# TestDeriveTargetBranch
# ---------------------------------------------------------------------------


class TestDeriveTargetBranch:
    def test_pr_uses_base_ref(self):
        assert derive_target_branch("pull_request", "main", "feature/x") == "main"

    def test_dispatch_uses_ref_name(self):
        assert derive_target_branch("workflow_dispatch", "", "main") == "main"


# ---------------------------------------------------------------------------
# TestValidationContextToDict
# ---------------------------------------------------------------------------


class TestValidationContextToDict:
    @pytest.fixture
    def sample_context(self):
        return ValidationContext(
            repository="QualityOnDemand",
            branch_type="main",
            trigger_type="pr",
            profile="standard",
            stage="standard",
            target_release_type="pre-release-rc",
            commonalities_release="r4.1",
            icm_release=None,
            is_release_review_pr=False,
            release_plan_changed=True,
            pr_number=42,
            apis=(
                ApiContext(
                    api_name="qos-booking",
                    target_api_version="1.0.0",
                    target_api_status="rc",
                    target_api_maturity="stable",
                    api_pattern="request-response",
                    spec_file="code/API_definitions/qos-booking.yaml",
                ),
            ),
            workflow_run_url="https://github.com/example/run/1",
            tooling_ref="abc123",
        )

    def test_all_keys_present(self, sample_context):
        d = sample_context.to_dict()
        expected_keys = {
            "repository", "branch_type", "trigger_type", "profile", "stage",
            "target_release_type", "commonalities_release", "icm_release",
            "is_release_review_pr", "release_plan_changed", "pr_number",
            "apis", "workflow_run_url", "tooling_ref",
        }
        assert set(d.keys()) == expected_keys

    def test_apis_serialized_as_list(self, sample_context):
        d = sample_context.to_dict()
        assert isinstance(d["apis"], list)
        assert len(d["apis"]) == 1
        assert isinstance(d["apis"][0], dict)
        assert d["apis"][0]["api_name"] == "qos-booking"

    def test_none_values_preserved(self, sample_context):
        d = sample_context.to_dict()
        assert d["icm_release"] is None
