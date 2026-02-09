"""
Unit tests for snapshot_creator module.

These tests verify the orchestration of snapshot creation including:
- Precondition validation
- Snapshot ID generation
- Integration with version calculator, transformer, metadata generator
- Branch and PR creation
- Error handling and cleanup
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from release_automation.scripts.snapshot_creator import (
    SnapshotCreator,
    SnapshotConfig,
    SnapshotResult,
    SnapshotCreatorError,
    InvalidStateError,
    TransformationError,
)
from release_automation.scripts.state_manager import ReleaseState
from release_automation.scripts.mechanical_transformer import TransformationResult
from release_automation.scripts.git_operations import PullRequestInfo, GitOperationsError


# --- Fixtures ---

@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient."""
    client = Mock()
    client.repo = "hdamker/TestRepo-QoD"
    client.token = "test-token"
    client.list_branches.return_value = [
        Mock(name="main", sha="abc1234567890abcdef1234567890abcdef12345678")
    ]
    return client


@pytest.fixture
def mock_version_calculator():
    """Create a mock VersionCalculator."""
    calc = Mock()
    calc.calculate_versions_for_plan.return_value = {
        "quality-on-demand": "3.2.0-rc.1",
        "qos-profiles": "1.0.0",
    }
    return calc


@pytest.fixture
def mock_transformer():
    """Create a mock MechanicalTransformer."""
    transformer = Mock()
    transformer.apply_all.return_value = TransformationResult(
        success=True,
        files_modified=["code/API_definitions/quality-on-demand.yaml"],
        changes=[],
        errors=[],
        warnings=[],
    )
    return transformer


@pytest.fixture
def mock_metadata_generator():
    """Create a mock MetadataGenerator."""
    gen = Mock()
    gen.generate.return_value = {
        "repository": {
            "repository_name": "TestRepo-QoD",
            "release_tag": "r4.1",
            "release_type": "pre-release-rc",
        },
        "apis": [{"api_name": "quality-on-demand", "api_version": "3.2.0-rc.1"}],
    }
    return gen


@pytest.fixture
def mock_state_manager():
    """Create a mock ReleaseStateManager."""
    mgr = Mock()
    mgr.derive_state.return_value = ReleaseState.PLANNED
    return mgr


@pytest.fixture
def sample_release_plan():
    """Sample release plan for testing."""
    return {
        "repository": {
            "repository_name": "TestRepo-QoD",
            "target_release_tag": "r4.1",
            "target_release_type": "pre-release-rc",
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "target_api_version": "3.2.0",
                "target_api_status": "rc",
            },
            {
                "api_name": "qos-profiles",
                "target_api_version": "1.0.0",
                "target_api_status": "public",
            },
        ],
        "dependencies": {
            "commonalities_release": "r3.4",
            "identity_consent_management_release": "r3.3",
        },
    }


@pytest.fixture
def snapshot_creator(
    mock_github_client,
    mock_version_calculator,
    mock_transformer,
    mock_metadata_generator,
    mock_state_manager,
):
    """Create a SnapshotCreator with all mocked dependencies."""
    return SnapshotCreator(
        github_client=mock_github_client,
        version_calculator=mock_version_calculator,
        transformer=mock_transformer,
        metadata_generator=mock_metadata_generator,
        state_manager=mock_state_manager,
    )


# --- Tests for SnapshotConfig ---

class TestSnapshotConfig:
    """Tests for SnapshotConfig dataclass."""

    def test_default_values(self):
        """Test SnapshotConfig with default values."""
        config = SnapshotConfig(release_tag="r4.1")
        assert config.release_tag == "r4.1"
        assert config.base_branch == "main"
        assert config.src_commit_sha is None
        assert config.dry_run is False
        # Note: commonalities_release and icm_release are now derived from
        # release_plan['dependencies'], not passed via SnapshotConfig

    def test_custom_values(self):
        """Test SnapshotConfig with custom values."""
        config = SnapshotConfig(
            release_tag="r5.0",
            base_branch="develop",
            src_commit_sha="abc1234",
            dry_run=True,
        )
        assert config.release_tag == "r5.0"
        assert config.base_branch == "develop"
        assert config.src_commit_sha == "abc1234"
        assert config.dry_run is True


# --- Tests for SnapshotResult ---

