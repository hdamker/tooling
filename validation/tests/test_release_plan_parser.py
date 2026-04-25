"""Unit tests for validation.context.release_plan_parser."""

from pathlib import Path

import pytest
import yaml

from validation.context.release_plan_parser import (
    ReleasePlanData,
    is_valid_release_tag,
    load_release_plan,
    parse_release_plan,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "release-plan-schema.yaml"
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
def full_plan_dict():
    return {
        "repository": {
            "release_track": "meta-release",
            "meta_release": "Spring26",
            "target_release_tag": "r4.1",
            "target_release_type": "pre-release-rc",
        },
        "dependencies": {
            "commonalities_release": "r4.2",
            "identity_consent_management_release": "r4.3",
        },
        "apis": [
            {
                "api_name": "quality-on-demand",
                "target_api_version": "1.0.0",
                "target_api_status": "rc",
            },
            {
                "api_name": "qos-booking",
                "target_api_version": "0.5.0",
                "target_api_status": "alpha",
            },
        ],
    }


# ---------------------------------------------------------------------------
# TestParseReleasePlan
# ---------------------------------------------------------------------------


class TestParseReleasePlan:
    def test_full_plan(self, full_plan_dict):
        result = parse_release_plan(full_plan_dict)
        assert result.target_release_type == "pre-release-rc"
        assert result.commonalities_release == "r4.2"
        assert result.icm_release == "r4.3"
        assert len(result.apis) == 2
        assert result.apis[0].api_name == "quality-on-demand"
        assert result.apis[1].api_name == "qos-booking"

    def test_plan_without_dependencies(self):
        data = {
            "repository": {
                "release_track": "independent",
                "target_release_tag": "r4.1",
                "target_release_type": "public-release",
            },
            "apis": [
                {
                    "api_name": "some-api",
                    "target_api_version": "2.0.0",
                    "target_api_status": "public",
                },
            ],
        }
        result = parse_release_plan(data)
        assert result.commonalities_release is None
        assert result.icm_release is None

    def test_plan_with_multiple_apis(self, full_plan_dict):
        result = parse_release_plan(full_plan_dict)
        assert len(result.apis) == 2
        assert result.apis[0].target_api_version == "1.0.0"
        assert result.apis[1].target_api_version == "0.5.0"

    def test_plan_with_none_release_type(self):
        data = {
            "repository": {
                "release_track": "independent",
                "target_release_tag": None,
                "target_release_type": "none",
            },
            "apis": [
                {
                    "api_name": "draft-api",
                    "target_api_version": "0.1.0",
                    "target_api_status": "draft",
                },
            ],
        }
        result = parse_release_plan(data)
        assert result.target_release_type == "none"


# ---------------------------------------------------------------------------
# TestLoadReleasePlan
# ---------------------------------------------------------------------------


class TestLoadReleasePlan:
    def test_valid_file(self, tmp_path, schema_path, full_plan_dict):
        plan_path = _write_yaml(tmp_path / "release-plan.yaml", full_plan_dict)
        result = load_release_plan(plan_path, schema_path)
        assert result is not None
        assert result.target_release_type == "pre-release-rc"
        assert len(result.apis) == 2

    def test_missing_file_returns_none(self, tmp_path, schema_path):
        result = load_release_plan(tmp_path / "release-plan.yaml", schema_path)
        assert result is None

    def test_empty_file_returns_none(self, tmp_path, schema_path):
        plan_path = tmp_path / "release-plan.yaml"
        plan_path.write_text("", encoding="utf-8")
        result = load_release_plan(plan_path, schema_path)
        assert result is None


# ---------------------------------------------------------------------------
# is_valid_release_tag
# ---------------------------------------------------------------------------


class TestIsValidReleaseTag:
    """CAMARA release-tag format precheck used by P-023."""

    @pytest.mark.parametrize(
        "tag",
        ["r1.1", "r1.2", "r4.2", "r10.20", "r99.99"],
    )
    def test_valid_tags(self, tag: str):
        assert is_valid_release_tag(tag) is True

    @pytest.mark.parametrize(
        "tag",
        [
            "r0.0",  # zero major
            "r0.1",  # zero major
            "r1.0",  # zero minor (not used in CAMARA history)
            "r4.x",  # non-numeric minor
            "r4",  # missing minor
            "4.2",  # missing leading r
            "R4.2",  # uppercase R
            "r04.2",  # leading-zero major
            "r4.02",  # leading-zero minor
            "r4.2-rc.1",  # extra suffix
            "r4.2 (1.2.0-rc.1)",  # enriched format — not a valid raw tag
            "",  # empty
            " r4.2",  # leading whitespace
            "r4.2 ",  # trailing whitespace
        ],
    )
    def test_invalid_tags(self, tag: str):
        assert is_valid_release_tag(tag) is False
