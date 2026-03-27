# Upstream Branching and Versioning Model

**Last Updated**: 2026-03-24

## Overview

The `camaraproject/tooling` repository uses feature branches for independent development streams. Each stream has its own lifecycle and tag namespace. Streams merge to `main` sequentially as they reach stability, with the `v1` tag assigned only after all streams are proven stable on `main`.

## Branch Layout

Development proceeds in two phases. Release automation merged to `main` first (at RC stability). The validation framework then branches from the merged `main` and merges when it reaches its own stability.

### Phase 1: Release automation development (complete)

```
main ──────────────────────── pr_validation v0 (production)
  │
  └── release-automation ──── release creation workflow (RC)
```

### Phase 2: Validation framework development (current)

```
main ──────────────────────── pr_validation v0 + release automation
  │
  └── validation-framework ── validation framework v1
```

| Branch | Purpose | Tag namespace | Status |
|--------|---------|---------------|--------|
| `main` | pr_validation v0 + release automation | `v0`, `v0.x.y`, `ra-v1-rc` | Active |
| `validation-framework` | Validation framework superseding pr_validation | `v1-rc` | Active development |

### Why sequential merges

- Release automation reached RC stability independently and can merge without waiting for the validation framework
- Merging release automation first avoids managing two long-lived feature branches with shared dependencies (validation depends on release automation data structures such as release-metadata.yaml schema and branch naming conventions)
- The validation framework branches from the merged `main`, inheriting both pr_validation v0 and release automation code as its base
- Post-merge improvements to release automation land on `main` via short-lived fix branches; the `validation-framework` branch picks them up via periodic merge from `main`

## Lifecycle Phases

### Release Automation Phases

#### Alpha (internal validation)

| Aspect | Detail |
|--------|--------|
| **Branch** | `release-automation` |
| **Caller ref** | `@release-automation` (branch HEAD) |
| **Test scope** | Test repositories (e.g., ReleaseTest) |
| **Tag** | None — branch HEAD is the reference |

The alpha phase validates the release automation on dedicated test repositories. Fixes land directly on the branch. No tag is needed because only test repositories reference this branch.

#### RC (early adopters)

| Aspect | Detail |
|--------|--------|
| **Branch** | `release-automation` |
| **Caller ref** | `@ra-v1-rc` (floating tag) |
| **Test scope** | Test repositories + volunteering API repositories |
| **Tag** | `ra-v1-rc` — moved forward after test repo validates each change |

The RC phase opens the release automation to volunteering API repositories. The `ra-v1-rc` tag provides a stable reference that only advances after validation on test repositories.

**Hotfix flow during RC:**
1. Fix lands on `release-automation` branch
2. Validate on test repositories (caller references `@release-automation`)
3. Move `ra-v1-rc` tag to the validated commit
4. Volunteering repos pick up the fix on next workflow trigger

#### Merge to main

The `release-automation` branch merges to `main` when it reaches RC stability. After merging:

- `ra-v1-rc` tag moves to the merge commit on `main`
- Consumers continue referencing `@ra-v1-rc` — no caller workflow change required
- `v0` tag advances to `v0.3.0` (after verifying pr_validation v0 is unchanged)
- The `release-automation` branch is deleted
- Further release automation fixes land on `main` via short-lived branches

### Validation Framework Phases

The `validation-framework` branch is created from the merged `main` and develops a new validation workflow that supersedes pr_validation v0:
- Validation aligned with the release concept (working on main and snapshot branches)
- Extended validation rules and enforcement of allowed changes per branch type
- Commonalities schema bundling (external `$ref` resolution)
- Replacement of MegaLinter

This workflow supersedes pr_validation v0 rather than replacing it — the v0 workflow remains available on `main` with the `v0` tag for repositories that have not yet migrated.

#### Development

| Aspect | Detail |
|--------|--------|
| **Branch** | `validation-framework` |
| **Caller ref** | `@validation-framework` (branch HEAD) |
| **Test scope** | Test repositories only |
| **Tag** | None — branch HEAD is the reference |

During development, the validation framework is tested on dedicated test repositories.

#### Dark deployment and RC

| Aspect | Detail |
|--------|--------|
| **Branch** | `validation-framework` |
| **Caller ref** | `@v1-rc` (floating tag) |
| **Test scope** | Test repositories + all repos (stage 0/dark) → volunteering repos (stages 1-2) |
| **Tag** | `v1-rc` — moved forward after test repo validates each change |

