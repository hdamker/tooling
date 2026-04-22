"""Context building for the CAMARA validation framework.

Assembles the unified validation context object from workflow inputs,
release-plan.yaml, and OpenAPI spec files.  All fields are always present
in the output — downstream consumers never need to handle missing keys.

Design doc references:
  - Section 8.3: context object structure
  - Section 8.1 step 4: context assembly
  - Section 1.1: trigger and branch type enums
  - Section 1.4: derived fields (maturity, api_pattern)
"""

from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .api_pattern_detector import detect_api_pattern_from_file
from .release_metadata_parser import load_release_metadata
from .release_plan_parser import load_release_plan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — branch types
# ---------------------------------------------------------------------------

BRANCH_MAIN = "main"
BRANCH_RELEASE = "release"
BRANCH_MAINTENANCE = "maintenance"
BRANCH_FEATURE = "feature"

# ---------------------------------------------------------------------------
# Constants — trigger types
# ---------------------------------------------------------------------------

TRIGGER_PR = "pr"
TRIGGER_DISPATCH = "dispatch"
TRIGGER_RELEASE_AUTOMATION = "release-automation"
TRIGGER_LOCAL = "local"

# ---------------------------------------------------------------------------
# Constants — profiles
# ---------------------------------------------------------------------------

PROFILE_ADVISORY = "advisory"
PROFILE_STANDARD = "standard"
PROFILE_STRICT = "strict"

_VALID_PROFILES = frozenset({PROFILE_ADVISORY, PROFILE_STANDARD, PROFILE_STRICT})

# ---------------------------------------------------------------------------
# Constants — API maturity
# ---------------------------------------------------------------------------

MATURITY_INITIAL = "initial"
MATURITY_STABLE = "stable"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiContext:
    """Per-API validation context.

    Attributes:
        api_name: Kebab-case API name (e.g. "qos-booking").
        target_api_version: Semantic version from release-plan (e.g. "1.0.0").
        target_api_status: Status from release-plan (draft/alpha/rc/public).
        target_api_maturity: Derived — "initial" (0.x) or "stable" (>=1.x).
        api_pattern: Detected from spec — request-response, implicit-subscription,
            or explicit-subscription.
        spec_file: Relative path to the spec file (e.g.
            "code/API_definitions/qos-booking.yaml").
    """

    api_name: str
    target_api_version: str
    target_api_status: str
    target_api_maturity: str
    api_pattern: str
    spec_file: str


