#!/usr/bin/env python3
"""
CAMARA Release Automation — Regression Runner

Exercises the release-automation-reusable.yml workflow on a persistent
test repository (default: camaraproject/ReleaseTest) via a round-trip
/create-snapshot + /discard-snapshot pair. Catches the bug class that
the validation regression canary cannot reach — runtime bugs in the RA
workflow and its shared actions. See the sibling validation regression
runner at validation/scripts/regression_runner.py.

Usage:
    python3 regression_runner.py --repo camaraproject/ReleaseTest \\
        --release-issue 90 \\
        [--summary-file release-automation-regression-summary.md]

    # Dry-run (no comments posted, no runs polled):
    python3 regression_runner.py --repo ... --release-issue 90 --dry-run

Exit codes:
    0  all phases PASS
    1  verification failure (run concluded non-success or post-state mismatch)
    2  infrastructure failure (gh error, timeout, state unsafe to proceed)

No real releases, tags, or draft builds are produced. The round-trip only
covers commands that are reversible — merging the Release Review PR or
invoking /publish-release is explicitly out of scope.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Package-relative imports so unit tests can patch at the right boundary.
# The release_automation/ package is already on sys.path when invoked via
# python3 release_automation/scripts/regression_runner.py (pytest uses
# repo root and the package's __init__.py).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from config import (  # noqa: E402
    LABEL_RELEASE_MGMT_BOT,
    RELEASE_REVIEW_BRANCH_PREFIX,
    SNAPSHOT_BRANCH_PREFIX,
    STATE_PLANNED,
    STATE_SNAPSHOT_ACTIVE,
)


logger = logging.getLogger("ra_regression_runner")


# Label prefix used by release-automation-reusable.yml for issue state.
# Deliberately hardcoded here rather than added to config.py — the value
# is defined by the reusable workflow's state-update step, not by the
# Python modules. If the workflow changes the prefix, update this line.
# Source of truth: .github/workflows/release-automation-reusable.yml
_STATE_LABEL_PREFIX = "release-state:"

# Caller workflow filename on the target test repo. Each release-plan
# repo copies this caller from the shared template.
_RA_CALLER_WORKFLOW = "release-automation.yml"


# ---------------------------------------------------------------------------
# Errors + phase report
# ---------------------------------------------------------------------------


class InfrastructureError(RuntimeError):
    """Raised for gh errors, missing preconditions, or timeouts.

    Distinct from a verification failure (which is a regression in RA, not
    infrastructure). Infrastructure errors map to exit code 2; verification
    failures map to exit 1.
    """


@dataclass
class PhaseReport:
    """Per-phase PASS/FAIL record with human-readable detail."""

    name: str
    passed: bool = False
    detail: str = ""
    run_url: str | None = None
    run_conclusion: str | None = None
    extras: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GitHub I/O helpers (duplicated from validation/scripts/regression_runner.py)
# ---------------------------------------------------------------------------


def gh(args: list[str], *, parse_json: bool = False) -> Any:
    """Run `gh <args>` and return stdout (optionally JSON-parsed).

    Raises InfrastructureError on non-zero exit. Stderr is captured and
    included in the exception message for diagnosis.
    """
    cmd = ["gh", *args]
    logger.debug("gh call: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as exc:
        raise InfrastructureError(
            "gh CLI not found — install https://cli.github.com and run `gh auth login`"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise InfrastructureError(
            f"gh {' '.join(args)}: exit {exc.returncode}\n"
            f"stderr: {exc.stderr.strip()}"
        ) from exc
    if parse_json:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InfrastructureError(
                f"gh {' '.join(args)}: could not parse stdout as JSON: {exc}"
            ) from exc
    return result.stdout


def _iso_to_dt(stamp: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (UTC) to a timezone-aware datetime."""
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def poll_run(
    repo: str,
    run_id: str,
    *,
    interval: int,
    timeout: int,
) -> str:
    """Wait until *run_id* completes; return its conclusion string.

    Raises InfrastructureError on timeout. Conclusion may be "success",
    "failure", "cancelled", "neutral", "skipped", etc. — caller decides
    what to treat as verification failure vs infrastructure failure.
    """
    deadline = time.monotonic() + timeout
    while True:
        data = gh(
            [
                "run", "view", run_id,
                "--repo", repo,
                "--json", "status,conclusion",
            ],
            parse_json=True,
        )
        status = data.get("status")
        conclusion = data.get("conclusion") or ""
        logger.debug("run %s status=%s conclusion=%s", run_id, status, conclusion)
        if status == "completed":
            return conclusion
        if time.monotonic() >= deadline:
            raise InfrastructureError(
                f"run {run_id} did not complete within {timeout}s "
                f"(last status={status})"
            )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Issue / branch / PR readers