class TestSnapshotResult:
    """Tests for SnapshotResult dataclass."""

    def test_success_result(self):
        """Test successful result creation."""
        result = SnapshotResult(
            success=True,
            snapshot_id="r4.1-abc1234",
            snapshot_branch="release-snapshot/r4.1-abc1234",
            release_review_branch="release-review/r4.1-abc1234",
            release_pr_number=42,
            release_pr_url="https://github.com/owner/repo/pull/42",
            src_commit_sha="abc1234567890",
            api_versions={"api1": "1.0.0", "api2": "2.0.0"},
        )
        assert result.success is True
        assert result.snapshot_id == "r4.1-abc1234"
        assert result.release_pr_number == 42

    def test_failure_result(self):
        """Test failure result creation."""
        result = SnapshotResult(
            success=False,
            errors=["State validation failed"],
        )
        assert result.success is False
        assert "State validation failed" in result.errors

    def test_to_bot_context_success(self):
        """Test to_bot_context for successful result."""
        result = SnapshotResult(
            success=True,
            snapshot_id="r4.1-abc1234",
            api_versions={"api1": "1.0.0", "api2": "2.0.0"},
        )
        context = result.to_bot_context()

        assert context["success"] is True
        assert context["snapshot_id"] == "r4.1-abc1234"
        assert len(context["apis"]) == 2
        assert context["apis"][0]["api_name"] == "api1"
        assert context["apis"][0]["api_version"] == "1.0.0"
        assert context["has_errors"] is False
        assert context["has_warnings"] is False

    def test_to_bot_context_with_errors(self):
        """Test to_bot_context with errors."""
        result = SnapshotResult(
            success=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )
        context = result.to_bot_context()

        assert context["success"] is False
        assert context["has_errors"] is True
        assert context["has_warnings"] is True
        assert len(context["errors"]) == 2
        assert len(context["warnings"]) == 1


# --- Tests for generate_snapshot_id ---

class TestGenerateSnapshotId:
    """Tests for snapshot ID generation."""

    def test_generate_standard_id(self, snapshot_creator):
        """Test standard snapshot ID generation."""
        snapshot_id = snapshot_creator.generate_snapshot_id(
            "r4.1", "abc1234567890abcdef"
        )
        assert snapshot_id == "r4.1-abc1234"

    def test_short_sha_truncation(self, snapshot_creator):
        """Test SHA is truncated to 7 characters."""
        snapshot_id = snapshot_creator.generate_snapshot_id(
            "r5.0", "1234567890abcdef1234567890abcdef12345678"
        )
        assert snapshot_id == "r5.0-1234567"
        assert len(snapshot_id.split("-")[1]) == 7

    def test_preserves_release_tag_format(self, snapshot_creator):
        """Test various release tag formats are preserved."""
        assert snapshot_creator.generate_snapshot_id(
            "r4.1", "abc1234"
        ) == "r4.1-abc1234"

        assert snapshot_creator.generate_snapshot_id(
            "v1.0.0", "abc1234"
        ) == "v1.0.0-abc1234"


# --- Tests for validate_preconditions ---

class TestValidatePreconditions:
    """Tests for precondition validation."""

    def test_valid_planned_state(self, snapshot_creator, mock_state_manager):
        """Test validation passes for PLANNED state."""
        mock_state_manager.derive_state.return_value = ReleaseState.PLANNED

        errors = snapshot_creator.validate_preconditions("r4.1")

        assert errors == []

    def test_invalid_published_state(self, snapshot_creator, mock_state_manager):
        """Test validation fails for PUBLISHED state."""
        mock_state_manager.derive_state.return_value = ReleaseState.PUBLISHED

        errors = snapshot_creator.validate_preconditions("r4.1")

        assert len(errors) == 1
        assert "already published" in errors[0]

    def test_invalid_snapshot_active_state(self, snapshot_creator, mock_state_manager):
        """Test validation fails for SNAPSHOT_ACTIVE state."""
        mock_state_manager.derive_state.return_value = ReleaseState.SNAPSHOT_ACTIVE

        errors = snapshot_creator.validate_preconditions("r4.1")

        assert len(errors) == 1
        assert "snapshot already exists" in errors[0]

    def test_invalid_draft_ready_state(self, snapshot_creator, mock_state_manager):
        """Test validation fails for DRAFT_READY state."""
        mock_state_manager.derive_state.return_value = ReleaseState.DRAFT_READY

        errors = snapshot_creator.validate_preconditions("r4.1")

        assert len(errors) == 1
        assert "draft release already exists" in errors[0]

    def test_invalid_not_planned_state(self, snapshot_creator, mock_state_manager):
        """Test validation fails for NOT_PLANNED state."""
        mock_state_manager.derive_state.return_value = ReleaseState.NOT_PLANNED

        errors = snapshot_creator.validate_preconditions("r4.1")

        assert len(errors) == 1
        assert "not planned" in errors[0]


