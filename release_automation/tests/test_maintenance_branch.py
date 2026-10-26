"""Tests for maintenance_branch.py: create-maintenance-branch checks and creation (spec 3.1-3.6)."""

from dataclasses import fields

import pytest
import yaml

from release_automation.scripts.maintenance_branch import (
    BranchPlan,
    CreateResult,
    check,
    create,
)
from release_automation.scripts.state_manager import ReleaseState, ReleaseStateManager
from release_automation.tests.fake_github import FakeGitHub, gh_error

MB = "maintenance/r1"
SRC = "a" * 40

PLAN_R18 = """\
# CAMARA Release Plan
repository:
  release_track: independent

  # Release tag -- first release for a repository is r1.1
  target_release_tag: r1.8

  # Options: none | pre-release-alpha | pre-release-rc | public-release | maintenance-release
  target_release_type: maintenance-release

dependencies:
  commonalities_release: r4.4

apis:
  - api_name: sample-service
    target_api_version: 0.1.2
    target_api_status: public
"""

RA_CALLER = "name: CAMARA Release Automation\n# main's caller\n"
VF_CALLER = "name: CAMARA Validation\n# main's caller\n"
CHANGELOG_R18 = "# r1.8\n\n# r1.7\n\n# r1.6\n"


def release(tag, prerelease=False, draft=False):
    return {"tag": tag, "draft": draft, "prerelease": prerelease, "html_url": f"https://x/releases/tag/{tag}"}


def metadata(tag, sha=SRC):
    return f"repository:\n  release_tag: {tag}\n  src_commit_sha: {sha}\n"


def repo(releases=None, branches=None, files=None, tags=None, fail=None):
    """ReleaseTest2's cycle 1: rc pre-releases r1.1-r1.5, public r1.6, maintenance r1.7 and r1.8."""
    if releases is None:
        releases = [release(f"r1.{n}", prerelease=True) for n in range(1, 6)]
        releases += [release("r1.6"), release("r1.7"), release("r1.8")]
    base_files = {
        ("r1.8", "release-metadata.yaml"): metadata("r1.8"),
        ("r1.8", "CHANGELOG/CHANGELOG-r1.md"): CHANGELOG_R18,
        ("main", ".github/workflows/release-automation.yml"): RA_CALLER,
        ("main", ".github/workflows/camara-validation.yml"): VF_CALLER,
        (SRC, "release-plan.yaml"): PLAN_R18,
    }
    return FakeGitHub(
        releases=releases,
        branches={"main": "m1", **(branches or {})},
        files={**base_files, **(files or {})},
        tags={"r1.8": "t18", "source/r1.8": SRC, **(tags or {})},
        fail=fail,
    )


PLAN = BranchPlan(cycle="r1", branch=MB, patched_release="r1.8", patched_sha=SRC, next_tag="r1.9")


# ── checks ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("main_tag", ["r2.1", "r3.1"])
def test_main_on_a_later_cycle_gets_a_branch_plan(main_tag):
    # spec 3.5: any type on main, none included — only the tag's cycle counts
    assert check(repo(), "r1", main_tag) == PLAN


@pytest.mark.parametrize("main_tag", ["r1.9", "r1.8"])
def test_refused_while_main_is_still_on_the_cycle(main_tag):
    # spec 3.1
    message = check(repo(), "r1", main_tag)

    assert f"main has not left cycle r1: release-plan.yaml on main targets {main_tag}" in message


def test_refused_when_the_newest_release_of_the_cycle_is_a_pre_release():
    # spec 3.2: an rc on the line published from main is finished from main first
    gh = repo(releases=[release("r1.6"), release("r1.7"), release("r1.8", prerelease=True)])

    message = check(gh, "r1", "r2.1")

    assert "r1.8, the newest release of cycle r1, is a pre-release" in message


def test_refused_when_the_branch_exists():
    # spec 3.3
    message = check(repo(branches={MB: "b1"}), "r1", "r2.1")

    assert message == f"{MB} already exists."


def test_refused_without_a_public_release_in_the_cycle():
    gh = repo(releases=[release("r1.1", prerelease=True), release("r2.1")])

    assert check(gh, "r1", "r2.1") == "Cycle r1 has no public release to maintain."


@pytest.mark.parametrize("cycle", ["", "1", "r0", "r1.8", "maintenance/r1"])
def test_refused_for_a_cycle_that_is_not_rx(cycle):
    assert "cycle must name a release cycle" in check(repo(), cycle, "r2.1")


def test_newest_release_by_tag_version_not_by_date():
    # r1.10 published before r1.9 (listing order is by date)
    gh = repo(
        releases=[release("r1.6"), release("r1.10"), release("r1.9")],
        files={("r1.10", "release-metadata.yaml"): metadata("r1.10", "b" * 40)},
    )

    plan = check(gh, "r1", "r2.1")

    assert (plan.patched_release, plan.patched_sha, plan.next_tag) == ("r1.10", "b" * 40, "r1.11")


def test_drafts_and_other_cycles_are_ignored():
    gh = repo(releases=[release("r1.6"), release("r1.8"), release("r2.1"), release("r1.9", draft=True)])

    assert check(gh, "r1", "r2.1") == PLAN


