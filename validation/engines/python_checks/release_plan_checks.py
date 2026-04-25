"""Release-plan.yaml semantic checks.

Validates semantic rules beyond JSON schema: track/meta-release consistency,
release-type/API-status alignment, and API file existence.

Logic ported from ``validation/scripts/validate-release-plan.py`` as pure
functions producing findings (not print/exit).  The original script is NOT
imported or modified.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from validation.context import ValidationContext
from validation.context.release_plan_parser import is_valid_release_tag

from ._types import load_yaml_safe, make_finding

# Allowed meta-release values.  Update as new meta-releases are added.
ALLOWED_META_RELEASES = ["Fall25", "Spring26", "Fall26", "Sync26", "Signal27"]

_RELEASE_PLAN_PATH = "release-plan.yaml"


# ---------------------------------------------------------------------------
# Semantic check functions (ported from validate-release-plan.py)
# ---------------------------------------------------------------------------


def _check_track_consistency(
    release_plan: dict,
) -> List[dict]:
    """Check release_track and meta_release are consistent."""
    repo = release_plan.get("repository", {})
    release_track = repo.get("release_track")
    meta_release = repo.get("meta_release")

    findings: List[dict] = []

    if release_track == "meta-release" and not meta_release:
        findings.append(
            make_finding(
                engine_rule="check-release-plan-semantics",
                level="error",
                message=(
                    "release_track is 'meta-release' but meta_release "
                    "field is missing"
                ),
                path=_RELEASE_PLAN_PATH,
                line=1,
            )
        )
    elif release_track == "independent" and meta_release:
        findings.append(
            make_finding(
                engine_rule="check-release-plan-semantics",
                level="warn",
                message=(
                    f"release_track is '{release_track}' but meta_release "
                    f"field is present"
                ),
                path=_RELEASE_PLAN_PATH,
                line=1,
            )
        )

    if meta_release and meta_release not in ALLOWED_META_RELEASES:
        findings.append(
            make_finding(
                engine_rule="check-release-plan-semantics",
                level="error",
                message=(
                    f"meta_release '{meta_release}' is not valid. "
                    f"Allowed values: {', '.join(ALLOWED_META_RELEASES)}"
                ),
                path=_RELEASE_PLAN_PATH,
                line=1,
            )
        )

    return findings


def _check_release_type_consistency(
    release_plan: dict,
) -> List[dict]:
    """Check API statuses align with target_release_type.

    Rules:
    - none: no constraints
    - pre-release-alpha: all APIs >= alpha (no draft)
    - pre-release-rc: all APIs >= rc (no draft or alpha)
    - public-release: all APIs must be public
    - maintenance-release: all APIs must be public
    """
    repo = release_plan.get("repository", {})
    apis = release_plan.get("apis", [])
    release_type = repo.get("target_release_type")

    if not release_type or release_type == "none":
        return []

    findings: List[dict] = []

    if release_type == "pre-release-alpha":
        draft_apis = [
            api.get("api_name", "?")
            for api in apis
            if api.get("target_api_status") == "draft"
        ]
        if draft_apis:
            findings.append(
                make_finding(
                    engine_rule="check-release-plan-semantics",
                    level="error",
                    message=(
                        f"target_release_type is 'pre-release-alpha' but "
                        f"these APIs are 'draft': {', '.join(draft_apis)}"
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )

    elif release_type == "pre-release-rc":
        invalid_apis = [
            api.get("api_name", "?")
            for api in apis
            if api.get("target_api_status") in ("draft", "alpha")
        ]
        if invalid_apis:
            findings.append(
                make_finding(
                    engine_rule="check-release-plan-semantics",
                    level="error",
                    message=(
                        f"target_release_type is 'pre-release-rc' but "
                        f"these APIs are not rc/public: "
                        f"{', '.join(invalid_apis)}"
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )

    elif release_type in ("public-release", "maintenance-release"):
        non_public = [
            api.get("api_name", "?")
            for api in apis
            if api.get("target_api_status") != "public"
        ]
        if non_public:
            findings.append(
                make_finding(
                    engine_rule="check-release-plan-semantics",
                    level="error",
                    message=(
                        f"target_release_type is '{release_type}' but "
                        f"these APIs are not 'public': "
                        f"{', '.join(non_public)}"
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )

    return findings


def _check_file_existence(
    release_plan: dict, repo_path: Path
) -> List[dict]:
    """Check API definition files exist.

    Two-tier severity:
    - alpha/rc/public: missing file is ERROR
    - draft: missing file with orphan files is WARNING
    """
    apis = release_plan.get("apis", [])
    api_dir = repo_path / "code" / "API_definitions"

    # Collect declared API names.
    all_api_names = {
        api.get("api_name")
        for api in apis
        if api.get("api_name")
    }

    # Discover existing files.
    existing_stems: set[str] = set()
    if api_dir.is_dir():
        existing_stems = {
            f.stem for f in api_dir.iterdir()
            if f.suffix == ".yaml" and f.is_file()
        }

    orphan_files = existing_stems - all_api_names

    findings: List[dict] = []

    for api in apis:
        api_name = api.get("api_name")
        status = api.get("target_api_status")

        if not api_name:
            continue

        api_file = api_dir / f"{api_name}.yaml"
        file_exists = api_file.exists()

        if status in ("alpha", "rc", "public"):
            if not file_exists:
                findings.append(
                    make_finding(
                        engine_rule="check-release-plan-semantics",
                        level="error",
                        message=(
                            f"API definition file not found for '{api_name}' "
                            f"(status: {status}). Expected: "
                            f"code/API_definitions/{api_name}.yaml"
                        ),
                        path=f"code/API_definitions/{api_name}.yaml",
                        line=1,
                        api_name=api_name,
                    )
                )
        elif status == "draft":
            if not file_exists and orphan_files:
                orphan_list = ", ".join(sorted(orphan_files))
                findings.append(
                    make_finding(
                        engine_rule="check-release-plan-semantics",
                        level="warn",
                        message=(
                            f"No API definition file found for draft API "
                            f"'{api_name}'. Unmatched files in "
                            f"code/API_definitions/: {orphan_list}. "
                            f"Check for possible naming mismatch"
                        ),
                        path=_RELEASE_PLAN_PATH,
                        line=1,
                        api_name=api_name,
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Top-level check function
# ---------------------------------------------------------------------------


def check_release_plan_semantics(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Run all release-plan.yaml semantic checks.

    Repo-level check.  Reads release-plan.yaml from the repository root
    and performs track consistency, release-type consistency, and file
    existence checks.
    """
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)

    if release_plan is None:
        # No release-plan.yaml — nothing to validate.
        return []

    findings: List[dict] = []
    findings.extend(_check_track_consistency(release_plan))
    findings.extend(_check_release_type_consistency(release_plan))
    findings.extend(_check_file_existence(release_plan, repo_path))

    return findings


