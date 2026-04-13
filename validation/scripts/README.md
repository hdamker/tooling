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

### Prerequisites

- Python 3.11+ with `pyyaml` and `jsonschema`
- `gh` CLI installed and authenticated (`gh auth status` must be green)
- The test repo must have the Validation Framework caller workflow installed
  (`.github/workflows/camara-validation.yml`)
- Each `regression/*` branch must contain `.regression/regression-expected.yaml`
  conforming to `validation/schemas/regression-expected-schema.yaml`

### Run

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    [--branch-filter 'regression/r4.1-*'] \
    [--workflow-file camara-validation.yml] \
    [--poll-interval 15] [--poll-timeout 1800] \
    [--summary-file regression-summary.md]
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | all branches PASS |
| 1 | one or more branches FAIL (diff mismatch) |
| 2 | infrastructure failure (gh error, timeout, missing artifact, schema invalid) |

### Capture a new fixture

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    --capture regression/r4.1-main-baseline \
    --out /tmp/expected.yaml \
    [--capture-description "baseline"]
```

Review the generated file, commit it to the branch at
`.regression/regression-expected.yaml`, then re-run the runner without
`--capture` to verify PASS.

### Fixture match semantics

- Match key is `(rule_id, path, level)` — or `(engine/engine_rule, path, level)`
  when the framework has no `rule_id` for the rule.
- Line numbers and messages are **not** part of the match key.
- `count` means "at least N" in both `exact` and `subset` modes.
- `match_mode: exact` (default) fails on unexpected extra findings;
  `match_mode: subset` allows extras and only fails on missing expected findings.
- The optional top-level `summary` block is checked against
  `summary.json.counts` before per-finding diffing; any mismatch there is a
  separate failure axis.

### Tooling ref pinning (known constraint)

The caller workflow hardcodes `uses: camaraproject/tooling/.github/workflows/validation.yml@v1-rc`
and does not forward `workflow_dispatch` inputs to the reusable. OIDC
resolution inside the reusable therefore locks to whatever commit `v1-rc`
currently points at — a local `gh workflow run` cannot override this.

Fixtures are implicitly pinned to that ref. Record the current `v1-rc` SHA in
each branch's `REGRESSION.md` (`gh api repos/camaraproject/tooling/git/refs/tags/v1-rc --jq '.object.sha'`).
If `v1-rc` moves, recapture the fixtures.

### Troubleshooting

- **`gh CLI not found`** — install from <https://cli.github.com/> and run
  `gh auth login`.
- **`timed out waiting for dispatched run to appear`** — GitHub Actions
  backlog; retry after a minute, or raise `--poll-timeout`.
- **`findings.json not found in downloaded artifact`** — the workflow run
  probably failed before the output step. Check the run URL printed in
  the log.
- **Capture-then-verify fails on immediate re-run** — the validation output
  is non-deterministic for this branch. Treat as a framework bug, not a
  runner bug; stop and investigate.
