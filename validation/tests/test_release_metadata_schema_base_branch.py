"""release-metadata-schema.yaml: optional repository.base_branch (audit field, written by release automation)."""

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator

SCHEMA = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "schemas" / "release-metadata-schema.yaml").read_text()
)


def metadata(**repository):
    return {
        "repository": {
            "repository_name": "ReleaseTest2",
            "release_tag": "r1.8",
            "release_type": "maintenance-release",
            "release_date": None,
            "src_commit_sha": "a" * 40,
            **repository,
        },
        "apis": [{
            "api_name": "sample-service",
            "api_version": "0.1.2",
            "api_title": "Sample Service",
        }],
    }


@pytest.mark.parametrize("repository", [{}, {"base_branch": "main"}, {"base_branch": "maintenance/r1"}])
def test_valid(repository):
    assert list(Draft7Validator(SCHEMA).iter_errors(metadata(**repository))) == []


@pytest.mark.parametrize("base_branch", ["maintenance-r1", "maintenance/r0", "feature/x", ""])
def test_invalid_base_branch(base_branch):
    errors = list(Draft7Validator(SCHEMA).iter_errors(metadata(base_branch=base_branch)))

    assert [list(e.path) for e in errors] == [["repository", "base_branch"]]
