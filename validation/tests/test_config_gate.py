"""Unit tests for validation.config.config_gate."""

from pathlib import Path

import pytest
import yaml

from validation.config.config_gate import (
    ConfigValidationError,
    StageGateResult,
    load_and_validate_config,
    resolve_stage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "validation-config-schema.yaml"
)


@pytest.fixture
def schema_path():
    """Path to the real validation-config schema."""
    return SCHEMA_PATH


@pytest.fixture
def sample_config():
    """A realistic validated config dict."""
    return {
        "version": 1,
        "defaults": {"stage": "disabled"},
        "fork_owners": ["hdamker", "rartych"],
        "repositories": {
            "ReleaseTest": {"stage": "advisory"},
            "QualityOnDemand": {"stage": "enabled"},
        },
    }


def _write_yaml(path: Path, data) -> Path:
    """Write a Python object as YAML to *path* and return the path."""
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# TestLoadAndValidateConfig
# ---------------------------------------------------------------------------


class TestLoadAndValidateConfig:
    """Tests for config file loading and schema validation."""

    def test_valid_config(self, tmp_path, schema_path, sample_config):
        cfg_path = _write_yaml(tmp_path / "config.yaml", sample_config)
        result = load_and_validate_config(cfg_path, schema_path)
        assert result["version"] == 1
        assert result["defaults"]["stage"] == "disabled"
        assert "ReleaseTest" in result["repositories"]

    def test_minimal_config(self, tmp_path, schema_path):
        """Only required fields — no fork_owners, no repositories."""
        cfg = {"version": 1, "defaults": {"stage": "disabled"}}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        result = load_and_validate_config(cfg_path, schema_path)
        assert result["version"] == 1

    def test_invalid_version_rejected(self, tmp_path, schema_path):
        cfg = {"version": 2, "defaults": {"stage": "disabled"}}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError) as exc_info:
            load_and_validate_config(cfg_path, schema_path)
        assert "version" in str(exc_info.value).lower()

    def test_invalid_stage_rejected(self, tmp_path, schema_path):
        cfg = {"version": 1, "defaults": {"stage": "blocking"}}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError):
            load_and_validate_config(cfg_path, schema_path)

    def test_old_standard_stage_rejected(self, tmp_path, schema_path):
        """The old 'standard' stage value is no longer valid."""
        cfg = {"version": 1, "defaults": {"stage": "standard"}}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError):
            load_and_validate_config(cfg_path, schema_path)

    def test_missing_defaults_rejected(self, tmp_path, schema_path):
        cfg = {"version": 1}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError) as exc_info:
            load_and_validate_config(cfg_path, schema_path)
        assert "defaults" in str(exc_info.value).lower()

    def test_extra_properties_rejected(self, tmp_path, schema_path):
        cfg = {"version": 1, "defaults": {"stage": "disabled"}, "unknown_key": True}
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError):
            load_and_validate_config(cfg_path, schema_path)

    def test_empty_file_rejected(self, tmp_path, schema_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("", encoding="utf-8")
        with pytest.raises(ConfigValidationError) as exc_info:
            load_and_validate_config(cfg_path, schema_path)
        assert "empty" in str(exc_info.value).lower()

    def test_multiple_errors_collected(self, tmp_path, schema_path):
        """Config with several violations — all should be reported."""
        cfg = {"version": 99, "extra": True}  # wrong version, missing defaults, extra key
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError) as exc_info:
            load_and_validate_config(cfg_path, schema_path)
        assert len(exc_info.value.errors) >= 2

    def test_profiles_in_defaults_accepted(self, tmp_path, schema_path):
        """Default profiles are valid optional fields."""
        cfg = {
            "version": 1,
            "defaults": {
                "stage": "disabled",
                "pr_profile": "strict",
                "release_profile": "advisory",
            },
        }
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        result = load_and_validate_config(cfg_path, schema_path)
        assert result["defaults"]["pr_profile"] == "strict"

    def test_profiles_in_repo_accepted(self, tmp_path, schema_path):
        """Per-repo profiles are valid optional fields."""
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled"},
            "repositories": {
                "TestRepo": {
                    "stage": "enabled",
                    "pr_profile": "advisory",
                    "release_profile": "strict",
                },
            },
        }
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        result = load_and_validate_config(cfg_path, schema_path)
        assert result["repositories"]["TestRepo"]["pr_profile"] == "advisory"

    def test_invalid_profile_value_rejected(self, tmp_path, schema_path):
        """Profile values must be advisory/standard/strict."""
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled", "pr_profile": "blocking"},
        }
        cfg_path = _write_yaml(tmp_path / "config.yaml", cfg)
        with pytest.raises(ConfigValidationError):
            load_and_validate_config(cfg_path, schema_path)


