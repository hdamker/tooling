"""Plan documents for the act and finalize tests, built from flat keyword arguments."""

from dataclasses import fields
from typing import Any, Dict

from release_automation.scripts.maintenance_branch import BranchPlan
from release_automation.scripts.plan_document import CommonCache, PlanDocument
from release_automation.scripts.state_manager import ReleaseInfoResult, ReleaseState
from release_automation.scripts.trigger import Trigger

REPO_URL = "https://github.com/camaraproject/Example"

_TRIGGER = {f.name for f in fields(Trigger)}
_RELEASE = {f.name for f in fields(ReleaseInfoResult)}
_CACHE = {"common_cache_status": "status", "common_cache_details": "details", "common_sync_pr_url": "sync_pr_url"}


def make_plan(**kw: Any) -> PlanDocument:
    """
    A PlanDocument from the flat names the former dict plan used: Trigger fields
    (command, user, issue_number, ...), release fields (release_tag, state,
    snapshot_branch, release_issue_number, ...), common_cache_* and the
    decision fields (action, publish_mode, response, branch_plan, ...).
    """
    kw = dict(kw)
    trigger: Dict[str, Any] = {"should_continue": True}
    release: Dict[str, Any] = {"success": True}
    cache: Dict[str, Any] = {}
    document: Dict[str, Any] = {"repo_url": REPO_URL, "run_url": f"{REPO_URL}/actions/runs/999"}
    for name, value in kw.items():
        if name == "state":
            release["state"] = ReleaseState(value) if value else None
        elif name == "base_branch":
            release[name] = document[name] = value
        elif name == "release_tag":
            # The tag the event names and the tag of the derived release
            release[name] = trigger[name] = value
        elif name in ("release_issue_number", "release_pr_number"):
            release[name] = int(value) if value else None
        elif name in _CACHE:
            cache[_CACHE[name]] = value
        elif name == "branch_plan":
            document[name] = BranchPlan(**value) if isinstance(value, dict) else value
        elif name in _TRIGGER:
            trigger[name] = value
        elif name in _RELEASE:
            release[name] = value
        else:
            document[name] = value
    return PlanDocument(
        trigger=Trigger(**trigger), release=ReleaseInfoResult(**release), cache=CommonCache(**cache), **document,
    )
