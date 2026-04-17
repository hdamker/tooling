"""Unit tests for tooling_lib.cache_sync."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict

import yaml

from tooling_lib.cache_sync import (
    COMMON_DIR,
    MANIFEST_FILENAME,
    SourceStatus,
    SyncStatus,
    check_sync_status,
    git_blob_sha,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blob_sha(content: bytes) -> str:
    """Reference implementation for expected SHA values in tests."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _write_manifest(
    tmp_path: Path,
    sources: list,
) -> None:
    """Write a .sync-manifest.yaml into code/common/."""
    common_dir = tmp_path / COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": sources}
    (common_dir / MANIFEST_FILENAME).write_text(
        yaml.dump(manifest, default_flow_style=False), encoding="utf-8"
    )


def _write_common_file(tmp_path: Path, filename: str, content: str) -> str:
    """Write a file into code/common/ and return its git blob SHA."""
    common_dir = tmp_path / COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    (common_dir / filename).write_text(content, encoding="utf-8")
    return _blob_sha(data)


def _make_source(
    repo: str = "Commonalities",
    release: str = "r4.2",
    files: Dict[str, str] | None = None,
) -> dict:
    """Build a manifest source entry."""
    return {
        "repository": repo,
        "release": release,
        "files": files or {},
    }


# ---------------------------------------------------------------------------
# git_blob_sha
# ---------------------------------------------------------------------------


class TestGitBlobSha:

    def test_known_content(self):
        content = b"hello world"
        expected = hashlib.sha1(b"blob 11\0hello world").hexdigest()
        assert git_blob_sha(content) == expected

    def test_empty_content(self):
        expected = hashlib.sha1(b"blob 0\0").hexdigest()
        assert git_blob_sha(b"") == expected

    def test_binary_content(self):
        content = bytes(range(256))
        header = f"blob {len(content)}\0".encode("ascii")
        expected = hashlib.sha1(header + content).hexdigest()
        assert git_blob_sha(content) == expected


# ---------------------------------------------------------------------------
# check_sync_status — structural checks
# ---------------------------------------------------------------------------


class TestSyncStatusStructural:

    def test_no_common_dir(self, tmp_path: Path):
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.no_common_dir is True
        assert status.in_sync is False

    def test_no_manifest(self, tmp_path: Path):
        (tmp_path / COMMON_DIR).mkdir(parents=True)
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.no_manifest is True
        assert status.in_sync is False

    def test_invalid_yaml_manifest(self, tmp_path: Path):
        common_dir = tmp_path / COMMON_DIR
        common_dir.mkdir(parents=True)
        (common_dir / MANIFEST_FILENAME).write_text(
            ": invalid: yaml: [", encoding="utf-8"
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.no_manifest is True

    def test_manifest_missing_sources_key(self, tmp_path: Path):
        common_dir = tmp_path / COMMON_DIR
        common_dir.mkdir(parents=True)
        (common_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"version": 1}), encoding="utf-8"
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.no_manifest is True

    def test_manifest_sources_not_a_list(self, tmp_path: Path):
        common_dir = tmp_path / COMMON_DIR
        common_dir.mkdir(parents=True)
        (common_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"sources": "not-a-list"}), encoding="utf-8"
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.no_manifest is True


# ---------------------------------------------------------------------------
# check_sync_status — tag matching
# ---------------------------------------------------------------------------


