# Python check registry.
# Each check is a CheckDescriptor with name, scope, and function.
# The CHECKS list defines execution order.

from __future__ import annotations

from ._types import CheckDescriptor, CheckScope

from .bundling_checks import check_component_renaming_conflict
from .error_code_checks import check_conflict_deprecated, check_contextcode_format
from .externaldocs_checks import check_externaldocs
from .filename_checks import check_filename_kebab_case, check_filename_matches_api_name
from .info_description_checks import check_info_description_templates
from .metadata_checks import check_commonalities_version
from .readme_checks import (
    check_api_readiness_checklist_removal,
    check_readme_placeholder_removal,
)
from .common_cache_checks import check_common_cache_sync
from .release_plan_checks import (
    check_declared_dependency_tags_exist,
    check_orphan_api_definitions,
    check_release_plan_active_release_state,
    check_release_plan_api_names_unique,
    check_release_plan_exclusivity,
    check_release_plan_published_history,
    check_release_plan_semantics,
    check_release_plan_terminal_api_status,
)
from .release_review_checks import check_release_review_file_restriction
from .subscription_checks import (
    check_cloudevent_via_ref,
    check_event_type_format,
    check_sinkcredential_secrets_writeonly,
    check_subscription_filename,
)
from .test_checks import (
    check_test_directory_exists,
    check_test_file_version,
    check_test_files_exist,
)
from .version_checks import (
    check_feature_file_url_version,
    check_info_version_format,
    check_server_url_api_name,
    check_server_url_version,
)
from .yaml_parser_conformance_checks import check_yaml_parser_conformance

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
    CheckDescriptor("check-feature-file-url-version", CheckScope.API, check_feature_file_url_version),
    CheckDescriptor("check-commonalities-version", CheckScope.API, check_commonalities_version),
    CheckDescriptor("check-subscription-filename", CheckScope.API, check_subscription_filename),
    CheckDescriptor("check-event-type-format", CheckScope.API, check_event_type_format),
    CheckDescriptor("check-sinkcredential-secrets-writeonly", CheckScope.API, check_sinkcredential_secrets_writeonly),
    CheckDescriptor("check-cloudevent-via-ref", CheckScope.API, check_cloudevent_via_ref),
    CheckDescriptor("check-conflict-deprecated", CheckScope.API, check_conflict_deprecated),
    CheckDescriptor("check-contextcode-format", CheckScope.API, check_contextcode_format),
    CheckDescriptor("check-yaml-parser-conformance", CheckScope.API, check_yaml_parser_conformance),
    CheckDescriptor(
        "check-info-description-mandatory-missing",
        CheckScope.API,
        check_info_description_templates,
    ),
    CheckDescriptor(
        "check-component-renaming-conflict",
        CheckScope.API,
        check_component_renaming_conflict,
    ),
    CheckDescriptor("check-externaldocs-repository", CheckScope.API, check_externaldocs),
    # --- Repo-level checks (run once) ---
    CheckDescriptor("check-test-directory-exists", CheckScope.REPO, check_test_directory_exists),
    CheckDescriptor("check-release-plan-semantics", CheckScope.REPO, check_release_plan_semantics),
    CheckDescriptor("check-release-plan-api-names-unique", CheckScope.REPO, check_release_plan_api_names_unique),
    CheckDescriptor("check-release-plan-published-history", CheckScope.REPO, check_release_plan_published_history),
    CheckDescriptor("check-release-plan-terminal-api-status", CheckScope.REPO, check_release_plan_terminal_api_status),
    CheckDescriptor("check-readme-placeholder-removal", CheckScope.REPO, check_readme_placeholder_removal),
    CheckDescriptor("check-api-readiness-checklist-removal", CheckScope.REPO, check_api_readiness_checklist_removal),
    CheckDescriptor("check-release-review-file-restriction", CheckScope.REPO, check_release_review_file_restriction),
    CheckDescriptor("check-orphan-api-definitions", CheckScope.REPO, check_orphan_api_definitions),
    CheckDescriptor("check-common-cache-sync", CheckScope.REPO, check_common_cache_sync),
    CheckDescriptor("check-release-plan-exclusivity", CheckScope.REPO, check_release_plan_exclusivity),
    CheckDescriptor("check-release-plan-active-release-state", CheckScope.REPO, check_release_plan_active_release_state),
    CheckDescriptor("check-declared-dependency-tags-exist", CheckScope.REPO, check_declared_dependency_tags_exist),
]

__all__ = ["CHECKS", "CheckDescriptor", "CheckScope"]