When the validation framework is ready for wider deployment, the `v1-rc` floating tag is introduced on the `validation-framework` branch. The validation caller workflow is rolled out to all repositories referencing `@v1-rc`. The central config file controls which repos actually run validation — the reusable workflow exits immediately for repos at stage 0 (dark).

#### Release automation integration

When the validation framework reaches sufficient stability, the release automation integration (pre-snapshot validation gate, bundled spec handoff) is implemented on the `validation-framework` branch. At this point, both the validation and release automation reusable workflows live on `validation-framework`, and `v1-rc` covers the combined stack.

Repositories that need the integrated release automation switch their RA caller from `@ra-v1-rc` (on main) to `@v1-rc` (on validation-framework). Repositories that do not need early integration keep their RA caller on `@ra-v1-rc` and transition directly to `@v1` after the merge to main.

#### Merge to main

The `validation-framework` branch merges to `main` when the combined stack is stable. `v1-rc` moves to the merge commit on `main`.

### GA Transition

Once the validation framework merges to `main` and the combined stack is proven stable:

- `v1` tag created on `main` (+ semver `v1.0.0`)
- Campaign updates all callers to `@v1`:
  - RA callers: most repos transition from `@ra-v1-rc` → `@v1` (direct, never left main)
  - RA callers: test/volunteer repos transition from `@v1-rc` → `@v1`
  - Validation callers: all repos transition from `@v1-rc` → `@v1`
- `ra-v1-rc` and `v1-rc` tags are retired
- `v0` tag remains on its last commit for repos not yet migrated from pr_validation

| Aspect | After RA merge | During VF development | After VF merge + v1 tag |
|--------|---------------|----------------------|------------------------|
| **Branch** | `main` | `main` + `validation-framework` | `main` |
| **RA caller ref** | `@ra-v1-rc` (on main) | most: `@ra-v1-rc` (main), test: `@v1-rc` (VF branch) | `@v1` |
| **Validation caller ref** | — | `@v1-rc` (VF branch) | `@v1` |
| **Test scope** | RA: test + volunteering | VF: test + volunteering, RA integration: test only | All API repos |

## Tag Strategy

| Tag | Type | Scope | Moves? |
|-----|------|-------|--------|
| `v0` | Floating major | main | Yes — tracks latest v0.x.y |
| `v0.x.y` | Semver | main (pr_validation only for x < 3, incl. release automation for x >= 3) | No — immutable |
| `ra-v1-rc` | Floating RC | release-automation branch → main | Yes — retired when `v1` is assigned |
| `v1-rc` | Floating RC | validation-framework branch → main | Yes — moved after test repo validates; retired when `v1` is assigned |
| `v1` | Floating major | main (after GA proven) | Yes — tracks latest v1.x.y |
| `v1.x.y` | Semver | main (after GA) | No — immutable |

## Caller Workflow References

Each API repository's caller workflow references the reusable workflow by tag or branch:

```yaml
uses: camaraproject/tooling/.github/workflows/release-automation-reusable.yml@<ref>
```

| Phase | RA caller `<ref>` | Validation caller `<ref>` | Who uses it |
|-------|-------------------|--------------------------|-------------|
| RA Alpha | `release-automation` | — | Test repos only |
| RA RC | `ra-v1-rc` | — | Test + volunteering repos |
| RA post-merge | `ra-v1-rc` (on main) | — | Test + volunteering repos |
| VF development | `ra-v1-rc` (on main) | `validation-framework` | VF: test repos only |
| VF dark/RC | `ra-v1-rc` (on main) | `v1-rc` | VF: all repos (dark) → volunteering |
| RA integration | test: `v1-rc`, rest: `ra-v1-rc` | `v1-rc` | RA+VF integration: test repos only |
| GA | `v1` | `v1` | All API repos |

The campaign infrastructure in `project-administration` distributes caller workflow updates when transitioning between phases.

### Reusable workflow checkout consistency

The reusable workflow derives tooling checkout repository and ref from OIDC claims:
`job_workflow_ref` (repository identity) and `job_workflow_sha` (commit identity).
This guarantees that Python scripts and shared actions are checked out from the same repository
and commit as the reusable workflow itself, even when callers reference floating tags such as
`ra-v1-rc` or `v1`.

An optional `tooling_ref_override` input can be set in the caller workflow for break-glass
or testing scenarios. The override must be a full 40-character SHA.

## Coexistence with pr_validation v0

Release automation and the validation framework coexist with pr_validation v0 without changes to the existing validation workflow. No modifications to pr_validation are required for either stream to function. After the release-automation merge, `main` contains both pr_validation v0 and the release automation; after the validation-framework merge, `main` contains all three.
