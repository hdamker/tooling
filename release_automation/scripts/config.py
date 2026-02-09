"""
Central configuration for release automation scripts.
"""

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

# Branch patterns
SNAPSHOT_BRANCH_PREFIX = "release-snapshot/"
RELEASE_REVIEW_BRANCH_PREFIX = "release-review/"

# Labels
LABEL_RELEASE_MGMT_BOT = "Release-Mgmt-Bot"

# Release type display names (short form for titles, messages)
SHORT_TYPE_MAP = {
    "pre-release-alpha": "alpha",
    "pre-release-rc": "rc",
    "public-release": "public",
    "maintenance-release": "maintenance",
}
