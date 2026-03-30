"""Unit tests for validation.context.context_builder."""

from pathlib import Path

import pytest
import yaml

from validation.context.context_builder import (
    ApiContext,
    ValidationContext,
    build_validation_context,
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


# ---------------------------------------------------------------------------
# TestBuildValidationContext — metadata fallback
# ---------------------------------------------------------------------------

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
PLAN_SCHEMA = SCHEMAS_DIR / "release-plan-schema.yaml"
METADATA_SCHEMA = SCHEMAS_DIR / "release-metadata-schema.yaml"


def _write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return path


class TestBuildValidationContextMetadataFallback:
    """Test that build_validation_context falls back to release-metadata.yaml
    when release-plan.yaml is absent and the PR targets a snapshot branch."""

    @pytest.fixture
    def repo_with_metadata(self, tmp_path):
        """Repo checkout with release-metadata.yaml but no release-plan.yaml."""
        spec_dir = tmp_path / "code" / "API_definitions"
        spec_dir.mkdir(parents=True)
        # Minimal spec so api_pattern detection doesn't crash
        (spec_dir / "quality-on-demand.yaml").write_text(
            "openapi: '3.0.3'\ninfo:\n  title: QoD\n  version: wip\npaths: {}\n",
            encoding="utf-8",
        )
        _write_yaml(
            tmp_path / "release-metadata.yaml",
            {
                "repository": {
                    "repository_name": "QualityOnDemand",
                    "release_tag": "r4.1",
                    "release_type": "pre-release-rc",
                    "release_date": None,
                    "src_commit_sha": "a" * 40,
                },
                "dependencies": {
                    "commonalities_release": "r4.2 (1.2.0-rc.1)",
                    "identity_consent_management_release": "r4.3 (1.1.0)",
                },
                "apis": [
                    {
                        "api_name": "quality-on-demand",
                        "api_version": "1.0.0-rc.2",
                        "api_title": "Quality On Demand",
                    },
                ],
            },
        )
        return tmp_path

    def test_fallback_populates_context(self, repo_with_metadata):
        ctx = build_validation_context(
            repo_name="camaraproject/QualityOnDemand",
            event_name="pull_request",
            ref_name="release-review/r4.1-abc1234",
            base_ref="release-snapshot/r4.1-abc1234",
            repo_path=repo_with_metadata,
            release_plan_schema_path=PLAN_SCHEMA,
            release_metadata_schema_path=METADATA_SCHEMA,
        )
        assert ctx.is_release_review_pr is True
        assert ctx.profile == "strict"
        assert ctx.target_release_type == "pre-release-rc"
        assert ctx.commonalities_release == "r4.2"
        assert ctx.icm_release == "r4.3"
        assert len(ctx.apis) == 1
        assert ctx.apis[0].api_name == "quality-on-demand"
        assert ctx.apis[0].target_api_version == "1.0.0-rc.2"
        assert ctx.apis[0].target_api_status == "rc"

    def test_no_fallback_when_release_plan_exists(self, repo_with_metadata):
        """When release-plan.yaml exists, metadata fallback is not used."""
        _write_yaml(
            repo_with_metadata / "release-plan.yaml",
            {
                "repository": {
                    "release_track": "meta-release",
                    "meta_release": "Spring26",
                    "target_release_tag": "r4.1",
                    "target_release_type": "public-release",
                },
                "apis": [
                    {
                        "api_name": "quality-on-demand",
                        "target_api_version": "1.0.0",
                        "target_api_status": "public",
                    },
                ],
            },
        )
        ctx = build_validation_context(
            repo_name="camaraproject/QualityOnDemand",
            event_name="pull_request",
            ref_name="release-review/r4.1-abc1234",
            base_ref="release-snapshot/r4.1-abc1234",
            repo_path=repo_with_metadata,
            release_plan_schema_path=PLAN_SCHEMA,
            release_metadata_schema_path=METADATA_SCHEMA,
        )
        # Should use release-plan.yaml values, not metadata
        assert ctx.target_release_type == "public-release"

    def test_no_fallback_for_non_review_pr(self, tmp_path):
        """Metadata fallback only activates for release-review PRs."""
        _write_yaml(
            tmp_path / "release-metadata.yaml",
            {
                "repository": {
                    "repository_name": "Foo",
                    "release_tag": "r4.1",
                    "release_type": "pre-release-rc",
                    "release_date": None,
                    "src_commit_sha": "b" * 40,
                },
                "apis": [],
            },
        )
        ctx = build_validation_context(
            repo_name="camaraproject/Foo",
            event_name="pull_request",
            ref_name="fix/something",
            base_ref="main",
            repo_path=tmp_path,
            release_plan_schema_path=PLAN_SCHEMA,
            release_metadata_schema_path=METADATA_SCHEMA,
        )
        # Not a release review → no fallback → target_release_type stays None
        assert ctx.is_release_review_pr is False
        assert ctx.target_release_type is None