# ---------------------------------------------------------------------------
# P-019 (NEW-003): Orphan API definitions
# ---------------------------------------------------------------------------


def check_orphan_api_definitions(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Detect YAML files in API_definitions not listed in release-plan.yaml.

    Repo-level check.  Compares YAML file stems in
    ``code/API_definitions/`` against API names declared in
    ``release-plan.yaml``.  Files not in the release plan are flagged
    as potential orphans or naming mismatches.
    """
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    api_dir = repo_path / "code" / "API_definitions"
    if not api_dir.is_dir():
        return []

    # Declared API names from release plan
    apis = release_plan.get("apis", [])
    declared_names = {
        api.get("api_name")
        for api in apis
        if isinstance(api, dict) and api.get("api_name")
    }

    # YAML files on disk
    existing_stems = {
        f.stem for f in api_dir.iterdir()
        if f.suffix == ".yaml" and f.is_file()
    }

    orphans = sorted(existing_stems - declared_names)

    return [
        make_finding(
            engine_rule="check-orphan-api-definitions",
            level="warn",
            message=(
                f"API definition file '{name}.yaml' is not listed in "
                f"release-plan.yaml — possible orphan or naming mismatch"
            ),
            path=f"code/API_definitions/{name}.yaml",
            line=1,
        )
        for name in orphans
    ]


# ---------------------------------------------------------------------------
# P-022: check-release-plan-exclusivity
# ---------------------------------------------------------------------------


def check_release_plan_exclusivity(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Flag non-release-plan files co-changed with release-plan.yaml.

    Repo-level check.  Reads ``context.non_release_plan_files_changed``
    (populated by the workflow layer when release-plan.yaml is in the
    diff).  Emits one error finding listing the co-changed files so the
    codeowner can split the PR.
    """
    other_files = context.non_release_plan_files_changed
    if not other_files:
        return []

    # Cap the listed files to keep the message readable; full list is
    # still visible in the PR diff.
    preview_limit = 10
    file_list = list(other_files)
    if len(file_list) > preview_limit:
        preview = ", ".join(file_list[:preview_limit])
        suffix = f", and {len(file_list) - preview_limit} more"
    else:
        preview = ", ".join(file_list)
        suffix = ""

    return [
        make_finding(
            engine_rule="check-release-plan-exclusivity",
            level="error",
            message=(
                f"release-plan.yaml was changed alongside "
                f"{len(file_list)} other file(s): {preview}{suffix}. "
                f"release-plan.yaml changes should be submitted in a "
                f"dedicated PR so that any new validation findings remain "
                f"clearly attributable to the release-plan change."
            ),
            path=_RELEASE_PLAN_PATH,
            line=1,
        )
    ]


# ---------------------------------------------------------------------------
# P-023: check-declared-dependency-tags-exist
# ---------------------------------------------------------------------------

# Dependency spec: (YAML field name, display name, source repo,
# context-flag attribute, context-tag-exists attribute).  YAML field
# names match release-plan-schema.yaml; display names mirror the short
# form used in user-facing messages.
_DEPENDENCY_SPEC = [
    (
        "commonalities_release",
        "commonalities_release",
        "camaraproject/Commonalities",
        "commonalities_release_changed",
        "commonalities_tag_exists",
    ),
    (
        "identity_consent_management_release",
        "icm_release",
        "camaraproject/IdentityAndConsentManagement",
        "icm_release_changed",
        "icm_tag_exists",
    ),
]


def check_declared_dependency_tags_exist(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify that declared dependency tags exist in their source repos.

    Repo-level check.  For each dependency (``commonalities_release``,
    ``identity_consent_management_release``):

    - If the declaration did not change in this PR's diff, skip (the
      existing state is not this PR's responsibility).
    - If the declaration changed and the tag was confirmed absent by the
      workflow layer (``<dep>_tag_exists == False``), emit an error.
    - If the declaration changed and the workflow layer could not verify
      the tag (``<dep>_tag_exists is None``), emit a warn finding so the
      codeowner is aware the check was skipped.
    """
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    dependencies = release_plan.get("dependencies") or {}

    findings: List[dict] = []

    for (
        yaml_field,
        display_name,
        source_repo,
        changed_attr,
        exists_attr,
    ) in _DEPENDENCY_SPEC:
        if not getattr(context, changed_attr, False):
            # Declaration unchanged in this PR — skip (fail open).
            continue

        declared_tag = dependencies.get(yaml_field)
        if not declared_tag:
            # Declaration advanced to null/removed — not P-023's concern
            # (schema or P-009 semantics handle this).
            continue

        if not is_valid_release_tag(str(declared_tag)):
            # Format-invalid tags (e.g. "r0.0", "r4.x") would otherwise
            # surface as the misleading "tag does not exist" message
            # below. Emit a dedicated format error and skip the
            # existence lookup.
            findings.append(
                make_finding(
                    engine_rule="check-declared-dependency-tags-exist",
                    level="error",
                    message=(
                        f"Declared {display_name} tag '{declared_tag}' "
                        f"is not a valid CAMARA release tag format. "
                        f"Expected r<major>.<minor> with positive "
                        f"integer components (e.g. r4.2)."
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )
            continue

        exists = getattr(context, exists_attr, None)

        if exists is False:
            findings.append(
                make_finding(
                    engine_rule="check-declared-dependency-tags-exist",
                    level="error",
                    message=(
                        f"Declared {display_name} tag '{declared_tag}' "
                        f"does not exist in {source_repo}. Verify the "
                        f"tag name or publish it before advancing the "
                        f"dependency."
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )
        elif exists is None:
            findings.append(
                make_finding(
                    engine_rule="check-declared-dependency-tags-exist",
                    level="warn",
                    message=(
                        f"Could not verify that {display_name} tag "
                        f"'{declared_tag}' exists in {source_repo} "
                        f"(GitHub API lookup unavailable). Re-run the "
                        f"workflow to retry, or confirm the tag manually."
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                )
            )

    return findings
