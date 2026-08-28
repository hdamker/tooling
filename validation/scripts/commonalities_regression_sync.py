#!/usr/bin/env python3
"""
CAMARA Validation Framework — CommonalitiesTest Regression Sync

Path-scoped content diff and copy/manifest logic for the tooling-owned
CommonalitiesTest regression pipeline. Each sub-command operates on
already-checked-out local directories; the calling workflow owns cloning,
committing, cherry-picking, and pushing.

Sub-commands:
    diff-common     --source DIR --dest DIR [--github-output FILE]
    diff-templates  --source DIR --dest DIR [--github-output FILE]
    sync-common     --source DIR --dest DIR --release-plan FILE
    sync-templates  --source DIR --dest DIR

diff-* sub-commands write `common_changed=true|false` /
`templates_changed=true|false` to $GITHUB_OUTPUT (or --github-output) and
always exit 0 — the diff result is data, not a pass/fail signal.

The diff is a path-scoped content compare, not a HEAD-moved check: the
Commonalities `main` HEAD can move for reasons entirely outside these
paths, so a raw SHA comparison is neither necessary nor sufficient for
"there is something to sync."
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import yaml

MANIFEST_FILENAME = ".sync-manifest.yaml"


def git_blob_sha(content: bytes) -> str:
    """SHA-1 matching `git hash-object` / the GitHub Contents API `.sha` field."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _yaml_files(directory: Path) -> dict[str, Path]:
    return {
        p.name: p
        for p in sorted(directory.glob("*.yaml"))
        if p.name != MANIFEST_FILENAME
    }


def diff_yaml_dirs(source: Path, dest: Path) -> bool:
    """True if the `*.yaml` file set or content of `dest` differs from `source`.

    `source` must exist. A missing `dest` counts as changed (nothing synced
    yet). `.sync-manifest.yaml` in `dest` is not a source file and is ignored.
    """
    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")
    if not dest.is_dir():
        return True

    source_files = _yaml_files(source)
    dest_files = _yaml_files(dest)

    if set(source_files) != set(dest_files):
        return True

    for name, source_path in source_files.items():
        if source_path.read_bytes() != dest_files[name].read_bytes():
            return True

    return False


def read_commonalities_release(release_plan_path: Path) -> str:
    """Read `commonalities_release` from a CommonalitiesTest `release-plan.yaml`.

    The synced manifest's `release` field must string-agree with this value
    (P-021's sync-status check) -- reading it here keeps release-plan.yaml
    the single place that changes when Commonalities advances its target
    release, instead of also hardcoding the value into the pipeline.
    """
    data = yaml.safe_load(release_plan_path.read_text(encoding="utf-8"))
    return data["commonalities_release"]


def sync_common(source: Path, dest: Path, release_label: str) -> dict[str, str]:
    """Copy `*.yaml` from `source` into `dest`, replacing `dest`'s current set.

    Writes `.sync-manifest.yaml` in `dest` per the shape the RA sync-common
    handler already produces (tooling_lib.cache_sync's expected schema).
    Returns the filename -> git-blob-sha map written into the manifest.
    """
    dest.mkdir(parents=True, exist_ok=True)

    for stale in _yaml_files(dest).values():
        stale.unlink()

    files: dict[str, str] = {}
    for name, source_path in sorted(_yaml_files(source).items()):
        content = source_path.read_bytes()
        (dest / name).write_bytes(content)
        files[name] = git_blob_sha(content)

    manifest = {
        "sources": [
            {
                "repository": "Commonalities",
                "release": release_label,
                "files": files,
            }
        ]
    }
    (dest / MANIFEST_FILENAME).write_text(
        yaml.dump(manifest, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return files


def sync_templates(source: Path, dest: Path) -> list[str]:
    """Copy `*.yaml` from `source` into `dest`, replacing `dest`'s current set.

    Unsubstituted — a faithful copy including Commonalities' own placeholder
    markers. Models the fresh mirror, not a published API repository.
    """
    dest.mkdir(parents=True, exist_ok=True)

    for stale in _yaml_files(dest).values():
        stale.unlink()

    copied = []
    for name, source_path in sorted(_yaml_files(source).items()):
        (dest / name).write_bytes(source_path.read_bytes())
        copied.append(name)
    return copied


def _write_github_output(path: str | None, key: str, value: str) -> None:
    line = f"{key}={value}\n"
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    else:
        print(line, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="commonalities_regression_sync.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", required=True, type=Path)
        p.add_argument("--dest", required=True, type=Path)

    p_diff_common = sub.add_parser("diff-common")
    add_common_args(p_diff_common)
    p_diff_common.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))

    p_diff_templates = sub.add_parser("diff-templates")
    add_common_args(p_diff_templates)
    p_diff_templates.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))

    p_sync_common = sub.add_parser("sync-common")
    add_common_args(p_sync_common)
    p_sync_common.add_argument("--release-plan", required=True, type=Path)

    p_sync_templates = sub.add_parser("sync-templates")
    add_common_args(p_sync_templates)

    args = parser.parse_args(argv)

    if args.command == "diff-common":
        changed = diff_yaml_dirs(args.source, args.dest)
        _write_github_output(args.github_output, "common_changed", "true" if changed else "false")
        print(f"common_changed={'true' if changed else 'false'}")
        return 0

    if args.command == "diff-templates":
        changed = diff_yaml_dirs(args.source, args.dest)
        _write_github_output(args.github_output, "templates_changed", "true" if changed else "false")
        print(f"templates_changed={'true' if changed else 'false'}")
        return 0

    if args.command == "sync-common":
        release_label = read_commonalities_release(args.release_plan)
        files = sync_common(args.source, args.dest, release_label=release_label)
        print(f"synced {len(files)} common file(s) into {args.dest} (release={release_label})")
        return 0

    if args.command == "sync-templates":
        copied = sync_templates(args.source, args.dest)
        print(f"synced {len(copied)} template file(s) into {args.dest}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
