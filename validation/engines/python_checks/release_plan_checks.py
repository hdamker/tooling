"""Release-plan.yaml semantic checks.

Validates semantic rules beyond JSON schema: track/meta-release consistency,
release-type/API-status alignment, and API file existence.

Logic ported from ``validation/scripts/validate-release-plan.py`` as pure
functions producing findings (not print/exit).  The original script is NOT
imported or modified.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import List, Optional

from release_automation.scripts import config
from validation.context import ValidationContext
from validation.context.release_history import (
    TERMINAL_RELEASE_TYPES,
    PublishedRelease,
    normalize_api_version_base,
    parse_release_tag,
)
from validation.context.release_plan_parser import is_valid_release_tag

from ._types import load_yaml_safe, make_finding

# Allowed meta-release values.  Update as new meta-releases are added.
ALLOWED_META_RELEASES = ["Fall25", "Spring26", "Fall26", "Sync26", "Signal27"]

_RELEASE_PLAN_PATH = "release-plan.yaml"

_ACTIVE_RELEASE_STATES = frozenset(
    {
        config.STATE_SNAPSHOT_ACTIVE,
        config.STATE_DRAFT_READY,
    }
)


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
# P-034: check-release-plan-api-names-unique
# ---------------------------------------------------------------------------


def check_release_plan_api_names_unique(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Detect duplicate ``apis[].api_name`` entries in release-plan.yaml."""
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    apis = release_plan.get("apis", [])
    if not isinstance(apis, list):
        return []

    names = [
        api.get("api_name")
        for api in apis
        if isinstance(api, dict) and isinstance(api.get("api_name"), str)
    ]
    duplicates = sorted(
        (name, count) for name, count in Counter(names).items() if count > 1
    )

    findings: List[dict] = []
    for api_name, count in duplicates:
        message = (
            f"release-plan.yaml contains {count} entries for api_name "
            f"'{api_name}'. Keep exactly one entry for each api_name."
        )
        if context.release_plan_changed is False:
            message = (
                "Pre-existing release-plan condition: "
                f"{message} Submit the fix in a dedicated release-plan PR."
            )
        findings.append(
            make_finding(
                engine_rule="check-release-plan-api-names-unique",
                level="error",
                message=message,
                path=_RELEASE_PLAN_PATH,
                line=1,
                api_name=api_name,
            )
        )

    return findings


# ---------------------------------------------------------------------------
# P-035: check-release-plan-published-history
# ---------------------------------------------------------------------------


def _planned_api_set(release_plan: dict) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted(_planned_api_entries(release_plan)))


def _published_api_set(release: PublishedRelease) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                api.api_name,
                normalize_api_version_base(api.api_version),
                api.status,
            )
            for api in release.apis
        )
    )


def _plan_matches_published_release(
    release_plan: dict, release: PublishedRelease
) -> bool:
    repo = release_plan.get("repository", {})
    release_type = repo.get("target_release_type")
    if release_type != release.release_type:
        return False
    return _planned_api_set(release_plan) == _published_api_set(release)


def _plan_api_entries_match_published_release(
    release_plan: dict, release: PublishedRelease
) -> bool:
    return _planned_api_set(release_plan) == _published_api_set(release)


def _inactive_plan_matches_published_release(
    release_plan: dict, release: PublishedRelease
) -> bool:
    repo = release_plan.get("repository", {})
    if repo.get("target_release_type") != "none":
        return False
    return _planned_api_set(release_plan) == _published_api_set(release)


def _prefix_pre_existing_release_plan_condition(
    context: ValidationContext, message: str
) -> str:
    if context.release_plan_changed is False:
        return (
            "Pre-existing release-plan condition: "
            f"{message} Submit the fix in a dedicated release-plan PR."
        )
    return message


def _normalized_optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized_release_tag(value: object) -> str:
    text = _normalized_optional_text(value)
    return text.split(maxsplit=1)[0] if text else ""


def _plan_dependency_tags(release_plan: dict) -> tuple[str, str]:
    deps = release_plan.get("dependencies", {})
    if not isinstance(deps, dict):
        deps = {}
    return (
        _normalized_release_tag(deps.get("commonalities_release")),
        _normalized_release_tag(deps.get("identity_consent_management_release")),
    )


def _published_dependency_tags(release: PublishedRelease) -> tuple[str, str]:
    return (
        _normalized_release_tag(release.commonalities_release),
        _normalized_release_tag(release.icm_release),
    )


def _base_attribution_available(context: ValidationContext) -> bool:
    return context.base_release_track is not None


