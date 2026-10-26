"""
Bot message context for CAMARA release automation.

BotContext is the schema every bot message template, the issue sync and the
other consumers render from (technical-architecture.md section 2.9). Each job
derives the run's base context from the plan document with bot_context(); a
comment adds its delta on top (bot_responder.merge_comment_context).
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from . import config
from .commands import actions_for
from .plan_document import PlanDocument


@dataclass
class BotContext:
    """
    Unified context for all bot message rendering and issue updates.

    Every field has a type-appropriate default so that templates can render
    safely in any workflow state. Boolean flags are derived automatically
    from string fields by derive_flags().
    """

    # Trigger fields
    command: str = ""
    command_args: str = ""
    user: str = ""
    trigger_type: str = ""  # "slash_command", "workflow_dispatch", "push", "issue_close", ...

    # Issue creation fields (for issue_created template)
    closed_issue_number: str = ""
    closed_issue_url: str = ""
    release_plan_url: str = ""

    # State fields
    release_tag: str = ""
    state: str = ""
    release_type: str = ""
    meta_release: str = ""
    short_type: str = ""  # Derived: alpha, rc, public, maintenance
    base_branch: str = ""  # Branch the release is cut from: main or maintenance/rX

    # Snapshot fields
    snapshot_id: str = ""
    snapshot_branch: str = ""
    snapshot_branch_url: str = ""
    release_review_branch: str = ""
    release_review_branch_url: str = ""
    src_commit_sha: str = ""
    release_pr_number: str = ""
    release_pr_url: str = ""

    # API fields — list of dicts with keys:
    #   api_name, target_api_version, target_api_status, api_version, api_title
    apis: List[Dict[str, str]] = field(default_factory=list)

    # Dependency fields
    commonalities_release: str = ""
    identity_consent_management_release: str = ""

    # Error fields
    error_message: str = ""
    error_type: str = ""

    # Derived boolean flags (set by derive_flags())
    is_missing_file: bool = False
    is_malformed_yaml: bool = False
    is_missing_field: bool = False
    is_release_line: bool = False
    state_snapshot_active: bool = False
    state_draft_ready: bool = False
    state_published: bool = False
    trigger_workflow_dispatch: bool = False
    trigger_issue_close: bool = False
    has_meta_release: bool = False
    has_reason: bool = False

    # Display fields
    workflow_run_url: str = ""
    draft_release_url: str = ""
    candidate_block_stripped: str = ""
    reason: str = ""

    # Publication fields
    release_url: str = ""
    reference_tag: str = ""
    reference_tag_url: str = ""
    sync_pr_number: str = ""
    sync_pr_url: str = ""
    main_sync_pr_number: str = ""  # Case B: the sync PR into main
    main_sync_pr_url: str = ""
    src_commit_sha_short: str = ""  # First 7 chars of src_commit_sha
    confirm_tag: str = ""  # Tag from --confirm argument
    publish_warnings: str = ""  # Semicolon-separated warnings from non-critical post-publish steps

    # Derived publication flags (set by derive_flags())
    has_sync_pr: bool = False
    has_main_sync_pr: bool = False
    has_publish_warnings: bool = False

    # Common file cache sync fields
    common_cache_status: str = ""      # "stale", "in_sync", or "" (unchecked)
    common_cache_details: str = ""     # Human-readable staleness description
    common_sync_pr_url: str = ""       # URL of open sync-common/* PR

    # Derived cache sync flags (set by derive_flags())
    common_cache_stale: bool = False
    has_common_sync_pr: bool = False

    # Valid actions of the state the comment reports (set by derive_flags())
    valid_actions: str = ""

    def derive_flags(self) -> None:
        """Compute boolean flags and derived fields from string fields."""
        self.is_missing_file = self.error_type == "missing_file"
        self.is_malformed_yaml = self.error_type == "malformed_yaml"
        self.is_missing_field = self.error_type == "missing_field"
        self.is_release_line = self.error_type == "release_line"
        self.state_snapshot_active = self.state == config.STATE_SNAPSHOT_ACTIVE
        self.state_draft_ready = self.state == config.STATE_DRAFT_READY
        self.state_published = self.state == config.STATE_PUBLISHED
        self.trigger_workflow_dispatch = self.trigger_type == "workflow_dispatch"
        self.trigger_issue_close = self.trigger_type == "issue_close"
        self.has_meta_release = bool(self.meta_release)
        self.has_reason = bool(self.reason)
        self.has_sync_pr = bool(self.sync_pr_url)
        self.has_main_sync_pr = bool(self.main_sync_pr_url)
        self.has_publish_warnings = bool(self.publish_warnings)
        self.common_cache_stale = self.common_cache_status == "stale"
        self.has_common_sync_pr = bool(self.common_sync_pr_url)
        self.valid_actions = actions_for(self.state, self.release_tag, self.release_pr_url)
        if not self.src_commit_sha_short:
            self.src_commit_sha_short = self.src_commit_sha[:7]
        if not self.short_type:
            self.short_type = config.SHORT_TYPE_MAP.get(
                self.release_type, self.release_type
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        The context for pystache rendering: every field, no None values,
        booleans kept as bool (pystache treats False as falsy).
        """
        return asdict(self)


def build_context(**fields: Any) -> Dict[str, Any]:
    """
    A complete context from BotContext fields: all keys, defaults filled,
    flags derived. A field name outside the schema is an error.
    """
    ctx = BotContext(**fields)
    ctx.derive_flags()
    return ctx.to_dict()


def bot_context(plan: PlanDocument) -> Dict[str, Any]:
    """The run's base context, derived from the plan document."""
    release = plan.release
    return build_context(
        command=plan.trigger.command,
        command_args=plan.trigger.command_args,
        user=plan.trigger.user,
        trigger_type=plan.trigger.trigger_type,
        confirm_tag=plan.trigger.confirm_tag,
        release_plan_url=plan.release_plan_url,
        release_tag=plan.release_tag,
        state=plan.state,
        release_type=plan.release_type,
        meta_release=release.meta_release or "",
        base_branch=plan.base_branch,
        snapshot_id=release.snapshot_id,
        snapshot_branch=plan.snapshot_branch,
        snapshot_branch_url=plan.tree_url(plan.snapshot_branch),
        release_review_branch=release.release_review_branch,
        release_review_branch_url=plan.tree_url(release.release_review_branch),
        src_commit_sha=release.src_commit_sha,
        release_pr_number=plan.release_pr_number,
        release_pr_url=plan.pr_url(plan.release_pr_number),
        draft_release_url=release.draft_release_url,
        apis=list(release.apis),
        commonalities_release=release.commonalities_release,
        identity_consent_management_release=release.identity_consent_management_release,
        workflow_run_url=plan.run_url,
        common_cache_status=plan.cache.status,
        common_cache_details=plan.cache.details,
        common_sync_pr_url=plan.cache.sync_pr_url,
    )