@dataclass(frozen=True)
class ValidationContext:
    """Unified validation context.  All fields always present.

    None values represent absent data (e.g. no release-plan.yaml or
    non-PR trigger).
    """

    # Repository identification
    repository: str
    branch_type: str
    trigger_type: str
    profile: str
    stage: str

    # Release context (from release-plan.yaml; None if absent)
    target_release_type: Optional[str]
    commonalities_release: Optional[str]
    commonalities_version: Optional[str]
    icm_release: Optional[str]

    # PR-specific (None / False for non-PR triggers)
    base_ref: Optional[str]
    is_release_review_pr: bool
    release_plan_changed: Optional[bool]
    pr_number: Optional[int]

    # Per-API contexts (empty tuple if no release-plan.yaml)
    apis: Tuple[ApiContext, ...]

    # Workflow metadata
    workflow_run_url: str
    tooling_ref: str

    # Release-plan validation context (Step 6b outputs; defaults when absent)
    # commonalities_release_changed / icm_release_changed: True when the
    # respective dependency declaration differs between base and head.
    # release_plan_check_only: True when a Commonalities advance is detected —
    # orchestrator skips Spectral/gherkin engines and post-filter keeps only
    # rules in the release-plan-validation group.  ICM advance does NOT set
    # this flag (no common files to sync).
    # *_tag_exists: tri-state — True (confirmed), False (confirmed missing),
    # None (check did not run or API lookup failed).
    # non_release_plan_files_changed: files co-changed alongside release-plan.yaml
    # in the current PR diff (P-022 exclusivity input).
    commonalities_release_changed: bool = False
    icm_release_changed: bool = False
    release_plan_check_only: bool = False
    commonalities_tag_exists: Optional[bool] = None
    icm_tag_exists: Optional[bool] = None
    non_release_plan_files_changed: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Serialize to dict with all keys present.

        ``apis`` is converted from a tuple of dataclasses to a list of dicts.
        """
        d = dataclasses.asdict(self)
        # asdict converts nested dataclasses to dicts but keeps tuples as
        # tuples — convert apis to a list for JSON serialization.
        d["apis"] = list(d["apis"])
        return d


# ---------------------------------------------------------------------------
# Pure derivation functions
# ---------------------------------------------------------------------------


def derive_branch_type(branch_name: str) -> str:
    """Derive the branch type from a branch name.

    Args:
        branch_name: Target branch for PRs (base_ref) or checked-out branch
            for dispatch (ref_name).

    Returns:
        One of BRANCH_MAIN, BRANCH_RELEASE, BRANCH_MAINTENANCE, BRANCH_FEATURE.
    """
    if branch_name == "main":
        return BRANCH_MAIN
    if branch_name.startswith("release-snapshot/"):
        return BRANCH_RELEASE
    if branch_name.startswith("maintenance/"):
        return BRANCH_MAINTENANCE
    return BRANCH_FEATURE


def derive_trigger_type(event_name: str, mode: str = "") -> str:
    """Map a GitHub event name (+ optional mode) to a trigger type.

    Args:
        event_name: ``github.event_name`` value.
        mode: Workflow input — ``"pre-snapshot"`` sets release-automation.

    Returns:
        One of TRIGGER_PR, TRIGGER_DISPATCH, TRIGGER_RELEASE_AUTOMATION,
        TRIGGER_LOCAL.
    """
    if mode == "pre-snapshot":
        return TRIGGER_RELEASE_AUTOMATION
    if event_name == "pull_request":
        return TRIGGER_PR
    if event_name == "workflow_dispatch":
        return TRIGGER_DISPATCH
    # Safe fallback for unknown events.
    return TRIGGER_DISPATCH


def derive_target_branch(
    event_name: str, base_ref: str, ref_name: str
) -> str:
    """Return the relevant branch name for branch type derivation.

    For PRs the target branch (base_ref) determines which rules apply.
    For dispatch the checked-out branch (ref_name) is used.
    """
    if event_name == "pull_request":
        return base_ref
    return ref_name


def select_profile(
    trigger_type: str,
    branch_type: str,
    is_release_review_pr: bool,
    profile_override: str = "",
    pr_profile: str = "standard",
    release_profile: str = "standard",
) -> str:
    """Auto-select the validation profile.

    If *profile_override* is a valid profile name it takes precedence.

    Profile selection:
        dispatch / local              → advisory (hardcoded)
        release-automation            → release_profile from config
        pr + release + review         → release_profile from config
        pr + any other                → pr_profile from config
    """
    if profile_override and profile_override in _VALID_PROFILES:
        return profile_override

    if trigger_type in (TRIGGER_DISPATCH, TRIGGER_LOCAL):
        return PROFILE_ADVISORY
    if trigger_type == TRIGGER_RELEASE_AUTOMATION:
        return release_profile
    # trigger_type == TRIGGER_PR
    if branch_type == BRANCH_RELEASE and is_release_review_pr:
        return release_profile
    return pr_profile


def derive_api_maturity(target_api_version: str) -> str:
    """Derive API maturity from the semantic version.

    Major version 0 → initial; ≥ 1 → stable.
    """
    match = re.match(r"^(\d+)\.", target_api_version)
    if match:
        major = int(match.group(1))
        return MATURITY_STABLE if major >= 1 else MATURITY_INITIAL
    return MATURITY_INITIAL


def is_release_review_pr_check(base_ref: str) -> bool:
    """True when the PR targets a release-snapshot branch."""
    return base_ref.startswith("release-snapshot/")


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


def build_validation_context(
    repo_name: str,
    event_name: str,
    ref_name: str,
    base_ref: str,
    mode: str = "",
    profile_override: str = "",
    stage: str = "",
    pr_profile: str = "standard",
    release_profile: str = "standard",
    pr_number: Optional[int] = None,
    release_plan_changed: Optional[bool] = None,
    repo_path: Optional[Path] = None,
    release_plan_schema_path: Optional[Path] = None,
    release_metadata_schema_path: Optional[Path] = None,
    workflow_run_url: str = "",
    tooling_ref: str = "",
    commonalities_version: Optional[str] = None,
    release_plan_check_only: bool = False,
    commonalities_release_changed: bool = False,
    icm_release_changed: bool = False,
    commonalities_tag_exists: Optional[bool] = None,
    icm_tag_exists: Optional[bool] = None,
    non_release_plan_files_changed: Tuple[str, ...] = (),
) -> ValidationContext:
    """Assemble the unified validation context.

    Composes all derivation functions and I/O loaders into a single
    immutable context object.
    """
    # Derive branch and trigger
    target_branch = derive_target_branch(event_name, base_ref, ref_name)
    branch_type = derive_branch_type(target_branch)
    trigger_type = derive_trigger_type(event_name, mode)

    # Release review detection (only meaningful for PRs)
    is_review = is_release_review_pr_check(base_ref) if base_ref else False

    # Profile selection
    profile = select_profile(
        trigger_type, branch_type, is_review, profile_override,
        pr_profile=pr_profile, release_profile=release_profile,
    )

    # Release plan
    target_release_type: Optional[str] = None
    commonalities_release: Optional[str] = None
    icm_release: Optional[str] = None
    api_contexts: Tuple[ApiContext, ...] = ()

    if repo_path is not None and release_plan_schema_path is not None:
        plan_path = repo_path / "release-plan.yaml"
        release_plan = load_release_plan(plan_path, release_plan_schema_path)

        # Fallback: on snapshot branches release-plan.yaml is removed and
        # replaced with release-metadata.yaml.  Use it to populate context
        # so Spectral gets the correct ruleset and per-API checks run.
        if release_plan is None and is_review and release_metadata_schema_path is not None:
            metadata_path = repo_path / "release-metadata.yaml"
            release_plan = load_release_metadata(
                metadata_path, release_metadata_schema_path
            )
            if release_plan is not None:
                logger.info(
                    "Using release-metadata.yaml fallback for snapshot branch context"
                )

        if release_plan is not None:
            target_release_type = release_plan.target_release_type
            commonalities_release = release_plan.commonalities_release
            icm_release = release_plan.icm_release

            # Build per-API contexts
            api_list = []
            for api in release_plan.apis:
                spec_file = f"code/API_definitions/{api.api_name}.yaml"
                spec_path = repo_path / spec_file
                api_pattern = detect_api_pattern_from_file(spec_path)
                maturity = derive_api_maturity(api.target_api_version)
                api_list.append(
                    ApiContext(
                        api_name=api.api_name,
                        target_api_version=api.target_api_version,
                        target_api_status=api.target_api_status,
                        target_api_maturity=maturity,
                        api_pattern=api_pattern,
                        spec_file=spec_file,
                    )
                )
            api_contexts = tuple(api_list)

    return ValidationContext(
        repository=repo_name,
        branch_type=branch_type,
        trigger_type=trigger_type,
        profile=profile,
        stage=stage,
        target_release_type=target_release_type,
        commonalities_release=commonalities_release,
        commonalities_version=commonalities_version,
        icm_release=icm_release,
        base_ref=base_ref or None,
        is_release_review_pr=is_review,
        release_plan_changed=release_plan_changed,
        pr_number=pr_number,
        apis=api_contexts,
        workflow_run_url=workflow_run_url,
        tooling_ref=tooling_ref,
        commonalities_release_changed=commonalities_release_changed,
        icm_release_changed=icm_release_changed,
        release_plan_check_only=release_plan_check_only,
        commonalities_tag_exists=commonalities_tag_exists,
        icm_tag_exists=icm_tag_exists,
        non_release_plan_files_changed=non_release_plan_files_changed,
    )