def _release_plan_attribution_changed(
    release_plan: dict, context: ValidationContext
) -> bool:
    repo = release_plan.get("repository", {})
    if not isinstance(repo, dict):
        repo = {}
    return (
        _normalized_optional_text(context.base_release_track)
        != _normalized_optional_text(repo.get("release_track"))
        or _normalized_optional_text(context.base_meta_release)
        != _normalized_optional_text(repo.get("meta_release"))
    )


def _release_history_finding(
    context: ValidationContext, message: str, suggestion: str
) -> dict:
    return make_finding(
        engine_rule="check-release-plan-published-history",
        level="error",
        message=_prefix_pre_existing_release_plan_condition(context, message),
        path=_RELEASE_PLAN_PATH,
        line=1,
        suggestion=suggestion,
    )


def _planned_api_entries(release_plan: dict) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for api in release_plan.get("apis", []):
        if not isinstance(api, dict):
            continue
        api_name = api.get("api_name")
        api_version = api.get("target_api_version")
        api_status = api.get("target_api_status")
        if (
            isinstance(api_name, str)
            and isinstance(api_version, str)
            and isinstance(api_status, str)
        ):
            entries.append((api_name, api_version, api_status))
    return entries


def _plan_declares_new_api_content(
    release_plan: dict, context: ValidationContext
) -> Optional[bool]:
    history = context.release_history
    if history is None:
        return None

    for api_name, api_version, api_status in _planned_api_entries(release_plan):
        if (api_version, api_status) not in history.terminal_api_version_statuses(
            api_name
        ):
            if history.may_have_missing_terminal_metadata():
                return None
            return True
    return False


