"""Tests for maintenance_branch.py: create-maintenance-branch checks and creation (spec 3.1-3.6)."""

import pytest
import yaml

from release_automation.scripts.maintenance_branch import (
    BranchPlan,
    check,
    create,
)
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


def test_branch_at_the_source_commit_then_one_direct_commit():
    # spec 3.5
    gh = repo()

    result = create(gh, PLAN)

    assert result.success, result.error_message
    setup = gh.commits[0]
    assert setup["branch"] == MB and setup["parent"] == SRC
    assert setup["paths"] == [
        ".github/workflows/camara-validation.yml",
        ".github/workflows/release-automation.yml",
        "CHANGELOG/CHANGELOG-r1.md",
    ]
    assert gh.files[(MB, ".github/workflows/release-automation.yml")] == RA_CALLER
    assert gh.files[(MB, ".github/workflows/camara-validation.yml")] == VF_CALLER
    # From the tag: the source commit lacks the patched release's own section
    assert gh.files[(MB, "CHANGELOG/CHANGELOG-r1.md")] == CHANGELOG_R18
    assert gh.calls.index("create_branch_at_sha") < gh.calls.index("commit_files")
    assert (result.branch, result.setup_commit_sha) == (MB, setup["sha"])
    assert result.warning == ""


def test_plan_pr_targets_the_next_tag_with_versions_unchanged():
    # spec 3.5
    gh = repo()

    result = create(gh, PLAN)

    pr = gh.prs[0]
    assert (pr["head"], pr["base"]) == ("release-plan/r1.9", MB)
    assert "r1.9" in pr["title"] and MB in pr["title"]
    assert "patch version" in pr["body"]
    plan = gh.files[("release-plan/r1.9", "release-plan.yaml")]
    parsed = yaml.safe_load(plan)
    assert parsed["repository"]["target_release_tag"] == "r1.9"
    assert parsed["repository"]["target_release_type"] == "maintenance-release"
    assert parsed["apis"] == yaml.safe_load(PLAN_R18)["apis"]
    assert parsed["dependencies"] == yaml.safe_load(PLAN_R18)["dependencies"]
    # Only the two values change; comments and layout stay
    assert plan == PLAN_R18.replace("target_release_tag: r1.8", "target_release_tag: r1.9")
    # The plan branch starts at the set-up commit
    assert gh.commits[1]["branch"] == "release-plan/r1.9"
    assert (result.plan_pr_number, result.plan_pr_url) == (str(pr["number"]), f"https://github.com/camaraproject/Example/pull/{pr['number']}")
    assert gh.labelled == [(pr["number"], ["automated"])]


def test_plan_from_a_public_release_becomes_a_maintenance_release():
    gh = repo(files={(SRC, "release-plan.yaml"): PLAN_R18.replace(
        "target_release_type: maintenance-release", 'target_release_type: "public-release"')})

    create(gh, PLAN)

    plan = yaml.safe_load(gh.files[("release-plan/r1.9", "release-plan.yaml")])
    assert plan["repository"]["target_release_type"] == "maintenance-release"


def test_warning_when_the_source_tag_points_elsewhere():
    # spec 3.6: the release-metadata.yaml SHA is used
    gh = repo(tags={"source/r1.8": "f" * 40})

    result = create(gh, PLAN)

    assert result.success
    assert gh.commits[0]["parent"] == SRC
    assert "source/r1.8 points to fffffff, not to src_commit_sha aaaaaaa" in result.warning


def test_missing_validation_caller_and_changelog_are_warnings():
    gh = repo(files={
        ("main", ".github/workflows/camara-validation.yml"): None,
        ("r1.8", "CHANGELOG/CHANGELOG-r1.md"): None,
    })

    result = create(gh, PLAN)

    assert result.success
    assert gh.commits[0]["paths"] == [".github/workflows/release-automation.yml"]
    assert ".github/workflows/camara-validation.yml not found on main" in result.warning
    assert "CHANGELOG/CHANGELOG-r1.md not found on tag r1.8" in result.warning


def test_failure_when_the_branch_appeared_meanwhile():
    gh = repo(branches={MB: "b1"})

    result = create(gh, PLAN)

    assert not result.success
    assert f"{MB} already exists" in result.error_message
    assert gh.commits == [] and gh.prs == []


def test_failure_of_the_direct_commit_names_the_branch_left_behind():
    gh = repo(fail={"commit_files": [gh_error("HTTP 422: Repository rule violations found")]})

    result = create(gh, PLAN)

    assert not result.success
    assert "Repository rule violations" in result.error_message
    assert f"{MB} was created at {SRC[:7]}" in result.error_message
    assert gh.prs == []


def test_failure_of_the_plan_pr_keeps_the_branch():
    gh = repo(fail={"create_pr": [gh_error("HTTP 422")]})

    result = create(gh, PLAN)

    assert not result.success
    assert result.branch == MB and result.setup_commit_sha
    assert "plan PR" in result.error_message
