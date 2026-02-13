# Upstream Branching and Versioning Model

**Last Updated**: 2026-02-13

## Overview

The `camaraproject/tooling` repository uses parallel long-lived branches for independent feature streams. Each stream has its own development lifecycle and tag namespace. Streams merge to `main` together as a coordinated release, with the `v1` tag assigned only after the merged configuration is proven stable.

## Branch Layout

```
main ──────────────────────── pr_validation v0 (production)
  │
  ├── release-automation ──── release creation workflow
  │
  └── <v1-ci-workflow> ─────── CI/build/validation v1 (future, name TBD)
```

| Branch | Purpose | Tag namespace |
|--------|---------|---------------|
| `main` | pr_validation v0 improvements | `v0`, `v0.x.y` |
| `release-automation` | Release creation workflow | `ra-v1-rc` |
| *v1 CI branch (TBD)* | Validation + build workflow superseding pr_validation | TBD |

### Why parallel branches

- `main` serves production consumers referencing `@v0` — it must remain stable for pr_validation
- Release automation and the v1 CI workflow have design dependencies but can be developed and tested independently
- Merging to `main` only when both streams are ready prevents partial integration issues

## Lifecycle Phases

### Alpha (internal validation)

| Aspect | Detail |
|--------|--------|
| **Branch** | `release-automation` |
| **Caller ref** | `@release-automation` (branch HEAD) |
| **Test scope** | Test repositories (ReleaseTest + hdamker test repos) |
| **Tag** | None — branch HEAD is the reference |

The alpha phase validates the release automation on dedicated test repositories. Fixes land directly on the branch. No tag is needed because only test repositories reference this branch.

### RC (early adopters)

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

### GA Transition

GA is a two-step process: merge first, then assign the `v1` tag after the merged configuration is proven stable.

**Step 1: Merge to main**

Both `release-automation` and the v1 CI workflow merge to `main` when they reach RC stability. After merging:

- The RC tags (`ra-v1-rc` and the v1 CI equivalent) move to commits on `main`
- Consumers continue referencing their RC tags — no change required
- Test repositories and volunteering repos validate the merged configuration on `main`

**Step 2: Assign v1 tag**

Once the merged configuration is proven stable on `main`:

- `v1` tag created on `main` (+ semver `v1.0.0`)
- Campaign updates all API repo callers to `@v1`
- `v0` tag remains on its last commit for repos not yet migrated

| Aspect | After merge (step 1) | After v1 tag (step 2) |
|--------|---------------------|----------------------|
| **Branch** | `main` | `main` |
| **Caller ref** | `@ra-v1-rc` (now on main) | `@v1` |
| **Test scope** | Test repos + volunteering repos | All API repositories |
| **Tag** | RC tags moved to main | `v1`, `v1.0.0` |

## Tag Strategy

| Tag | Type | Scope | Moves? |
|-----|------|-------|--------|
| `v0` | Floating major | pr_validation on main | Yes — tracks latest v0.x.y |
| `v0.x.y` | Semver | pr_validation on main | No — immutable |
| `ra-v1-rc` | Floating RC | release-automation branch, then main | Yes — moved after test repo validates |
| `v1` | Floating major | main (after GA proven) | Yes — tracks latest v1.x.y |
| `v1.x.y` | Semver | main (after GA) | No — immutable |

## Caller Workflow References

The caller workflow in each API repository references the reusable workflow:

```yaml
uses: camaraproject/tooling/.github/workflows/release-automation-reusable.yml@<ref>
```

| Phase | `<ref>` value | Who uses it |
|-------|---------------|-------------|
| Alpha | `release-automation` | Test repositories only |
| RC | `ra-v1-rc` | Test repositories + volunteering repos |
| Post-merge | `ra-v1-rc` (on main) | Test repos + volunteering repos |
| GA | `v1` | All API repos |

The campaign infrastructure in `project-administration` distributes caller workflow updates when transitioning between phases.

## Coexistence with pr_validation v0

The release automation is designed to work alongside pr_validation v0 without changes to the existing validation workflow. The `release-automation` branch includes the current pr_validation v0 code (branched from `main`) plus the release automation additions. No modifications to pr_validation are required for the release automation to function.

## v1 CI Workflow (future)

A separate branch (name TBD) will develop a new CI/build/validation workflow that supersedes pr_validation v0:
- CI aligned with the release concept (working on main and snapshot branches)
- Extended validation rules and enforcement of allowed changes per branch type
- Build components (e.g., bundled API definitions)
- Replacement of MegaLinter

This workflow supersedes pr_validation v0 rather than replacing it — the v0 workflow remains available on `main` with the `v0` tag for repositories that have not yet migrated.

The v1 CI branch is developed independently. Dependencies on release automation data structures (e.g., release-metadata.yaml schema, branch naming conventions) are considered at design time but the two streams are not merged during development.
