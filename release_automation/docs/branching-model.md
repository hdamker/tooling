# Branching and Versioning Model

**Last Updated**: 2026-05-05

`tooling/main` is the only long-lived branch. All development happens on fork branches that merge into `main` via pull request.

## 1. v1-rc — RA + VF release candidate (current)

`v1-rc` is a floating lightweight tag on `main` covering the unified validation framework and release automation. API repositories pin `@v1-rc` from their caller workflows. The tag advances after each change is validated against the gates below.

### Tag-move gates

| Change scope | Required signal before tag move |
|---|---|
| `.github/workflows/`, `release_automation/`, `shared-actions/`, `tooling_lib/` | Full manual end-to-end test on [`camaraproject/ReleaseTest`](https://github.com/camaraproject/ReleaseTest) (`/create-snapshot` → release-review merge → draft build → `/publish-release` → cleanup) |
| `validation/rules/`, `validation/engines/python_checks/`, `validation/context/` (rule-metadata only) | Validation Regression canary green |
| Documentation only | Tag does not move |

### Regression workflows

Two canaries verify the framework on every push to `main` that touches their declared paths:

| Workflow | Scope |
|---|---|
| [`validation-regression.yml`](../../.github/workflows/validation-regression.yml) | Diffs validation findings against committed expected fixtures on each `regression/*` branch of [`camaraproject/ReleaseTest`](https://github.com/camaraproject/ReleaseTest) |
| [`release-automation-regression.yml`](../../.github/workflows/release-automation-regression.yml) | sync-issue (dispatch and slash), a rejected command, and a `/create-snapshot` + `/discard-snapshot` round-trip with issue-close auto-reopen, and a closing issue close that recreates the Release Issue on ReleaseTest, matched against expected bot replies |

Both use a short-lived `camara-validation` GitHub App installation token for cross-repo access to ReleaseTest.

### Mandatory E2E for release-automation changes

The Release Automation Regression canary is publish-free — it does not exercise publish, draft build, or release artifact creation. Any change touching `release-automation-reusable.yml`, `release_automation/`, `shared-actions/create-snapshot/`, or related publish-side code requires a full manual E2E on ReleaseTest before `v1-rc` advances.

## 2. v1 — GA (planned)

When `v1-rc` has soaked sufficiently in production, it is promoted to `v1` (with semver `v1.0.0`). API repository callers transition from `@v1-rc` to `@v1` via campaign. The legacy `v0` tag remains available for repositories not yet onboarded to v1.

## 3. Feature development

Standard CAMARA contribution flow:

1. Fork `camaraproject/tooling`.
2. Create a branch on the fork.
3. Open a pull request against `main`.
4. Codeowner review per [`CODEOWNERS`](../../CODEOWNERS).
5. Merge after review and required checks pass.

Long-lived feature branches in the upstream repository are not the default. They may be appropriate for cross-cutting initiatives whose scope justifies the additional coordination overhead (sync PRs, configuration parallelism, regression-canary pinning), and are decided case-by-case.

## 4. Hotfixes

When a critical fix cannot wait for a regular feature cycle:

1. Branch `fix/<description>` from `main`.
2. Implement and validate the fix.
3. Place a hotfix tag on the validated commit so consumers can pin to an immutable reference.
4. Merge the branch back into `main` as soon as possible — the fix must not stay isolated on the hotfix branch.

## Appendix: development history

Two long-lived feature branches preceded the current single-branch model:

- **`release-automation`** — release-automation development. Merged into `main` 2026-03-27 ([#135](https://github.com/camaraproject/tooling/pull/135)); the `ra-v1-rc` tag was retired with the merge.
- **`validation-framework`** — validation framework and release-automation integration. Merged into `main` 2026-05-05 ([#260](https://github.com/camaraproject/tooling/pull/260)). The unified `v1-rc` tag spanned the merge unchanged.

Both branches are retired.
