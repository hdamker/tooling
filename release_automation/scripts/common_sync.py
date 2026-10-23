"""
Common-file sync for CAMARA release automation.

Detection: compare an API repository's code/common/ cache with the
Commonalities release it declares (tooling_lib.cache_sync). The plan job uses
the result to block /create-snapshot on a stale cache and to feed the drift
warning. Repair (rebuilding the cache and its sync PR) still runs inline in the
workflow.

This module depends only on tooling_lib.cache_sync; the release-state gate
stays with the caller.

Usage (workflow step):
    python3 -m release_automation.scripts.common_sync
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tooling_lib.cache_sync import SyncStatus, check_sync_status

# Releases before r4.2 have no sync manifest to check against.
FIRST_CHECKED_RELEASE = (4, 2)


@dataclass(frozen=True)
class CacheCheck:
    """Detection result; status is in_sync, stale, or "" when not checked."""
    status: str = ""
    details: str = ""


def describe(status: SyncStatus) -> str:
    """One-line description of a stale cache."""
    parts = []
    if status.no_common_dir:
        parts.append("code/common/ directory is missing")
    elif status.no_manifest:
        parts.append("code/common/.sync-manifest.yaml is missing")
    else:
        for src in status.sources:
            if src.tag_mismatch:
                expected_tag, actual_tag = src.tag_mismatch
                parts.append(f"{src.repository}: expected {expected_tag}, manifest has {actual_tag}")
            for fname in src.missing_files:
                parts.append(f"{fname} missing from code/common/")
            for fname in src.modified_files:
                parts.append(f"{fname} modified since last sync")
    return "; ".join(parts) if parts else "cache mismatch detected"


def detect(api_repo: Path, commonalities_release: str) -> CacheCheck:
    """
    Check code/common/ against the declared Commonalities release.

    Args:
        api_repo: Checkout of the API repository (code/common/ is enough)
        commonalities_release: Declared release, e.g. "r4.2"

    Returns:
        CacheCheck; empty status when the release is unparsable or before r4.2
    """
    m = re.fullmatch(r"r(\d+)\.(\d+)", commonalities_release)
    if not m:
        print(f"Cannot parse commonalities_release '{commonalities_release}', skipping cache check")
        return CacheCheck()
    if (int(m.group(1)), int(m.group(2))) < FIRST_CHECKED_RELEASE:
        print(f"commonalities_release {commonalities_release} < r4.2, skipping cache check")
        return CacheCheck()

    status = check_sync_status(api_repo, {"Commonalities": commonalities_release})
    if status.in_sync:
        print(f"Common file cache is in sync with {commonalities_release}")
        return CacheCheck(status="in_sync")

    details = describe(status)
    print(f"Common file cache is stale: {details}")
    return CacheCheck(status="stale", details=details)


def main() -> int:
    from release_automation.scripts.trigger import write_outputs

    check = detect(Path(os.environ["API_REPO_PATH"]), os.environ["COMMONALITIES_RELEASE"])
    write_outputs(os.environ["GITHUB_OUTPUT"], {
        "common_cache_status": check.status,
        "common_cache_details": check.details,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
