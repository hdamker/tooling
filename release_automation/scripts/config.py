"""
Central configuration for release automation scripts: file names, states,
branch patterns, the markers of workflow-owned Release Issues, and the one
release-type table every module reads.
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional

# File paths
RELEASE_PLAN_FILE = "release-plan.yaml"
RELEASE_METADATA_FILE = "release-metadata.yaml"
COMMONALITIES_FILE = "Commonalities/release-metadata.yaml"
ICM_FILE = "IdentityConsentManagement/release-metadata.yaml"

# Release states
STATE_PLANNED = "planned"
STATE_SNAPSHOT_ACTIVE = "snapshot-active"
STATE_DRAFT_READY = "draft-ready"
STATE_PUBLISHED = "published"
STATE_NOT_PLANNED = "not-planned"

# Branches
MAIN_BRANCH = "main"
SNAPSHOT_BRANCH_PREFIX = "release-snapshot/"
RELEASE_REVIEW_BRANCH_PREFIX = "release-review/"

# Labels
LABEL_RELEASE_MGMT_BOT = "Release-Mgmt-Bot"
RELEASE_ISSUE_LABEL = "release-issue"

# Markers of a workflow-owned Release Issue (in its body)
WORKFLOW_MARKER = "<!-- release-automation:workflow-owned -->"
RELEASE_TAG_MARKER_RE = re.compile(r"<!--\s*release-automation:release-tag:(?P<tag>.*?)\s*-->")

# How a release is published once its Release PR is merged:
#   draft    — merge creates a draft release; /publish-release --confirm publishes it
#   on_merge — merge publishes directly
PUBLISH_MODE_DRAFT = "draft"
PUBLISH_MODE_ON_MERGE = "on_merge"

# Who may post /publish-release:
#   codeowners — users on the first "*" line of CODEOWNERS (main); maintain
#                and admin bypass; no list means write access suffices
PUBLISHERS_CODEOWNERS = "codeowners"


@dataclass(frozen=True)
class ReleaseType:
    """
    One target_release_type of release-plan.yaml.

    Attributes:
        name: The value in release-plan.yaml and release-metadata.yaml
        short: Display name in titles, comments and PR titles
        description: Display name in the CHANGELOG draft
        prerelease: Published as a GitHub pre-release
        publish_mode: PUBLISH_MODE_DRAFT | PUBLISH_MODE_ON_MERGE
        publishers: Who may post /publish-release (PUBLISHERS_CODEOWNERS)
    """
    name: str
    short: str
    description: str
    prerelease: bool
    publish_mode: str
    publishers: str


# The one release-type table. Policy values expected to change (RM#675) are
# publish_mode and publishers; the initial values reproduce the behaviour
# before this table.
RELEASE_TYPES: Dict[str, ReleaseType] = {
    t.name: t for t in (
        ReleaseType("pre-release-alpha", "alpha", "pre-release", True, PUBLISH_MODE_DRAFT, PUBLISHERS_CODEOWNERS),
        ReleaseType("pre-release-rc", "rc", "release candidate", True, PUBLISH_MODE_DRAFT, PUBLISHERS_CODEOWNERS),
        ReleaseType("public-release", "public", "public release", False, PUBLISH_MODE_DRAFT, PUBLISHERS_CODEOWNERS),
        ReleaseType("maintenance-release", "maintenance", "maintenance release", False, PUBLISH_MODE_DRAFT,
                    PUBLISHERS_CODEOWNERS),
    )
}

# target_release_type of a parked plan: no release is being prepared
RELEASE_TYPE_NONE = "none"


def release_type(name: Optional[str]) -> Optional[ReleaseType]:
    return RELEASE_TYPES.get(name or "")


def short_type(name: Optional[str]) -> str:
    """Display name of a release type; "" for none, the value itself when unknown."""
    if not name or name == RELEASE_TYPE_NONE:
        return ""
    known = release_type(name)
    return known.short if known else name


def is_prerelease(name: Optional[str]) -> bool:
    known = release_type(name)
    return known.prerelease if known else False


# Release type display names (short form for titles, messages)
SHORT_TYPE_MAP = {name: t.short for name, t in RELEASE_TYPES.items()}
