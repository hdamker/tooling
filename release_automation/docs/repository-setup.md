# Repository Setup for Release Automation

**Last Updated**: 2026-02-18

## Overview

API repositories that adopt the CAMARA release automation need specific repository-level configuration. The workflow manages its own labels and concurrency, but cannot self-configure branch protection, CODEOWNERS entries, or install the caller workflow.

This document defines the required configuration for each API repository. It serves as the **specification** that the automated onboarding tooling implements — repository administrators do not need to apply or verify this configuration manually.

**Automated application**: The [release automation onboarding campaign](https://github.com/camaraproject/project-administration/pull/134) in `project-administration` applies the full configuration to API repositories. It includes a campaign workflow (caller workflow, CHANGELOG structure, CODEOWNERS adjustments) and an admin script (repository ruleset). Both support dry-run/plan modes and phased rollout — test repositories first, then volunteering repos, then all.

**New repositories**: After rollout, the configuration will also be applied to `Template_API_Repository` ([camaraproject/tooling#82](https://github.com/camaraproject/tooling/issues/82)), so that newly created API repositories inherit it automatically.

### What the workflow manages internally

| Item | Mechanism |
|------|-----------|
| 6 labels | Auto-created on first use (`release-issue` + 5 state labels) |
| Concurrency | `concurrency:` block in reusable workflow (one run per repo) |
| Permissions | `permissions:` block in caller workflow |

### What needs external configuration

| Item | Purpose | Section |
|------|---------|---------|
| Repository ruleset | Branch protection for snapshot branches | [Ruleset](#repository-ruleset) |
| CODEOWNERS file | Codeowner assignment for `/publish-release` authorization | [CODEOWNERS](#codeowners-requirements) |
| Caller workflow file | Entry point that connects the repo to the automation | [Caller Workflow](#caller-workflow) |
| `release-plan.yaml` | Release configuration (target tag, type, APIs) | [Required Files](#required-files) |
| README delimiters | Release Information section markers | [Required Files](#required-files) |
| CHANGELOG structure | Directory layout for per-cycle changelog files | [CHANGELOG Structure](#changelog-structure) |

---

## Repository Rulesets

Three rulesets protect branches managed by the release automation:

1. **Snapshot branch protection** — protects `release-snapshot/**` branches with branch protection rules and PR review requirements
2. **Release pointer branch protection** — protects `release/**` pointer branches (fully immutable)
3. **Pre-release pointer branch protection** — protects `pre-release/**` pointer branches (immutable but deletable by codeowners)

The `camara-release-automation` GitHub App is the bypass actor for all rulesets, allowing the workflow to create and manage these branches while humans are governed by protection rules.

No ruleset is needed for `release-review/**` branches — codeowners push review fixes directly to these branches, and the workflow handles creation and cleanup.

### Snapshot Branch Protection

| Property | Value |
|----------|-------|
| **Name** | `release-snapshot-protection` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `release-snapshot/**` |
| **Bypass actors** | `camara-release-automation` GitHub App (always) |

**Branch protection rules:**
- Restrict creations — only bypass actors may create snapshot branches
- Restrict deletions — only bypass actors may delete
- Block force pushes

**PR review rules:**
- Require a pull request before merging
- Required approvals: 2 (ensures two distinct people must approve, even if a person is in both codeowner and RM reviewer teams)
- Require review from Code Owners
- Dismiss stale reviews on new pushes
- Required reviewers: `release-management_reviewers` team (1 approval, all files)

The dual review gate ensures both API codeowners and Release Management reviewers must approve before a Release PR can be merged:
- The `*` CODEOWNERS pattern assigns API codeowners as reviewers
- The ruleset's `required_reviewers` field auto-requests the `release-management_reviewers` team

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
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "creation" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 2,
        "dismiss_stale_reviews_on_push": true,
        "required_reviewers": [
          {
            "minimum_approvals": 1,
            "file_patterns": ["*"],
            "reviewer": {
              "id": 13109132,
              "type": "Team"
            }
          }
        ],
        "require_code_owner_review": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "bypass_actors": [
    {
      "actor_id": 2865881,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
```

Notes:
- `actor_id: 2865881` is the `camara-release-automation` GitHub App ID
- `reviewer.id: 13109132` is the `release-management_reviewers` team ID
- The `required_reviewers` field is a beta feature in the GitHub Rulesets API
- The canonical ruleset is maintained in `Template_API_Repository` — the JSON above matches it

</details>

### Release Pointer Branch Protection

After publication, the automation creates a pointer branch at the release tag commit (`release/rX.Y` for public releases, `pre-release/rX.Y` for pre-releases). This prevents GitHub's "commit does not belong to any branch" warning when browsing the tag tree view.

Two rulesets enforce immutability (no commits, no force pushes). They differ only in deletion policy:

**`release-pointer-protection`** — public release pointers are fully protected:

| Property | Value |
|----------|-------|
| **Name** | `release-pointer-protection` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `release/**` |
| **Bypass actors** | `camara-release-automation` GitHub App (always), Organization admins (always) |

Rules: restrict creations, restrict deletions, restrict updates, block force pushes. No PR review rules.

**`pre-release-pointer-protection`** — pre-release pointers are immutable but deletable:

| Property | Value |
|----------|-------|
| **Name** | `pre-release-pointer-protection` |
| **Enforcement** | Active |
| **Target** | Include branches matching: `pre-release/**` |
| **Bypass actors** | `camara-release-automation` GitHub App (always), Organization admins (always) |

Rules: restrict creations, restrict updates, block force pushes. **No deletion rule** — codeowners can delete older pre-release pointers to manage the branch list as pre-releases accumulate during a release cycle.

<details>
<summary>GitHub API payloads</summary>

```json
{
  "name": "release-pointer-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/release/**"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "creation" },
    { "type": "deletion" },
    { "type": "update" },
    { "type": "non_fast_forward" }
  ],
  "bypass_actors": [
    {
      "actor_id": null,
      "actor_type": "OrganizationAdmin",
      "bypass_mode": "always"
    },
    {
      "actor_id": 2865881,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
```

```json
{
  "name": "pre-release-pointer-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/pre-release/**"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "creation" },
    { "type": "update" },
    { "type": "non_fast_forward" }
  ],
  "bypass_actors": [
    {
      "actor_id": null,
      "actor_type": "OrganizationAdmin",
      "bypass_mode": "always"
    },
    {
      "actor_id": 2865881,
      "actor_type": "Integration",
      "bypass_mode": "always"
    }
  ]
}
```

Notes:
- `actor_id: 2865881` is the `camara-release-automation` GitHub App ID
- The `update` rule prevents any commits to pointer branches — they must stay at the tag commit

</details>

### Applying rulesets programmatically

The GitHub Rulesets API is **not idempotent** — calling `POST` twice creates duplicate rulesets. The admin script in `project-administration` uses a check-then-create/update pattern:

```bash
# List existing rulesets
existing=$(gh api repos/{owner}/{repo}/rulesets --jq '.[].name')

# Check if it exists, then create or update
if echo "$existing" | grep -q "release-snapshot-protection"; then
  id=$(gh api repos/{owner}/{repo}/rulesets --jq '.[] | select(.name == "release-snapshot-protection") | .id')
  gh api -X PUT repos/{owner}/{repo}/rulesets/$id --input payload.json
else
  gh api -X POST repos/{owner}/{repo}/rulesets --input payload.json
fi
```

See `project-administration/scripts/apply-release-rulesets.sh` for the full script.

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
```

### CODEOWNERS and RM reviewer assignment

CAMARA repositories have `/CHANGELOG.md` and `/CHANGELOG.MD` lines in CODEOWNERS that assign `@camaraproject/release-management_reviewers` as reviewers for the legacy root changelog file. These lines are **kept** during onboarding:

- They prevent codeowners from making unreviewed changes to the legacy `CHANGELOG.md` during Phase 1 (migration period), encouraging use of the new `CHANGELOG/` directory structure instead
- RM reviewer assignment for Release PRs on snapshot branches is additionally enforced via the ruleset's `required_reviewers` field, which auto-requests the team and blocks merge until they approve
- The `*` CODEOWNERS pattern ensures API codeowners review all files

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

### Onboarding: CHANGELOG.md handling

The onboarding campaign detects the state of the root `CHANGELOG.md` and applies the appropriate action:

| Root CHANGELOG.md state | Action | CHANGELOG/README.md |
|--------------------------|--------|---------------------|
| **Unchanged template** (≤1 line) | Delete the placeholder | Fresh index (no historical reference) |
| **Real content** (>1 line) | Add forward-reference note | Index with link to root CHANGELOG.md |
| **Not present** | No action | Fresh index (no historical reference) |

**Repos with unchanged template CHANGELOG.md** (e.g., ConsentManagement, eSimRemoteManagement):

These repos were created from `Template_API_Repository` and never added real changelog entries. The single-line placeholder is deleted and `CHANGELOG/README.md` is created without a historical reference:

```markdown
# Changelog

Release changelogs are organized by release cycle.
```

**Repos with real changelog content** (most existing repos):

The existing root `CHANGELOG.md` is preserved with a forward-reference note prepended:

```markdown
> Starting with release automation, new release changelogs are maintained
> in the [CHANGELOG/](CHANGELOG/) directory with per-cycle files.
```

`CHANGELOG/README.md` includes a link back to the historical content:

```markdown
# Changelog

Release changelogs are organized by release cycle.

For historical release notes predating the automated release process,
see [CHANGELOG.md](../CHANGELOG.md) in the repository root.
```

### Phase 2 — Content migration (separate, later)

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
  - Branch protection: restrict creations, deletions, block force pushes
  - PR rules: 2 approvals, code owner review, dismiss stale reviews
  - Required reviewers: `release-management_reviewers` (1 approval)
  - Bypass: `camara-release-automation` GitHub App
- [ ] Ruleset `release-pointer-protection` exists and is **active**
  - Target: `release/**`
  - Rules: restrict creations, deletions, updates, block force pushes
  - Bypass: `camara-release-automation` GitHub App, Organization admins
- [ ] Ruleset `pre-release-pointer-protection` exists and is **active**
  - Target: `pre-release/**`
  - Rules: restrict creations, updates, block force pushes (no deletion rule)
  - Bypass: `camara-release-automation` GitHub App, Organization admins

### CODEOWNERS

- [ ] `CODEOWNERS` file exists in repository root
- [ ] First `*` line lists at least one individual codeowner (`@username`)
- [ ] `/CHANGELOG.md` and/or `/CHANGELOG.MD` lines present with `@camaraproject/release-management_reviewers`

### Caller Workflow

- [ ] `.github/workflows/release-automation.yml` exists
- [ ] `uses:` line references correct org/repo/ref for current phase
- [ ] `permissions:` includes `contents: write`, `issues: write`, `pull-requests: write`
- [ ] `concurrency:` group is `release-automation-${{ github.repository }}`

### Required Files

- [ ] `release-plan.yaml` exists on `main` with valid `target_release_tag` and `target_release_type`
- [ ] `README.md` contains `<!-- CAMARA:RELEASE-INFO:START -->` and `<!-- CAMARA:RELEASE-INFO:END -->` delimiters

### CHANGELOG Structure

- [ ] `CHANGELOG/README.md` exists as index file
- [ ] Root `CHANGELOG.md` either: has forward-reference note (repos with history), or is deleted (repos with unchanged template placeholder)

### Smoke Test

- [ ] Run `workflow_dispatch` manually — verify Release Issue is created with correct state
- [ ] Verify 6 labels were auto-created: `release-issue`, `release-state:planned`, `release-state:snapshot-active`, `release-state:draft-ready`, `release-state:published`, `release-state:not-planned`
- [ ] Verify Release Issue body has correct configuration summary and valid actions
