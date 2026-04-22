# Regression Testing for the Validation Framework

A safety net for evolving the validation framework with confidence.

## Why it exists

The Validation Framework will be the gate that decides whether a CAMARA API
release proceeds. As new rules land and existing ones evolve, two failure
modes have to stay out of the framework:

1. A rule starts firing where it shouldn't. Codeowners drown in noise and
   lose trust in the tool.
2. A rule stops firing where it should. Codeowners ship a defect and nobody
   noticed.

Unit tests catch implementation bugs in individual checks. They don't catch
the cumulative behaviour of the whole framework against real API specs.
Regression testing closes that gap.

## What it does

Think of a canary in a coal mine.

A curated set of CAMARA-style API specs lives on regression branches in
`camaraproject/ReleaseTest`. Two flavours, both useful:

- **Known-good baselines** — clean specs paired with the (small) set of
  advisory findings the framework legitimately produces against them.
  These verify that "clean stays clean": no new false positives creep in
  as rules evolve.
- **Known-bad targeted branches** — specs containing intentional defects
  paired with the specific findings those defects must trigger. These
  verify that "broken stays broken": rules don't silently stop catching
  the things they were written to catch.

What's frozen on each branch is not the quality of the spec but the
**expected verdict** the framework should deliver about it. Each branch
ships with a `regression-expected.yaml` fixture that lists exactly which
findings the framework should produce.

A runner script dispatches the validation framework against each regression
branch, downloads the findings, and diffs them against the committed
expectation. PASS means the framework's behaviour is unchanged from the
last fixture capture. FAIL means something changed — and the diff shows
exactly which rules now report differently and against which files.

## Why ReleaseTest is special

Most CAMARA repositories use the **stable** version of the framework — a
tag called `v1-rc`. That tag only moves when the framework team
deliberately rolls out a new version to all repositories.

`camaraproject/ReleaseTest` is different on purpose. Its caller workflow
targets `validation.yml@validation-framework` — that is, the **HEAD of the
development branch**, not the stable tag. Every push to the
`validation-framework` branch is exercised against ReleaseTest's regression
fixtures **before** `v1-rc` is moved for the rest of the org. If a change
accidentally breaks something, the canary catches it minutes after the
push, in isolation, before any production API repository sees the change.

## What we achieve

- **Confidence to evolve rules.** Rule developers can refactor or add
  checks without fearing they'll silently break something elsewhere — the
  canary tells them within minutes if they did.
- **A safety net before each framework release.** Before the `v1-rc` tag
  is moved to a new commit, the canary is green. If it isn't, the release
  doesn't go out.
- **Living evidence of which rules are tested.** The framework has 142
  rules. The rule inventory records which of them are pinned by a
  regression branch. Adding more themed branches grows that number and
  gives a measurable picture of test coverage.
- **An authoritative answer when codeowners ask "did anything change?"**
  Either the canary is unchanged (no behaviour change) or it's changed
  and we can point at exactly which rules now report differently.

## What it is *not*

- Not a test of the **APIs themselves**. It doesn't tell us whether
  QualityOnDemand or Device Location are correct. It tests whether the
  validation framework judges them correctly.
- Not user-facing. Codeowners never see this. It's a developer tool for
  the framework team, like a smoke alarm that only the firefighters check.
- Not a replacement for the manual review work that goes into release
  PRs. It complements that — humans review release content; the canary
  makes sure the tools they rely on haven't drifted.

## How it works concretely

### Components

```
camaraproject/tooling                       camaraproject/ReleaseTest
─────────────────────                       ────────────────────────
validation/                                 main
├── docs/                                   ├── code/API_definitions/...
│   └── regression-testing.md   ◄── this    │
├── schemas/                                regression/r4.1-main-baseline
│   └── regression-expected-schema.yaml     ├── code/API_definitions/...   (frozen)
├── scripts/                                └── .regression/
│   ├── regression_runner.py                    ├── REGRESSION.md          (purpose)
│   └── README.md (CLI reference)               └── regression-expected.yaml (fixture)
└── rules/
    └── rule-inventory.yaml (tested_rules)  regression/<other-themes>...
```