# ---------------------------------------------------------------------------


def read_state_label(labels: list[dict[str, Any]]) -> str | None:
    """Extract the release-state:* value from a list of label objects.

    Returns the state string (e.g. "planned", "snapshot-active") or None
    if no release-state:* label is present. Raises InfrastructureError if
    more than one release-state:* label is found — that indicates workflow
    corruption and must not be silently collapsed.
    """
    found: list[str] = []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else None
        if isinstance(name, str) and name.startswith(_STATE_LABEL_PREFIX):
            found.append(name[len(_STATE_LABEL_PREFIX):])
    if len(found) > 1:
        raise InfrastructureError(
            f"Release Issue carries multiple {_STATE_LABEL_PREFIX}* labels: "
            f"{sorted(found)}"
        )
    return found[0] if found else None


def get_release_issue_state(repo: str, issue_number: int) -> str | None:
    """Read the release-state:* label value on the given issue."""
    data = gh(
        [
            "api", f"repos/{repo}/issues/{issue_number}",
            "--jq", "{labels: .labels, state: .state}",
        ],
        parse_json=True,
    )
    if data.get("state") != "open":
        raise InfrastructureError(
            f"{repo}#{issue_number}: issue is not open (state={data.get('state')!r})"
        )
    return read_state_label(data.get("labels", []))


def snapshot_id_from_branch(branch_name: str) -> str:
    """Extract snapshot id from a release-snapshot/ or release-review/ branch name.

    Example:
        'release-snapshot/r1.2-abc1234' -> 'r1.2-abc1234'
        'release-review/r1.2-abc1234' -> 'r1.2-abc1234'
        'release-review/r1.2-abc1234-preserved' -> 'r1.2-abc1234'
    """
    for prefix in (SNAPSHOT_BRANCH_PREFIX, RELEASE_REVIEW_BRANCH_PREFIX):
        if branch_name.startswith(prefix):
            tail = branch_name[len(prefix):]
            if tail.endswith("-preserved"):
                tail = tail[: -len("-preserved")]
            return tail
    raise InfrastructureError(
        f"not a snapshot/review branch name: {branch_name!r}"
    )


def find_snapshot_branch(repo: str) -> str | None:
    """Return the name of the single active release-snapshot/* branch, or None.

    Raises InfrastructureError if more than one snapshot branch exists —
    that indicates prior-run corruption and must not be silently collapsed.
    """
    data = gh(
        [
            "api", f"repos/{repo}/branches",
            "--paginate",
            "--jq", ".[].name",
        ]
    )
    names = [
        line.strip()
        for line in data.splitlines()
        if line.strip().startswith(SNAPSHOT_BRANCH_PREFIX)
    ]
    if len(names) > 1:
        raise InfrastructureError(
            f"{repo}: multiple active snapshot branches: {names}"
        )
    return names[0] if names else None


def branch_exists(repo: str, branch_name: str) -> bool:
    """Return True iff *branch_name* currently exists on *repo*."""
    try:
        gh(
            [
                "api", f"repos/{repo}/branches/{branch_name}",
                "--jq", ".name",
            ]
        )
        return True
    except InfrastructureError as exc:
        # `gh api` returns non-zero with "HTTP 404" in stderr for missing
        # branches. Any other error re-raises.
        if "HTTP 404" in str(exc) or "Not Found" in str(exc):
            return False
        raise


def release_review_pr_for_issue(repo: str, issue_number: int) -> int | None:
    """Return the PR number of the Release Review PR referencing *issue_number*, or None.

    The Release Review PR is the one whose head branch matches
    release-review/* AND whose body references #<issue_number>. Since the
    head-branch invariant is sufficient on a round-trip-tested repo, we
    search on head branch only.
    """
    data = gh(
        [
            "pr", "list",
            "--repo", repo,
            "--state", "open",
            "--json", "number,headRefName,title",
            "--limit", "20",
        ],
        parse_json=True,
    )
    for pr in data:
        head = pr.get("headRefName", "")
        if head.startswith(RELEASE_REVIEW_BRANCH_PREFIX) and not head.endswith(
            "-preserved"
        ):
            return pr.get("number")
    return None


# ---------------------------------------------------------------------------
# Fire + run discovery
# ---------------------------------------------------------------------------


def post_issue_comment(repo: str, issue_number: int, body: str) -> None:
    """Post *body* as a new comment on *issue_number* in *repo*."""
    gh(
        [
            "issue", "comment", str(issue_number),
            "--repo", repo,
            "--body", body,
        ]
    )


