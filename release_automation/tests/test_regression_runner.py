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
    _build_command_body,
    _canary_run_url,
    _first_nonblank_line,
    _iso_to_dt,
    _match_comment_title,
    fetch_last_bot_comment,
    find_recent_caller_run,
    find_release_issue,
    get_release_issue_state,
    load_expected_comment_titles,
    phase_fire_create_snapshot,
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
        assert "PASS: 2 of 2 phases passed" in out
        assert "`o/r`" in out
        assert "#90" in out
        assert "https://x/1" in out
        # Successful phases with a run_url still emit a detail section.
        assert "conclusion: `success`" in out

    def test_fail_shows_per_phase(self):
        reports = [
            PhaseReport(name="pre-check", passed=False, detail="state=planned"),
        ]
        out = render_markdown(reports, "o/r", 90)
        assert "FAIL: 0 of 1 phases passed" in out
        assert "state=planned" in out

    def test_partial_pass_header_says_fail(self):
        reports = [
            PhaseReport(name="pre-check", passed=True, detail="ok"),
            PhaseReport(name="verify", passed=False, detail="state unchanged"),
        ]
        out = render_markdown(reports, "o/r", 90)
        # 1/2 is not overall PASS — header must say FAIL, not leave it ambiguous.
        assert "FAIL: 1 of 2 phases passed" in out
        assert "PASS: " not in out.split("\n")[0]

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


# ---------------------------------------------------------------------------
# find_release_issue
# ---------------------------------------------------------------------------


MARKER = "<!-- release-automation:workflow-owned -->"


