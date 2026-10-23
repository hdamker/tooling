"""Tests for labels.py (the labels release automation applies)."""

import pytest

from release_automation.scripts.github_client import GitHubClientError
from release_automation.scripts.labels import (
    LABELS,
    RELEASE_ISSUE_LABELS,
    add_pr_labels,
    ensure_labels,
)


class FakeGitHub:
    def __init__(self, existing=(), fail_create=False, fail_add=False):
        self.existing = set(existing)
        self.fail_create = fail_create
        self.fail_add = fail_add
        self.looked_up = []
        self.created = []
        self.labelled = []

    def get_label(self, name):
        self.looked_up.append(name)
        return {"name": name} if name in self.existing else None

    def create_label(self, name, color, description=""):
        if self.fail_create:
            raise GitHubClientError("gh command failed: 422")
        self.created.append((name, color, description))
        self.existing.add(name)

    def add_pr_labels(self, pr_number, labels):
        if self.fail_add:
            raise GitHubClientError("gh command failed: label not found")
        self.labelled.append((pr_number, list(labels)))


def test_table_covers_every_label_ra_applies():
    names = [name for name, _, _ in LABELS]

    assert names == [
        "release-issue",
        "release-state:planned",
        "release-state:snapshot-active",
        "release-state:draft-ready",
        "release-state:published",
        "release-state:not-planned",
        "common-sync",
        "automated",
        "post-release",
    ]
    for _, color, description in LABELS:
        assert len(color) == 6 and int(color, 16) >= 0
        assert description


def test_release_issue_labels_are_the_issue_and_state_labels():
    assert RELEASE_ISSUE_LABELS == [
        "release-issue",
        "release-state:planned",
        "release-state:snapshot-active",
        "release-state:draft-ready",
        "release-state:published",
        "release-state:not-planned",
    ]


def test_ensure_labels_creates_only_missing_ones():
    gh = FakeGitHub(existing={"automated"})

    created = ensure_labels(gh, ["common-sync", "automated"])

    assert created == ["common-sync"]
    assert gh.looked_up == ["common-sync", "automated"]
    assert [name for name, _, _ in gh.created] == ["common-sync"]


def test_ensure_labels_uses_table_color_and_description():
    gh = FakeGitHub()

    ensure_labels(gh, ["release-issue"])

    assert gh.created == [("release-issue", "5319E7", "Release tracking issue managed by automation")]


def test_ensure_labels_rejects_a_name_outside_the_table():
    with pytest.raises(KeyError):
        ensure_labels(FakeGitHub(), ["needs-triage"])


def test_add_pr_labels_creates_then_labels():
    gh = FakeGitHub()

    add_pr_labels(gh, 31, ["post-release", "automated"])

    assert [name for name, _, _ in gh.created] == ["post-release", "automated"]
    assert gh.labelled == [(31, ["post-release", "automated"])]


def test_add_pr_labels_failure_is_a_warning(capsys):
    gh = FakeGitHub(existing={"post-release", "automated"}, fail_add=True)

    add_pr_labels(gh, 31, ["post-release", "automated"])

    out = capsys.readouterr().out
    assert "::warning::Could not add labels post-release, automated to #31: gh command failed: label not found" in out


def test_label_creation_failure_is_a_warning_and_labelling_still_tried(capsys):
    gh = FakeGitHub(existing={"automated"}, fail_create=True)

    add_pr_labels(gh, 31, ["post-release", "automated"])

    assert "::warning::Could not create label post-release: gh command failed: 422" in capsys.readouterr().out
    assert gh.labelled == [(31, ["post-release", "automated"])]
