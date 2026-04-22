"""
Unit tests for the Release Automation regression runner.

Pure-logic coverage only — network and subprocess calls are mocked at the
`gh()` boundary. These tests verify state-label parsing, run-discovery
filtering, markdown rendering, phase decision matrix, and branch-name
parsing. Integration behaviour is covered by CI staging (see
private-dev-docs/validation-framework/prompts/prompt-project-session.md).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from release_automation.scripts.regression_runner import (
    InfrastructureError,
    PhaseReport,
    _iso_to_dt,
    find_recent_caller_run,
    get_release_issue_state,
    phase_pre_check,
    phase_verify_post_create,
    phase_verify_post_discard,
    read_state_label,
    render_markdown,
    snapshot_id_from_branch,
)


# ---------------------------------------------------------------------------
# read_state_label
# ---------------------------------------------------------------------------


class TestReadStateLabel:
    def test_returns_planned(self):
        labels = [
            {"name": "release-issue"},
            {"name": "release-state:planned"},
        ]
        assert read_state_label(labels) == "planned"

    def test_returns_snapshot_active(self):
        labels = [{"name": "release-state:snapshot-active"}]
        assert read_state_label(labels) == "snapshot-active"

    def test_returns_none_when_no_state_label(self):
        labels = [{"name": "release-issue"}, {"name": "bug"}]
        assert read_state_label(labels) is None

    def test_returns_none_for_empty_list(self):
        assert read_state_label([]) is None

    def test_raises_on_multiple_state_labels(self):
        labels = [
            {"name": "release-state:planned"},
            {"name": "release-state:snapshot-active"},
        ]
        with pytest.raises(InfrastructureError, match="multiple"):
            read_state_label(labels)

    def test_ignores_non_dict_entries(self):
        labels = [None, "weird", {"name": "release-state:planned"}]
        assert read_state_label(labels) == "planned"

    def test_ignores_non_string_name(self):
        labels = [{"name": 42}, {"name": "release-state:planned"}]
        assert read_state_label(labels) == "planned"

    def test_ignores_labels_without_name_key(self):
        labels = [{"color": "red"}, {"name": "release-state:planned"}]
        assert read_state_label(labels) == "planned"


# ---------------------------------------------------------------------------
# snapshot_id_from_branch
# ---------------------------------------------------------------------------


class TestSnapshotIdFromBranch:
    def test_snapshot_branch(self):
        assert snapshot_id_from_branch("release-snapshot/r1.2-abc1234") == "r1.2-abc1234"

    def test_release_review_branch(self):
        assert snapshot_id_from_branch("release-review/r1.2-abc1234") == "r1.2-abc1234"

    def test_preserved_branch(self):
        assert (
            snapshot_id_from_branch("release-review/r1.2-abc1234-preserved")
            == "r1.2-abc1234"
        )

    def test_rejects_unrelated_branch(self):
        with pytest.raises(InfrastructureError, match="not a snapshot/review branch"):
            snapshot_id_from_branch("main")

    def test_rejects_feature_branch(self):
        with pytest.raises(InfrastructureError):
            snapshot_id_from_branch("feat/something")


# ---------------------------------------------------------------------------
# _iso_to_dt
# ---------------------------------------------------------------------------


class TestIsoToDt:
    def test_parses_utc_timestamp(self):
        result = _iso_to_dt("2026-04-22T15:30:00Z")
        assert result == datetime(2026, 4, 22, 15, 30, 0, tzinfo=timezone.utc)
        assert result.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# phase_pre_check — decision matrix
# ---------------------------------------------------------------------------


def _mock_issue_labels(labels: list[dict[str, str]], state: str = "open"):
    """Helper that returns a dict mimicking `gh api issues/<N>` output."""
    return {"labels": labels, "state": state}


class TestPhasePreCheck:
    def test_pass_when_state_planned(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels([{"name": "release-state:planned"}]),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is True
        assert "planned" in report.detail

    def test_fail_when_snapshot_active(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels(
                [{"name": "release-state:snapshot-active"}]
            ),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is False
        assert "snapshot-active" in report.detail
        # The snapshot-active branch emits the manual-recovery hint.
        assert "/discard-snapshot" in report.detail

    def test_fail_when_draft_ready(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels(
                [{"name": "release-state:draft-ready"}]
            ),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is False
        assert "draft-ready" in report.detail
        # Non-snapshot-active states do NOT get the discard hint (it would be wrong).
        assert "/discard-snapshot" not in report.detail

    def test_fail_when_published(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels(
                [{"name": "release-state:published"}]
            ),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is False

    def test_fail_when_no_state_label(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels([{"name": "other"}]),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is False
        assert "no release-state:" in report.detail

    def test_fail_when_issue_closed(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels(
                [{"name": "release-state:planned"}], state="closed",
            ),
        ):
            report = phase_pre_check("camaraproject/ReleaseTest", 90)
        assert report.passed is False
        assert "could not read state" in report.detail
        # Infrastructure-style message — has the "could not" sentinel that
        # drives exit-code 2 classification in main().
        assert report.detail.startswith("could not ")


# ---------------------------------------------------------------------------
# get_release_issue_state (integration through gh mock)
# ---------------------------------------------------------------------------


class TestGetReleaseIssueState:
    def test_extracts_state(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels([{"name": "release-state:planned"}]),
        ):
            assert get_release_issue_state("o/r", 1) == "planned"

    def test_returns_none_when_absent(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels([]),
        ):
            assert get_release_issue_state("o/r", 1) is None

    def test_raises_when_not_open(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=_mock_issue_labels([], state="closed"),
        ):
            with pytest.raises(InfrastructureError, match="not open"):
                get_release_issue_state("o/r", 1)


# ---------------------------------------------------------------------------
# find_recent_caller_run — event filter + newest-after-marker selection
# ---------------------------------------------------------------------------


class TestFindRecentCallerRun:
    def test_picks_newest_after_marker(self):
        marker = datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)
        runs = [
            {
                "databaseId": 1,
                "createdAt": "2026-04-22T09:59:00Z",
                "status": "completed",
                "conclusion": "success",
                "url": "https://x/1",
            },
            {
                "databaseId": 2,
                "createdAt": "2026-04-22T10:01:00Z",
                "status": "in_progress",
                "conclusion": None,
                "url": "https://x/2",
            },
            {
                "databaseId": 3,
                "createdAt": "2026-04-22T10:02:00Z",
                "status": "queued",
                "conclusion": None,
                "url": "https://x/3",
            },
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=runs,
        ):
            run = find_recent_caller_run(
                "o/r",
                workflow_file="release-automation.yml",
                since=marker,
                attempts=1,
                interval=0.0,
            )
        # Newest (after marker) is run 3.
        assert run["databaseId"] == 3

    def test_ignores_runs_before_marker(self):
        marker = datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)
        runs = [
            {
                "databaseId": 1,
                "createdAt": "2026-04-22T09:00:00Z",
                "status": "completed",
                "conclusion": "success",
                "url": "https://x/1",
            },
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=runs,
        ):
            with pytest.raises(InfrastructureError, match="no .* run appeared"):
                find_recent_caller_run(
                    "o/r",
                    workflow_file="release-automation.yml",
                    since=marker,
                    attempts=1,
                    interval=0.0,
                )

    def test_ignores_malformed_timestamps(self):
        marker = datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)
        runs = [
            {
                "databaseId": 1,
                "createdAt": "not-a-timestamp",
                "status": "queued",
                "conclusion": None,
                "url": "https://x/1",
            },
            {
                "databaseId": 2,
                "createdAt": "2026-04-22T10:05:00Z",
                "status": "queued",
                "conclusion": None,
                "url": "https://x/2",
            },
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=runs,
        ):
            run = find_recent_caller_run(
                "o/r",
                workflow_file="release-automation.yml",
                since=marker,
                attempts=1,
                interval=0.0,
            )
        assert run["databaseId"] == 2


# ---------------------------------------------------------------------------
# phase_verify_post_create
# ---------------------------------------------------------------------------


def _make_gh_router(responses):
    """Dispatch gh(args) calls to successive responses keyed by first arg pattern.

    Each response is (match_prefix, return_value). The router is called
    with the full args list and returns the first matching response.
    """
    def router(args, parse_json=False):  # noqa: ARG001
        for pattern, value in responses:
            if pattern in " ".join(args):
                return value
        raise AssertionError(f"no mock configured for: {args}")
    return router


class TestPhaseVerifyPostCreate:
    def test_pass_when_all_three_checks_ok(self):
        issue_response = {
            "labels": [{"name": "release-state:snapshot-active"}],
            "state": "open",
        }
        branches_response = (
            "main\nrelease-snapshot/r1.2-abc1234\nrelease-review/r1.2-abc1234\n"
        )
        pr_list_response = [
            {
                "number": 101,
                "headRefName": "release-review/r1.2-abc1234",
                "title": "Release Review: ...",
            }
        ]
        responses = [
            ("issues/90", issue_response),
            ("/branches --paginate", branches_response),
            ("pr list", pr_list_response),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_make_gh_router(responses),
        ):
            report, snapshot_id = phase_verify_post_create(
                "camaraproject/ReleaseTest", 90
            )
        assert report.passed is True
        assert snapshot_id == "r1.2-abc1234"
        assert report.extras  # should carry the per-check messages

    def test_fail_when_state_still_planned(self):
        issue_response = {
            "labels": [{"name": "release-state:planned"}],
            "state": "open",
        }
        branches_response = "main\n"
        pr_list_response: list[dict] = []
        responses = [
            ("issues/90", issue_response),
            ("/branches --paginate", branches_response),
            ("pr list", pr_list_response),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_make_gh_router(responses),
        ):
            report, snapshot_id = phase_verify_post_create(
                "camaraproject/ReleaseTest", 90
            )
        assert report.passed is False
        assert snapshot_id is None

    def test_fail_when_multiple_snapshot_branches(self):
        issue_response = {
            "labels": [{"name": "release-state:snapshot-active"}],
            "state": "open",
        }
        branches_response = (
            "release-snapshot/r1.2-abc1234\nrelease-snapshot/r1.2-def5678\n"
        )
        responses = [
            ("issues/90", issue_response),
            ("/branches --paginate", branches_response),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_make_gh_router(responses),
        ):
            report, snapshot_id = phase_verify_post_create(
                "camaraproject/ReleaseTest", 90
            )
        # Should surface an infra-style failure (caught by find_snapshot_branch).
        assert report.passed is False
        assert snapshot_id is None
        assert report.detail.startswith("could not ") or "multiple" in report.detail


# ---------------------------------------------------------------------------
# phase_verify_post_discard
# ---------------------------------------------------------------------------


class TestPhaseVerifyPostDiscard:
    def test_pass_when_state_planned_and_preserved_exists(self):
        issue_response = {
            "labels": [{"name": "release-state:planned"}],
            "state": "open",
        }
        # branch_exists calls: first the snapshot (should 404), then the preserved (should exist)
        def gh_mock(args, parse_json=False):  # noqa: ARG001
            joined = " ".join(args)
            if "issues/90" in joined:
                return issue_response
            if "branches/release-snapshot/r1.2-abc1234" in joined:
                raise InfrastructureError("HTTP 404: Not Found")
            if "branches/release-review/r1.2-abc1234-preserved" in joined:
                return ".name is release-review/r1.2-abc1234-preserved"
            raise AssertionError(f"unmocked: {args}")

        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=gh_mock,
        ):
            report = phase_verify_post_discard(
                "camaraproject/ReleaseTest", 90, snapshot_id="r1.2-abc1234",
            )
        assert report.passed is True

    def test_fail_when_snapshot_branch_still_exists(self):
        issue_response = {
            "labels": [{"name": "release-state:planned"}],
            "state": "open",
        }

        def gh_mock(args, parse_json=False):  # noqa: ARG001
            joined = " ".join(args)
            if "issues/90" in joined:
                return issue_response
            if "branches/release-snapshot/r1.2-abc1234" in joined:
                return "release-snapshot/r1.2-abc1234"  # still present
            if "branches/release-review/r1.2-abc1234-preserved" in joined:
                return "release-review/r1.2-abc1234-preserved"
            raise AssertionError(f"unmocked: {args}")

        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=gh_mock,
        ):
            report = phase_verify_post_discard(
                "camaraproject/ReleaseTest", 90, snapshot_id="r1.2-abc1234",
            )
        assert report.passed is False
        assert "still exists" in report.detail

    def test_fail_when_preserved_branch_missing(self):
        issue_response = {
            "labels": [{"name": "release-state:planned"}],
            "state": "open",
        }

        def gh_mock(args, parse_json=False):  # noqa: ARG001
            joined = " ".join(args)
            if "issues/90" in joined:
                return issue_response
            if "branches/release-snapshot/r1.2-abc1234" in joined:
                raise InfrastructureError("HTTP 404: Not Found")
            if "branches/release-review/r1.2-abc1234-preserved" in joined:
                raise InfrastructureError("HTTP 404: Not Found")
            raise AssertionError(f"unmocked: {args}")

        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=gh_mock,
        ):
            report = phase_verify_post_discard(
                "camaraproject/ReleaseTest", 90, snapshot_id="r1.2-abc1234",
            )
        assert report.passed is False
        assert "missing" in report.detail

    def test_skips_branch_checks_when_snapshot_id_missing(self):
        issue_response = {
            "labels": [{"name": "release-state:planned"}],
            "state": "open",
        }
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issue_response,
        ):
            report = phase_verify_post_discard(
                "camaraproject/ReleaseTest", 90, snapshot_id=None,
            )
        assert report.passed is False
        assert "not captured" in report.detail


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_all_pass_header(self):
        reports = [
            PhaseReport(name="pre-check", passed=True, detail="ok"),
            PhaseReport(
                name="fire /create-snapshot",
                passed=True,
                detail="run completed",
                run_url="https://x/1",
                run_conclusion="success",
            ),
        ]
        out = render_markdown(reports, "o/r", 90)
        assert "2/2 phases PASS" in out
        assert "`o/r`" in out
        assert "#90" in out
        assert "PASS" in out
        assert "https://x/1" in out
        # Successful phases with a run_url still emit a detail section.
        assert "conclusion: `success`" in out

    def test_fail_shows_per_phase(self):
        reports = [
            PhaseReport(name="pre-check", passed=False, detail="state=planned"),
        ]
        out = render_markdown(reports, "o/r", 90)
        assert "0/1 phases PASS" in out
        assert "FAIL" in out
        assert "state=planned" in out

    def test_pipe_escape_in_detail(self):
        reports = [
            PhaseReport(name="x", passed=True, detail="a | b | c"),
        ]
        out = render_markdown(reports, "o/r", 90)
        # Pipes in detail are escaped so the markdown table doesn't split them.
        assert r"a \| b \| c" in out

    def test_empty_detail_renders_dash(self):
        reports = [PhaseReport(name="x", passed=True, detail="")]
        out = render_markdown(reports, "o/r", 90)
        assert "| x | PASS | - |" in out

    def test_extras_render_as_bullets(self):
        reports = [
            PhaseReport(
                name="verify post-create",
                passed=True,
                detail="all ok",
                extras=["state=snapshot-active", "pr=#101"],
            ),
        ]
        out = render_markdown(reports, "o/r", 90)
        assert "- state=snapshot-active" in out
        assert "- pr=#101" in out
