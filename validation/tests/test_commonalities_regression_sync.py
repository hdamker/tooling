"""Unit tests for validation.scripts.commonalities_regression_sync.

Covers pure-logic functions only: content diff (added/removed/modified) and
copy+manifest writing. Git/gh orchestration is verified manually during
integration (same convention as test_regression_runner.py).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "validation" / "scripts" / "commonalities_regression_sync.py"
_spec = importlib.util.spec_from_file_location("commonalities_regression_sync", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
crs = importlib.util.module_from_spec(_spec)
sys.modules["commonalities_regression_sync"] = crs
_spec.loader.exec_module(crs)


diff_yaml_dirs = crs.diff_yaml_dirs
read_commonalities_release = crs.read_commonalities_release
sync_common = crs.sync_common
sync_templates = crs.sync_templates
MANIFEST_FILENAME = crs.MANIFEST_FILENAME


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# diff_yaml_dirs
# ---------------------------------------------------------------------------


def test_diff_identical_dirs_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "a.yaml", "a: 1\n")

    assert diff_yaml_dirs(source, dest) is False


def test_diff_modified_file_is_changed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "a.yaml", "a: 2\n")

    assert diff_yaml_dirs(source, dest) is True


def test_diff_added_file_is_changed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(source / "b.yaml", "b: 1\n")
    _write(dest / "a.yaml", "a: 1\n")

    assert diff_yaml_dirs(source, dest) is True


def test_diff_removed_file_is_changed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "a.yaml", "a: 1\n")
    _write(dest / "b.yaml", "b: 1\n")

    assert diff_yaml_dirs(source, dest) is True


def test_diff_ignores_manifest_file_in_dest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "a.yaml", "a: 1\n")
    _write(dest / MANIFEST_FILENAME, "sources: []\n")

    assert diff_yaml_dirs(source, dest) is False


def test_diff_missing_dest_dir_is_changed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")

    assert diff_yaml_dirs(source, dest) is True


def test_diff_missing_source_dir_raises(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(dest / "a.yaml", "a: 1\n")

    with pytest.raises(FileNotFoundError):
        diff_yaml_dirs(source, dest)


# ---------------------------------------------------------------------------
# read_commonalities_release
# ---------------------------------------------------------------------------


def test_read_commonalities_release(tmp_path: Path) -> None:
    path = tmp_path / "release-plan.yaml"
    _write(path, "commonalities_release: r4.4\nrelease_track: independent\n")

    assert read_commonalities_release(path) == "r4.4"


def test_read_commonalities_release_missing_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "release-plan.yaml"
    _write(path, "release_track: independent\n")

    with pytest.raises(KeyError):
        read_commonalities_release(path)


# ---------------------------------------------------------------------------
# sync_common
# ---------------------------------------------------------------------------


def test_sync_common_copies_files_and_writes_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "CAMARA_common.yaml", "a: 1\n")
    _write(source / "CAMARA_event_common.yaml", "b: 1\n")
    dest.mkdir(parents=True)

    files = sync_common(source, dest, release_label="r4.4")

    assert (dest / "CAMARA_common.yaml").read_text(encoding="utf-8") == "a: 1\n"
    assert (dest / "CAMARA_event_common.yaml").read_text(encoding="utf-8") == "b: 1\n"
    assert set(files) == {"CAMARA_common.yaml", "CAMARA_event_common.yaml"}

    manifest = yaml.safe_load((dest / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["sources"][0]["repository"] == "Commonalities"
    assert manifest["sources"][0]["release"] == "r4.4"
    assert manifest["sources"][0]["files"] == files


def test_sync_common_removes_stale_dest_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "a.yaml", "a: 1\n")
    _write(dest / "stale.yaml", "stale: true\n")

    sync_common(source, dest, release_label="r4.4")

    assert not (dest / "stale.yaml").exists()


def test_sync_common_manifest_sha_matches_git_hash_object(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    dest.mkdir(parents=True)

    files = sync_common(source, dest, release_label="r4.4")

    # git hash-object semantics: sha1("blob {len}\0" + content)
    import hashlib

    content = b"a: 1\n"
    expected = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    assert files["a.yaml"] == expected


# ---------------------------------------------------------------------------
# sync_templates
# ---------------------------------------------------------------------------


def test_sync_templates_copies_yaml_files_unsubstituted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "sample-service.yaml", "externalDocs:\n  url: '{apiRepository}'\n")
    dest.mkdir(parents=True)

    copied = sync_templates(source, dest)

    assert copied == ["sample-service.yaml"]
    assert (dest / "sample-service.yaml").read_text(encoding="utf-8") == (
        "externalDocs:\n  url: '{apiRepository}'\n"
    )


def test_sync_templates_removes_stale_dest_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.yaml", "a: 1\n")
    _write(dest / "old.yaml", "old: true\n")

    sync_templates(source, dest)

    assert not (dest / "old.yaml").exists()
    assert (dest / "a.yaml").exists()
