"""
Snapshot creator for CAMARA release automation.

This module orchestrates the complete snapshot creation flow, including
version calculation, mechanical transformations, and metadata generation.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from . import config
from .changelog_generator import ChangelogGenerator
from .git_operations import GitOperations, GitOperationsError, PullRequestInfo
from .github_client import GitHubClient
from .mechanical_transformer import MechanicalTransformer, TransformationContext
from .metadata_generator import MetadataGenerator
from .readme_updater import ReadmeUpdater, ReadmeUpdateError
from .state_manager import ReleaseState, ReleaseStateManager
from .template_loader import render_template
from .version_calculator import VersionCalculator


@dataclass
class SnapshotConfig:
    """Configuration for snapshot creation."""
    release_tag: str
    base_branch: str = "main"
    src_commit_sha: Optional[str] = None
    dry_run: bool = False
    # Note: commonalities_release and icm_release are derived from
    # release_plan['dependencies'], not passed via config


@dataclass
class SnapshotResult:
    """Result of snapshot creation."""
    success: bool
    snapshot_id: Optional[str] = None
    snapshot_branch: Optional[str] = None
    release_review_branch: Optional[str] = None
    release_pr_number: Optional[int] = None
    release_pr_url: Optional[str] = None
    src_commit_sha: Optional[str] = None
    api_versions: Dict[str, str] = field(default_factory=dict)
    transformation_summary: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_bot_context(self) -> Dict[str, Any]:
        """
        Convert to context dict for bot message templates.

        Returns:
            Dict suitable for Mustache template rendering
        """
        return {
            "success": self.success,
            "snapshot_id": self.snapshot_id,
            "snapshot_branch": self.snapshot_branch,
            "release_review_branch": self.release_review_branch,
            "release_pr_number": self.release_pr_number,
            "release_pr_url": self.release_pr_url,
            "src_commit_sha": self.src_commit_sha,
            "apis": [
                {"api_name": name, "api_version": version}
                for name, version in self.api_versions.items()
            ],
            "transformation_summary": self.transformation_summary,
            "errors": self.errors,
            "warnings": self.warnings,
            "has_errors": len(self.errors) > 0,
            "has_warnings": len(self.warnings) > 0,
        }


class SnapshotCreatorError(Exception):
    """Base exception for snapshot creator errors."""
    pass


class InvalidStateError(SnapshotCreatorError):
    """Raised when snapshot creation attempted in invalid state."""
    pass


class TransformationError(SnapshotCreatorError):
    """Raised when transformations fail critically."""
    pass


class SnapshotCreator:
    """
    Orchestrates release snapshot creation.

    Creates snapshot branches with all transformations applied,
    generates release-metadata.yaml, and creates the Release PR.
    """

    SNAPSHOT_BRANCH_PREFIX = "release-snapshot"
    RELEASE_REVIEW_BRANCH_PREFIX = "release-review"
    SHORT_SHA_LENGTH = 7
    BOT_NAME = "CAMARA Release Bot"
    BOT_EMAIL = "noreply@camaraproject.org"

    def __init__(
        self,
        github_client: GitHubClient,
        version_calculator: VersionCalculator,
        transformer: MechanicalTransformer,
        metadata_generator: MetadataGenerator,
        state_manager: ReleaseStateManager,
    ):
        """
        Initialize snapshot creator with dependencies.

        Args:
            github_client: GitHubClient instance for repository operations
            version_calculator: VersionCalculator for API version extensions
            transformer: MechanicalTransformer for placeholder replacements
            metadata_generator: MetadataGenerator for release-metadata.yaml
            state_manager: ReleaseStateManager for state validation
        """
        self.gh = github_client
        self.version_calc = version_calculator
        self.transformer = transformer
        self.metadata_gen = metadata_generator
        self.state_manager = state_manager

    def create_snapshot(
        self,
        release_plan: Dict[str, Any],
        config: SnapshotConfig,
    ) -> SnapshotResult:
        """
        Create a complete release snapshot.

        Args:
            release_plan: Parsed release-plan.yaml content
            config: Snapshot configuration

        Returns:
            SnapshotResult with all details or errors
        """
        result = SnapshotResult(success=False)
        temp_dir = None
        snapshot_branch = None
        release_review_branch = None

        try:
            # Step 1: Validate preconditions
            errors = self.validate_preconditions(config.release_tag)
            if errors:
                result.errors = errors
                return result

            # Step 2: Get base commit SHA
            if config.src_commit_sha:
                base_sha = config.src_commit_sha
            else:
                # Get from main branch via API
                branches = self.gh.list_branches(config.base_branch)
                if not branches:
                    result.errors.append(
                        f"Base branch '{config.base_branch}' not found"
                    )
                    return result
                base_sha = branches[0].sha

            result.src_commit_sha = base_sha

            # Step 3: Generate snapshot ID
            snapshot_id = self.generate_snapshot_id(config.release_tag, base_sha)
            result.snapshot_id = snapshot_id

            # Step 4: Calculate API versions
            api_versions = self.version_calc.calculate_versions_for_plan(release_plan)
            result.api_versions = api_versions

            # Step 5: Define branch names
            snapshot_branch = f"{self.SNAPSHOT_BRANCH_PREFIX}/{snapshot_id}"
            release_review_branch = f"{self.RELEASE_REVIEW_BRANCH_PREFIX}/{snapshot_id}"
            result.snapshot_branch = snapshot_branch
            result.release_review_branch = release_review_branch

            if config.dry_run:
                result.success = True
                result.warnings.append("Dry run: no branches or PR created")
                return result

            # Step 6: Clone repository to temp directory
            temp_dir = tempfile.mkdtemp(prefix="camara-snapshot-")
            git_ops = GitOperations(
                repo=self.gh.repo,
                work_dir=temp_dir,
                token=self.gh.token,
            )

            git_ops.clone(branch=config.base_branch)
            git_ops.configure_user(self.BOT_NAME, self.BOT_EMAIL)

            # Step 7: Create snapshot branch
            git_ops.create_branch(snapshot_branch)

            # Step 8: Apply transformations
            # Extract dependency release tags from release-plan.yaml
            dependencies = release_plan.get("dependencies", {})
            commonalities_release = dependencies.get("commonalities_release", "main")
            icm_release = dependencies.get("identity_consent_management_release", "main")

            context = TransformationContext(
                release_tag=config.release_tag,
                api_versions=api_versions,
                commonalities_release=commonalities_release,
                icm_release=icm_release,
                repo_name=self.gh.repo.split("/")[-1],
                release_plan=release_plan,
            )

            transform_result = self.transformer.apply_all(temp_dir, context)
            result.transformation_summary = {
                "files_modified": len(transform_result.files_modified),
                "changes": len(transform_result.changes),
            }
            result.warnings.extend(transform_result.warnings)

            if not transform_result.success:
                result.errors.extend(transform_result.errors)
                raise TransformationError("Transformations failed")

            # Step 9: Generate and write release-metadata.yaml
            api_titles = self._extract_api_titles(release_plan, temp_dir)
            metadata = self.metadata_gen.generate(
                release_plan, api_versions, base_sha, api_titles,
                repo=self.gh.repo,
            )
            metadata_path = os.path.join(temp_dir, "release-metadata.yaml")
            with open(metadata_path, "w") as f:
                yaml.safe_dump(metadata, f, default_flow_style=False, sort_keys=False)

            # Step 9b: Remove release-plan.yaml from snapshot
            # release-metadata.yaml is the authoritative artifact; the plan is
            # an input file that should not appear on the release branch.
            plan_path = os.path.join(temp_dir, "release-plan.yaml")
            if os.path.exists(plan_path):
                os.remove(plan_path)

            # Step 10: Commit changes
            commit_message = f"Release automation: create snapshot {snapshot_id}"
            git_ops.commit_all(commit_message)

            # Step 11: Push snapshot branch
            git_ops.push(snapshot_branch)

            # Step 12a: Create release-review branch from snapshot
            git_ops.create_branch(release_review_branch, from_ref="HEAD")

            # Step 12b: Update README Release Information
            try:
                readme_changed = self._update_readme(
                    temp_dir, config, release_plan, api_versions, metadata
                )
                if readme_changed:
                    git_ops.commit_all(
                        f"Update README Release Information for {config.release_tag}"
                    )
            except ReadmeUpdateError as e:
                result.warnings.append(f"README update skipped: {e}")
            except Exception as e:
                result.warnings.append(f"README update failed: {e}")

            # Step 12c: Generate CHANGELOG draft
            try:
                repo_name = self.gh.repo.split("/")[-1]
                self._generate_changelog(
                    temp_dir, config, release_plan, api_versions, metadata, repo_name
                )
                git_ops.commit_all(
                    f"Add CHANGELOG draft for {config.release_tag}"
                )
            except Exception as e:
                result.warnings.append(f"CHANGELOG generation failed: {e}")

            # Step 13: Push release-review branch
            git_ops.push(release_review_branch)

            # Step 14: Create Release PR
            pr_info = self._create_release_pr(
                git_ops,
                config.release_tag,
                snapshot_id,
                api_versions,
                release_plan,
            )
            result.release_pr_number = pr_info.number
            result.release_pr_url = pr_info.url

            result.success = True

        except InvalidStateError as e:
            result.errors.append(str(e))
        except TransformationError as e:
            result.errors.append(str(e))
            cleanup_errors = self._cleanup_branches(snapshot_branch, release_review_branch)
            result.warnings.extend(cleanup_errors)
        except GitOperationsError as e:
            result.errors.append(f"Git operation failed: {e}")
            cleanup_errors = self._cleanup_branches(snapshot_branch, release_review_branch)
            result.warnings.extend(cleanup_errors)
        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            cleanup_errors = self._cleanup_branches(snapshot_branch, release_review_branch)
            result.warnings.extend(cleanup_errors)
        finally:
            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

        return result

    def validate_preconditions(self, release_tag: str) -> List[str]:
        """
        Validate all preconditions for snapshot creation.

        Checks:
        1. Current state is PLANNED
        2. No existing snapshot branch for this release

        Args:
            release_tag: Release tag to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check current state
        state = self.state_manager.derive_state(release_tag)

        if state == ReleaseState.PUBLISHED:
            errors.append(
                f"Release {release_tag} is already published. "
                "Cannot create snapshot for a published release."
            )
        elif state == ReleaseState.SNAPSHOT_ACTIVE:
            errors.append(
                f"A snapshot already exists for {release_tag}. "
                "Use /discard-snapshot first if you want to create a new one."
            )
        elif state == ReleaseState.DRAFT_READY:
            errors.append(
                f"A draft release already exists for {release_tag}. "
                "Use /delete-draft first if you want to start over."
            )
        elif state == ReleaseState.NOT_PLANNED:
            errors.append(
                f"Release {release_tag} is not planned. "
                "Update release-plan.yaml to set target_release_type to a valid value."
            )
        elif state != ReleaseState.PLANNED:
            errors.append(
                f"Unexpected state '{state.value}' for {release_tag}. "
                "Expected PLANNED state for snapshot creation."
            )

        return errors

    def generate_snapshot_id(self, release_tag: str, commit_sha: str) -> str:
        """
        Generate unique snapshot ID from release tag and commit SHA.

        Format: {release_tag}-{short_sha}
        Example: r4.1-abc1234

        Args:
            release_tag: Release tag (e.g., "r4.1")
            commit_sha: Full commit SHA

        Returns:
            Snapshot ID string
        """
        short_sha = commit_sha[: self.SHORT_SHA_LENGTH]
        return f"{release_tag}-{short_sha}"

    def _extract_api_titles(
        self,
        release_plan: Dict[str, Any],
        repo_path: str,
    ) -> Dict[str, str]:
        """
        Extract API titles from release plan or OpenAPI specs.

        Args:
            release_plan: Parsed release-plan.yaml
            repo_path: Path to cloned repository

        Returns:
            Dict mapping api_name to title
        """
        titles = {}

        for api in release_plan.get("apis", []):
            api_name = api.get("api_name")
            if not api_name:
                continue

            # Try to get title from release plan first
            title = api.get("api_title")

            # Fall back to reading from OpenAPI spec
            if not title:
                spec_path = os.path.join(
                    repo_path, "code", "API_definitions", f"{api_name}.yaml"
                )
                if os.path.exists(spec_path):
                    try:
                        with open(spec_path, "r") as f:
                            spec = yaml.safe_load(f)
                            title = spec.get("info", {}).get("title", api_name)
                    except (yaml.YAMLError, IOError):
                        title = api_name
                else:
                    title = api_name

            titles[api_name] = title

        return titles

    def _create_release_pr(
        self,
        git_ops: GitOperations,
        release_tag: str,
        snapshot_id: str,
        api_versions: Dict[str, str],
        release_plan: Dict[str, Any],
    ) -> PullRequestInfo:
        """
        Create the Release PR.

        Args:
            git_ops: GitOperations instance
            release_tag: Release tag
            snapshot_id: Snapshot ID
            api_versions: Calculated API versions
            release_plan: Release plan dict

        Returns:
            PullRequestInfo with PR number and URL
        """
        # Build PR title: "Release Review: RepoName rX.Y (short_type meta_release)"
        repo_name = self.gh.repo.split("/")[-1]
        release_type = release_plan.get("repository", {}).get("target_release_type", "")
        meta_release = release_plan.get("repository", {}).get("meta_release", "")
        short_type = config.SHORT_TYPE_MAP.get(release_type, release_type)
        type_suffix = f" ({short_type} {meta_release})" if meta_release else f" ({short_type})" if short_type else ""
        title = f"Release Review: {repo_name} {release_tag}{type_suffix}"

        # Build PR body from template
        apis = [
            {"api_name": name, "api_version": version}
            for name, version in api_versions.items()
        ]
        body = render_template("release_review_pr", {
            "release_tag": release_tag,
            "snapshot_id": snapshot_id,
            "apis": apis,
        })

        return git_ops.create_pr(
            title=title,
            body=body,
            head=f"{self.RELEASE_REVIEW_BRANCH_PREFIX}/{snapshot_id}",
            base=f"{self.SNAPSHOT_BRANCH_PREFIX}/{snapshot_id}",
        )

    def _get_latest_public_release(self) -> Optional[str]:
        """Query GitHub releases for the latest non-prerelease, non-draft release tag."""
        releases = self.gh.get_releases(include_drafts=False)
        for release in releases:
            if not release.prerelease:
                return release.tag_name
        return None

    def _get_previous_release(self) -> Optional[str]:
        """Query GitHub releases for the most recent release tag (any type)."""
        releases = self.gh.get_releases(include_drafts=False)
        if releases:
            return releases[0].tag_name
        return None

    def _read_release_metadata(self, tag: str) -> Optional[Dict[str, Any]]:
        """Read release-metadata.yaml from a release tag.

        Tries two sources in order:
        1. Repository tree at tag (newer releases with committed file)
        2. Release asset (legacy releases where metadata was uploaded)

        Returns:
            Parsed metadata dict, or None if not found/parseable.
        """
        # Try 1: repository tree (newer releases)
        content = self.gh.get_file_content("release-metadata.yaml", ref=tag)
        # Try 2: release asset (legacy releases)
        if not content:
            content = self.gh.download_release_asset(tag, "release-metadata.yaml")
        if not content:
            return None
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError:
            return None

    def _get_candidate_changes(
        self, release_tag: str, previous_release: Optional[str]
    ) -> Optional[str]:
        """Use GitHub's generate-notes API to get PR-level change descriptions.

        Falls back to None on API errors (non-fatal).
        """
        return self.gh.generate_release_notes(release_tag, previous_release)

    def _update_readme(
        self,
        temp_dir: str,
        config: SnapshotConfig,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        metadata: Dict[str, Any],
    ) -> bool:
        """Update README Release Information section on release-review branch.

        Determines release state by checking existing GitHub releases.
        Formats API links and calls ReadmeUpdater.

        Returns:
            True if README was modified, False otherwise.

        Raises:
            ReadmeUpdateError: If README is missing delimiters.
        """
        readme_path = os.path.join(temp_dir, "README.md")
        if not os.path.exists(readme_path):
            return False

        # Determine release state from metadata (release-metadata.yaml values)
        release_type = metadata.get("repository", {}).get("release_type", "")
        existing_public = self._get_latest_public_release()
        is_prerelease = release_type in ("pre-release-alpha", "pre-release-rc")

        if is_prerelease and not existing_public:
            release_state = "prerelease_only"
        elif is_prerelease and existing_public:
            release_state = "public_with_prerelease"
        elif not is_prerelease:
            release_state = "public_release"
        else:
            release_state = "no_release"

        repo_name = self.gh.repo.split("/")[-1]
        org = self.gh.repo.split("/")[0]

        # Build API info for link formatting
        apis_list = [
            {"file_name": api_name, "version": version}
            for api_name, version in api_versions.items()
        ]

        # Build data dict
        data = {
            "repo_name": repo_name,
        }

        if release_state in ("public_release", "public_with_prerelease"):
            if is_prerelease:
                # Pre-release: public section shows existing public release info
                public_tag = existing_public
                public_metadata = self._read_release_metadata(public_tag)
                public_apis = []
                public_meta_release = ""
                if public_metadata:
                    for api in public_metadata.get("apis", []):
                        public_apis.append({
                            "file_name": api.get("api_file_name", api.get("api_name", "")),
                            "version": api.get("api_version", ""),
                        })
                    public_meta_release = public_metadata.get(
                        "repository", {}
                    ).get("meta_release", "")
            else:
                # Public release: show current snapshot info
                public_tag = config.release_tag
                public_apis = apis_list
                public_meta_release = release_plan.get(
                    "repository", {}
                ).get("meta_release", "")

            data["latest_public_release"] = public_tag
            data["github_url"] = f"https://github.com/{org}/{repo_name}/releases/tag/{public_tag}"
            data["meta_release"] = public_meta_release
            data["formatted_apis"] = ReadmeUpdater.format_api_links(
                public_apis, repo_name, public_tag, org
            )

        if release_state in ("prerelease_only", "public_with_prerelease"):
            data["newest_prerelease"] = config.release_tag
            data["prerelease_github_url"] = (
                f"https://github.com/{org}/{repo_name}/releases/tag/{config.release_tag}"
            )
            data["prerelease_type"] = (
                "release candidate" if release_type == "pre-release-rc" else "pre-release"
            )
            data["formatted_prerelease_apis"] = ReadmeUpdater.format_api_links(
                apis_list, repo_name, config.release_tag, org
            )

        updater = ReadmeUpdater()
        return updater.update_release_info(readme_path, release_state, data)

    def _generate_changelog(
        self,
        temp_dir: str,
        config: SnapshotConfig,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        metadata: Dict[str, Any],
        repo_name: str,
    ) -> str:
        """Generate CHANGELOG draft on release-review branch.

        Determines previous release, fetches candidate changes from GitHub's
        generate-notes API, generates draft, writes to CHANGELOG directory.

        Returns:
            Relative path to the written CHANGELOG file.
        """
        previous_release = self._get_previous_release()
        candidate_changes = self._get_candidate_changes(
            config.release_tag, previous_release
        )

        generator = ChangelogGenerator()
        content = generator.generate_draft(
            release_tag=config.release_tag,
            metadata=metadata,
            repo_name=repo_name,
            candidate_changes=candidate_changes,
        )
        return generator.write_changelog(temp_dir, content, config.release_tag, repo_name)

    def _cleanup_branches(
        self,
        snapshot_branch: Optional[str],
        release_review_branch: Optional[str],
    ) -> List[str]:
        """
        Clean up branches on failure.

        Args:
            snapshot_branch: Snapshot branch name to delete
            release_review_branch: Release review branch name to delete

        Returns:
            List of cleanup error messages
        """
        cleanup_errors = []

        # We need to create a temporary GitOperations just for cleanup
        # Since we might not have a cloned repo anymore
        temp_dir = tempfile.mkdtemp(prefix="camara-cleanup-")
        try:
            git_ops = GitOperations(
                repo=self.gh.repo,
                work_dir=temp_dir,
                token=self.gh.token,
            )
            # Clone minimally just to have access to remote
            try:
                git_ops.clone()

                if release_review_branch:
                    try:
                        git_ops.delete_remote_branch(release_review_branch)
                    except GitOperationsError as e:
                        cleanup_errors.append(
                            f"Failed to delete {release_review_branch}: {e}"
                        )

                if snapshot_branch:
                    try:
                        git_ops.delete_remote_branch(snapshot_branch)
                    except GitOperationsError as e:
                        cleanup_errors.append(
                            f"Failed to delete {snapshot_branch}: {e}"
                        )
            except GitOperationsError:
                # If clone fails, we can't cleanup via git
                pass

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return cleanup_errors
