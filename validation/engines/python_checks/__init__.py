# Python check registry.
# Each check is a CheckDescriptor with name, scope, and function.
# The CHECKS list defines execution order.

from __future__ import annotations

from ._types import CheckDescriptor, CheckScope

from .changelog_checks import check_changelog_format
from .filename_checks import check_filename_kebab_case, check_filename_matches_api_name
from .metadata_checks import check_commonalities_version
from .readme_checks import check_readme_placeholder_removal
from .release_plan_checks import check_release_plan_semantics
from .release_review_checks import check_release_review_file_restriction
from .test_checks import (
    check_test_directory_exists,
    check_test_file_version,
    check_test_files_exist,
)
from .version_checks import (
    check_info_version_format,
    check_server_url_api_name,
    check_server_url_version,
)

# Ordered registry.  Execution order matches this list.
# Adding a new check: import the function and append a CheckDescriptor.
CHECKS: list[CheckDescriptor] = [
    # --- Per-API checks (run once per API in context.apis) ---
    CheckDescriptor("check-filename-kebab-case", CheckScope.API, check_filename_kebab_case),
    CheckDescriptor("check-filename-matches-api-name", CheckScope.API, check_filename_matches_api_name),
    CheckDescriptor("check-info-version-format", CheckScope.API, check_info_version_format),
    CheckDescriptor("check-server-url-version", CheckScope.API, check_server_url_version),
    CheckDescriptor("check-server-url-api-name", CheckScope.API, check_server_url_api_name),
    CheckDescriptor("check-test-files-exist", CheckScope.API, check_test_files_exist),
    CheckDescriptor("check-test-file-version", CheckScope.API, check_test_file_version),
    # --- Repo-level checks (run once) ---
    CheckDescriptor("check-test-directory-exists", CheckScope.REPO, check_test_directory_exists),
    CheckDescriptor("check-release-plan-semantics", CheckScope.REPO, check_release_plan_semantics),
    CheckDescriptor("check-changelog-format", CheckScope.REPO, check_changelog_format),
    CheckDescriptor("check-commonalities-version", CheckScope.API, check_commonalities_version),
    CheckDescriptor("check-readme-placeholder-removal", CheckScope.REPO, check_readme_placeholder_removal),
    CheckDescriptor("check-release-review-file-restriction", CheckScope.REPO, check_release_review_file_restriction),
]

__all__ = ["CHECKS", "CheckDescriptor", "CheckScope"]
