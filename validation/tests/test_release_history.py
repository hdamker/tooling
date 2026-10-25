"""Unit tests for validation.context.release_history."""

from __future__ import annotations

import json
from pathlib import Path

from validation.context.release_history import (
    load_release_history,
    normalize_api_version_base,
    parse_release_history,
    parse_release_tag,
)


def _history_payload(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "repository": "camaraproject/QualityOnDemand",
        "base_ref": "main",
        "lookup_status": "complete",
        "published_releases": [
            {
                "tag": "r4.2",
                "release_type": "public-release",
                "prerelease": False,
                "published_at": "2026-01-15T00:00:00Z",
                "src_commit_sha": "a" * 40,
                "metadata_available": True,
                "apis": [
                    {
                        "api_name": "quality-on-demand",
                        "api_version": "1.0.0",
                        "api_file_name": "quality-on-demand",
                    },
                    {
                        "api_name": "quality-on-demand",
                        "api_version": "1.1.0-rc.1",
                        "api_file_name": "quality-on-demand",
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_parse_release_tag_orders_camara_tags():
    assert parse_release_tag("r4.10") > parse_release_tag("r4.2")
    assert parse_release_tag("r5.1") > parse_release_tag("r4.99")
    assert parse_release_tag("not-a-release") is None


def test_normalize_api_version_base_strips_release_extensions():
    assert normalize_api_version_base("1.2.3-alpha.4") == "1.2.3"
    assert normalize_api_version_base("1.2.3-rc.1") == "1.2.3"
    assert normalize_api_version_base("1.2.3") == "1.2.3"


def test_parse_complete_history_snapshot():
    snapshot = parse_release_history(_history_payload())

    assert snapshot is not None
    assert snapshot.lookup_status == "complete"
    assert snapshot.latest_release().tag == "r4.2"
    assert snapshot.release_by_tag("r4.2").apis[0].api_name == "quality-on-demand"


def test_terminal_api_version_statuses_use_only_public_or_maintenance_releases():
    snapshot = parse_release_history(
        _history_payload(
            published_releases=[
                {
                    "tag": "r4.2",
                    "release_type": "public-release",
                    "metadata_available": True,
                    "apis": [
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.0.0",
                        }
                    ],
                },
                {
                    "tag": "r4.3",
                    "release_type": "pre-release-alpha",
                    "metadata_available": True,
                    "apis": [
                        {
                            "api_name": "quality-on-demand",
                            "api_version": "1.1.0-alpha.1",
                        }
                    ],
                },
            ]
        )
    )

    assert snapshot is not None
    assert snapshot.terminal_api_version_statuses("quality-on-demand") == {
        ("1.0.0", "public")
    }


def test_partial_history_with_release_entries_has_tag_coverage():
    snapshot = parse_release_history(
        _history_payload(
            lookup_status="partial",
            published_releases=[
                {
                    "tag": "r4.2",
                    "release_type": "",
                    "prerelease": False,
                    "metadata_available": False,
                    "apis": [],
                }
            ],
        )
    )

    assert snapshot is not None
    assert snapshot.release_tags_available() is True
    assert snapshot.may_have_missing_terminal_metadata() is True


def test_partial_history_without_release_entries_has_no_tag_coverage():
    snapshot = parse_release_history(
        _history_payload(lookup_status="partial", published_releases=[])
    )

    assert snapshot is not None
    assert snapshot.release_tags_available() is False
    assert snapshot.may_have_missing_terminal_metadata() is False


def test_maintenance_branches_parsed_and_absent_means_unknown():
    snapshot = parse_release_history(
        _history_payload(maintenance_branches=["maintenance/r1", "feature/x", 3])
    )
    assert snapshot is not None
    assert snapshot.maintenance_branches == ("maintenance/r1",)
    assert snapshot.has_maintenance_branch(1) is True
    assert snapshot.has_maintenance_branch(2) is False

    legacy = parse_release_history(_history_payload())
    assert legacy is not None
    assert legacy.maintenance_branches is None
    assert legacy.has_maintenance_branch(1) is None


def test_maintenance_line_releases_and_patched_release():
    snapshot = parse_release_history(
        _history_payload(
            published_releases=[
                {"tag": "r1.5", "release_type": "pre-release-rc", "prerelease": True,
                 "metadata_available": True, "apis": []},
                {"tag": "r1.6", "release_type": "public-release",
                 "metadata_available": True, "apis": []},
                {"tag": "r1.7", "release_type": "pre-release-rc", "prerelease": True,
                 "metadata_available": True, "apis": []},
                {"tag": "r2.1", "release_type": "pre-release-alpha", "prerelease": True,
                 "metadata_available": True, "apis": []},
            ]
        )
    )
    assert snapshot is not None
    assert snapshot.is_maintenance_line(1) is True
    assert snapshot.is_maintenance_line(2) is False
    assert snapshot.latest_release(cycle=1).tag == "r1.7"
    assert snapshot.latest_release().tag == "r2.1"
    assert snapshot.patched_release(1).tag == "r1.6"
    assert snapshot.patched_release(2) is None
    assert [r.tag for r in snapshot.later_cycle_releases(1)] == ["r2.1"]


def test_patched_release_unknown_when_newer_terminal_metadata_missing():
    snapshot = parse_release_history(
        _history_payload(
            lookup_status="partial",
            published_releases=[
                {"tag": "r1.6", "release_type": "public-release",
                 "metadata_available": True, "apis": []},
                {"tag": "r1.7", "release_type": "", "prerelease": False,
                 "metadata_available": False, "apis": []},
            ],
        )
    )
    assert snapshot is not None
    assert snapshot.is_maintenance_line(1) is True
    assert snapshot.patched_release(1) is None


def test_load_release_history_missing_path_returns_none(tmp_path: Path):
    assert load_release_history(tmp_path / "missing.json") is None


def test_load_release_history_invalid_json_returns_none(tmp_path: Path):
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")

    assert load_release_history(path) is None


def test_load_release_history_from_file(tmp_path: Path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_history_payload()), encoding="utf-8")

    snapshot = load_release_history(path)

    assert snapshot is not None
    assert snapshot.repository == "camaraproject/QualityOnDemand"