def check_release_plan_published_history(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate repository-level release-plan consistency against history."""
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    history = context.release_history
    if history is None:
        return []

    repo = release_plan.get("repository", {})
    release_type = repo.get("target_release_type", "none")
    target_tag = repo.get("target_release_tag")

    # A parked plan (target_release_type: none) only carries forward the last
    # release.  On a PR that does not touch release-plan.yaml there is no
    # actionable release-planning finding, so stay silent rather than block
    # unrelated work.  When the plan IS edited under none, the consistency checks
    # below still apply: the plan must remain in a shape where flipping the
    # release type makes it valid.
    if release_type == "none" and context.release_plan_changed is not True:
        return []

    if release_type != "none" and not target_tag:
        return [
            _release_history_finding(
                context,
                f"target_release_tag is required when target_release_type is "
                f"'{release_type}'.",
                "Set target_release_tag for the release being prepared, or set "
                "target_release_type: none when no release is being prepared.",
            )
        ]

    if not target_tag:
        return []

    published_target = (
        history.release_by_tag(target_tag) if history.release_tags_available() else None
    )
    if (
        published_target is not None
        and published_target.metadata_available
        and _plan_api_entries_match_published_release(release_plan, published_target)
    ):
        if _plan_dependency_tags(release_plan) != _published_dependency_tags(
            published_target
        ):
            return [
                _release_history_finding(
                    context,
                    f"target_release_tag '{target_tag}' is already published, "
                    "so dependencies must not be changed for this release.",
                    "Restore the dependency tags published with this release, "
                    "or start a new release cycle with an unpublished "
                    "target_release_tag.",
                )
            ]
        if (
            context.release_plan_changed is True
            and _base_attribution_available(context)
            and _release_plan_attribution_changed(release_plan, context)
        ):
            return [
                _release_history_finding(
                    context,
                    f"target_release_tag '{target_tag}' is already published, "
                    "so release_track and meta_release must not be changed for "
                    "this release.",
                    "Start a new release cycle in this repository. The "
                    "inclusion of an already-published release, if approved, "
                    "is handled by Release Management outside this "
                    "repository's release-plan.",
                )
            ]

    # A maintenance-line plan (its cycle already has a terminal release, M1)
    # is compared with that cycle's tags only; later cycles live on main or
    # their own line.  Other plans keep the repository-wide latest tag.
    parsed_target = parse_release_tag(target_tag)
    line_cycle = (
        parsed_target.major
        if parsed_target is not None
        and history.is_maintenance_line(parsed_target.major)
        else None
    )
    latest_release = (
        history.latest_release(cycle=line_cycle)
        if history.release_tags_available()
        else None
    )
    latest_tag = latest_release.tag if latest_release is not None else None

    if (
        latest_release is not None
        and latest_release.metadata_available
        and target_tag == latest_release.tag
        and _plan_matches_published_release(release_plan, latest_release)
    ):
        return []

    if (
        published_target is not None
        and published_target.metadata_available
        and _inactive_plan_matches_published_release(release_plan, published_target)
        and (line_cycle is None or target_tag == latest_tag)
    ):
        return []

    if (
        published_target is not None
        and published_target.metadata_available
        and not _plan_matches_published_release(release_plan, published_target)
        and not _inactive_plan_matches_published_release(
            release_plan, published_target
        )
    ):
        return [
            _release_history_finding(
                context,
                f"target_release_tag '{target_tag}' is already published, but "
                "release-plan.yaml no longer matches that published release. "
                "Bump target_release_tag or restore the published API entries.",
                "Restore the release plan to match the published tag, or choose "
                "the next unpublished target_release_tag for a new release.",
            )
        ]

    parsed_latest = parse_release_tag(latest_tag) if latest_tag else None
    if (
        parsed_target is not None
        and parsed_latest is not None
        and parsed_target < parsed_latest
    ):
        return [
            _release_history_finding(
                context,
                f"target_release_tag '{target_tag}' is lower than latest "
                f"published release tag '{latest_tag}'.",
                "Use a target_release_tag greater than the latest published "
                "release tag for this release line.",
            )
        ]

    if (
        parsed_target is not None
        and parsed_target.minor == 1
        and parsed_target.major > 1
        and history.release_tags_available()
        and not history.has_cycle(parsed_target.major - 1)
    ):
        previous_cycle = f"r{parsed_target.major - 1}.y"
        return [
            _release_history_finding(
                context,
                f"target_release_tag '{target_tag}' opens release cycle "
                f"r{parsed_target.major} without any published "
                f"{previous_cycle} release.",
                "Publish or target the previous release cycle before opening "
                "the next cycle.",
            )
        ]

    target_metadata_missing = (
        published_target is not None and not published_target.metadata_available
    )
    if release_type != "none" and not target_metadata_missing:
        new_api_content = _plan_declares_new_api_content(release_plan, context)
        if new_api_content is False:
            return [
                _release_history_finding(
                    context,
                    f"target_release_type '{release_type}' cannot start a new "
                    "release because every planned API entry was already "
                    "published with the same version and status in a public or "
                    "maintenance release.",
                    "Change at least one API entry in a valid way before "
                    "preparing a new release, or set target_release_type: none "
                    "if no API publication is intended.",
                )
            ]

    return []


# ---------------------------------------------------------------------------
# P-036: check-release-plan-terminal-api-status
# ---------------------------------------------------------------------------


def _terminal_api_status_findings(
    release_plan: dict, context: ValidationContext
) -> list[dict]:
    history = context.release_history
    if history is None:
        return []

    findings: list[dict] = []
    for api_name, api_version, api_status in _planned_api_entries(release_plan):
        terminal_statuses = {
            status
            for version, status in history.terminal_api_version_statuses(api_name)
            if version == api_version
        }
        if terminal_statuses and api_status not in terminal_statuses:
            expected = " or ".join(f"'{status}'" for status in sorted(terminal_statuses))
            findings.append(
                make_finding(
                    engine_rule="check-release-plan-terminal-api-status",
                    level="error",
                    message=_prefix_pre_existing_release_plan_condition(
                        context,
                        f"API '{api_name}' was already published as version "
                        f"{api_version}; target_api_status must remain "
                        f"{expected} for that version.",
                    ),
                    path=_RELEASE_PLAN_PATH,
                    line=1,
                    api_name=api_name,
                    suggestion=(
                        "Keep target_api_status aligned with the published "
                        "version, or bump target_api_version before changing "
                        "API status."
                    ),
                )
            )
    return findings


def check_release_plan_terminal_api_status(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate status for API versions already in terminal releases."""
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    history = context.release_history
    if history is None:
        return []

    return _terminal_api_status_findings(release_plan, context)


# ---------------------------------------------------------------------------
# P-041: check-release-plan-maintenance-line
# ---------------------------------------------------------------------------

_MAINTENANCE_LINE_TYPES = ("maintenance-release", "pre-release-rc")
_MAINTENANCE_BRANCH_RE = re.compile(r"^maintenance/r([1-9]\d*)$")


_MAINTENANCE_RELEASES_URL = (
    "https://github.com/camaraproject/ReleaseManagement/blob/main/"
    "documentation/release-process/maintenance-releases.md"
)


def _maintenance_line_finding(
    context: ValidationContext, message: str, suggestion: str
) -> dict:
    return make_finding(
        engine_rule="check-release-plan-maintenance-line",
        level="error",
        message=_prefix_pre_existing_release_plan_condition(context, message),
        path=_RELEASE_PLAN_PATH,
        line=1,
        suggestion=suggestion,
    )


def _next_line_tag(context: ValidationContext, cycle: int) -> Optional[str]:
    history = context.release_history
    latest = history.latest_release(cycle=cycle) if history is not None else None
    if latest is None or latest.parsed_tag is None:
        return None
    return f"r{cycle}.{latest.parsed_tag.minor + 1}"


def check_release_plan_maintenance_line(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate a plan against the maintenance line it belongs to (003 M1/M3/M6)."""
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    history = context.release_history
    if history is None or not history.release_tags_available():
        return []

    repo = release_plan.get("repository", {})
    if not isinstance(repo, dict):
        return []
    release_type = repo.get("target_release_type", "none")
    target_tag = repo.get("target_release_tag")
    parsed_target = parse_release_tag(target_tag) if target_tag else None
    if parsed_target is None:
        return []

    # Same guard as P-035: a parked plan only matters when the PR edits it.
    if release_type == "none" and context.release_plan_changed is not True:
        return []

    cycle = parsed_target.major
    branch_match = _MAINTENANCE_BRANCH_RE.fullmatch(history.base_ref)
    line_cycle = int(branch_match.group(1)) if branch_match else None

    if line_cycle is not None and cycle != line_cycle:
        return [
            _maintenance_line_finding(
                context,
                f"on branch '{history.base_ref}' target_release_tag must be in "
                f"release cycle r{line_cycle}, not '{target_tag}'.",
                f"Plan the next r{line_cycle}.y release on this branch; new "
                "release cycles are planned on main.",
            )
        ]

    # Published tags are P-035's: the plan must match what was published.
    if history.release_by_tag(target_tag) is not None:
        return []

    if line_cycle is None:
        if not history.is_maintenance_line(cycle):
            return []

        branch = f"maintenance/r{cycle}"
        if history.has_maintenance_branch(cycle):
            return [
                _maintenance_line_finding(
                    context,
                    f"release cycle r{cycle} is maintained on branch "
                    f"'{branch}'; main must not plan '{target_tag}'.",
                    f"Plan the {target_tag} release on '{branch}', and keep "
                    "main on a later release cycle.",
                )
            ]

        later = history.later_cycle_releases(cycle)
        if later:
            later_tag = max(later, key=lambda release: release.parsed_tag).tag
            return [
                _maintenance_line_finding(
                    context,
                    f"release '{later_tag}' is already published in a later "
                    f"cycle, so main can no longer release in cycle "
                    f"r{cycle}; maintenance releases of r{cycle} need the "
                    f"branch '{branch}'.",
                    f"Create '{branch}' from main: Actions → CAMARA Release "
                    "Automation → Run workflow, action "
                    f"create-maintenance-branch, cycle r{cycle}. Then plan "
                    f"'{target_tag}' there, or plan a later release on main. "
                    f"See {_MAINTENANCE_RELEASES_URL}",
                )
            ]

    if release_type != "none" and release_type not in _MAINTENANCE_LINE_TYPES:
        return [
            _maintenance_line_finding(
                context,
                f"release cycle r{cycle} already has a public release, so "
                f"target_release_type '{release_type}' is not allowed for "
                f"'{target_tag}'; use 'maintenance-release' or "
                "'pre-release-rc'.",
                f"Use maintenance-release or pre-release-rc for a fix of "
                f"r{cycle}, or open the next release cycle "
                f"r{cycle + 1}.1 for new work.",
            )
        ]

    next_tag = _next_line_tag(context, cycle)
    if next_tag is not None and target_tag != next_tag:
        return [
            _maintenance_line_finding(
                context,
                f"target_release_tag '{target_tag}' skips tags: the next tag "
                f"of release cycle r{cycle} is '{next_tag}'.",
                f"Set target_release_tag: {next_tag}.",
            )
        ]

    return []


# ---------------------------------------------------------------------------
# P-042: check-release-plan-maintenance-api-versions
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _semver(version: str) -> Optional[tuple[int, int, int]]:
    match = _SEMVER_RE.fullmatch(normalize_api_version_base(version))
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _later_cycle_has_higher_major(
    context: ValidationContext, cycle: int, api_name: str, major: int
) -> bool:
    history = context.release_history
    if history is None:
        return False
    for release in history.later_cycle_releases(cycle):
        if (
            not release.metadata_available
            or release.release_type not in TERMINAL_RELEASE_TYPES
        ):
            continue
        for api in release.apis:
            published = _semver(api.api_version)
            if api.api_name == api_name and published and published[0] > major:
                return True
    return False


def _maintenance_api_version_message(
    context: ValidationContext,
    cycle: int,
    api_name: str,
    planned: tuple[int, int, int],
    patched: tuple[int, int, int],
    patched_version: str,
    patched_tag: str,
    planned_version: str,
) -> Optional[str]:
    base = (
        f"API '{api_name}' changes '{patched_version}' in {patched_tag} to "
        f"'{planned_version}'"
    )
    if planned < patched:
        return f"{base}; a maintenance release must not lower the version."
    if planned[0] != patched[0]:
        return f"{base}; a maintenance line allows no major version change."
    if planned[1] == patched[1]:
        return None
    if patched[0] == 0:
        return (
            f"{base}; for 0.y.z versions the minor version is breaking, so a "
            "maintenance line allows only patch versions."
        )
    if _later_cycle_has_higher_major(context, cycle, api_name, patched[0]):
        return None
    return (
        f"{base}, a new minor version; a maintenance line allows that only "
        "when a later release cycle has published a higher major version of "
        "the API."
    )


def check_release_plan_maintenance_api_versions(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate API versions of a maintenance-line plan against the patched release (003 M2)."""
    plan_path = repo_path / _RELEASE_PLAN_PATH
    release_plan = load_yaml_safe(plan_path)
    if release_plan is None:
        return []

    history = context.release_history
    if history is None or not history.release_tags_available():
        return []

    repo = release_plan.get("repository", {})
    if not isinstance(repo, dict):
        return []
    release_type = repo.get("target_release_type", "none")
    target_tag = repo.get("target_release_tag")
    parsed_target = parse_release_tag(target_tag) if target_tag else None
    if parsed_target is None or history.release_by_tag(target_tag) is not None:
        return []
    if release_type == "none" and context.release_plan_changed is not True:
        return []

    cycle = parsed_target.major
    patched = history.patched_release(cycle)
    if patched is None:
        return []

    def finding(message: str, suggestion: str, api_name: Optional[str] = None) -> dict:
        return make_finding(
            engine_rule="check-release-plan-maintenance-api-versions",
            level="error",
            message=_prefix_pre_existing_release_plan_condition(context, message),
            path=_RELEASE_PLAN_PATH,
            line=1,
            api_name=api_name,
            suggestion=suggestion,
        )

    planned = {name: version for name, version, _ in _planned_api_entries(release_plan)}
    published = {api.api_name: api.api_version for api in patched.apis}
    added = sorted(set(planned) - set(published))
    removed = sorted(set(published) - set(planned))
    if added or removed:
        changes = "; ".join(
            part
            for part in (
                f"added: {', '.join(added)}" if added else "",
                f"removed: {', '.join(removed)}" if removed else "",
            )
            if part
        )
        return [
            finding(
                f"a maintenance release must keep the same APIs as "
                f"{patched.tag}, the release it patches ({changes}).",
                "Restore the API list of the patched release; new APIs are "
                "released on main in a later release cycle.",
            )
        ]

    findings: List[dict] = []
    for api_name, planned_version in planned.items():
        planned_semver = _semver(planned_version)
        patched_semver = _semver(published[api_name])
        if planned_semver is None or patched_semver is None:
            continue
        message = _maintenance_api_version_message(
            context,
            cycle,
            api_name,
            planned_semver,
            patched_semver,
            normalize_api_version_base(published[api_name]),
            patched.tag,
            planned_version,
        )
        if message:
            findings.append(
                finding(
                    message,
                    "Keep the published version or raise only the patch "
                    "version for a maintenance release.",
                    api_name=api_name,
                )
            )
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
# P-033: check-release-plan-active-release-state
# ---------------------------------------------------------------------------


def check_release_plan_active_release_state(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Block release-plan.yaml edits while a release snapshot is active."""
    if context.trigger_type != "pr" or context.release_plan_changed is not True:
        return []

    active_release = context.active_release_state
    active_state = active_release.state
    snapshot_branch = active_release.snapshot_branch
    has_active_state = active_state in _ACTIVE_RELEASE_STATES

    if not snapshot_branch and not has_active_state:
        return []

    details: list[str] = []
    if snapshot_branch:
        details.append(f"active snapshot branch: {snapshot_branch}")
    if has_active_state:
        state_detail = f"release state is '{active_state}'"
        if active_release.release_issue_number is not None:
            state_detail += f" (Release Issue #{active_release.release_issue_number})"
        details.append(state_detail)

    return [
        make_finding(
            engine_rule="check-release-plan-active-release-state",
            level="error",
            message=(
                "release-plan.yaml cannot be changed while an active release "
                f"exists ({'; '.join(details)}). Finish, discard, or publish "
                "the active snapshot before changing release-plan.yaml."
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