# ---------------------------------------------------------------------------
# TestResolveStage
# ---------------------------------------------------------------------------


class TestResolveStage:
    """Tests for stage resolution logic (pure function, dict input)."""

    def test_known_repo_uses_repo_stage(self, sample_config):
        result = resolve_stage(
            sample_config, "camaraproject/ReleaseTest", "camaraproject", "pull_request"
        )
        assert result.stage == "advisory"

    def test_unknown_repo_falls_back_to_default(self, sample_config):
        result = resolve_stage(
            sample_config, "camaraproject/UnknownRepo", "camaraproject", "pull_request"
        )
        assert result.stage == "disabled"

    def test_disabled_does_not_continue(self, sample_config):
        result = resolve_stage(
            sample_config, "camaraproject/UnknownRepo", "camaraproject", "pull_request"
        )
        assert result.should_continue is False
        assert "not enabled" in result.reason

    def test_advisory_pr_does_not_continue(self, sample_config):
        result = resolve_stage(
            sample_config, "camaraproject/ReleaseTest", "camaraproject", "pull_request"
        )
        assert result.should_continue is False
        assert "advisory" in result.reason.lower()

    def test_advisory_dispatch_continues(self, sample_config):
        result = resolve_stage(
            sample_config,
            "camaraproject/ReleaseTest",
            "camaraproject",
            "workflow_dispatch",
        )
        assert result.should_continue is True
        assert result.stage == "advisory"

    def test_enabled_continues(self, sample_config):
        result = resolve_stage(
            sample_config,
            "camaraproject/QualityOnDemand",
            "camaraproject",
            "pull_request",
        )
        assert result.should_continue is True
        assert result.stage == "enabled"

    def test_fork_listed_owner_overrides_to_enabled(self, sample_config):
        result = resolve_stage(
            sample_config,
            "hdamker/QualityOnDemand",
            "hdamker",
            "pull_request",
        )
        assert result.stage == "enabled"
        assert result.is_fork is True
        assert result.fork_override_applied is True
        assert result.should_continue is True

    def test_fork_unlisted_owner_keeps_resolved_stage(self, sample_config):
        result = resolve_stage(
            sample_config,
            "unknown-user/QualityOnDemand",
            "unknown-user",
            "pull_request",
        )
        # QualityOnDemand is "enabled" in config, but no fork override for
        # an unlisted owner — the stage stays as looked up.
        assert result.stage == "enabled"
        assert result.is_fork is True
        assert result.fork_override_applied is False

    def test_upstream_owner_not_fork(self, sample_config):
        result = resolve_stage(
            sample_config, "camaraproject/ReleaseTest", "camaraproject", "workflow_dispatch"
        )
        assert result.is_fork is False
        assert result.fork_override_applied is False

    def test_gsma_owner_is_upstream(self, sample_config):
        result = resolve_stage(
            sample_config,
            "GSMA-Open-Gateway/SomeAPI",
            "GSMA-Open-Gateway",
            "pull_request",
        )
        assert result.is_fork is False

    def test_repo_name_extracted_from_full_name(self, sample_config):
        """'camaraproject/QualityOnDemand' should look up 'QualityOnDemand'."""
        result = resolve_stage(
            sample_config,
            "camaraproject/QualityOnDemand",
            "camaraproject",
            "pull_request",
        )
        assert result.stage == "enabled"

    def test_fork_disabled_unlisted_stays_disabled(self, sample_config):
        """Unlisted fork owner of a disabled repo -> stays disabled."""
        result = resolve_stage(
            sample_config,
            "stranger/UnknownRepo",
            "stranger",
            "workflow_dispatch",
        )
        assert result.stage == "disabled"
        assert result.should_continue is False
        assert result.is_fork is True
        assert result.fork_override_applied is False

    def test_fork_disabled_listed_overrides_to_enabled(self, sample_config):
        """Listed fork owner of a disabled repo -> overrides to enabled."""
        result = resolve_stage(
            sample_config,
            "hdamker/UnknownRepo",
            "hdamker",
            "workflow_dispatch",
        )
        assert result.stage == "enabled"
        assert result.should_continue is True
        assert result.fork_override_applied is True

    def test_empty_fork_owners(self):
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled"},
            "fork_owners": [],
            "repositories": {},
        }
        result = resolve_stage(cfg, "hdamker/Repo", "hdamker", "workflow_dispatch")
        assert result.stage == "disabled"
        assert result.fork_override_applied is False

    def test_no_fork_owners_key(self):
        cfg = {"version": 1, "defaults": {"stage": "disabled"}, "repositories": {}}
        result = resolve_stage(cfg, "hdamker/Repo", "hdamker", "workflow_dispatch")
        assert result.stage == "disabled"
        assert result.fork_override_applied is False

    def test_no_repositories_key(self):
        cfg = {"version": 1, "defaults": {"stage": "enabled"}}
        result = resolve_stage(
            cfg, "camaraproject/AnyRepo", "camaraproject", "pull_request"
        )
        assert result.stage == "enabled"
        assert result.should_continue is True


