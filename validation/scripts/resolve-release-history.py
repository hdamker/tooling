#!/usr/bin/env python3
"""Resolve published release history for offline validation rules.

The workflow owns GitHub access.  This script uses the release automation
GitHub client to read published releases and their release-metadata.yaml, then
writes a compact JSON snapshot consumed by validation.orchestrator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

TOOLING_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLING_ROOT))

from release_automation.scripts.github_client import GitHubClient, GitHubClientError


def _metadata_release(release, metadata: dict[str, Any] | None) -> dict[str, Any]:
    repo = metadata.get("repository", {}) if isinstance(metadata, dict) else {}
    deps = metadata.get("dependencies", {}) if isinstance(metadata, dict) else {}
    apis = metadata.get("apis", []) if isinstance(metadata, dict) else []
    return {
        "tag": release.tag_name,
        "release_type": str(repo.get("release_type") or ""),
        "prerelease": bool(release.prerelease),
        "published_at": "",
        "src_commit_sha": str(repo.get("src_commit_sha") or ""),
        "metadata_available": isinstance(metadata, dict),
        "commonalities_release": _release_tag(deps.get("commonalities_release")),
        "icm_release": _release_tag(
            deps.get("identity_consent_management_release")
        ),
        "apis": [
            {
                "api_name": str(api.get("api_name") or ""),
                "api_version": str(api.get("api_version") or ""),
                "api_file_name": str(api.get("api_file_name") or ""),
            }
            for api in apis
            if isinstance(api, dict)
            and api.get("api_name")
            and api.get("api_version")
        ],
    }


def _release_tag(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    return stripped.split(maxsplit=1)[0] if stripped else ""


def resolve_history(
    *,
    repo: str,
    base_ref: str,
    token: str | None = None,
) -> dict[str, Any]:
    client = GitHubClient(repo=repo, token=token)
    lookup_status = "complete"
    published_releases: list[dict[str, Any]] = []

    # None tells the consumer the branch list is unknown; an empty list means
    # the repository has no maintenance branches.
    try:
        maintenance_branches: list[str] | None = sorted(
            branch.name for branch in client.list_branches("maintenance/*")
        )
    except GitHubClientError:
        maintenance_branches = None

    # Contract for the consumer (validation.context.release_history): a "partial"
    # snapshot never truncates the release list.  Partial means either the whole
    # listing failed (empty published_releases) or per-tag metadata was
    # unavailable (release entries present, metadata_available False).  The tag
    # list itself is always complete, so tag-only checks may rely on it while
    # metadata-dependent checks must guard on metadata_available.
    try:
        releases = client.get_releases(include_drafts=False)
    except GitHubClientError as exc:
        return {
            "schema_version": 1,
            "repository": repo,
            "base_ref": base_ref,
            "lookup_status": "partial",
            "lookup_error": str(exc),
            "published_releases": [],
            "maintenance_branches": maintenance_branches,
        }

    for release in releases:
        try:
            metadata = client.get_release_metadata(release.tag_name)
        except GitHubClientError:
            metadata = None
            lookup_status = "partial"
        if metadata is None:
            lookup_status = "partial"
        published_releases.append(_metadata_release(release, metadata))

    return {
        "schema_version": 1,
        "repository": repo,
        "base_ref": base_ref,
        "lookup_status": lookup_status,
        "history_scope": {
            "selection": "published-releases",
        },
        "published_releases": published_releases,
        "maintenance_branches": maintenance_branches,
    }


def write_outputs(outputs: dict[str, str], target: Path | None) -> None:
    if target is None:
        for key, value in outputs.items():
            print(f"{key}={value}")
        return
    with target.open("a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="Repository in owner/name form (default: $GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("GITHUB_BASE_REF", "main"),
        help="Base ref being validated.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Path to write release-history JSON. Defaults to RUNNER_TEMP.",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="Path to the GITHUB_OUTPUT file.",
    )
    args = parser.parse_args(argv)

    if not args.repo:
        print("::warning::Release-history lookup skipped: repository is unknown")
        return 0

    output_path = (
        Path(args.output)
        if args.output
        else Path(os.environ.get("RUNNER_TEMP", ".")) / "release-history.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = resolve_history(
        repo=args.repo,
        base_ref=args.base_ref,
        token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"),
    )
    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    write_outputs(
        {"release_history_path": str(output_path)},
        Path(args.github_output) if args.github_output else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
