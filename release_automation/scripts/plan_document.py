"""
The plan document of CAMARA release automation.

The plan job derives the release state once and writes one typed document;
the snapshot, act and finalize jobs read it and never derive again. Besides
the trigger, the derived release and the common-cache check it carries the
policy's decision: the response the plan job posted, the action the next job
executes, and for create-maintenance-branch what the action creates.

The document travels between jobs as JSON (to_json / from_json). Nothing else
travels: each job derives the bot comment context from it (bot_context).
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .maintenance_branch import BranchPlan
from .state_manager import ConfigurationError, ReleaseInfoResult, ReleaseState
from .trigger import Trigger


@dataclass(frozen=True)
class CommonCache:
    """Common-file cache detection result (code/common/ against the declared release)."""
    status: str = ""  # in_sync | stale | "" (not checked)
    details: str = ""
    sync_pr_url: str = ""


@dataclass(frozen=True)
class PlanDocument:
    """
    What the plan job decided and what it knows.

    Attributes:
        trigger: The classified event
        release: The release of the base branch as derived in plan; success is
            False on a configuration error
        cache: Common-file cache detection on the base branch
        base_branch: Branch the release is cut from (release_line)
        allowed: A Plan to execute (True) or a Rejection (False)
        publish_mode: draft | on_merge, per release type
        response: Template the plan job posted ("" for none)
        action: What the snapshot/act job executes ("" for none)
        branch_plan: What create-maintenance-branch creates (that action only)
        error_message: Why the trigger was rejected or refused, or the
            configuration error
        error_type: Configuration error category ("" otherwise)
        repo_url: https://github.com/<owner>/<repo>
        run_url: The workflow run
        result_comment_id: The acknowledgment updated with interim_processing,
            which finalize replaces with the result ("" if none)
    """
    trigger: Trigger = field(default_factory=Trigger)
    release: ReleaseInfoResult = field(default_factory=lambda: ReleaseInfoResult(success=True))
    cache: CommonCache = field(default_factory=CommonCache)
    base_branch: str = ""
    allowed: bool = True
    publish_mode: str = ""
    response: str = ""
    action: str = ""
    branch_plan: Optional[BranchPlan] = None
    error_message: str = ""
    error_type: str = ""
    repo_url: str = ""
    run_url: str = ""
    result_comment_id: str = ""

    # ── views of the release ──

    @property
    def release_tag(self) -> str:
        return self.release.release_tag or ""

    @property
    def state(self) -> str:
        return self.release.state.value if self.release.state else ""

    @property
    def release_type(self) -> str:
        return self.release.release_type or ""

    @property
    def release_issue_number(self) -> str:
        return str(self.release.release_issue_number) if self.release.release_issue_number else ""

    @property
    def release_pr_number(self) -> str:
        return str(self.release.release_pr_number) if self.release.release_pr_number else ""

    @property
    def snapshot_branch(self) -> str:
        return self.release.snapshot_branch or ""

    @property
    def release_review_branch(self) -> str:
        return self.release.release_review_branch

    @property
    def src_commit_sha(self) -> str:
        return self.release.src_commit_sha

    @property
    def release_plan_url(self) -> str:
        return f"{self.repo_url}/blob/{self.base_branch}/release-plan.yaml" if self.repo_url else ""

    def tree_url(self, ref: str) -> str:
        return f"{self.repo_url}/tree/{ref}" if ref else ""

    def pr_url(self, number: str) -> str:
        return f"{self.repo_url}/pull/{number}" if number else ""

    # ── JSON ──

    def to_json(self) -> str:
        document = asdict(self)
        release = document["release"]
        release["state"] = self.release.state.value if self.release.state else None
        return json.dumps(document)

    @classmethod
    def from_json(cls, text: str) -> "PlanDocument":
        document: Dict[str, Any] = json.loads(text)
        release = dict(document.pop("release"))
        state = release.pop("state")
        config_error = release.pop("config_error")
        branch_plan = document.pop("branch_plan")
        return cls(
            trigger=Trigger(**document.pop("trigger")),
            release=ReleaseInfoResult(
                state=ReleaseState(state) if state else None,
                config_error=ConfigurationError(**config_error) if config_error else None,
                **release,
            ),
            cache=CommonCache(**document.pop("cache")),
            branch_plan=BranchPlan(**branch_plan) if branch_plan else None,
            **document,
        )
