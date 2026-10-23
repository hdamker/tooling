"""Tests for common_sync.py detection (code/common/ cache against the declared release).

Expected values reproduce the former inline `Check common cache sync` step of
release-automation-reusable.yml.
"""

from pathlib import Path

import pytest

from release_automation.scripts import common_sync
from release_automation.scripts.common_sync import CacheCheck, describe, detect
from tooling_lib.cache_sync import SourceStatus, SyncStatus


@pytest.mark.parametrize("release", ["", "main", "r4", "v4.2", "r4.2.1"])
def test_unparsable_release_is_not_checked(tmp_path, release):
    assert detect(tmp_path, release) == CacheCheck()


@pytest.mark.parametrize("release", ["r3.9", "r4.0", "r4.1"])
def test_release_before_r4_2_is_not_checked(tmp_path, release):
    assert detect(tmp_path, release) == CacheCheck()


@pytest.mark.parametrize("release", ["r4.2", "r4.10", "r5.1"])
def test_checked_releases_pass_expected_mapping(tmp_path, monkeypatch, release):
    seen = {}

    def fake_check(path, expected):
        seen.update(path=path, expected=expected)
        return SyncStatus(sources=[SourceStatus(repository="Commonalities")])

    monkeypatch.setattr(common_sync, "check_sync_status", fake_check)

    assert detect(tmp_path, release) == CacheCheck(status="in_sync")
    assert seen == {"path": tmp_path, "expected": {"Commonalities": release}}


def test_missing_common_dir_on_disk_is_stale(tmp_path):
    assert detect(tmp_path, "r4.2") == CacheCheck(
        status="stale", details="code/common/ directory is missing"
    )


def test_stale_result(tmp_path, monkeypatch):
    monkeypatch.setattr(common_sync, "check_sync_status", lambda p, e: SyncStatus(no_manifest=True))

    assert detect(tmp_path, "r4.2") == CacheCheck(
        status="stale", details="code/common/.sync-manifest.yaml is missing"
    )


@pytest.mark.parametrize(
    "status,details",
    [
        (SyncStatus(no_common_dir=True, no_manifest=True), "code/common/ directory is missing"),
        (SyncStatus(no_manifest=True), "code/common/.sync-manifest.yaml is missing"),
        (
            SyncStatus(sources=[
                SourceStatus(
                    repository="Commonalities",
                    tag_mismatch=("r4.3", "r4.2"),
                    missing_files=["CAMARA_common.yaml"],
                    modified_files=["CAMARA_event_common.yaml"],
                ),
            ]),
            "Commonalities: expected r4.3, manifest has r4.2; "
            "CAMARA_common.yaml missing from code/common/; "
            "CAMARA_event_common.yaml modified since last sync",
        ),
        (SyncStatus(sources=[]), "cache mismatch detected"),
    ],
)
def test_describe(status, details):
    assert describe(status) == details


def test_main_writes_outputs(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("API_REPO_PATH", str(tmp_path / "missing"))
    monkeypatch.setenv("COMMONALITIES_RELEASE", "r4.2")

    common_sync.main()

    from release_automation.tests.test_trigger import read_outputs
    assert read_outputs(output) == {
        "common_cache_status": "stale",
        "common_cache_details": "code/common/ directory is missing",
    }
