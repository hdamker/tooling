# Repository Setup for Release Automation

**Last Updated**: 2026-02-13

## Overview

API repositories that adopt the CAMARA release automation need specific repository-level configuration. The workflow manages its own labels and concurrency, but cannot self-configure branch protection, CODEOWNERS entries, or install the caller workflow.

This document defines the required configuration for each API repository. It serves as:
- **Setup guide** for repository administrators onboarding new or existing repos
- **Verification reference** for test repo setup (WS9 testing phase)
- **Input specification** for the onboarding campaign and admin tooling

### What the workflow manages internally

| Item | Mechanism |
|------|-----------|
| 6 labels | Auto-created on first use (`release-issue` + 5 state labels) |
| Concurrency | `concurrency:` block in reusable workflow (one run per repo) |
| Permissions | `permissions:` block in caller workflow |

### What needs external configuration

| Item | Purpose | Section |
|------|---------|---------|
| 3 repository rulesets | Branch protection for automation-managed branches | [Rulesets](#repository-rulesets) |
| CODEOWNERS entry | RM reviewer assignment for Release PRs | [CODEOWNERS](#codeowners-requirements) |
| Caller workflow file | Entry point that connects the repo to the automation | [Caller Workflow](#caller-workflow) |
| `release-plan.yaml` | Release configuration (target tag, type, APIs) | [Required Files](#required-files) |
| README delimiters | Release Information section markers | [Required Files](#required-files) |
| CHANGELOG structure | Directory layout for per-cycle changelog files | [CHANGELOG Structure](#changelog-structure) |

---

## Repository Rulesets

Three rulesets protect the branches that the release automation creates and manages. All three use **GitHub Actions** as a bypass actor to allow the workflow's `GITHUB_TOKEN` to operate while blocking direct human modifications.

### 1. Snapshot Branch Protection

Prevents human modification of snapshot branches. The workflow pushes mechanically generated content (transformed API files, release-metadata.yaml) to these branches — any human modification would compromise release integrity.

| Property | Value |
|----------|-------|
| **Name** | `release-snapshot-protection` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `release-snapshot/**` |
| **Bypass actors** | GitHub Actions (always) |

**Rules:**
- Restrict pushes — only bypass actors may push
- Restrict deletions — only bypass actors may delete
- Block force pushes

<details>
<summary>GitHub API payload for programmatic application</summary>

```json
{
  "name": "release-snapshot-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/release-snapshot/**"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "non_fast_forward" },
    { "type": "deletion" },
    {
      "type": "push",
      "parameters": {
        "restrict_pushes": true
      }
    }
  ],
  "bypass_actors": [
    {
      "actor_id": 2,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
```

Note: `actor_id: 2` refers to the GitHub Actions app. Verify the correct ID for your organization via `GET /orgs/{org}/rulesets` on an existing ruleset that uses GitHub Actions bypass.

</details>

### 2. Release-Review Branch Protection

Prevents deletion of release-review branches while allowing codeowners to push review fixes. The release-review branch is the PR head where codeowners may address review comments directly.

| Property | Value |
|----------|-------|
| **Name** | `release-review-protection` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `release-review/**` |
| **Bypass actors** | GitHub Actions (always) |

**Rules:**
- Restrict deletions — only bypass actors may delete (workflow cleans up after publication)
- Block force pushes

Note: No push restriction — codeowners may push directly to fix review comments on the Release PR.

<details>
<summary>GitHub API payload</summary>

```json
{
  "name": "release-review-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/release-review/**"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "non_fast_forward" },
    { "type": "deletion" }
  ],
  "bypass_actors": [
    {
      "actor_id": 2,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
```

</details>

### 3. Release PR Approval Requirements

Enforces review gates on pull requests that target snapshot branches. The Release PR (head: `release-review/*`, base: `release-snapshot/*`) is the human approval gate before draft release creation.

| Property | Value |
|----------|-------|
| **Name** | `release-snapshot-pr-rules` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `release-snapshot/**` |

**Rules:**
- Require pull request before merging
- Required approvals: 1 (minimum)
- Require review from Code Owners
- Dismiss stale reviews on new pushes

The dual review gate is enforced through CODEOWNERS file patterns:
- The `*` pattern assigns all codeowners as reviewers
- The `/CHANGELOG/` pattern assigns `@camaraproject/release-management_reviewers`

Both groups must approve before the PR can be merged.

<details>
<summary>GitHub API payload</summary>

```json
{
  "name": "release-snapshot-pr-rules",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/release-snapshot/**"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    }
  ]
}
```

</details>

### Applying rulesets programmatically

The GitHub Rulesets API is **not idempotent** — calling `POST` twice creates duplicate rulesets. Use the following pattern for safe re-application:

```bash
# 1. List existing rulesets
existing=$(gh api repos/{owner}/{repo}/rulesets --jq '.[].name')

# 2. For each target ruleset, check if it exists
if echo "$existing" | grep -q "release-snapshot-protection"; then
  # Update existing (get ID first)
  id=$(gh api repos/{owner}/{repo}/rulesets --jq '.[] | select(.name == "release-snapshot-protection") | .id')
  gh api -X PUT repos/{owner}/{repo}/rulesets/$id --input payload.json
else
  # Create new
  gh api -X POST repos/{owner}/{repo}/rulesets --input payload.json
fi
```

---

## CODEOWNERS Requirements

### Standard CAMARA format

The release automation expects the standard CODEOWNERS format used across CAMARA repositories:

```
# Default owners for the whole repository
* @codeowner1 @codeowner2 @codeowner3

# Admin-managed files
/CODEOWNERS @camaraproject/admins
/MAINTAINERS.MD @camaraproject/admins

# Release Management reviewers for changelog files
/CHANGELOG.md @camaraproject/release-management_reviewers
/CHANGELOG.MD @camaraproject/release-management_reviewers
```

### Required addition for release automation

Add the following line to enable RM reviewer assignment for the new per-cycle changelog directory:

```
/CHANGELOG/ @camaraproject/release-management_reviewers
```

The release automation creates per-cycle changelog files at `CHANGELOG/CHANGELOG-rX.md` (e.g., `CHANGELOG/CHANGELOG-r4.md` for release cycle 4). Without this CODEOWNERS entry, Release Management reviewers would not be auto-assigned to Release PRs that modify these files.

### How CODEOWNERS is used by the automation

The `/publish-release` command checks CODEOWNERS to authorize the publishing user:

1. Reads the `CODEOWNERS` file from the `main` branch
2. Finds the first line matching the `*` pattern and extracts all `@username` mentions
3. Compares the command user against the extracted list

**Authorization tiers:**
- `admin` / `maintain` permission: bypass CODEOWNERS check (break-glass)
- `write` permission: must be listed in CODEOWNERS `*` line
- `read` / no permission: rejected

**Notes:**
- GitHub's CODEOWNERS uses "last matching pattern wins" for reviewer assignment. The automation's publish authorization currently takes the first `*` line. In standard CAMARA repositories there is only one `*` line, so this is equivalent. Repositories should not have multiple `*` lines.
- Team references (e.g., `@camaraproject/team`) on the `*` line are extracted but do not match individual usernames — use individual `@username` entries on the `*` line
- If the CODEOWNERS file does not exist (404), the check is skipped and only repository permission is verified
- Pattern-specific rules (e.g., `/CHANGELOG/`) do not affect `/publish-release` authorization — they only affect PR review assignment

---

## Caller Workflow

The caller workflow is the entry point that connects an API repository to the release automation. It is a static YAML file installed at `.github/workflows/release-automation.yml`.

### Source template

The canonical caller workflow template is maintained in the tooling repository:

```
camaraproject/tooling (release-automation branch)
  └── release_automation/workflows/release-automation-caller.yml
```

The onboarding campaign reads this file and copies it to each target repository. Do not maintain separate copies — the template in `tooling` is the single source of truth.

### Reference lifecycle

The caller's `uses:` line references the reusable workflow in `camaraproject/tooling`. The reference changes as the automation progresses through rollout phases:

| Phase | `uses:` ref | Who uses it |
|-------|-------------|-------------|
| Alpha | `@release-automation` | Test repositories |
| RC | `@ra-v1-rc` | Test + volunteering repos |
| GA | `@v1` | All API repositories |

See [branching-model.md](branching-model.md) for the full lifecycle and tag strategy.

When transitioning between phases, a campaign updates the `uses:` line across all participating repositories.

### Key configuration in the caller

| Aspect | Value | Purpose |
|--------|-------|---------|
| **Permissions** | `contents: write`, `issues: write`, `pull-requests: write` | Branch/release ops, issue management, PR creation |
| **Concurrency** | `release-automation-${{ github.repository }}`, `cancel-in-progress: false` | Serialize runs, prevent race conditions |
| **Triggers** | `issue_comment`, `issues`, `pull_request`, `push`, `workflow_dispatch` | Slash commands, lifecycle events, auto-sync, manual |

---

## Required Files

### release-plan.yaml

Must exist on the `main` branch with valid content. This file drives the release automation — it defines what release to prepare and which APIs to include.

Minimum required fields:

```yaml
repository:
  target_release_tag: r1.1
  target_release_type: pre-release-rc  # or: pre-release-alpha, public-release, none
  release_track: meta-release           # independent or meta-release
  meta_release: Sync26

apis:
  - api_name: quality-on-demand
    api_version: 0.11.0

dependencies:
  commonalities: "0.5"                 # Commonalities version
  identity-and-consent-management: "0.3"  # ICM version (if applicable)
```

Valid `target_release_type` values: `pre-release-alpha`, `pre-release-rc`, `public-release`, `maintenance-release`, `none`

Setting `target_release_type: none` signals no active release — the automation sets the Release Issue state to `not-planned`.

The `release-plan.yaml` file is distributed by the `campaign-release-plan-rollout` campaign in `project-administration`. See the [release-plan schema](../../validation/schemas/release-plan-schema.yaml) for the complete specification.

### README.md delimiters

The README must contain release information section delimiters:

```markdown
<!-- CAMARA:RELEASE-INFO:START -->
## Release Information
...
<!-- CAMARA:RELEASE-INFO:END -->
```

These delimiters are used by the release automation to update the Release Information section during snapshot creation and post-release sync. If missing, the README update step will fail.

The delimiters are distributed by the `campaign-release-info` campaign in `project-administration`.

---

## CHANGELOG Structure

The release automation uses a per-cycle directory structure for changelog files:

```
CHANGELOG/
  CHANGELOG-r1.md   # All releases in cycle 1 (r1.1, r1.2, ...)
  CHANGELOG-r2.md   # All releases in cycle 2 (r2.1, r2.2, ...)
  README.md          # Index pointing to available files and legacy CHANGELOG.md
```

Each `/create-snapshot` command generates a release section in the appropriate per-cycle file. Multiple releases within the same cycle (e.g., r4.1 alpha, r4.1 RC, r4.2) accumulate in the same file with newest entries at the top.

### Migration from root CHANGELOG.md

Existing CAMARA repositories have a `CHANGELOG.md` at the repository root containing historical release notes. The migration to the new directory structure happens in two phases:

**Phase 1 — Onboarding (non-breaking)**

The onboarding campaign adds preparatory files without modifying existing content:

1. Add a forward-reference note at the top of the existing root `CHANGELOG.md`:
   ```markdown
   > Starting with release automation, new release changelogs are maintained
   > in the [CHANGELOG/](CHANGELOG/) directory with per-cycle files.
   ```

2. Create `CHANGELOG/README.md` as an index:
   ```markdown
   # Changelog

   Release changelogs are organized by release cycle.

   For historical release notes predating the automated release process,
   see [CHANGELOG.md](../CHANGELOG.md) in the repository root.
   ```

**Phase 2 — Content migration (separate, later)**

A follow-up campaign moves the legacy content from root `CHANGELOG.md` into the `CHANGELOG/` directory. The root file is reduced to a pointer. Details of the content migration (single archive file vs. split into per-cycle files) are decided at that time.

**Link safety**: Tag-specific links (e.g., `github.com/.../blob/r1.2/CHANGELOG.md`) are unaffected — tags are immutable snapshots of the repository at that point in time. The root placeholder preserves links to `CHANGELOG.md` on the default branch.

---

## Recommended Enhancements

### Configuration drift protection

When a release snapshot is active, changes to `release-plan.yaml` on `main` can cause the snapshot to diverge from the current configuration. The release automation includes a post-merge warning (config drift warning posted to the Release Issue), but does not block the PR.

For stronger protection, the `pr_validation` workflow can be extended to block PRs that modify `release-plan.yaml` when a `release-snapshot/*` branch exists. This is tracked as [camaraproject/tooling#63](https://github.com/camaraproject/tooling/issues/63) and can be implemented independently on the `main` branch (pr_validation v0).

---

## Verification Checklist

Use this checklist to verify that a repository is correctly configured for release automation. This is the acceptance checklist for test repo setup.

### Rulesets

- [ ] Ruleset `release-snapshot-protection` exists and is **active**
  - Target: `release-snapshot/**`
  - Rules: restrict pushes, restrict deletions, block force pushes
  - Bypass: GitHub Actions
- [ ] Ruleset `release-review-protection` exists and is **active**
  - Target: `release-review/**`
  - Rules: restrict deletions, block force pushes
  - Bypass: GitHub Actions
- [ ] Ruleset `release-snapshot-pr-rules` exists and is **active**
  - Target: `release-snapshot/**`
  - Rules: require PR, 1 approval, code owner review, dismiss stale reviews

### CODEOWNERS

- [ ] `CODEOWNERS` file exists in repository root
- [ ] First `*` line lists at least one individual codeowner (`@username`)
- [ ] `/CHANGELOG/` line present with `@camaraproject/release-management_reviewers`
- [ ] `/CHANGELOG.md` and `/CHANGELOG.MD` lines present (existing CAMARA standard)

### Caller Workflow

- [ ] `.github/workflows/release-automation.yml` exists
- [ ] `uses:` line references correct org/repo/ref for current phase
- [ ] `permissions:` includes `contents: write`, `issues: write`, `pull-requests: write`
- [ ] `concurrency:` group is `release-automation-${{ github.repository }}`

### Required Files

- [ ] `release-plan.yaml` exists on `main` with valid `target_release_tag` and `target_release_type`
- [ ] `README.md` contains `<!-- CAMARA:RELEASE-INFO:START -->` and `<!-- CAMARA:RELEASE-INFO:END -->` delimiters

### CHANGELOG Structure

- [ ] Root `CHANGELOG.md` has forward-reference note pointing to `CHANGELOG/` directory
- [ ] `CHANGELOG/README.md` exists as index file

### Smoke Test

- [ ] Run `workflow_dispatch` manually — verify Release Issue is created with correct state
- [ ] Verify 6 labels were auto-created: `release-issue`, `release-state:planned`, `release-state:snapshot-active`, `release-state:draft-ready`, `release-state:published`, `release-state:not-planned`
- [ ] Verify Release Issue body has correct configuration summary and valid actions
