#!/usr/bin/env python3
"""
CAMARA Validation Framework — Regression Runner

Dispatches the Validation Framework against regression/* branches of a test
repository, downloads findings, and diffs them against a committed
regression-expected.yaml fixture on each branch.

Usage:
    python3 regression_runner.py --repo camaraproject/ReleaseTest \\
        [--branch-filter 'regression/r4.1-*'] \\
        [--workflow-file camara-validation.yml] \\
        [--poll-interval 15] [--poll-timeout 1800]

    # Capture an expected-findings fixture from a fresh run:
    python3 regression_runner.py --repo camaraproject/ReleaseTest \\
        --capture regression/r4.1-main-baseline --out /tmp/expected.yaml

Exit codes:
    0  all branches PASS (or capture succeeded)
    1  one or more branches FAIL (diff mismatch)
    2  infrastructure failure (gh error, timeout, missing artifact, invalid schema)

Design reference: private-dev-docs/validation-framework/session-logs/
  (initial session — WS07 Phase 3 regression infrastructure)
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:
    print("Error: pyyaml package is required. Install with: pip install pyyaml")
    sys.exit(2)

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError:
    print("Error: jsonschema package is required. Install with: pip install jsonschema")
    sys.exit(2)


logger = logging.getLogger("regression_runner")


# ---------------------------------------------------------------------------
# Types and errors
# ---------------------------------------------------------------------------


class InfrastructureError(RuntimeError):
    """Raised for gh errors, missing artifacts, schema failures, or timeouts.

    Distinct from a failed diff (which is a regression, not infrastructure).
    Infrastructure errors map to exit code 2; diff failures map to exit 1.
    """


# Match key = (rule_key, path, level). rule_key is the framework rule_id
# when present, otherwise f"{engine}/{engine_rule}". Level is the
# post-filter level string ("error", "warn", "hint").
MatchKey = tuple[str, str, str]


@dataclass
class DiffReport:
    branch: str
    match_mode: str
    matched: int
    missing: list[dict[str, Any]] = field(default_factory=list)
    unexpected: list[dict[str, Any]] = field(default_factory=list)
    summary_mismatch: str | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.missing
            and not self.unexpected
            and self.summary_mismatch is None
        )


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_path() -> Path:
    return _repo_root() / "validation" / "schemas" / "regression-expected-schema.yaml"


# ---------------------------------------------------------------------------
# Pure logic — loader, normalize, diff, capture
# ---------------------------------------------------------------------------


def load_expected(source: str | Path) -> dict[str, Any]:
    """Load and schema-validate a regression-expected.yaml fixture.

    Accepts a Path (file on disk) or a raw YAML string. Raises
    InfrastructureError on schema violations so that the runner maps to
    exit code 2 rather than treating a malformed fixture as a regression.
    """
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
        origin = str(source)
    else:
        text = source
        origin = "<inline>"

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InfrastructureError(f"{origin}: YAML parse error: {exc}") from exc

    if not isinstance(data, dict):
        raise InfrastructureError(f"{origin}: expected a YAML mapping at the root")

    schema_path = _schema_path()
    if not schema_path.exists():
        raise InfrastructureError(f"Schema file not found: {schema_path}")
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"{origin}: schema validation failed:"]
        for err in errors:
            path = ".".join(str(p) for p in err.absolute_path) or "<root>"
            lines.append(f"  at {path}: {err.message}")
        raise InfrastructureError("\n".join(lines))

    # Reject duplicate match keys within the fixture — they must be
    # collapsed into one entry with `count`.
    seen: dict[MatchKey, int] = {}
    for idx, item in enumerate(data.get("findings", [])):
        key = _expected_key(item)
        if key in seen:
            raise InfrastructureError(
                f"{origin}: duplicate finding entry at index {idx} "
                f"(match key already at index {seen[key]}). "
                f"Collapse into one entry with count."
            )
        seen[key] = idx

    return data


def _expected_key(entry: dict[str, Any]) -> MatchKey:
    """Compute the match key for an expected-finding entry."""
    if "rule_id" in entry:
        rule_key = entry["rule_id"]
    else:
        rule_key = f"{entry['engine']}/{entry['engine_rule']}"
    return (rule_key, entry["path"], entry["level"])


def normalize_finding(finding: dict[str, Any]) -> MatchKey:
    """Compute the match key for an actual finding dict from findings.json.

    Deliberately ignores `line`, `column`, `message`, `api_name`, `hint`,
    and any engine-specific extras. Uses `rule_id` when present, falling
    back to `engine/engine_rule` otherwise.
    """
    rule_id = finding.get("rule_id")
    if rule_id:
        rule_key = rule_id
    else:
        engine = finding.get("engine", "?")
        engine_rule = finding.get("engine_rule", "?")
        rule_key = f"{engine}/{engine_rule}"
    return (rule_key, finding.get("path", ""), finding.get("level", ""))


def _index_expected(findings: list[dict[str, Any]]) -> dict[MatchKey, int]:
    counts: dict[MatchKey, int] = {}
    for entry in findings:
        counts[_expected_key(entry)] = entry.get("count", 1)
    return counts


def _index_actual(findings: list[dict[str, Any]]) -> dict[MatchKey, int]:
    counts: dict[MatchKey, int] = {}
    for finding in findings:
        key = normalize_finding(finding)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _check_summary(
    expected: dict[str, Any] | None,
    actual_summary: dict[str, Any] | None,
) -> str | None:
    if expected is None:
        return None
    if actual_summary is None:
        return "expected `summary` block but no summary.json was found"
    counts = actual_summary.get("counts", {})
    mismatches: list[str] = []
    for key in ("errors", "warnings", "hints"):
        if key not in expected:
            continue
        want = expected[key]
        have = counts.get(key, 0)
        if want != have:
            mismatches.append(f"{key}: expected={want} actual={have}")
    if mismatches:
        return "; ".join(mismatches)
    return None


def diff_findings(
    expected: dict[str, Any],
    actual: list[dict[str, Any]],
    actual_summary: dict[str, Any] | None = None,
) -> DiffReport:
    """Diff actual findings against an expected fixture.

    Match key is (rule_id_or_engine_rule, path, level). `count` is minimum
    required — surpluses are only a failure in `exact` match_mode. Line
    numbers and messages are deliberately ignored.
    """
    mode = expected.get("match_mode", "exact")
    expected_counts = _index_expected(expected.get("findings", []))
    actual_counts = _index_actual(actual)

    missing: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    matched = 0

    for key, need in expected_counts.items():
        have = actual_counts.get(key, 0)
        matched += min(need, have)
        if have < need:
            missing.append(
                {
                    "rule": key[0],
                    "path": key[1],
                    "level": key[2],
                    "expected": need,
                    "actual": have,
                }
            )

    if mode == "exact":
        for key, have in actual_counts.items():
            need = expected_counts.get(key, 0)
            if have > need:
                unexpected.append(
                    {
                        "rule": key[0],
                        "path": key[1],
                        "level": key[2],
                        "expected": need,
                        "actual": have,
                    }
                )

    summary_mismatch = _check_summary(expected.get("summary"), actual_summary)

    return DiffReport(
        branch=expected.get("branch", "<unknown>"),
        match_mode=mode,
        matched=matched,
        missing=missing,
        unexpected=unexpected,
        summary_mismatch=summary_mismatch,
    )


def capture_to_yaml(
    actual: list[dict[str, Any]],
    *,
    branch: str,
    run_url: str | None,
    tooling_ref: str | None,
    description: str | None = None,
) -> str:
    """Group actual findings into a regression-expected.yaml document.

    Collapses duplicate match keys into a single entry with `count`. Emits
    deterministic ordering (sorted by rule_key, path, level) so that
    repeated captures produce identical output for clean diffs.
    """
    counts: dict[MatchKey, int] = {}
    for finding in actual:
        key = normalize_finding(finding)
        counts[key] = counts.get(key, 0) + 1

    # Aggregate counts (matches summary.json["counts"] shape used by the
    # VF output pipeline).
    errors = sum(1 for f in actual if f.get("level") == "error")
    warnings = sum(1 for f in actual if f.get("level") == "warn")
    hints = sum(1 for f in actual if f.get("level") == "hint")

    findings_entries: list[dict[str, Any]] = []
    for (rule_key, path, level), count in sorted(counts.items()):
        entry: dict[str, Any] = {}
        if re.match(r"^[A-Z]-[0-9]{3}$", rule_key):
            entry["rule_id"] = rule_key
        else:
            engine, _, engine_rule = rule_key.partition("/")
            entry["engine"] = engine
            entry["engine_rule"] = engine_rule
        entry["path"] = path
        entry["level"] = level
        if count > 1:
            entry["count"] = count
        findings_entries.append(entry)

    doc: dict[str, Any] = {
        "schema_version": 1,
        "branch": branch,
    }
    if description:
        doc["description"] = description
    doc["captured_at"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    if run_url:
        doc["captured_from_run"] = run_url
    if tooling_ref:
        doc["tooling_ref"] = tooling_ref
    doc["summary"] = {
        "errors": errors,
        "warnings": warnings,
        "hints": hints,
    }
    doc["match_mode"] = "exact"
    doc["findings"] = findings_entries

    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(reports: dict[str, DiffReport]) -> str:
    """Render a per-branch PASS/FAIL summary as markdown."""
    total = len(reports)
    passed = sum(1 for r in reports.values() if r.passed)
    lines: list[str] = []
    lines.append(f"## Regression Runner — {passed}/{total} branches PASS")
    lines.append("")
    lines.append("| Branch | Result | Matched | Missing | Unexpected | Summary |")
    lines.append("|---|---|---:|---:|---:|---|")
    for branch, report in sorted(reports.items()):
        status = "PASS" if report.passed else "FAIL"
        summary_note = report.summary_mismatch or "-"
        lines.append(
            f"| `{branch}` | {status} | {report.matched} | "
            f"{len(report.missing)} | {len(report.unexpected)} | {summary_note} |"
        )
    for branch, report in sorted(reports.items()):
        if report.passed:
            continue
        lines.append("")
        lines.append(f"### `{branch}` — diff detail")
        if report.summary_mismatch:
            lines.append(f"- **summary mismatch**: {report.summary_mismatch}")
        for entry in report.missing:
            lines.append(
                f"- **missing** `{entry['rule']}` at `{entry['path']}` "
                f"({entry['level']}): expected {entry['expected']}, actual {entry['actual']}"
            )
        for entry in report.unexpected:
            lines.append(
                f"- **unexpected** `{entry['rule']}` at `{entry['path']}` "
                f"({entry['level']}): expected {entry['expected']}, actual {entry['actual']}"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# GitHub I/O (via gh CLI subprocess)
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


def list_regression_branches(repo: str, pattern: str) -> list[str]:
    """Return branch names on *repo* matching *pattern* (fnmatch glob)."""
    branches = gh(
        ["api", f"repos/{repo}/branches", "--paginate", "--jq", ".[].name"]
    )
    names = [line.strip() for line in branches.splitlines() if line.strip()]
    return sorted(name for name in names if fnmatch.fnmatch(name, pattern))


def fetch_expected(repo: str, branch: str) -> dict[str, Any]:
    """Fetch and validate `.regression/regression-expected.yaml` from *branch*."""
    path = ".regression/regression-expected.yaml"
    try:
        payload = gh(
            [
                "api",
                f"repos/{repo}/contents/{path}",
                "-H", "Accept: application/vnd.github+json",
                "--jq", ".content",
                "-X", "GET",
                "-f", f"ref={branch}",
            ]
        )
    except InfrastructureError as exc:
        raise InfrastructureError(
            f"{repo}@{branch}: could not fetch {path} — {exc}"
        ) from exc
    content_b64 = payload.strip().replace("\n", "")
    try:
        text = base64.b64decode(content_b64).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 — any decode error is infra
        raise InfrastructureError(
            f"{repo}@{branch}: could not base64-decode {path}: {exc}"
        ) from exc
    return load_expected(text)


def branch_tip_sha(repo: str, branch: str) -> str:
    """Return the current tip SHA of *branch* on *repo*."""
    data = gh(
        ["api", f"repos/{repo}/branches/{branch}", "--jq", ".commit.sha"]
    )
    sha = data.strip()
    if not re.match(r"^[0-9a-f]{40}$", sha):
        raise InfrastructureError(
            f"{repo}@{branch}: unexpected branch tip response: {sha!r}"
        )
    return sha


def _iso_to_dt(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def dispatch_validation(
    repo: str,
    branch: str,
    *,
    workflow_file: str,
    startup_attempts: int = 15,
    startup_interval: float = 2.0,
) -> str:
    """Dispatch *workflow_file* on *branch* of *repo* and return the run ID.

    GitHub's `workflow run` endpoint does not return the created run ID, so
    we record a UTC marker, call dispatch, then poll `gh run list` for a new
    workflow_dispatch run whose `createdAt` is >= marker and whose `headSha`
    matches the branch tip. Raises InfrastructureError on timeout.
    """
    sha = branch_tip_sha(repo, branch)
    marker = datetime.now(timezone.utc).replace(microsecond=0)
    gh(
        [
            "workflow", "run", workflow_file,
            "--repo", repo,
            "--ref", branch,
        ]
    )
    logger.info("dispatched %s on %s@%s; polling for run id", workflow_file, repo, branch)

    for _ in range(startup_attempts):
        time.sleep(startup_interval)
        runs = gh(
            [
                "run", "list",
                "--repo", repo,
                "--workflow", workflow_file,
                "--branch", branch,
                "--event", "workflow_dispatch",
                "--json", "databaseId,createdAt,headSha,status,conclusion",
                "--limit", "10",
            ],
            parse_json=True,
        )
        for run in runs:
            try:
                created = _iso_to_dt(run["createdAt"])
            except (KeyError, ValueError):
                continue
            if created >= marker and run.get("headSha") == sha:
                run_id = str(run["databaseId"])
                logger.info("found dispatched run id=%s", run_id)
                return run_id

    raise InfrastructureError(
        f"{repo}@{branch}: timed out waiting for dispatched run to appear "
        f"(polled {startup_attempts} times)"
    )


def poll_run(
    repo: str,
    run_id: str,
    *,
    interval: int,
    timeout: int,
) -> str:
    """Wait until *run_id* completes; return its conclusion string.

    Raises InfrastructureError on timeout. A conclusion of "success" is the
    only value that guarantees artifacts are ready; other conclusions still
    produce a result and are returned for the caller to decide.
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


