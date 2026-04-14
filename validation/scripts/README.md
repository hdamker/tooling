# Validation Framework — Scripts

CLI entry points for the validation framework. Callable both from reusable
workflow steps and from a developer workstation.

## `validate-release-plan.py`

Validates `release-plan.yaml` files against the JSON schema and semantic rules.
Called by `pr_validation` via `shared-actions/validate-release-plan`. Do not
modify its CLI or exit codes without updating that action.

```
python3 validate-release-plan.py <release-plan-file> [--check-files]
```

## `regression_runner.py`

Dispatches the validation framework against `regression/*` branches of a test
repository, downloads findings, and diffs them against the committed
`.regression/regression-expected.yaml` fixture on each branch.

For motivation, the canary model, the fixture format, and day-to-day
workflows (capture, verify, recapture, adding new branches), see the manual:
**[../docs/regression-testing.md](../docs/regression-testing.md)**.

This file is the CLI reference only.

### Prerequisites

- Python 3.11+ with `pyyaml` and `jsonschema`
- `gh` CLI installed and authenticated (`gh auth status` must be green)
- The test repo must have the validation framework caller workflow installed
  at `.github/workflows/camara-validation.yml`
- For verify mode: each `regression/*` branch must contain
  `.regression/regression-expected.yaml` conforming to
  [../schemas/regression-expected-schema.yaml](../schemas/regression-expected-schema.yaml)

### Verify mode

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    [--branch-filter 'regression/r4.1-*'] \
    [--workflow-file camara-validation.yml] \
    [--poll-interval 15] [--poll-timeout 1800] \
    [--summary-file regression-summary.md] \
    [-v|--verbose]
```

Default `--branch-filter` is `regression/*`. Default `--workflow-file` is
`camara-validation.yml`.

### Capture mode

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    --capture regression/r4.1-main-baseline \
    --out /tmp/expected.yaml \
    [--capture-description "baseline - ReleaseTest main, unmodified"]
```

Writes a fresh `regression-expected.yaml` to `--out`. Review, commit to the
branch at `.regression/regression-expected.yaml`, and re-run in verify mode
to confirm PASS. See the manual for the full add-a-new-branch flow.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All branches PASS (or capture succeeded) |
| 1 | One or more branches FAIL (diff mismatch) |
| 2 | Infrastructure failure (gh error, timeout, missing artifact, schema invalid) |

### Troubleshooting

- **`gh CLI not found`** — install from <https://cli.github.com/> and run
  `gh auth login`.
- **`timed out waiting for dispatched run to appear`** — GitHub Actions
  backlog; retry after a minute, or raise `--poll-timeout`.
- **`findings.json not found in downloaded artifact`** — the workflow run
  probably failed before the output step. Check the run URL printed in
  the log.
- **Capture-then-verify fails on immediate re-run** — the validation output
  is non-deterministic for this branch. That's a framework bug, not a
  runner bug; stop and investigate. See the "Sharp edges" section of the
  manual.