### The fixture format

Each regression branch has a `.regression/regression-expected.yaml` file
that conforms to
[validation/schemas/regression-expected-schema.yaml](../schemas/regression-expected-schema.yaml).
It records:

- `branch` — the regression branch name (informational)
- `description` — what this branch tests
- `captured_at`, `captured_from_run`, `tooling_ref` — provenance: when the
  fixture was generated, which run produced it, and the validation
  framework SHA in effect at the time
- `summary` — expected aggregate counts (errors / warnings / hints), used
  as a fast sanity check
- `match_mode` — `exact` (default) rejects unexpected findings; `subset`
  allows extras
- `findings[]` — the expected list, where each entry is a unique
  `(rule_id, path, level)` tuple with an optional `count` (default 1)

### The match key — what counts as "the same finding"

Two findings are considered the same if they share the same
`(rule_id, path, level)` tuple. For findings that don't have a framework
`rule_id` (raw engine rules without metadata), the runner falls back to
`(engine/engine_rule, path, level)`.

Three things are deliberately **excluded** from the match key:

- **Line numbers.** Source maps shift as bundled output evolves; pinning
  on a line number turns every cosmetic source change into a "regression".
- **Messages.** Phrasing improves over time without changing the substance
  of the check.
- **Counts above the expected minimum.** A `count: N` entry means "at least
  N", not "exactly N". A spec fix that removes one of three duplicate hints
  is a desired change, not a regression. (This rule applies even in
  `exact` match mode; `exact` only restricts what extra `(rule, path,
  level)` keys are allowed, not how many times each one fires.)

### The runner

[validation/scripts/regression_runner.py](../scripts/regression_runner.py)
is a single-file Python CLI that talks to GitHub via the `gh` CLI. Two
modes:

**Verify mode** (default): for each matching regression branch, the runner

1. Fetches `regression-expected.yaml` from the branch via the GitHub
   contents API
2. Dispatches the validation workflow on the branch via
   `gh workflow run camara-validation.yml --ref <branch>`
3. Polls for the new run to appear (using a UTC timestamp marker plus the
   branch tip SHA to disambiguate from concurrent runs) and waits for it
   to complete
4. Downloads the `validation-diagnostics` artifact, reads
   `findings.json`, `summary.json`, and `context.json`
5. Diffs actual findings against the expected fixture and reports
6. Exits 0 (all PASS), 1 (one or more FAIL), or 2 (infrastructure
   failure)

**Capture mode** (`--capture <branch> --out <path>`): the runner runs
steps 2–4 above, then groups the actual findings into a
`regression-expected.yaml` document, and writes it to the requested
output path. The reviewer then commits that file to the branch at
`.regression/regression-expected.yaml`.

The same dispatch / download / diff code path serves both modes — there
is one set of bugs, not two.

### How `tooling_ref` is recorded

Every validation run writes its resolved tooling SHA into `context.json`
in the diagnostics artifact (the orchestrator already does this for the
workflow summary). The runner reads it directly from there, so the value
in the fixture is the SHA the run actually used, regardless of which ref
the caller targets. On ReleaseTest that's the `validation-framework` HEAD
at run time; on dark / production repos it would be whatever `v1-rc`
points at.

## Day-to-day usage

### Automatic runs on `validation-framework`

The regression runner fires automatically on every push to
`validation-framework` that touches `validation/**`, `shared-actions/**`,
or the workflow itself. The workflow lives at
[.github/workflows/validation-regression.yml](../../.github/workflows/validation-regression.yml)
on this same branch (so it only exists where it matters and does not
run on `main`). Manual dispatch is available via the Actions UI for
fix-then-verify cycles.

