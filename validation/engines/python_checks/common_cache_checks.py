"""Common-file cache sync check (P-021).

Wrapper around :func:`tooling_lib.cache_sync.check_sync_status` that
converts the structured :class:`~tooling_lib.cache_sync.SyncStatus`
into VF findings.

DEC-027 (RA-integrated sync), DEC-030 (manifest-based validation).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from tooling_lib.cache_sync import COMMON_DIR, SyncStatus, check_sync_status
from validation.context import ValidationContext

from ._types import make_finding

_ENGINE_RULE = "check-common-cache-sync"


def check_common_cache_sync(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Verify ``code/common/`` files match the sync manifest.

    Repo-level check — runs once, not per-API.

    Skipped when ``release-plan.yaml`` is absent at the repo root
    (release-review/snapshot branches post-bundling per DEC-021):
    ``code/common/`` is intentionally absent in the same context, so
    there is nothing to verify. ``commonalities_release`` may still be
    populated from the release-metadata.yaml fallback in those cases.

    Builds the expected-releases dict from *context* and delegates to
    :func:`~tooling_lib.cache_sync.check_sync_status`.  Returns an
    empty list when no expected releases can be determined (e.g. no
    ``release-plan.yaml``).
    """
    if not (repo_path / "release-plan.yaml").is_file():
        return []

    expected = _build_expected_releases(context)
    if not expected:
        return []

    status = check_sync_status(repo_path, expected)
    return _status_to_findings(status)


# ------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------


def _build_expected_releases(context: ValidationContext) -> dict:
    """Derive expected source-repo releases from the validation context."""
    expected: dict = {}
    if context.commonalities_release:
        expected["Commonalities"] = context.commonalities_release
    return expected


def _status_to_findings(status: SyncStatus) -> List[dict]:
    """Convert a *SyncStatus* into a list of VF findings."""
    findings: List[dict] = []

    if status.no_common_dir:
        findings.append(
            make_finding(
                engine_rule=_ENGINE_RULE,
                level="warn",
                message=(
                    f"{COMMON_DIR}/ directory is missing — required for "
                    f"repos declaring a commonalities_release dependency"
                ),
                path=COMMON_DIR,
            )
        )
        return findings

    if status.no_manifest:
        findings.append(
            make_finding(
                engine_rule=_ENGINE_RULE,
                level="warn",
                message=(
                    f"Sync manifest ({COMMON_DIR}/.sync-manifest.yaml) is "
                    f"missing — common files must be managed by the sync "
                    f"mechanism"
                ),
                path=f"{COMMON_DIR}/.sync-manifest.yaml",
            )
        )
        return findings

    for src in status.sources:
        if src.tag_mismatch:
            expected, actual = src.tag_mismatch
            findings.append(
                make_finding(
                    engine_rule=_ENGINE_RULE,
                    level="warn",
                    message=(
                        f"{src.repository}: dependency declares {expected} "
                        f"but common files synced from {actual}"
                    ),
                    path=f"{COMMON_DIR}/.sync-manifest.yaml",
                )
            )

        for filename in src.missing_files:
            findings.append(
                make_finding(
                    engine_rule=_ENGINE_RULE,
                    level="warn",
                    message=(
                        f"{src.repository}: expected file '{filename}' is "
                        f"missing from {COMMON_DIR}/"
                    ),
                    path=f"{COMMON_DIR}/{filename}",
                )
            )

        for filename in src.modified_files:
            findings.append(
                make_finding(
                    engine_rule=_ENGINE_RULE,
                    level="warn",
                    message=(
                        f"{src.repository}: '{filename}' has been modified "
                        f"since last sync"
                    ),
                    path=f"{COMMON_DIR}/{filename}",
                )
            )

    return findings