def find_recent_caller_run(
    repo: str,
    *,
    workflow_file: str,
    since: datetime,
    attempts: int = 15,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll `gh run list` for an issue_comment-triggered run newer than *since*.

    Returns the run dict (with databaseId, createdAt, url, status, conclusion)
    once one is observed. Raises InfrastructureError on timeout.
    """
    for _ in range(attempts):
        time.sleep(interval)
        runs = gh(
            [
                "run", "list",
                "--repo", repo,
                "--workflow", workflow_file,
                "--event", "issue_comment",
                "--json", "databaseId,createdAt,status,conclusion,url",
                "--limit", "10",
            ],
            parse_json=True,
        )
        candidates: list[dict[str, Any]] = []
        for run in runs:
            try:
                created = _iso_to_dt(run["createdAt"])
            except (KeyError, ValueError):
                continue
            if created >= since:
                candidates.append(run)
        if candidates:
            # Newest first — take the one with the latest createdAt.
            candidates.sort(key=lambda r: r["createdAt"], reverse=True)
            run = candidates[0]
            logger.info(
                "found caller run id=%s (%s)",
                run.get("databaseId"), run.get("url"),
            )
            return run
    raise InfrastructureError(
        f"{repo}: no {workflow_file} issue_comment run appeared within "
        f"{attempts * interval:.0f}s since {since.isoformat()}"
    )


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


def phase_pre_check(repo: str, issue_number: int) -> PhaseReport:
    """Phase 1 — confirm the target issue is in release-state:planned.

    Fail-loudly if it is not. Any other state risks stomping on a real
    release cycle (or a prior smoke run that left state dirty); recovery
    is a manual /discard-snapshot by an operator.
    """
    report = PhaseReport(name="pre-check")
    try:
        state = get_release_issue_state(repo, issue_number)
    except InfrastructureError as exc:
        report.detail = f"could not read state: {exc}"
        return report

    if state is None:
        report.detail = (
            f"{repo}#{issue_number} has no {_STATE_LABEL_PREFIX}* label — "
            f"unsafe to proceed"
        )
        return report

    if state != STATE_PLANNED:
        hint = ""
        if state == STATE_SNAPSHOT_ACTIVE:
            hint = (
                " — a prior run may have left state dirty; manual "
                "`/discard-snapshot` on the Release Issue is required to "
                "recover before the next run"
            )
        report.detail = (
            f"state is {state!r}, expected {STATE_PLANNED!r}{hint}"
        )
        return report

    report.passed = True
    report.detail = f"state={state!r} on {repo}#{issue_number}"
    return report


def phase_fire_create_snapshot(
    repo: str,
    issue_number: int,
    *,
    poll_timeout: int,
    dry_run: bool,
) -> tuple[PhaseReport, str | None]:
    """Phase 2 — post /create-snapshot, discover the caller run, poll it.

    Returns (report, run_id). run_id is None on dry-run or failure.
    """
    report = PhaseReport(name="fire /create-snapshot")
    if dry_run:
        report.passed = True
        report.detail = f"DRY-RUN: would post /create-snapshot on {repo}#{issue_number}"
        return report, None

    marker = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        post_issue_comment(repo, issue_number, "/create-snapshot")
        logger.info("posted /create-snapshot on %s#%s; polling for run", repo, issue_number)
        run = find_recent_caller_run(
            repo,
            workflow_file=_RA_CALLER_WORKFLOW,
            since=marker,
        )
    except InfrastructureError as exc:
        report.detail = f"could not fire /create-snapshot: {exc}"
        return report, None

    run_id = str(run["databaseId"])
    report.run_url = run.get("url")

    try:
        conclusion = poll_run(
            repo, run_id, interval=15, timeout=poll_timeout
        )
    except InfrastructureError as exc:
        report.detail = f"run {run_id} polling error: {exc}"
        return report, run_id

    report.run_conclusion = conclusion
    if conclusion == "success":
        report.passed = True
        report.detail = f"run completed with conclusion={conclusion!r}"
    else:
        report.detail = (
            f"run concluded {conclusion!r} (expected 'success') — "
            f"see run for details"
        )
    return report, run_id


def phase_verify_post_create(repo: str, issue_number: int) -> tuple[PhaseReport, str | None]:
    """Phase 3 — confirm the world looks like a successful /create-snapshot.

    Requirements:
    - issue state label == snapshot-active
    - exactly one release-snapshot/* branch exists
    - a Release Review PR exists (head branch starts with release-review/)

    Returns (report, snapshot_id) — snapshot_id is needed by verify-post-discard
    to confirm the rename to -preserved.
    """
    report = PhaseReport(name="verify post-create")
    try:
        state = get_release_issue_state(repo, issue_number)
    except InfrastructureError as exc:
        report.detail = f"could not read state: {exc}"
        return report, None

    checks: list[tuple[bool, str]] = []

    state_ok = state == STATE_SNAPSHOT_ACTIVE
    checks.append(
        (state_ok, f"state={state!r} {'==' if state_ok else '!='} snapshot-active")
    )

    try:
        snapshot_branch = find_snapshot_branch(repo)
    except InfrastructureError as exc:
        report.detail = f"snapshot branch lookup failed: {exc}"
        return report, None
    checks.append(
        (snapshot_branch is not None, f"snapshot branch={snapshot_branch!r}")
    )

    try:
        pr_number = release_review_pr_for_issue(repo, issue_number)
    except InfrastructureError as exc:
        report.detail = f"PR lookup failed: {exc}"
        return report, None
    checks.append(
        (pr_number is not None, f"release review PR=#{pr_number}" if pr_number else "no release review PR")
    )

    report.extras = [msg for _, msg in checks]
    report.passed = all(ok for ok, _ in checks)
    report.detail = "; ".join(msg for _, msg in checks)

    snapshot_id: str | None = None
    if snapshot_branch:
        try:
            snapshot_id = snapshot_id_from_branch(snapshot_branch)
        except InfrastructureError:
            snapshot_id = None
    return report, snapshot_id


def phase_fire_discard_snapshot(
    repo: str,
    issue_number: int,
    *,
    poll_timeout: int,
    dry_run: bool,
) -> tuple[PhaseReport, str | None]:
    """Phase 4 — post /discard-snapshot, discover the caller run, poll it."""
    report = PhaseReport(name="fire /discard-snapshot")
    if dry_run:
        report.passed = True
        report.detail = f"DRY-RUN: would post /discard-snapshot on {repo}#{issue_number}"
        return report, None

    marker = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        post_issue_comment(repo, issue_number, "/discard-snapshot")
        logger.info("posted /discard-snapshot on %s#%s; polling for run", repo, issue_number)
        run = find_recent_caller_run(
            repo,
            workflow_file=_RA_CALLER_WORKFLOW,
            since=marker,
        )
    except InfrastructureError as exc:
        report.detail = f"could not fire /discard-snapshot: {exc}"
        return report, None

    run_id = str(run["databaseId"])
    report.run_url = run.get("url")

    try:
        conclusion = poll_run(
            repo, run_id, interval=15, timeout=poll_timeout
        )
    except InfrastructureError as exc:
        report.detail = f"run {run_id} polling error: {exc}"
        return report, run_id

    report.run_conclusion = conclusion
    if conclusion == "success":
        report.passed = True
        report.detail = f"run completed with conclusion={conclusion!r}"
    else:
        report.detail = (
            f"run concluded {conclusion!r} (expected 'success') — "
            f"see run for details"
        )
    return report, run_id


def phase_verify_post_discard(
    repo: str, issue_number: int, snapshot_id: str | None
) -> PhaseReport:
    """Phase 5 — confirm the world looks like a successful /discard-snapshot.

    Requirements:
    - issue state label == planned
    - the prior release-snapshot/<snapshot_id> branch is gone
    - a release-review/<snapshot_id>-preserved branch exists
    """
    report = PhaseReport(name="verify post-discard")
    try:
        state = get_release_issue_state(repo, issue_number)
    except InfrastructureError as exc:
        report.detail = f"could not read state: {exc}"
        return report

    checks: list[tuple[bool, str]] = []

    state_ok = state == STATE_PLANNED
    checks.append(
        (state_ok, f"state={state!r} {'==' if state_ok else '!='} planned")
    )

    if snapshot_id:
        snap_branch = f"{SNAPSHOT_BRANCH_PREFIX}{snapshot_id}"
        preserved_branch = f"{RELEASE_REVIEW_BRANCH_PREFIX}{snapshot_id}-preserved"
        try:
            snap_still = branch_exists(repo, snap_branch)
            preserved = branch_exists(repo, preserved_branch)
        except InfrastructureError as exc:
            report.detail = f"branch existence check failed: {exc}"
            return report
        checks.append(
            (not snap_still, f"snapshot branch {snap_branch!r} {'still exists' if snap_still else 'gone'}")
        )
        checks.append(
            (preserved, f"preserved branch {preserved_branch!r} {'present' if preserved else 'missing'}")
        )
    else:
        checks.append(
            (False, "snapshot_id not captured in phase 3 — skipping branch checks")
        )

    report.extras = [msg for _, msg in checks]
    report.passed = all(ok for ok, _ in checks)
    report.detail = "; ".join(msg for _, msg in checks)
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(reports: list[PhaseReport], repo: str, issue_number: int) -> str:
    """Render a phase-by-phase PASS/FAIL summary as markdown."""
    passed = sum(1 for r in reports if r.passed)
    total = len(reports)
    lines: list[str] = []
    lines.append(
        f"## Release Automation Regression — {passed}/{total} phases PASS"
    )
    lines.append("")
    lines.append(f"- target repo: `{repo}`")
    lines.append(f"- release issue: #{issue_number}")
    lines.append("")
    lines.append("| Phase | Result | Detail |")
    lines.append("|---|---|---|")
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        detail = report.detail.replace("|", "\\|") if report.detail else "-"
        lines.append(f"| {report.name} | {status} | {detail} |")

    # Per-phase detail (run URLs, extras)
    for report in reports:
        if report.run_url is None and not report.extras:
            continue
        lines.append("")
        lines.append(f"### {report.name}")
        if report.run_url:
            lines.append(f"- run: {report.run_url}")
        if report.run_conclusion:
            lines.append(f"- conclusion: `{report.run_conclusion}`")
        for extra in report.extras:
            lines.append(f"- {extra}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regression_runner.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="owner/repo of the test repository (e.g. camaraproject/ReleaseTest)",
    )
    parser.add_argument(
        "--release-issue",
        type=int,
        required=True,
        help="issue number of the persistent Release Issue on --repo",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="write a markdown summary report to this path",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=600,
        help="max seconds to wait for each caller run to complete (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do not post comments or poll runs; only exercise the pre-check",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="verbose logging",
    )
    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_phases(
    repo: str,
    issue_number: int,
    *,
    poll_timeout: int,
    dry_run: bool,
) -> list[PhaseReport]:
    """Orchestrate all phases. Stop at the first fatal-to-continue failure."""
    reports: list[PhaseReport] = []

    pre = phase_pre_check(repo, issue_number)
    reports.append(pre)
    if not pre.passed:
        return reports

    create_report, _create_run_id = phase_fire_create_snapshot(
        repo, issue_number,
        poll_timeout=poll_timeout, dry_run=dry_run,
    )
    reports.append(create_report)
    if dry_run:
        logger.info("dry-run: skipping post-create verify, discard, post-discard verify")
        return reports
    if not create_report.passed:
        # A failed /create-snapshot should not be followed by /discard-snapshot:
        # if /create-snapshot failed before changing state, discard is invalid;
        # if /create-snapshot failed after changing state, an operator needs
        # to investigate before automation mutates further.
        return reports

    verify_create, snapshot_id = phase_verify_post_create(repo, issue_number)
    reports.append(verify_create)

    discard_report, _discard_run_id = phase_fire_discard_snapshot(
        repo, issue_number,
        poll_timeout=poll_timeout, dry_run=dry_run,
    )
    reports.append(discard_report)
    if not discard_report.passed:
        return reports

    verify_discard = phase_verify_post_discard(repo, issue_number, snapshot_id)
    reports.append(verify_discard)
    return reports


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    _setup_logging(args.verbose)

    try:
        reports = run_phases(
            args.repo, args.release_issue,
            poll_timeout=args.poll_timeout,
            dry_run=args.dry_run,
        )
    except InfrastructureError as exc:
        print(f"INFRA: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(reports, args.repo, args.release_issue)
    print(markdown)
    if args.summary_file:
        args.summary_file.write_text(markdown, encoding="utf-8")

    all_passed = all(r.passed for r in reports)
    passed = sum(1 for r in reports if r.passed)
    total = len(reports)
    print(
        f"{'PASS' if all_passed else 'FAIL'}: {passed}/{total} phases",
        file=sys.stderr,
    )

    # Distinguish infrastructure exit (2) from verification exit (1).
    # Infrastructure exit is surfaced earlier via the InfrastructureError
    # path above. If we got here but not all phases passed, it's either
    # a verification failure (conclusion != success or state mismatch)
    # OR an infrastructure problem captured inside a phase's detail (the
    # phase put a "could not ..." message into report.detail). We treat
    # the former as exit 1 and the latter as exit 2 by looking at the
    # first failing phase's detail for the sentinel prefix "could not".
    if all_passed:
        return 0
    for report in reports:
        if not report.passed and report.detail.startswith("could not "):
            return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