def test_refused_when_the_patched_release_has_no_source_commit():
    gh = repo(files={("r1.8", "release-metadata.yaml"): "repository:\n  release_tag: r1.8\n"})

    message = check(gh, "r1", "r2.1")

    assert "r1.8 has no src_commit_sha in release-metadata.yaml" in message


def test_refused_when_the_patched_release_has_no_metadata():
    gh = repo(files={("r1.8", "release-metadata.yaml"): None})

    assert "r1.8 has no src_commit_sha in release-metadata.yaml" in check(gh, "r1", "r2.1")


# ── creation ─────────────────────────────────────────────────────────────────


PARKED_R19 = PLAN_R18.replace("target_release_tag: r1.8", "target_release_tag: r1.9").replace(
    "target_release_type: maintenance-release", "target_release_type: none")


def test_branch_at_the_source_commit_then_one_direct_commit():
    # spec 3.5
    gh = repo()

    result = create(gh, PLAN)

    assert result.success, result.error_message
    (setup,) = gh.commits
    assert setup["branch"] == MB and setup["parent"] == SRC
    assert setup["paths"] == [
        ".github/workflows/camara-validation.yml",
        ".github/workflows/release-automation.yml",
        "CHANGELOG/CHANGELOG-r1.md",
        "release-plan.yaml",
    ]
    assert gh.files[(MB, ".github/workflows/release-automation.yml")] == RA_CALLER
    assert gh.files[(MB, ".github/workflows/camara-validation.yml")] == VF_CALLER
    # From the tag: the source commit lacks the patched release's own section
    assert gh.files[(MB, "CHANGELOG/CHANGELOG-r1.md")] == CHANGELOG_R18
    assert gh.calls.index("create_branch_at_sha") < gh.calls.index("commit_files")
    assert result == CreateResult(success=True, branch=MB, setup_commit_sha=setup["sha"])


def test_setup_commit_parks_the_plan_at_the_next_tag():
    # spec 3.5 (107 D1): no plan branch, no plan PR
    gh = repo()

    create(gh, PLAN)

    plan = gh.files[(MB, "release-plan.yaml")]
    # Only the two values change; comments, layout, dependencies and APIs stay
    assert plan == PARKED_R19
    assert gh.prs == [] and set(gh.branches) == {"main", MB}
    assert {f.name for f in fields(CreateResult)} == {
        "success", "branch", "setup_commit_sha", "warning", "error_message"}


def test_parked_plan_puts_the_line_in_not_planned():
    # spec 3.7: the push of the setup commit creates no Release Issue (not-planned without an issue: no action)
    gh = repo()
    create(gh, PLAN)

    info = ReleaseStateManager(gh).derive_state(base_branch=MB)

    assert (info.state, info.release_tag) == (ReleaseState.NOT_PLANNED, "r1.9")


def test_plan_from_a_public_release_is_parked_too():
    gh = repo(files={(SRC, "release-plan.yaml"): PLAN_R18.replace(
        "target_release_type: maintenance-release", 'target_release_type: "public-release"')})

    create(gh, PLAN)

    plan = yaml.safe_load(gh.files[(MB, "release-plan.yaml")])
    assert plan["repository"] == {"release_track": "independent", "target_release_tag": "r1.9", "target_release_type": "none"}


def test_warning_when_the_source_tag_points_elsewhere():
    # spec 3.6: the release-metadata.yaml SHA is used
    gh = repo(tags={"source/r1.8": "f" * 40})

    result = create(gh, PLAN)

    assert result.success
    assert gh.commits[0]["parent"] == SRC
    assert "source/r1.8 points to fffffff, not to src_commit_sha aaaaaaa" in result.warning


def test_warning_when_the_source_tag_is_missing():
    gh = repo()
    del gh.tags["source/r1.8"]

    result = create(gh, PLAN)

    assert result.success
    assert gh.commits[0]["parent"] == SRC
    assert result.warning == (
        "source/r1.8 not found; the branch starts at src_commit_sha aaaaaaa of r1.8 (release-metadata.yaml)"
    )


def test_missing_validation_caller_and_changelog_are_warnings():
    gh = repo(files={
        ("main", ".github/workflows/camara-validation.yml"): None,
        ("r1.8", "CHANGELOG/CHANGELOG-r1.md"): None,
    })

    result = create(gh, PLAN)

    assert result.success
    assert gh.commits[0]["paths"] == [".github/workflows/release-automation.yml", "release-plan.yaml"]
    assert ".github/workflows/camara-validation.yml not found on main" in result.warning
    assert "CHANGELOG/CHANGELOG-r1.md not found on tag r1.8" in result.warning


def test_failure_when_the_branch_appeared_meanwhile():
    gh = repo(branches={MB: "b1"})

    result = create(gh, PLAN)

    assert not result.success
    assert f"{MB} already exists" in result.error_message
    assert gh.commits == []


def test_failure_of_the_direct_commit_names_the_branch_left_behind():
    gh = repo(fail={"commit_files": [gh_error("HTTP 422: Repository rule violations found")]})

    result = create(gh, PLAN)

    assert not result.success
    assert "Repository rule violations" in result.error_message
    assert f"{MB} was created at {SRC[:7]}" in result.error_message
