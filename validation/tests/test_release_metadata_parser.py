"""Unit tests for validation.context.release_metadata_parser."""

from pathlib import Path

import pytest
import yaml

from validation.context.release_metadata_parser import (
    _derive_api_status,
    _extract_release_tag,
    load_release_metadata,
    parse_release_metadata,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "release-metadata-schema.yaml"
)


def _write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schema_path():
    return SCHEMA_PATH


@pytest.fixture
def full_metadata_dict():
    return {
        "repository": {
            "repository_name": "QualityOnDemand",
            "release_tag": "r4.1",
            "release_type": "pre-release-rc",
            "release_date": None,
            "src_commit_sha": "a" * 40,
        },
        "dependencies": {
            "commonalities_release": "r4.2 (1.2.0-rc.1)",
            "identity_consent_management_release": "r4.3 (1.1.0)",
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "api_version": "1.0.0-rc.2",
                "api_title": "Quality On Demand",
            },
            {
                "api_name": "qos-booking",
                "api_version": "0.5.0-alpha.1",
                "api_title": "QoS Booking",
            },
        ],
    }


# ---------------------------------------------------------------------------
# TestExtractReleaseTag
# ---------------------------------------------------------------------------


class TestExtractReleaseTag:
    def test_enriched_format(self):
        assert _extract_release_tag("r4.2 (1.2.0-rc.1)") == "r4.2"

    def test_plain_tag(self):
        assert _extract_release_tag("r4.2") == "r4.2"

    def test_double_digit(self):
        assert _extract_release_tag("r12.34 (2.0.0)") == "r12.34"

    def test_none(self):
        assert _extract_release_tag(None) is None

    def test_empty(self):
        assert _extract_release_tag("") is None

    def test_invalid(self):
        assert _extract_release_tag("not-a-tag") is None

    def test_whitespace(self):
        assert _extract_release_tag("  r4.2 (1.0.0)") == "r4.2"


# ---------------------------------------------------------------------------
# TestDeriveApiStatus
# ---------------------------------------------------------------------------


class TestDeriveApiStatus:
    def test_alpha(self):
        assert _derive_api_status("0.5.0-alpha.1") == "alpha"

    def test_rc(self):
        assert _derive_api_status("1.0.0-rc.2") == "rc"

    def test_public(self):
        assert _derive_api_status("1.0.0") == "public"

    def test_public_patch(self):
        assert _derive_api_status("2.1.3") == "public"

    def test_initial_public(self):
        assert _derive_api_status("0.1.0") == "public"


# ---------------------------------------------------------------------------
# TestParseReleaseMetadata
# ---------------------------------------------------------------------------


class TestParseReleaseMetadata:
    def test_full_metadata(self, full_metadata_dict):
        result = parse_release_metadata(full_metadata_dict)
        assert result.target_release_type == "pre-release-rc"
        assert result.commonalities_release == "r4.2"
        assert result.icm_release == "r4.3"
        assert len(result.apis) == 2
        assert result.apis[0].api_name == "quality-on-demand"
        assert result.apis[0].target_api_version == "1.0.0-rc.2"
        assert result.apis[0].target_api_status == "rc"
        assert result.apis[1].api_name == "qos-booking"
        assert result.apis[1].target_api_version == "0.5.0-alpha.1"
        assert result.apis[1].target_api_status == "alpha"

    def test_metadata_without_dependencies(self):
        data = {
            "repository": {
                "repository_name": "Foo",
                "release_tag": "r4.1",
                "release_type": "public-release",
                "release_date": None,
                "src_commit_sha": "b" * 40,
            },
            "apis": [
                {
                    "api_name": "foo-api",
                    "api_version": "1.0.0",
                    "api_title": "Foo API",
                },
            ],
        }
        result = parse_release_metadata(data)
        assert result.target_release_type == "public-release"
        assert result.commonalities_release is None
        assert result.icm_release is None
        assert len(result.apis) == 1
        assert result.apis[0].target_api_status == "public"

    def test_metadata_without_apis(self):
        data = {
            "repository": {
                "repository_name": "Foo",
                "release_tag": "r4.1",
                "release_type": "public-release",
                "release_date": None,
                "src_commit_sha": "c" * 40,
            },
        }
        result = parse_release_metadata(data)
        assert result.apis == ()

    def test_api_with_missing_fields_skipped(self):
        data = {
            "repository": {
                "repository_name": "Foo",
                "release_tag": "r4.1",
                "release_type": "public-release",
                "release_date": None,
                "src_commit_sha": "d" * 40,
            },
            "apis": [
                {"api_name": "good-api", "api_version": "1.0.0", "api_title": "Good"},
                {"api_name": "no-version"},  # missing api_version
            ],
        }
        result = parse_release_metadata(data)
        assert len(result.apis) == 1
        assert result.apis[0].api_name == "good-api"


# ---------------------------------------------------------------------------
# TestLoadReleaseMetadata
# ---------------------------------------------------------------------------


class TestLoadReleaseMetadata:
    def test_load_valid(self, tmp_path, schema_path, full_metadata_dict):
        metadata_file = _write_yaml(tmp_path / "release-metadata.yaml", full_metadata_dict)
        result = load_release_metadata(metadata_file, schema_path)
        assert result is not None
        assert result.target_release_type == "pre-release-rc"
        assert result.commonalities_release == "r4.2"
        assert len(result.apis) == 2

    def test_missing_file(self, tmp_path, schema_path):
        result = load_release_metadata(tmp_path / "nonexistent.yaml", schema_path)
        assert result is None

    def test_empty_file(self, tmp_path, schema_path):
        (tmp_path / "release-metadata.yaml").write_text("", encoding="utf-8")
        result = load_release_metadata(tmp_path / "release-metadata.yaml", schema_path)
        assert result is None

    def test_invalid_yaml(self, tmp_path, schema_path):
        (tmp_path / "release-metadata.yaml").write_text(
            "{{invalid yaml", encoding="utf-8"
        )
        result = load_release_metadata(tmp_path / "release-metadata.yaml", schema_path)
        assert result is None

    def test_schema_violation_graceful(self, tmp_path, schema_path):
        """Schema violations log warnings but still return parsed data."""
        data = {
            "repository": {"release_type": "public-release"},
            # missing required fields — schema violation
            "apis": [
                {"api_name": "foo", "api_version": "1.0.0", "api_title": "Foo"},
            ],
        }
        metadata_file = _write_yaml(tmp_path / "release-metadata.yaml", data)
        result = load_release_metadata(metadata_file, schema_path)
        assert result is not None
        assert result.target_release_type == "public-release"