class TestFindReleaseIssue:
    def test_single_match(self):
        issues = [
            {"number": 93, "body": f"{MARKER}\n\nsome body text"},
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            assert find_release_issue("o/r") == 93

    def test_zero_matches_raises(self):
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=[],
        ):
            with pytest.raises(InfrastructureError, match="no open Release Issue"):
                find_release_issue("o/r")

    def test_multiple_matches_raises(self):
        issues = [
            {"number": 90, "body": f"{MARKER}\n\nold cycle"},
            {"number": 93, "body": f"{MARKER}\n\nnew cycle"},
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            with pytest.raises(InfrastructureError, match="multiple open Release Issues.*#90.*#93"):
                find_release_issue("o/r")

    def test_labeled_but_no_marker_is_excluded(self):
        # gh API filters by label server-side, but a maintainer could
        # hand-label an issue without the workflow-owned body marker.
        # That's not a workflow-owned issue; it must not match.
        issues = [
            {"number": 42, "body": "This is a hand-labeled release issue, not the workflow's."},
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            with pytest.raises(InfrastructureError, match="no open Release Issue"):
                find_release_issue("o/r")

    def test_marker_case_sensitivity(self):
        # The marker must match exactly — substring check on the body.
        issues = [
            {"number": 42, "body": "<!-- Release-Automation:Workflow-Owned -->"},  # wrong case
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            with pytest.raises(InfrastructureError, match="no open Release Issue"):
                find_release_issue("o/r")

    def test_null_body_is_tolerated(self):
        # GitHub occasionally returns null for empty bodies; don't crash.
        issues = [
            {"number": 42, "body": None},
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            with pytest.raises(InfrastructureError, match="no open Release Issue"):
                find_release_issue("o/r")

    def test_marker_anywhere_in_body_matches(self):
        # Marker may appear after other content (future-proofing if the
        # template ever reorders).
        issues = [
            {"number": 93, "body": f"First line\n\nSecond line\n\n{MARKER}\n"},
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=issues,
        ):
            assert find_release_issue("o/r") == 93


# ---------------------------------------------------------------------------
# load_expected_comment_titles + _match_comment_title
# ---------------------------------------------------------------------------


class TestLoadExpectedCommentTitles:
    def test_loads_committed_config(self):
        # Smoke-test against the real file in the repo — covers both
        # "file exists" and "both commands present". If the workflow
        # changes the template titles, this test starts failing and
        # flags that the config must be updated too.
        titles = load_expected_comment_titles()
        assert "create-snapshot" in titles
        assert "discard-snapshot" in titles
        assert titles["create-snapshot"].startswith("**")
        assert titles["discard-snapshot"].startswith("**")

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "does-not-exist.yaml"
        with pytest.raises(InfrastructureError, match="not found"):
            load_expected_comment_titles(missing)

    def test_root_must_be_mapping(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("- not-a-mapping\n", encoding="utf-8")
        with pytest.raises(InfrastructureError, match="mapping"):
            load_expected_comment_titles(bad)

    def test_values_must_be_strings(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("create-snapshot: 42\n", encoding="utf-8")
        with pytest.raises(InfrastructureError, match="strings"):
            load_expected_comment_titles(bad)


class TestMatchCommentTitle:
    def test_exact_prefix_match(self):
        body = "**✅ Snapshot created — State: `snapshot-active`**\nmore text"
        assert _match_comment_title(body, "**✅ Snapshot created")

    def test_prefix_with_dynamic_tail(self):
        body = "**✅ Snapshot created — State: `snapshot-active`**\n..."
        # The prefix matches; the rest of the line is dynamic.
        assert _match_comment_title(body, "**✅ Snapshot created")

    def test_non_match(self):
        body = "**❌ Command rejected: `/create-snapshot` — State: `planned`**"
        assert not _match_comment_title(body, "**✅ Snapshot created")

    def test_skips_leading_blank_lines(self):
        body = "\n\n**🗑️ Snapshot discarded — State: `planned`**\nmore"
        assert _match_comment_title(body, "**🗑️ Snapshot discarded")

    def test_empty_body(self):
        assert not _match_comment_title("", "**✅ Snapshot created")
        assert _first_nonblank_line("") == ""


# ---------------------------------------------------------------------------
# fetch_last_bot_comment
# ---------------------------------------------------------------------------


def _comment(at: str, login: str, body: str = "", html_url: str = "https://x/c") -> dict:
    return {
        "body": body,
        "created_at": at,
        "user": {"login": login},
        "html_url": html_url,
    }


class TestFetchLastBotComment:
    def test_returns_newest_bot_comment(self):
        since = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
        comments = [
            _comment("2026-04-23T10:00:30Z", "github-actions[bot]", "first"),
            _comment("2026-04-23T10:01:00Z", "camara-release-automation[bot]", "second"),
            _comment("2026-04-23T10:00:45Z", "hdamker", "human comment ignored"),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=comments,
        ):
            result = fetch_last_bot_comment("o/r", 90, since)
        assert result is not None
        assert result["user"]["login"] == "camara-release-automation[bot]"
        assert result["body"] == "second"

    def test_ignores_comments_before_since(self):
        since = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
        comments = [
            _comment("2026-04-23T09:59:00Z", "github-actions[bot]", "too old"),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=comments,
        ):
            result = fetch_last_bot_comment("o/r", 90, since)
        assert result is None

    def test_returns_none_when_only_human_comments(self):
        since = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
        comments = [
            _comment("2026-04-23T10:05:00Z", "hdamker", "human"),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=comments,
        ):
            result = fetch_last_bot_comment("o/r", 90, since)
        assert result is None

    def test_handles_malformed_timestamps(self):
        since = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
        comments = [
            _comment("not-a-timestamp", "github-actions[bot]", "broken"),
            _comment("2026-04-23T10:05:00Z", "github-actions[bot]", "good"),
        ]
        with patch(
            "release_automation.scripts.regression_runner.gh",
            return_value=comments,
        ):
            result = fetch_last_bot_comment("o/r", 90, since)
        assert result is not None
        assert result["body"] == "good"


# ---------------------------------------------------------------------------
# _build_command_body + _canary_run_url
# ---------------------------------------------------------------------------


class TestCanaryRunURL:
    def test_composes_url_when_all_env_present(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "camaraproject/tooling")
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        assert _canary_run_url() == "https://github.com/camaraproject/tooling/actions/runs/12345"

    def test_none_when_any_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        assert _canary_run_url() is None


class TestBuildCommandBody:
    def test_starts_with_command_and_blank_line(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        body = _build_command_body("/create-snapshot", "Smoke test.")
        lines = body.split("\n")
        assert lines[0] == "/create-snapshot"
        assert lines[1] == ""
        # The caller's startsWith check requires the first line to be exactly
        # the command; the second line must be blank or whitespace so the
        # reusable workflow's regex `/^\/cmd(?:\s|$)/` also matches.
        assert body.startswith("/create-snapshot\n")

    def test_attribution_includes_run_url_when_in_ci(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "camaraproject/tooling")
        monkeypatch.setenv("GITHUB_RUN_ID", "99")
        body = _build_command_body("/create-snapshot", "Smoke test.")
        assert "(run: https://github.com/camaraproject/tooling/actions/runs/99)" in body
        assert "Release Automation Regression canary" in body

    def test_attribution_without_run_url_outside_ci(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        body = _build_command_body("/create-snapshot", "Smoke test.")
        assert "run:" not in body  # URL clause omitted
        assert "Release Automation Regression canary" in body
        assert "Smoke test." in body


# ---------------------------------------------------------------------------
# phase_fire_create_snapshot — failure classes after the polish
# ---------------------------------------------------------------------------


_EXPECTED = {
    "create-snapshot": "**✅ Snapshot created",
    "discard-snapshot": "**🗑️ Snapshot discarded",
}


def _gh_router(responses):
    """Dispatch `gh(args, ...)` calls to responses keyed by a substring pattern."""
    def router(args, parse_json=False):  # noqa: ARG001
        joined = " ".join(args)
        for pattern, value in responses:
            if pattern in joined:
                if callable(value):
                    return value(joined)
                return value
        raise AssertionError(f"no mock configured for: {joined}")
    return router


class TestPhaseFireCreateSnapshotPolished:
    def test_pass_on_matching_bot_reply(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        # Deterministic: skip polling delays and caller-run discovery delay.
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.time.sleep",
            lambda *_a, **_k: None,
        )
        comments = [
            _comment(
                "2026-04-23T05:00:30Z",
                "github-actions[bot]",
                "**✅ Snapshot created — State: `snapshot-active`**\nRelease PR: #94",
            ),
        ]
        caller_run = {
            "databaseId": 999,
            "createdAt": "2026-04-23T05:00:10Z",
            "status": "completed",
            "conclusion": "success",
            "url": "https://x/run/999",
        }
        responses = [
            ("issue comment", ""),  # post_issue_comment
            ("run list", [caller_run]),  # find_recent_caller_run
            ("run view", {"status": "completed", "conclusion": "success"}),  # poll_run
            ("issues/90/comments", comments),  # fetch_last_bot_comment
        ]
        # find_recent_caller_run uses an internal loop; force its `since`
        # to be in the past so any created_at compares pass.
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.datetime",
            _FixedDatetime("2026-04-23T04:59:00Z"),
        )
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_gh_router(responses),
        ):
            report, run_id = phase_fire_create_snapshot(
                "camaraproject/ReleaseTest", 90,
                poll_timeout=10, dry_run=False,
                expected_titles=_EXPECTED,
            )
        assert report.passed is True
        assert "Snapshot created" in report.detail
        assert run_id == "999"

    def test_fail_on_rejection_reply(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.time.sleep",
            lambda *_a, **_k: None,
        )
        comments = [
            _comment(
                "2026-04-23T05:00:30Z",
                "github-actions[bot]",
                "**❌ Command rejected: `/create-snapshot` — State: `planned`**\nYour current permission: none",
            ),
        ]
        caller_run = {
            "databaseId": 999,
            "createdAt": "2026-04-23T05:00:10Z",
            "status": "completed",
            "conclusion": "success",
            "url": "https://x/run/999",
        }
        responses = [
            ("issue comment", ""),
            ("run list", [caller_run]),
            ("run view", {"status": "completed", "conclusion": "success"}),
            ("issues/90/comments", comments),
        ]
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.datetime",
            _FixedDatetime("2026-04-23T04:59:00Z"),
        )
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_gh_router(responses),
        ):
            report, run_id = phase_fire_create_snapshot(
                "camaraproject/ReleaseTest", 90,
                poll_timeout=10, dry_run=False,
                expected_titles=_EXPECTED,
            )
        assert report.passed is False
        assert "Command rejected" in report.detail
        assert run_id == "999"
        # Extras carry the comment URL for operator diagnosis.
        assert any("https://x/c" in extra for extra in report.extras)

    def test_fail_when_caller_run_failed(self, monkeypatch):
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.time.sleep",
            lambda *_a, **_k: None,
        )
        caller_run = {
            "databaseId": 999,
            "createdAt": "2026-04-23T05:00:10Z",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://x/run/999",
        }
        responses = [
            ("issue comment", ""),
            ("run list", [caller_run]),
            ("run view", {"status": "completed", "conclusion": "failure"}),
        ]
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.datetime",
            _FixedDatetime("2026-04-23T04:59:00Z"),
        )
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_gh_router(responses),
        ):
            report, _ = phase_fire_create_snapshot(
                "camaraproject/ReleaseTest", 90,
                poll_timeout=10, dry_run=False,
                expected_titles=_EXPECTED,
            )
        assert report.passed is False
        assert "failure" in report.detail
        assert "RA workflow failed" in report.detail

    def test_fail_when_no_bot_reply(self, monkeypatch):
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.time.sleep",
            lambda *_a, **_k: None,
        )
        caller_run = {
            "databaseId": 999,
            "createdAt": "2026-04-23T05:00:10Z",
            "status": "completed",
            "conclusion": "success",
            "url": "https://x/run/999",
        }
        responses = [
            ("issue comment", ""),
            ("run list", [caller_run]),
            ("run view", {"status": "completed", "conclusion": "success"}),
            ("issues/90/comments", []),  # no comments at all
        ]
        monkeypatch.setattr(
            "release_automation.scripts.regression_runner.datetime",
            _FixedDatetime("2026-04-23T04:59:00Z"),
        )
        with patch(
            "release_automation.scripts.regression_runner.gh",
            side_effect=_gh_router(responses),
        ):
            report, _ = phase_fire_create_snapshot(
                "camaraproject/ReleaseTest", 90,
                poll_timeout=10, dry_run=False,
                expected_titles=_EXPECTED,
            )
        assert report.passed is False
        assert "no bot reply" in report.detail

    def test_dry_run_skips_everything(self):
        report, run_id = phase_fire_create_snapshot(
            "camaraproject/ReleaseTest", 90,
            poll_timeout=10, dry_run=True,
            expected_titles=_EXPECTED,
        )
        assert report.passed is True
        assert "DRY-RUN" in report.detail
        assert run_id is None


class _FixedDatetime:
    """Freeze `datetime.now(...)` to a specific UTC moment; everything else passes through.

    Used to make the fire-phase's UTC marker deterministic in tests so the
    run-discovery and comment-lookup filters compare against a known point.
    """

    def __init__(self, iso: str):
        self._now = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )

    def now(self, tz=None):
        return self._now if tz is None else self._now.astimezone(tz)

    def strptime(self, *args, **kwargs):
        return datetime.strptime(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(datetime, name)
