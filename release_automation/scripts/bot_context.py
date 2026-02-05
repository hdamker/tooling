"""
Bot message context for CAMARA release automation.

Provides the unified BotContext dataclass that carries all workflow data
needed by bot message templates, issue sync, and other consumers.
See technical-architecture.md Section 2.9 for the authoritative schema.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    trigger_pr_number: str = ""

    # State fields
    release_tag: str = ""
    state: str = ""
    release_type: str = ""
    meta_release: str = ""

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
    state_snapshot_active: bool = False
    state_draft_ready: bool = False

    # Display fields
    workflow_run_url: str = ""
    draft_release_url: str = ""
    reason: str = ""

    def derive_flags(self) -> None:
        """Compute boolean flags from string fields."""
        self.is_missing_file = self.error_type == "missing_file"
        self.is_malformed_yaml = self.error_type == "malformed_yaml"
        self.is_missing_field = self.error_type == "missing_field"
        self.state_snapshot_active = self.state == "snapshot-active"
        self.state_draft_ready = self.state == "draft-ready"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a dict suitable for pystache rendering.

        Guarantees:
        - All BotContext fields are present as keys
        - No None values
        - Boolean fields remain as bool (pystache treats False as falsy)
        - apis list entries are preserved as dicts
        """
        return {
            # Trigger fields
            "command": self.command,
            "command_args": self.command_args,
            "user": self.user,
            "trigger_pr_number": self.trigger_pr_number,
            # State fields
            "release_tag": self.release_tag,
            "state": self.state,
            "release_type": self.release_type,
            "meta_release": self.meta_release,
            # Snapshot fields
            "snapshot_id": self.snapshot_id,
            "snapshot_branch": self.snapshot_branch,
            "snapshot_branch_url": self.snapshot_branch_url,
            "release_review_branch": self.release_review_branch,
            "release_review_branch_url": self.release_review_branch_url,
            "src_commit_sha": self.src_commit_sha,
            "release_pr_number": self.release_pr_number,
            "release_pr_url": self.release_pr_url,
            # API fields
            "apis": self.apis,
            # Dependency fields
            "commonalities_release": self.commonalities_release,
            "identity_consent_management_release": self.identity_consent_management_release,
            # Error fields
            "error_message": self.error_message,
            "error_type": self.error_type,
            # Derived boolean flags
            "is_missing_file": self.is_missing_file,
            "is_malformed_yaml": self.is_malformed_yaml,
            "is_missing_field": self.is_missing_field,
            "state_snapshot_active": self.state_snapshot_active,
            "state_draft_ready": self.state_draft_ready,
            # Display fields
            "workflow_run_url": self.workflow_run_url,
            "draft_release_url": self.draft_release_url,
            "reason": self.reason,
        }