def download_findings(
    repo: str,
    run_id: str,
    workdir: Path,
    artifact_name: str = "validation-diagnostics",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Download the validation-diagnostics artifact and load findings, summary, context.

    Returns (findings_list, summary_dict_or_None, context_dict_or_None).
    Raises InfrastructureError if the artifact is missing or findings.json is
    not parseable. Summary and context are best-effort: if they fail to load,
    the corresponding return value is None.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    gh(
        [
            "run", "download", run_id,
            "--repo", repo,
            "--name", artifact_name,
            "--dir", str(workdir),
        ]
    )
    findings_path = workdir / "findings.json"
    if not findings_path.exists():
        # gh run download strips the artifact name from the path if --name is
        # passed; but some versions preserve it. Check both.
        nested = workdir / artifact_name / "findings.json"
        if nested.exists():
            findings_path = nested
    if not findings_path.exists():
        raise InfrastructureError(
            f"findings.json not found in downloaded artifact at {workdir}"
        )
    try:
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InfrastructureError(
            f"findings.json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(findings, list):
        raise InfrastructureError(
            f"findings.json root is not a list (got {type(findings).__name__})"
        )

    def _load_optional(name: str) -> dict[str, Any] | None:
        path = findings_path.parent / name
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    summary = _load_optional("summary.json")
    context = _load_optional("context.json")
    return findings, summary, context


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_branch(
    repo: str,
    branch: str,
    *,
    workflow_file: str,
    poll_interval: int,
    poll_timeout: int,
) -> DiffReport:
    """Full per-branch check: fetch expected, dispatch, poll, download, diff."""
    logger.info("[%s] fetching expected fixture", branch)
    expected = fetch_expected(repo, branch)

    logger.info("[%s] dispatching validation workflow", branch)
    run_id = dispatch_validation(repo, branch, workflow_file=workflow_file)

    logger.info("[%s] polling run %s", branch, run_id)
    conclusion = poll_run(repo, run_id, interval=poll_interval, timeout=poll_timeout)
    if conclusion not in {"success", "failure", "neutral"}:
        raise InfrastructureError(
            f"[{branch}] unexpected run conclusion: {conclusion}"
        )

    with tempfile.TemporaryDirectory(prefix="vf-regression-") as td:
        workdir = Path(td)
        logger.info("[%s] downloading diagnostics into %s", branch, workdir)
        actual, summary, _context = download_findings(repo, run_id, workdir)

    report = diff_findings(expected, actual, actual_summary=summary)
    report.branch = branch
    return report


def capture_branch(
    repo: str,
    branch: str,
    *,
    out_path: Path,
    workflow_file: str,
    poll_interval: int,
    poll_timeout: int,
    description: str | None,
) -> Path:
    """Dispatch the VF, download findings, and write a fresh expected fixture.

    Writes to *out_path*; the caller commits it to the branch after review.
    """
    logger.info("[%s] CAPTURE: dispatching workflow", branch)
    run_id = dispatch_validation(repo, branch, workflow_file=workflow_file)
    logger.info("[%s] CAPTURE: polling run %s", branch, run_id)
    conclusion = poll_run(repo, run_id, interval=poll_interval, timeout=poll_timeout)
    logger.info("[%s] CAPTURE: run completed (%s)", branch, conclusion)

    with tempfile.TemporaryDirectory(prefix="vf-capture-") as td:
        workdir = Path(td)
        actual, _summary, context = download_findings(repo, run_id, workdir)

    # The actually-used tooling SHA comes from the validation context
    # written by the orchestrator. This is the canonical answer and works
    # regardless of which ref the caller targets (@v1-rc on dark repos,
    # @validation-framework HEAD on the ReleaseTest canary, etc.).
    tooling_ref: str | None = (context or {}).get("tooling_ref") or None
    if tooling_ref and not re.match(r"^[0-9a-f]{40}$", tooling_ref):
        logger.warning(
            "context.json tooling_ref is not a 40-char SHA: %r — omitting from fixture",
            tooling_ref,
        )
        tooling_ref = None

    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    text = capture_to_yaml(
        actual,
        branch=branch,
        run_url=run_url,
        tooling_ref=tooling_ref,
        description=description,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    logger.info("[%s] CAPTURE: wrote %d findings to %s", branch, len(actual), out_path)
    return out_path


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
        "--branch-filter",
        default="regression/*",
        help="fnmatch glob over branch names (default: %(default)s)",
    )
    parser.add_argument(
        "--workflow-file",
        default="camara-validation.yml",
        help="caller workflow filename in the test repo (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=15,
        help="seconds between run status polls (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=1800,
        help="max seconds to wait for a run to complete (default: %(default)s)",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="write a markdown summary report to this path",
    )
    parser.add_argument(
        "--capture",
        metavar="BRANCH",
        help="CAPTURE MODE: dispatch against BRANCH and write a fresh "
             "regression-expected.yaml to --out (skips diff/reporting)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="output path for --capture mode",
    )
    parser.add_argument(
        "--capture-description",
        help="description field for captured fixture (optional)",
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


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    _setup_logging(args.verbose)

    try:
        if args.capture:
            if not args.out:
                print("error: --capture requires --out", file=sys.stderr)
                return 2
            capture_branch(
                args.repo,
                args.capture,
                out_path=args.out,
                workflow_file=args.workflow_file,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                description=args.capture_description,
            )
            print(f"CAPTURE OK: wrote {args.out}")
            return 0

        branches = list_regression_branches(args.repo, args.branch_filter)
        if not branches:
            print(
                f"No branches on {args.repo} match filter "
                f"{args.branch_filter!r}",
                file=sys.stderr,
            )
            return 2
        logger.info("matched %d branch(es): %s", len(branches), ", ".join(branches))

        reports: dict[str, DiffReport] = {}
        for branch in branches:
            report = run_branch(
                args.repo,
                branch,
                workflow_file=args.workflow_file,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )
            reports[branch] = report

    except InfrastructureError as exc:
        print(f"INFRA: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(reports)
    print(markdown)
    if args.summary_file:
        args.summary_file.write_text(markdown, encoding="utf-8")

    passed = all(r.passed for r in reports.values())
    total = len(reports)
    passing = sum(1 for r in reports.values() if r.passed)
    print(f"{'PASS' if passed else 'FAIL'}: {passing}/{total} branches", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