Cross-repo access to ReleaseTest is provided by a short-lived
`camara-validation` GitHub App installation token minted with
`owner: camaraproject, repositories: ReleaseTest`. There is no
persisted PAT.

Results surface in three places: (1) the workflow's own pass/fail
status in the Actions tab on `camaraproject/tooling`, (2) the markdown
summary on the run's summary page, and (3) the `validation-regression-summary`
artifact attached to each run (30-day retention).

### Verify all canary branches

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    --branch-filter 'regression/*'
```

Expected output for a clean run:

```
## Regression Runner — N/N branches PASS

| Branch | Result | Matched | Missing | Unexpected | Summary |
|---|---|---:|---:|---:|---|
| `regression/r4.1-main-baseline` | PASS | 27 | 0 | 0 | - |
PASS: 1/1 branches
```

Exit code 0. CLI flags and exit-code reference live in
[validation/scripts/README.md](../scripts/README.md).

### When a regression fires

The runner exits 1 and prints a per-branch diff. Three classes of failure:

- **Missing**: a finding in the fixture didn't appear in the actual run.
  Either the rule was deleted, or its conditions changed and it no longer
  fires on that file. If intentional → recapture. If not → fix the
  framework before merging the change to `validation-framework`.
- **Unexpected**: a finding appeared that wasn't in the fixture. Either a
  new rule was added (or activated) and is now firing, or a rule's
  conditions changed and it now fires where it didn't before. Same
  triage: intended → recapture; unintended → fix.
- **Summary mismatch**: the aggregate counts in `summary.json` don't
  match the fixture's `summary` block. This usually shows up alongside
  one of the other failures and confirms the cause.

### Recapturing a fixture

When a change is intentional, refresh the fixture:

```
python3 validation/scripts/regression_runner.py \
    --repo camaraproject/ReleaseTest \
    --capture regression/r4.1-main-baseline \
    --out /tmp/expected.yaml \
    --capture-description "baseline - ReleaseTest main, unmodified"
```

Review `/tmp/expected.yaml` against the previous version, commit it to
the branch at `.regression/regression-expected.yaml`, and re-run the
runner without `--capture` to confirm PASS. The fixture's `tooling_ref`
field will reflect the current `validation-framework` HEAD.

### Adding a new regression branch

1. Branch from `camaraproject/ReleaseTest@main` with a descriptive name
   under the `regression/` namespace. Naming convention:
   - **Baseline branches**: `regression/rX.Y-main-baseline`
   - **Broken-spec branches**: `regression/rX.Y-broken-spec-<theme>`

   The `rX.Y` prefix records the Commonalities minor release the branch
   was captured against. See [The broken-spec branch plan](#the-broken-spec-branch-plan)
   for the target theme set.
2. Make whatever spec edits the branch is meant to test. For a baseline
   branch, leave specs unmodified. For a broken-spec branch, keep edits
   surgical — one theme per branch — and avoid cascades into rules the
   branch is not meant to test.
3. Write a short `REGRESSION.md` at `.regression/REGRESSION.md`
   explaining what this branch is for, what it expects (edit-to-rule
   mapping for broken-spec branches), and the caller-workflow context
   if it's not the canary default.
4. Push the branch.
5. Run the runner in `--capture` mode to seed
   `.regression/regression-expected.yaml`.
6. Review, commit, push, and verify with the runner in default mode.
7. Update [validation/rules/rule-inventory.yaml](../rules/rule-inventory.yaml):
   add the new branch to the `tested_rules` entries for whichever rules
   it pins, and bump `summary.total_tested` to the new unique-rule count.

### Updating `tested_rules`

The `tested_rules` mapping in `rule-inventory.yaml` records which rules
are pinned by which regression branches:

```yaml
tested_rules:
  P-006: [regression/r4.1-main-baseline]
  S-211: [regression/r4.1-main-baseline]
  S-313: [regression/r4.1-main-baseline]
  S-314: [regression/r4.1-main-baseline]
  S-316: [regression/r4.1-main-baseline]