# ---------------------------------------------------------------------------
# TestResolveStageProfiles
# ---------------------------------------------------------------------------


class TestResolveStageProfiles:
    """Tests for profile resolution in resolve_stage."""

    def test_defaults_to_standard_when_absent(self):
        """No profiles anywhere -> both default to standard."""
        cfg = {
            "version": 1,
            "defaults": {"stage": "enabled"},
            "repositories": {"Repo": {"stage": "enabled"}},
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.pr_profile == "standard"
        assert result.release_profile == "standard"

    def test_pr_profile_from_repo_config(self):
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled"},
            "repositories": {
                "Repo": {"stage": "enabled", "pr_profile": "advisory"},
            },
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.pr_profile == "advisory"
        assert result.release_profile == "standard"  # not set -> default

    def test_release_profile_from_repo_config(self):
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled"},
            "repositories": {
                "Repo": {"stage": "enabled", "release_profile": "strict"},
            },
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.release_profile == "strict"
        assert result.pr_profile == "standard"  # not set -> default

    def test_profiles_fallback_to_defaults(self):
        """Repo entry has no profiles -> fall back to defaults section."""
        cfg = {
            "version": 1,
            "defaults": {
                "stage": "disabled",
                "pr_profile": "advisory",
                "release_profile": "strict",
            },
            "repositories": {"Repo": {"stage": "enabled"}},
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.pr_profile == "advisory"
        assert result.release_profile == "strict"

    def test_repo_profile_overrides_defaults(self):
        """Repo-level profile wins over defaults."""
        cfg = {
            "version": 1,
            "defaults": {
                "stage": "disabled",
                "pr_profile": "advisory",
                "release_profile": "advisory",
            },
            "repositories": {
                "Repo": {
                    "stage": "enabled",
                    "pr_profile": "strict",
                    "release_profile": "strict",
                },
            },
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.pr_profile == "strict"
        assert result.release_profile == "strict"

    def test_fork_override_forces_profiles_to_standard(self):
        """Fork override sets both profiles to standard regardless of config."""
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled"},
            "fork_owners": ["hdamker"],
            "repositories": {
                "Repo": {
                    "stage": "enabled",
                    "pr_profile": "strict",
                    "release_profile": "strict",
                },
            },
        }
        result = resolve_stage(cfg, "hdamker/Repo", "hdamker", "pull_request")
        assert result.fork_override_applied is True
        assert result.pr_profile == "standard"
        assert result.release_profile == "standard"

    def test_profiles_present_even_when_disabled(self):
        """Profiles are resolved even when stage is disabled (for diagnostics)."""
        cfg = {
            "version": 1,
            "defaults": {"stage": "disabled", "pr_profile": "strict"},
            "repositories": {},
        }
        result = resolve_stage(cfg, "camaraproject/Repo", "camaraproject", "pull_request")
        assert result.should_continue is False
        assert result.pr_profile == "strict"