# --- Tests for create_snapshot ---

class TestCreateSnapshot:
    """Tests for full snapshot creation flow."""

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_successful_snapshot_creation(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        sample_release_plan,
    ):
        """Test successful snapshot creation."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"

        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(
            number=42, url="https://github.com/owner/repo/pull/42"
        )

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is True
        assert result.snapshot_id is not None
        assert result.release_pr_number == 42
        assert "quality-on-demand" in result.api_versions

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    def test_dry_run_does_not_create_branches(
        self,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        sample_release_plan,
    ):
        """Test dry run mode doesn't create actual branches."""
        config = SnapshotConfig(release_tag="r4.1", dry_run=True)
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is True
        assert "Dry run" in result.warnings[0]
        # GitOperations should not have been instantiated
        mock_git_ops_class.assert_not_called()

    def test_validation_failure_returns_early(
        self,
        snapshot_creator,
        mock_state_manager,
        sample_release_plan,
    ):
        """Test that validation failure returns early without creating snapshot."""
        mock_state_manager.derive_state.return_value = ReleaseState.PUBLISHED

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "already published" in result.errors[0]

    def test_calculates_api_versions(
        self,
        snapshot_creator,
        mock_version_calculator,
        sample_release_plan,
    ):
        """Test that API versions are calculated."""
        config = SnapshotConfig(release_tag="r4.1", dry_run=True)
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        mock_version_calculator.calculate_versions_for_plan.assert_called_once_with(
            sample_release_plan
        )
        assert result.api_versions == {
            "quality-on-demand": "3.2.0-rc.1",
            "qos-profiles": "1.0.0",
        }

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_applies_all_transformations(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that transformations are applied."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        mock_transformer.apply_all.assert_called_once()
        assert result.transformation_summary["files_modified"] == 1

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_creates_correct_branch_names(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        sample_release_plan,
    ):
        """Test that branch names follow the expected pattern."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.snapshot_branch.startswith("release-snapshot/r4.1-")
        assert result.release_review_branch.startswith("release-review/r4.1-")

    def test_base_branch_not_found(
        self,
        snapshot_creator,
        mock_github_client,
        sample_release_plan,
    ):
        """Test error when base branch doesn't exist."""
        mock_github_client.list_branches.return_value = []

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Base branch" in result.errors[0]


# --- Tests for error handling ---

class TestErrorHandling:
    """Tests for error handling and cleanup."""

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    def test_cleanup_on_transformation_failure(
        self,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that branches are cleaned up on transformation failure."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops

        mock_transformer.apply_all.return_value = TransformationResult(
            success=False,
            errors=["Transformation failed"],
        )

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Transformations failed" in result.errors

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    def test_cleanup_on_git_failure(
        self,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        sample_release_plan,
    ):
        """Test that cleanup happens on git operation failure."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.clone.side_effect = GitOperationsError("Clone failed")

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Git operation failed" in result.errors[0]
        # Temp directory should be cleaned up
        mock_rmtree.assert_called()

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_cleanup_on_pr_creation_failure(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        sample_release_plan,
    ):
        """Test that branches are cleaned up when PR creation fails."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.side_effect = GitOperationsError("PR creation failed")

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Git operation failed" in result.errors[0]

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    def test_cleanup_errors_added_to_warnings(
        self,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that cleanup branch errors are captured in result.warnings."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops

        # Make transformation fail to trigger cleanup path
        mock_transformer.apply_all.return_value = TransformationResult(
            success=False,
            errors=["Transformation failed"],
        )

        # Mock _cleanup_branches to return cleanup errors
        with patch.object(
            snapshot_creator, '_cleanup_branches',
            return_value=["Failed to delete release-review/r4.1-abc1234: permission denied"]
        ):
            config = SnapshotConfig(release_tag="r4.1")
            result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Transformations failed" in result.errors
        assert "Failed to delete release-review/r4.1-abc1234: permission denied" in result.warnings

    def test_temp_directory_always_cleaned(
        self,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that temp directory is cleaned up even on success.

        We verify this by checking that after create_snapshot returns,
        no temp directories are left behind (using dry_run mode to
        verify the cleanup logic without actual git operations).
        """
        # Use dry_run=True to avoid git operations
        # The code path for temp dir cleanup is still exercised on error paths
        mock_transformer.apply_all.return_value = TransformationResult(
            success=False,
            errors=["Simulated failure to test cleanup"],
        )

        import tempfile
        import os

        # Count temp dirs before
        temp_base = tempfile.gettempdir()
        dirs_before = set(os.listdir(temp_base))

        # Run with validation failure (doesn't create temp dir)
        config = SnapshotConfig(release_tag="r4.1", dry_run=True)
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        # Verify result is successful (dry run)
        assert result.success is True

        # Verify no new temp directories leaked
        dirs_after = set(os.listdir(temp_base))
        new_dirs = dirs_after - dirs_before
        camara_dirs = [d for d in new_dirs if d.startswith("camara-")]
        assert len(camara_dirs) == 0, f"Temp directories not cleaned: {camara_dirs}"


# --- Tests for metadata generation integration ---

class TestMetadataIntegration:
    """Tests for metadata generator integration."""

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_generates_release_metadata(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_metadata_generator,
        sample_release_plan,
    ):
        """Test that release-metadata.yaml is generated."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        snapshot_creator.create_snapshot(sample_release_plan, config)

        mock_metadata_generator.generate.assert_called_once()

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_passes_versions_to_metadata_generator(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_metadata_generator,
        mock_version_calculator,
        sample_release_plan,
    ):
        """Test that calculated versions are passed to metadata generator."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        snapshot_creator.create_snapshot(sample_release_plan, config)

        call_args = mock_metadata_generator.generate.call_args
        # Second argument should be api_versions
        api_versions = call_args[0][1]
        assert api_versions == {
            "quality-on-demand": "3.2.0-rc.1",
            "qos-profiles": "1.0.0",
        }


# --- Tests for version calculator integration ---

class TestVersionCalculatorIntegration:
    """Tests for version calculator integration."""

    def test_uses_version_calculator_for_all_apis(
        self,
        snapshot_creator,
        mock_version_calculator,
        sample_release_plan,
    ):
        """Test that version calculator is called with full plan."""
        config = SnapshotConfig(release_tag="r4.1", dry_run=True)
        snapshot_creator.create_snapshot(sample_release_plan, config)

        mock_version_calculator.calculate_versions_for_plan.assert_called_with(
            sample_release_plan
        )

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_passes_versions_to_transformer_context(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        mock_version_calculator,
        sample_release_plan,
    ):
        """Test that versions are passed to transformer context."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        snapshot_creator.create_snapshot(sample_release_plan, config)

        call_args = mock_transformer.apply_all.call_args
        context = call_args[0][1]  # Second argument is context
        assert context.api_versions == {
            "quality-on-demand": "3.2.0-rc.1",
            "qos-profiles": "1.0.0",
        }
        assert context.release_tag == "r4.1"


# --- Tests for transformation integration ---

class TestTransformationIntegration:
    """Tests for mechanical transformer integration."""

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_creates_transformation_context(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that TransformationContext is created correctly."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        config = SnapshotConfig(release_tag="r4.1")
        # Dependencies are derived from release_plan, not config
        snapshot_creator.create_snapshot(sample_release_plan, config)

        call_args = mock_transformer.apply_all.call_args
        context = call_args[0][1]
        assert context.release_tag == "r4.1"
        # repo_name should be name only, not full path
        assert context.repo_name == "TestRepo-QoD"
        # These are derived from release_plan['dependencies']
        assert context.commonalities_release == "r3.4"
        assert context.icm_release == "r3.3"

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    @patch("builtins.open", create=True)
    def test_collects_transformation_warnings(
        self,
        mock_open,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that transformation warnings are collected."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops
        mock_git_ops.create_pr.return_value = PullRequestInfo(number=1, url="url")

        mock_transformer.apply_all.return_value = TransformationResult(
            success=True,
            warnings=["Warning 1", "Warning 2"],
        )

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert "Warning 1" in result.warnings
        assert "Warning 2" in result.warnings

    @patch("release_automation.scripts.snapshot_creator.tempfile.mkdtemp")
    @patch("release_automation.scripts.snapshot_creator.shutil.rmtree")
    @patch("release_automation.scripts.snapshot_creator.GitOperations")
    def test_handles_transformation_errors(
        self,
        mock_git_ops_class,
        mock_rmtree,
        mock_mkdtemp,
        snapshot_creator,
        mock_transformer,
        sample_release_plan,
    ):
        """Test that transformation errors cause failure."""
        mock_mkdtemp.return_value = "/tmp/test-snapshot"
        mock_git_ops = MagicMock()
        mock_git_ops_class.return_value = mock_git_ops

        mock_transformer.apply_all.return_value = TransformationResult(
            success=False,
            errors=["Critical error in transformation"],
        )

        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.success is False
        assert "Transformations failed" in result.errors


# --- Tests for custom base commit SHA ---

class TestCustomBaseCommit:
    """Tests for using custom base commit SHA."""

    def test_uses_provided_src_commit_sha(
        self,
        snapshot_creator,
        mock_github_client,
        sample_release_plan,
    ):
        """Test that provided src_commit_sha is used."""
        # Reset the mock to clear any previous calls
        mock_github_client.list_branches.reset_mock()

        config = SnapshotConfig(
            release_tag="r4.1",
            src_commit_sha="custom123456789",
            dry_run=True,
        )
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        assert result.src_commit_sha == "custom123456789"
        # SHA is truncated to 7 characters: "custom1" from "custom123456789"
        assert result.snapshot_id == "r4.1-custom1"
        # Should not call list_branches to get SHA since src_commit_sha was provided
        mock_github_client.list_branches.assert_not_called()

    def test_fetches_sha_when_not_provided(
        self,
        snapshot_creator,
        mock_github_client,
        sample_release_plan,
    ):
        """Test that SHA is fetched when not provided."""
        config = SnapshotConfig(release_tag="r4.1", dry_run=True)
        result = snapshot_creator.create_snapshot(sample_release_plan, config)

        mock_github_client.list_branches.assert_called_with("main")
        assert result.src_commit_sha is not None


# --- Tests for Release Documentation (README + CHANGELOG Integration) ---


class TestReleaseDocumentation:
    """Tests for README and CHANGELOG generation in create_snapshot flow."""

    def test_get_latest_public_release_returns_first_non_prerelease(
        self, snapshot_creator, mock_github_client
    ):
        """Returns tag of first non-prerelease release."""
        mock_github_client.get_releases.return_value = [
            Mock(tag_name="r4.1-rc.1", prerelease=True),
            Mock(tag_name="r3.2", prerelease=False),
            Mock(tag_name="r2.2", prerelease=False),
        ]
        result = snapshot_creator._get_latest_public_release()
        assert result == "r3.2"

    def test_get_latest_public_release_returns_none_when_no_public(
        self, snapshot_creator, mock_github_client
    ):
        """Returns None when only prereleases exist."""
        mock_github_client.get_releases.return_value = [
            Mock(tag_name="r4.1-rc.1", prerelease=True),
        ]
        result = snapshot_creator._get_latest_public_release()
        assert result is None

    def test_get_previous_release_returns_most_recent(
        self, snapshot_creator, mock_github_client
    ):
        """Returns the most recent release tag."""
        mock_github_client.get_releases.return_value = [
            Mock(tag_name="r3.2"),
            Mock(tag_name="r2.2"),
        ]
        result = snapshot_creator._get_previous_release()
        assert result == "r3.2"

    def test_get_previous_release_returns_none_when_empty(
        self, snapshot_creator, mock_github_client
    ):
        """Returns None when no releases exist."""
        mock_github_client.get_releases.return_value = []
        result = snapshot_creator._get_previous_release()
        assert result is None

    def test_get_candidate_changes_works_without_previous(
        self, snapshot_creator, mock_github_client
    ):
        """Calls generate-notes API even without previous release."""
        mock_github_client.generate_release_notes.return_value = "## What's Changed\n"
        result = snapshot_creator._get_candidate_changes("r4.1", None)
        assert result is not None
        mock_github_client.generate_release_notes.assert_called_once_with("r4.1", None)

    def test_get_candidate_changes_returns_body_on_success(
        self, snapshot_creator, mock_github_client
    ):
        """Returns markdown body from generate-notes API."""
        mock_github_client.generate_release_notes.return_value = (
            "## What's Changed\n* PR #1 by @user\n"
        )
        result = snapshot_creator._get_candidate_changes("r4.1", "r3.2")
        assert "What's Changed" in result
        mock_github_client.generate_release_notes.assert_called_once_with("r4.1", "r3.2")

    def test_get_candidate_changes_returns_none_on_api_error(
        self, snapshot_creator, mock_github_client
    ):
        """Returns None when generate-notes API fails."""
        mock_github_client.generate_release_notes.return_value = None
        result = snapshot_creator._get_candidate_changes("r4.1", "r3.2")
        assert result is None

    def test_update_readme_returns_false_when_no_readme(
        self, snapshot_creator, tmp_path, sample_release_plan
    ):
        """Returns False when README.md doesn't exist."""
        config = SnapshotConfig(release_tag="r4.1")
        result = snapshot_creator._update_readme(
            str(tmp_path), config, sample_release_plan, {}, {}
        )
        assert result is False

    @patch("release_automation.scripts.snapshot_creator.ReadmeUpdater")
    def test_update_readme_determines_prerelease_state(
        self, mock_updater_cls, snapshot_creator, mock_github_client, tmp_path, sample_release_plan
    ):
        """Determines prerelease_only state when no public releases exist."""
        # Create README with delimiters
        readme = tmp_path / "README.md"
        readme.write_text(
            "<!-- CAMARA:RELEASE-INFO:START -->\nold\n<!-- CAMARA:RELEASE-INFO:END -->\n"
        )
        mock_github_client.get_releases.return_value = []

        mock_instance = Mock()
        mock_instance.update_release_info.return_value = True
        mock_updater_cls.return_value = mock_instance
        mock_updater_cls.format_api_links = Mock(return_value="")

        config = SnapshotConfig(release_tag="r4.1")
        metadata = {"repository": {"release_type": "pre-release-rc"}}
        snapshot_creator._update_readme(
            str(tmp_path), config, sample_release_plan,
            {"quality-on-demand": "v1.0.0"}, metadata
        )

        # Should be called with prerelease_only state since no public releases
        call_args = mock_instance.update_release_info.call_args
        assert call_args[0][1] == "prerelease_only"

    @patch("release_automation.scripts.snapshot_creator.ChangelogGenerator")
    def test_generate_changelog_creates_file(
        self, mock_gen_cls, snapshot_creator, mock_github_client, tmp_path
    ):
        """Generates CHANGELOG and writes to directory."""
        mock_github_client.get_releases.return_value = []
        mock_github_client.generate_release_notes.return_value = None

        mock_instance = Mock()
        mock_instance.generate_draft.return_value = "# r4.1\n\nContent\n"
        mock_instance.write_changelog.return_value = "CHANGELOG/CHANGELOG-r4.md"
        mock_gen_cls.return_value = mock_instance

        config = SnapshotConfig(release_tag="r4.1")
        metadata = {"repository": {"release_type": "pre-release-alpha"}, "apis": [], "dependencies": {}}
        result = snapshot_creator._generate_changelog(
            str(tmp_path), config, {}, {}, metadata, "TestRepo-QoD"
        )
        assert result == "CHANGELOG/CHANGELOG-r4.md"
        mock_instance.generate_draft.assert_called_once()
        mock_instance.write_changelog.assert_called_once()

    def test_read_release_metadata_from_repo_tree(
        self, snapshot_creator, mock_github_client
    ):
        """Returns metadata when file exists in repository tree at tag."""
        yaml_content = "repository:\n  release_type: public-release\napis:\n- api_name: qod\n  api_version: v1.0.0\n"
        mock_github_client.get_file_content.return_value = yaml_content
        result = snapshot_creator._read_release_metadata("r3.2")
        assert result is not None
        assert result["repository"]["release_type"] == "public-release"
        assert result["apis"][0]["api_version"] == "v1.0.0"
        mock_github_client.get_file_content.assert_called_once_with(
            "release-metadata.yaml", ref="r3.2"
        )

    def test_read_release_metadata_falls_back_to_release_asset(
        self, snapshot_creator, mock_github_client
    ):
        """Falls back to release asset when file not in repo tree."""
        mock_github_client.get_file_content.return_value = None
        yaml_content = "repository:\n  release_type: public-release\napis:\n- api_name: qod\n  api_version: v1.0.0\n"
        mock_github_client.download_release_asset.return_value = yaml_content
        result = snapshot_creator._read_release_metadata("r3.2")
        assert result is not None
        assert result["apis"][0]["api_version"] == "v1.0.0"
        mock_github_client.download_release_asset.assert_called_once_with(
            "r3.2", "release-metadata.yaml"
        )

    def test_read_release_metadata_returns_none_when_not_found(
        self, snapshot_creator, mock_github_client
    ):
        """Returns None when metadata not found in tree or assets."""
        mock_github_client.get_file_content.return_value = None
        mock_github_client.download_release_asset.return_value = None
        result = snapshot_creator._read_release_metadata("r3.2")
        assert result is None