```

Always list-valued for uniformity when a rule is covered by multiple
branches. Treat the field as proof, not aspiration: bump it after the
runner reports PASS against the new fixture, not before.

## The broken-spec branch plan

Broken-spec branches are organised by **theme**, not by individual rule.
Each branch contains a small set of surgical edits to one or two spec
files on `camaraproject/ReleaseTest` that together trigger a coherent
group of rules. One branch = one workflow run — grouping by theme keeps
the canary dispatch budget small while still pinning every rule that
can reasonably be exercised from the spec side.

### Target themes

The r4.1 rule set partitions cleanly into seven themes (plus an optional
eighth for test-file quality). The table records the current plan; each
theme becomes one `regression/r4.1-broken-spec-<theme>` branch.

| # | Branch | Theme / target files | Rules covered | Rebase risk on minor bump |
|---|---|---|---|---|
| 1 | `regression/r4.1-broken-spec-api-metadata` | `sample-service.yaml` — `info`, `servers`, `tags` block | S-018, S-019, S-020, S-021, S-022, S-023, S-024, S-201, S-210 | LOW |
| 2 | `regression/r4.1-broken-spec-yaml-fundamentals` | `sample-service.yaml` YAML-level defects + `openapi:` version + schema type | Y-001…Y-013, S-005, S-016 | LOW |
| 3 | `regression/r4.1-broken-spec-error-handling` | `sample-service.yaml` — error responses + error codes | S-025, S-026, S-027, S-221, S-307, S-318 | LOW |
| 4 | `regression/r4.1-broken-spec-descriptions` | `sample-service.yaml` — descriptions on operations / parameters / properties / responses / array items | S-006, S-009, S-011, S-013, S-014, S-028, S-029, S-031, S-215, S-216, S-223 | MEDIUM |
| 5 | `regression/r4.1-broken-spec-schema-constraints` | `sample-service.yaml` components (not common files — avoid baseline collision) | S-012, S-017, S-030, S-300, S-303, S-308, S-309, S-310, S-311, S-312 | MEDIUM |
| 6 | `regression/r4.1-broken-spec-routing` | `sample-service.yaml` — paths, operationIds, HTTP methods, servers | S-002, S-003, S-007, S-008, S-010, S-204, S-214, S-217, S-218, S-220, S-222, S-224, S-225, S-226, S-227, S-301, S-306 | HIGH |
| 7 | `regression/r4.1-broken-spec-subscriptions` | `sample-service-subscriptions.yaml` + `sample-implicit-events.yaml` — CloudEvent / Protocol / sink / notifications + Python subscription checks | S-032, S-033, S-034, S-035, P-014, P-015, P-016, P-020 | HIGH |
| 8 (optional) | `regression/r4.1-broken-spec-test-files` | `release-plan.yaml` synthetic API + `sample-service.yaml` server URL + `sample-service-createResource.feature` gherkin defects | P-001, P-002, P-004, P-005, G-002, G-014, G-016, G-019, G-021, G-024, G-025 | LOW |

Rules **not** covered by any broken-spec branch:

- **Owned by the baseline fixture**: P-006, S-211, S-313, S-314, S-316.
  Broken-spec branches inherit these when captured, but do not own the
  pinning — they would double-count.
- **Un-triggerable via spec edits**: P-009, P-010, P-011, P-012, P-013,
  P-019 (release-plan / PR-context / fixture-dependent).
- **Branch-type dependent — silent on feature branches**: P-003
  (`check-info-version-format`) and P-007 (`check-test-file-version`)
  early-return unless `branch_type` is `main`, `release`, or
  `maintenance`. Regression branches are feature-named and always
  classify as `feature`, so these checks cannot be pinned via the
  broken-spec branch model. Unit tests at the Python check level remain
  authoritative for them.
- **Deprecated, OAS-3.1-only, or low-signal**: S-001, S-004, S-015,
  S-205, S-206, S-208, S-209, S-228, S-302, S-304, S-305, S-315, S-317,
  S-319.
- **Manual-only (not machine-checkable)**: the 25 `TG-*` rules from the
  testing guidelines audit.

### Inherited baseline findings

Broken-spec branches are cut from `main`, so every captured fixture
contains the full baseline finding set **plus** the new findings the
broken edits trigger. A broken-spec branch fixture is a complete
snapshot of its branch's output, not a delta. The runner's `exact`
match mode evaluates both halves together.

When designing a new broken-spec branch, pick edits whose new match keys
(`(rule_id, path, level)`) do **not** collide with baseline keys — the
baseline branch already pins those. If an edit would have collided, move
it to a different file or pick a different rule.

### Lifecycle across Commonalities versions

The `rX.Y` prefix records the Commonalities minor release the branch
was captured against. Two separate lifecycles apply:

- **Minor bump** (e.g. r4.1 → r4.2): rebase each broken-spec branch onto
  the updated ReleaseTest `main`, rename the prefix (`r4.1-broken-spec-*`
  → `r4.2-broken-spec-*`), recapture the fixture, force-push. Delete the
  old `r4.1-*` branch. Rationale: r4.2 is the current surface, and the
  broken-spec predicate ("info.description missing", "license.name
  wrong", etc.) is preserved by rebase for the LOW-risk themes. MEDIUM
  and HIGH risk themes may need the edits re-applied manually after the
  rebase — treat them as rewrites, not pure rebases.
- **Major bump** (e.g. r4.3 → r5.1): **keep** the last `r4.x-broken-spec-*`
  set as permanent regression coverage for the previous major, and
  create a fresh `r5.1-broken-spec-*` set from `r5.1` main. Breaking
  Commonalities changes can invalidate old predicates; the previous
  major stays frozen so long as it's still supported.

The same model applies to `regression/rX.Y-main-baseline` — rebase +
rename on minor bumps, preserve across majors.

## Sharp edges and known limitations

- **Tooling-ref pinning is set by the caller workflow.** A local
  `gh workflow run` cannot override which tooling SHA runs server-side.
  ReleaseTest pins to `validation-framework` HEAD by design (canary).
  Production API repos pin to `@v1-rc`. There is currently no way to
  test an un-published developer SHA against the runner — that's a
  separate piece of design work.
- **Dispatch → run-id race.** `gh workflow run` does not return a run
  ID. The runner records a UTC timestamp before dispatch and polls
  `gh run list` for a `workflow_dispatch` run with a matching branch
  tip SHA and a `createdAt` after the marker. Reliable in practice but
  worth knowing if you need to debug a dispatch that "vanished".
- **Findings ordering is not stable.** The post-filter emits findings in
  whatever order the engines produced them. The diff is set-based on
  the match key, so ordering is irrelevant — but if you eyeball
  `findings.json` and `regression-expected.yaml` side by side, expect
  them not to line up linearly.
- **Capture-then-verify must be deterministic.** If the runner captures
  a fixture and then immediately fails verification on a re-run against
  the same SHA, the framework's output is non-deterministic on that
  branch. That's a framework bug, not a runner bug — stop and
  investigate before adding the branch.

## Related references

- [validation/scripts/README.md](../scripts/README.md) — runner CLI
  reference, exit codes, troubleshooting
- [validation/schemas/regression-expected-schema.yaml](../schemas/regression-expected-schema.yaml)
  — JSON Schema for the fixture format
- [validation/rules/rule-inventory.yaml](../rules/rule-inventory.yaml)
  — rule registry with `tested_rules` coverage
- Upstream tracking issue: [camaraproject/ReleaseManagement#483](https://github.com/camaraproject/ReleaseManagement/issues/483)
- Umbrella validation framework issue: [camaraproject/ReleaseManagement#448](https://github.com/camaraproject/ReleaseManagement/issues/448)