class TestSyncStatusTagMatch:

    def test_tag_matches(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "content")
        _write_manifest(
            tmp_path,
            [_make_source(files={"CAMARA_common.yaml": sha})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is True
        assert len(status.sources) == 1
        assert status.sources[0].tag_mismatch is None

    def test_tag_mismatch(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "content")
        _write_manifest(
            tmp_path,
            [_make_source(release="r4.1", files={"CAMARA_common.yaml": sha})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is False
        assert status.sources[0].tag_mismatch == ("r4.2", "r4.1")

    def test_source_not_in_manifest(self, tmp_path: Path):
        _write_manifest(tmp_path, [_make_source(repo="OtherRepo")])
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is False
        assert len(status.sources) == 1
        assert status.sources[0].tag_mismatch == ("r4.2", "<not in manifest>")


# ---------------------------------------------------------------------------
# check_sync_status — file integrity
# ---------------------------------------------------------------------------


class TestSyncStatusFileIntegrity:

    def test_file_matches(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "data")
        _write_manifest(
            tmp_path,
            [_make_source(files={"CAMARA_common.yaml": sha})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is True
        assert status.sources[0].missing_files == []
        assert status.sources[0].modified_files == []

    def test_file_missing(self, tmp_path: Path):
        (tmp_path / COMMON_DIR).mkdir(parents=True, exist_ok=True)
        _write_manifest(
            tmp_path,
            [_make_source(files={"CAMARA_common.yaml": "a" * 40})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is False
        assert status.sources[0].missing_files == ["CAMARA_common.yaml"]

    def test_file_modified(self, tmp_path: Path):
        original_sha = _blob_sha(b"original content")
        _write_common_file(tmp_path, "CAMARA_common.yaml", "modified content")
        _write_manifest(
            tmp_path,
            [_make_source(files={"CAMARA_common.yaml": original_sha})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is False
        assert status.sources[0].modified_files == ["CAMARA_common.yaml"]

    def test_multiple_files_mixed(self, tmp_path: Path):
        sha_ok = _write_common_file(tmp_path, "CAMARA_common.yaml", "ok")
        sha_wrong = _blob_sha(b"expected")
        _write_common_file(tmp_path, "CAMARA_event_common.yaml", "actual")
        _write_manifest(
            tmp_path,
            [
                _make_source(
                    files={
                        "CAMARA_common.yaml": sha_ok,
                        "CAMARA_event_common.yaml": sha_wrong,
                        "CAMARA_missing.yaml": "b" * 40,
                    }
                )
            ],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is False
        src = status.sources[0]
        assert src.missing_files == ["CAMARA_missing.yaml"]
        assert src.modified_files == ["CAMARA_event_common.yaml"]

    def test_empty_files_dict(self, tmp_path: Path):
        _write_manifest(tmp_path, [_make_source(files={})])
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        # Tag matches, no files to check → in sync.
        assert status.in_sync is True


# ---------------------------------------------------------------------------
# check_sync_status — multi-source / extra files
# ---------------------------------------------------------------------------


class TestSyncStatusMultiSource:

    def test_extra_local_files_ignored(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "content")
        _write_common_file(tmp_path, "local_extra.yaml", "extra stuff")
        _write_manifest(
            tmp_path,
            [_make_source(files={"CAMARA_common.yaml": sha})],
        )
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is True

    def test_multiple_sources(self, tmp_path: Path):
        sha1 = _write_common_file(tmp_path, "CAMARA_common.yaml", "c1")
        sha2 = _write_common_file(tmp_path, "QoS_common.yaml", "q1")
        _write_manifest(
            tmp_path,
            [
                _make_source(
                    repo="Commonalities",
                    release="r4.2",
                    files={"CAMARA_common.yaml": sha1},
                ),
                _make_source(
                    repo="QoSProfiles",
                    release="r1.1",
                    files={"QoS_common.yaml": sha2},
                ),
            ],
        )
        status = check_sync_status(
            tmp_path,
            {"Commonalities": "r4.2", "QoSProfiles": "r1.1"},
        )
        assert status.in_sync is True
        assert len(status.sources) == 2

    def test_manifest_source_not_in_expected_skipped(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "c1")
        _write_manifest(
            tmp_path,
            [
                _make_source(
                    repo="Commonalities",
                    release="r4.2",
                    files={"CAMARA_common.yaml": sha},
                ),
                _make_source(
                    repo="UnexpectedRepo",
                    release="r1.1",
                    files={"other.yaml": "c" * 40},
                ),
            ],
        )
        # Only checking Commonalities — UnexpectedRepo is skipped.
        status = check_sync_status(tmp_path, {"Commonalities": "r4.2"})
        assert status.in_sync is True
        assert len(status.sources) == 1
        assert status.sources[0].repository == "Commonalities"


# ---------------------------------------------------------------------------
# SourceStatus.in_sync property
# ---------------------------------------------------------------------------


class TestSourceStatusProperty:

    def test_in_sync_when_clean(self):
        s = SourceStatus(repository="X")
        assert s.in_sync is True

    def test_not_in_sync_tag_mismatch(self):
        s = SourceStatus(repository="X", tag_mismatch=("r4.2", "r4.1"))
        assert s.in_sync is False

    def test_not_in_sync_missing_files(self):
        s = SourceStatus(repository="X", missing_files=["a.yaml"])
        assert s.in_sync is False

    def test_not_in_sync_modified_files(self):
        s = SourceStatus(repository="X", modified_files=["a.yaml"])
        assert s.in_sync is False


# ---------------------------------------------------------------------------
# SyncStatus.in_sync property
# ---------------------------------------------------------------------------


class TestSyncStatusProperty:

    def test_in_sync_all_sources_ok(self):
        s = SyncStatus(sources=[SourceStatus(repository="X")])
        assert s.in_sync is True

    def test_not_in_sync_no_common_dir(self):
        s = SyncStatus(no_common_dir=True)
        assert s.in_sync is False

    def test_not_in_sync_no_manifest(self):
        s = SyncStatus(no_manifest=True)
        assert s.in_sync is False

    def test_not_in_sync_source_problem(self):
        s = SyncStatus(
            sources=[
                SourceStatus(repository="X", tag_mismatch=("a", "b")),
            ]
        )
        assert s.in_sync is False

    def test_empty_sources_is_in_sync(self):
        s = SyncStatus(sources=[])
        assert s.in_sync is True
