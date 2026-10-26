# Release Creation Workflow — Technical Architecture

**Last Updated**: 2026-10-24

## Executive Summary

This document defines the technical architecture for the CAMARA release creation workflow automation. The architecture follows existing patterns established in the `tooling` repository (caller/reusable workflows, composite actions, Python scripts) while introducing new components for release orchestration.

### Design Principles

1. **Centralized logic, distributed triggers**: Core functionality in `tooling` repository; API repos have minimal caller workflows
2. **Fast feedback**: Early acknowledgment posted immediately (~5s), replaced with interim status for validated commands, then final results
3. **State from artifacts**: Derive state from repository artifacts (branches, tags, releases), not stored in issues
4. **Extensible transformations**: Placeholder replacement patterns configurable and extensible
5. **Clear separation**: Mechanical changes (automation-owned) vs documentation (human-reviewable)

---

## 1. Repository Structure

### Additions to `camaraproject/tooling`

```
tooling/
├── .github/workflows/
│   └── release-automation-reusable.yml   # Core reusable workflow
│
├── release_automation/                    # Top-level module
│   ├── workflows/
│   │   └── release-automation-caller.yml # Caller template for API repos
│   │
│   ├── scripts/
│   │   ├── __init__.py
│   │   ├── act.py                    # Act job: dispatches the plan's action, writes the JSON outcome
│   │   ├── bot_context.py            # BotContext dataclass
│   │   ├── bot_identity.py           # Commit identity (App bot or github-actions[bot])
│   │   ├── bot_responder.py          # Message formatting + template rendering
│   │   ├── changelog_generator.py    # CHANGELOG draft generation
│   │   ├── command_policy.py         # Plan job: Trigger x State -> Plan or Rejection, the response
│   │   ├── commands.py               # Slash commands, dispatch actions, valid actions per state
│   │   ├── common_sync.py            # Common cache detection and common sync
│   │   ├── config.py                 # Shared constants and configuration
│   │   ├── context_builder.py        # build_context() for unified context
│   │   ├── draft_release.py          # Draft release create/delete, snapshot discard
│   │   ├── finalize.py               # Finalize job: sync PR, common sync, Release Issue, result
│   │   ├── git_operations.py         # Git operations for snapshot/review branches
│   │   ├── github_client.py          # GitHub API wrapper
│   │   ├── issue_events.py           # Release Issue auto-reopen
│   │   ├── issue_manager.py          # Issue description/title updates
│   │   ├── issue_sync.py             # Release Issue lifecycle management
│   │   ├── labels.py                 # Labels applied by release automation
│   │   ├── mechanical_transformer.py # Placeholder replacement
│   │   ├── metadata_generator.py     # release-metadata.yaml generation
│   │   ├── readme_updater.py         # README Release Information updater
│   │   ├── regression_runner.py      # RA regression canary runner
│   │   ├── release_publisher.py      # Draft release publication
│   │   ├── snapshot_creator.py       # Snapshot + release-review branch creation
│   │   ├── snapshot_prep.py          # Snapshot job glue: settings check, validation gate, bot identity
│   │   ├── state_manager.py          # State derivation logic
│   │   ├── sync_pr.py                # Post-release sync PR
│   │   ├── template_loader.py        # Shared template loading utilities
│   │   ├── trigger.py                # Plan job: payload -> Trigger
│   │   ├── version_calculator.py     # API version extension calculation
│   │   ├── wip_checker.py            # wip version check before a snapshot
│   │   └── workflow_context.py       # Workflow context assembly helpers
│   │
│   ├── templates/
│   │   ├── bot_messages/
│   │   │   ├── command_rejected.md
│   │   │   ├── common_sync_failed.md
│   │   │   ├── common_sync_pr_created.md
│   │   │   ├── config_error.md
│   │   │   ├── draft_created.md
│   │   │   ├── draft_revoked.md
│   │   │   ├── interim_processing.md
│   │   │   ├── internal_error.md
│   │   │   ├── issue_created.md
│   │   │   ├── issue_reopened.md
│   │   │   ├── issue_synced.md
│   │   │   ├── publish_confirmation.md
│   │   │   ├── publish_failed.md
│   │   │   ├── release_published.md
│   │   │   ├── snapshot_created.md
│   │   │   ├── snapshot_discarded.md
│   │   │   ├── snapshot_failed.md
│   │   │   └── state_not_planned.md
│   │   │
│   │   ├── pr_bodies/
│   │   │   ├── release_review_pr.mustache
│   │   │   └── sync_pr.mustache
│   │   │
│   │   ├── readme/
│   │   │   ├── release-info-no-release.mustache
│   │   │   ├── release-info-prerelease-only.mustache
│   │   │   ├── release-info-public.mustache
│   │   │   └── release-info-public-with-prerelease.mustache
│   │   │
│   │   └── changelog/
│   │       └── release_section.mustache
│   │
│   ├── config/
│   │   └── transformations.yaml          # Placeholder transformation rules
│   │
│   ├── tests/
│   │   ├── test_state_manager.py
│   │   ├── test_version_calculator.py
│   │   ├── test_mechanical_transformer.py
│   │   └── fixtures/
│   │
│   └── docs/
│       └── technical-architecture.md     # This document
│
├── shared-actions/
│   ├── create-snapshot/                  # Orchestrates snapshot + release-review branch
│   │   └── action.yml
│   │
│   ├── derive-release-state/            # State derivation from artifacts
│   │   └── action.yml
│   │
│   ├── post-bot-comment/                # Create/update bot comments with templates
│   │   └── action.yml
│   │
│   ├── update-issue-section/            # Update reserved sections in issue body
│   │   └── action.yml
│   │
│   └── validate-release-plan/           # Existing plan validation
│       └── action.yml
│
└── validation/schemas/
    └── release-metadata-schema.yaml
```

---

## 2. Component Architecture

### 2.1 State Manager (`state_manager.py`)

Derives release state from repository artifacts. The state is never stored directly — it is computed each time from the current state of branches, tags, and releases.

**State derivation flow:**

```
┌─────────────────────────────────────────────────────────────────┐
│                      State Derivation Flow                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: repo, release_tag (e.g., "r4.1")                        │
│                                                                  │
│  ┌──────────────────┐                                           │
│  │ Check tag exists │──── Yes ───► PUBLISHED                    │
│  │  (rX.Y)          │                                           │
│  └────────┬─────────┘                                           │
│           │ No                                                   │
│           ▼                                                      │
│  ┌──────────────────────────┐                                   │
│  │ Check snapshot branch    │──── No ────┐                      │
│  │ (release-snapshot/rX.Y-*)│            │                      │
│  └────────┬─────────────────┘            │                      │
│           │ Yes                          ▼                      │
│           ▼                    ┌─────────────────────────┐      │
│  ┌──────────────────┐         │ Check release-plan.yaml │      │
│  │ Check draft      │         │ target_release_tag      │      │
│  │ release exists   │         │ target_release_type     │      │
│  └────────┬─────────┘         └────────┬────────────────┘      │
│           │                            │                        │
│           ├── Yes → DRAFT_READY        ├── type ≠ "none" and   │
│           │                            │   tag matches         │
│           └── No → SNAPSHOT_ACTIVE     │   → PLANNED           │
│                                        │                        │
│                                        └── else → NOT_PLANNED   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Release states:**

```python
class ReleaseState(Enum):
    PLANNED = "planned"
    SNAPSHOT_ACTIVE = "snapshot-active"
    DRAFT_READY = "draft-ready"
    PUBLISHED = "published"
    NOT_PLANNED = "not_planned"
```

**Key classes:**

- `ReleaseStateManager` — Derives state and reads snapshot metadata from artifacts
- `SnapshotInfo` — Data read from `release-metadata.yaml` on the snapshot branch (snapshot ID, branches, APIs with calculated versions, dependencies)
- `ReleaseInfoResult` — Return type from `derive_state()`, includes either state data or a `ConfigurationError`

### 2.2 Version Calculator (`version_calculator.py`)

Calculates API version extensions based on release history. For pre-release APIs, appends an extension number (e.g., `3.2.0-rc.2`) based on how many prior releases exist for the same API version and status.

**Flow:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Version Calculation Flow                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: api_name, target_version, target_status                 │
│         e.g., "location-verification", "3.2.0", "rc"            │
│                                                                  │
│  Step 1: If target_status == "public" → return target_version   │
│          (e.g., "3.2.0")                                        │
│                                                                  │
│  Step 2: Scan all release tags for this repository              │
│          For each tag, read release-metadata.yaml               │
│          Find versions matching: api_name + target_version +    │
│          target_status                                          │
│                                                                  │
│  Step 3: Count existing extensions                              │
│          e.g., found: ["3.2.0-rc.1"] → count = 1                │
│                                                                  │
│  Step 4: Calculate next extension                               │
│          next = count + 1 = 2                                   │
│          result = "3.2.0-rc.2"                                  │
│                                                                  │
│  Output: "3.2.0-rc.2"                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

Note: `target_status` values are API-level statuses (`draft`, `alpha`, `rc`, `public`) as defined in `release-plan.yaml`. These are distinct from repository-level `release_type` values (`pre-release-alpha`, `pre-release-rc`, `public-release`, `maintenance-release`).

**Repo-split continuity (`seeded_from`):** when `release-plan.yaml` declares a top-level `seeded_from` block (see `release-plan-schema.yaml`), `calculate_versions_for_plan` folds each API's declared `last_rc_api_version` / `last_alpha_api_version` into Step 3 above as one virtual entry alongside this repository's own release history, for the matching `target_status` only. This lets a freshly split-off repository with no release history of its own continue a predecessor repository's rc/alpha extension numbering (e.g., predecessor's `1.2.0-rc.3` → `1.2.0-rc.4` here) instead of restarting at `.1`. Once this repository accumulates its own releases, self-history naturally overtakes the seed value.

### 2.3 Metadata Generator (`metadata_generator.py`)

Generates `release-metadata.yaml` for snapshot branches, following the schema defined in `release-metadata-schema.yaml`.

**Output structure** (see schema for full validation rules):

```yaml
repository:
  repository_name: string      # From release-plan.yaml
  release_tag: string          # From release-plan.yaml
  release_type: string         # From release-plan.yaml (pre-release-alpha | pre-release-rc | public-release | maintenance-release)
  release_date: null | string  # null at creation, set at publication
  src_commit_sha: string       # Set at snapshot creation (40-char SHA)
  release_notes: string        # Optional, from release-plan.yaml

dependencies:
  commonalities_release: string
  identity_consent_management_release: string

apis:
  - api_name: string
    api_version: string        # Calculated version with extension
    api_title: string          # From OpenAPI info.title
```

**Field timing:**
- `src_commit_sha`: Set at snapshot creation — the full 40-character SHA of the source commit
- `release_date`: Set to null at snapshot creation, populated at publication

### 2.4 Mechanical Transformer (`mechanical_transformer.py`)

Applies placeholder replacements to release branches. Transformations are defined in `config/transformations.yaml` and include:

- **OpenAPI transformations**: `info.version` (wip → calculated version), server URL (`/vwip` → `/vN`), `x-camara-commonalities` version
- **GitHub link transformations**: Rewrite `blob/main/` and `raw.githubusercontent.com/.../main/` links to point to the release tag
- **CHANGELOG transformations**: Mustache-based section generation

Each transformation specifies a file pattern, match type (yaml_path or regex), and replacement template with context variables.

### 2.5 Issue Manager (`issue_manager.py`)

Manages Release Issue description sections and title updates. The issue body uses reserved sections delimited by HTML comment markers (`<!-- BEGIN:STATE -->`, `<!-- BEGIN:CONFIG -->`, `<!-- BEGIN:ACTIONS -->`). Automation updates only within these markers, preserving user-edited content above the automation boundary.

### 2.6 Bot Responder (`bot_responder.py`)

Renders bot messages from Mustache templates using pystache with strict mode (`missing_tags='strict'`). All template variables must be provided by the caller (see Section 2.9 for the unified context contract).

**Comment identification:** Each bot comment includes `<!-- release-bot:{release_tag} -->` for identification. Comments can be created or updated by `comment_id`.

**Template inventory** (`release_automation/templates/bot_messages/`):

| Template | Purpose |
|----------|---------|
| `interim_processing.md` | Immediate feedback for slash commands being processed |
| `command_rejected.md` | Command not allowed in current state or insufficient permissions |
| `config_error.md` | Invalid `release-plan.yaml` (missing, malformed, or incomplete) |
| `snapshot_created.md` | Snapshot and Release PR created successfully |
| `snapshot_failed.md` | Snapshot creation failed |
| `snapshot_discarded.md` | Snapshot discarded by user |
| `draft_created.md` | Draft release created from merged Release PR |
| `draft_revoked.md` | Draft release deleted by user |
| `issue_created.md` | Release Issue auto-created (posted on first sync) |
| `issue_reopened.md` | Issue auto-reopened because active artifacts exist |
| `issue_synced.md` | Result of `/sync-issue` |
| `state_not_planned.md` | Release set to NOT_PLANNED (`target_release_type: none`) |
| `publish_confirmation.md` | Confirmation prompt before publication |
| `release_published.md` | Release published successfully |
| `publish_failed.md` | Publication failed |
| `internal_error.md` | Unexpected internal error |

The "Valid actions" block of every comment and of the Release Issue body is the `valid_actions` context field, rendered by `commands.actions_for()` from `STATE_ACTIONS` for the state the comment reports (after the command for a result comment). Templates carry at most one situation-specific line above it.

**PR body templates** (`release_automation/templates/pr_bodies/`):
- `release_review_pr.mustache` — Release Review PR body with checklist
- `sync_pr.mustache` — Post-release sync PR body

**Other templates:**
- `readme/*.mustache` — 4 README Release Information templates (ported from campaign workflow)
- `changelog/release_section.mustache` — CHANGELOG draft section template

---

### 2.7 Issue Sync (`issue_sync.py`)

Synchronizes Release Issue lifecycle with current state derived from artifacts.

**Key behaviors:**
- Creates workflow-owned Release Issue when PLANNED state detected and no open workflow-owned issue exists
- Updates issue sections and labels when state changes
- Sets NOT_PLANNED when `target_release_type: none`
- Ignores manually-created issues (no workflow marker)

**Workflow-owned marker:** Issues created by automation include a hidden marker:
```markdown
<!-- release-automation:workflow-owned -->
```

---

### 2.8 Issue Closure Policy

Closure behavior depends on the current release state:

| State | Close Allowed? | System Reaction |
|-------|----------------|-----------------|
| PLANNED | Yes | No semantic effect; issue treated as historical |
| SNAPSHOT_ACTIVE | No | Auto-reopened with `issue_reopened.md` message |
| DRAFT_READY | No | Auto-reopened with `issue_reopened.md` message |
| PUBLISHED | Yes | Normal closure (automatic after success message is posted) |
| NOT_PLANNED | Yes | Humans close manually |

**Key rules:**
- Closing in PLANNED state does **NOT** cancel the release — release intent is derived only from `release-plan.yaml`
- Automation auto-closes after the success message is posted (PUBLISHED state only)
- If issue is closed in PLANNED and state remains PLANNED, automation creates a new issue on next sync trigger
- NOT_PLANNED is derived from `target_release_type: none`, not from issue closure. A closed NOT_PLANNED issue is not reopened — a *new* issue is created if the plan changes back to a valid release type.

---

### 2.9 Bot Message Context Contract

The workflow has multiple points that consume context data for rendering output. A unified context contract ensures all consumers receive all required variables regardless of the current state or trigger path.

#### Consumers

All consumers draw from the same unified context (BotContext schema):

| Consumer | Module | Rendering |
|----------|--------|-----------|
| Bot message templates (16) | bot_responder.py | Mustache (pystache strict mode) |
| Issue description (create/update) | issue_sync.py → issue_manager.py | f-string formatting |
| Issue config/actions sections | issue_sync.py → issue_manager.py | f-string formatting |
| Mechanical transformer | mechanical_transformer.py | Config-driven replacement |
| CHANGELOG generation | changelog_generator.py | Mustache template |
| README update | readme_updater.py | Mustache template + delimiter replacement |

#### BotContext Schema

All context variables are defined in a single `BotContext` dataclass (`bot_context.py`). The `build_context()` function (`context_builder.py`) constructs it from workflow job outputs, fills defaults for any missing data, and returns a dict guaranteed to have all keys.

**Principle:** If the data is produced by the workflow, make it available in the context — even if no current consumer uses it.

**Naming convention:** Field names follow `release-metadata.yaml` as the canonical source. All layers use the same canonical names — e.g., `src_commit_sha` (not `base_commit_sha`), `api_name`/`api_version`.

| Field | Type | Default | Source |
|-------|------|---------|--------|
| **Trigger fields** | | | |
| `command` | str | `""` | trigger |
| `command_args` | str | `""` | trigger |
| `user` | str | `""` | trigger |
| **State fields** | | | |
| `release_tag` | str | `""` | derive-state |
| `state` | str | `""` | derive-state |
| `release_type` | str | `""` | derive-state / release-plan |
| `meta_release` | str | `""` | release-plan |
| **Snapshot fields** | | | |
| `snapshot_id` | str | `""` | derive-state |
| `snapshot_branch` | str | `""` | derive-state |
| `release_review_branch` | str | `""` | derive-state |
| `src_commit_sha` | str | `""` | derive-state |
| `release_pr_number` | str | `""` | create-snapshot output |
| `release_pr_url` | str | `""` | create-snapshot output |
| **API fields** | | | |
| `apis` | list | `[]` | derive-state / create-snapshot |
| — `api_name` | str | | release-plan / release-metadata |
| — `target_api_version` | str | | release-plan |
| — `target_api_status` | str | | release-plan |
| — `api_version` | str | | release-metadata (calculated) |
| — `api_title` | str | | release-metadata (from OpenAPI) |
| **Dependency fields** | | | |
| `commonalities_release` | str | `""` | derive-state / create-snapshot |
| `identity_consent_management_release` | str | `""` | same |
| **Error fields** | | | |
| `error_message` | str | `""` | various |
| `error_type` | str | `""` | derive-state `config_error_type` |
| **Derived boolean flags** | | | |
| `is_missing_file` | bool | `False` | derived: `error_type == "missing_file"` |
| `is_malformed_yaml` | bool | `False` | derived: `error_type == "malformed_yaml"` |
| `is_missing_field` | bool | `False` | derived: `error_type == "missing_field"` |
| `state_snapshot_active` | bool | `False` | derived: `state == "snapshot-active"` |
| `state_draft_ready` | bool | `False` | derived: `state == "draft-ready"` |
| **Display fields** | | | |
| `workflow_run_url` | str | `""` | constructed in workflow |
| `draft_release_url` | str | `""` | `create-draft` outcome |
| `reason` | str | `""` | command_args (discard/delete) |

**APIs list — two data sources:**

The `apis` list combines data from two artifacts with different availability:

| Field | Source artifact | Available in PLANNED | Available in SNAPSHOT_ACTIVE+ |
|-------|----------------|---------------------|------------------------------|
| `api_name` | release-plan / release-metadata | Yes | Yes |
| `target_api_version` | release-plan | Yes | Yes |
| `target_api_status` | release-plan | Yes | Yes |
| `api_version` | release-metadata (calculated) | No | Yes |
| `api_title` | release-metadata (from OpenAPI) | No | Yes |

In PLANNED state, only target fields are populated. In SNAPSHOT_ACTIVE/DRAFT_READY, derive-state merges data from both artifacts.

#### Data Layering: ReleaseMetadata vs SnapshotInfo vs BotContext

| Dataclass | Module | Purpose |
|-----------|--------|---------|
| `ReleaseMetadata` | metadata_generator.py | Defines what's persisted in `release-metadata.yaml` |
| `SnapshotInfo` | state_manager.py | Data read back from artifacts by derive-state |
| `BotContext` | bot_context.py | Consumer-facing aggregation from all sources |

`BotContext` is a consumer-facing aggregation, NOT a replacement for `ReleaseMetadata`. The `build_context()` function fills defaults for everything missing — most fields are empty strings in PLANNED state.

**Data availability by state:**

| State | release-metadata.yaml? | Metadata fields in context? |
|-------|------------------------|-----------------------------|
| PLANNED | No | Only from release-plan.yaml |
| SNAPSHOT_ACTIVE | Yes (snapshot branch) | Full — derive-state extracts all data |
| DRAFT_READY | Yes (snapshot branch) | Full |
| PUBLISHED | Yes (on tag) | Derive-state does not read metadata from published tags |
| NOT_PLANNED | No | No |
| Config error | Unknown | No |

---

### 2.10 Release Documentation Generators

Two Python modules generate release documentation. The README updater runs as part of snapshot
creation, alongside the other mechanical transforms; the CHANGELOG generator runs on the
release-review branch, creating the single commit that differentiates it from the snapshot
branch.

#### 2.10.1 README Updater (`readme_updater.py`)

Updates the "Release Information" section in README.md, replacing content between delimiters (`<!-- CAMARA:RELEASE-INFO:START -->` / `<!-- CAMARA:RELEASE-INFO:END -->`). Runs during
`/create-snapshot`, before the snapshot commit — the block is a mechanical change, not
reviewable content, so it is committed with the snapshot rather than left editable on the
release-review branch.

**Release state determination** (during `/create-snapshot`):

| release_type | Prior public release? | → release_state |
|-------------|----------------------|-----------------|
| pre-release-alpha / pre-release-rc | No | prerelease_only |
| pre-release-alpha / pre-release-rc | Yes | public_with_prerelease |
| public-release / maintenance-release | (any) | public_release |

**Delimiter policy:** Delimiters must already exist in README.md. If missing, the update fails with an error (the campaign workflow's `ensure-delimited-section` action handles initial marker insertion).

**Templates:** 4 Mustache templates in `release_automation/templates/readme/`, ported from the campaign workflow.

#### 2.10.2 CHANGELOG Generator (`changelog_generator.py`)

Generates structured CHANGELOG draft sections for maintainers to complete during release review.

**File structure:**
```
CHANGELOG/
├── CHANGELOG-r4.md    # Sections for r4.1, r4.2 (newest first)
├── CHANGELOG-r3.md    # Sections for r3.1, r3.2
└── CHANGELOG-r2.md    # Sections for r2.1, r2.2
```

**Cycle mapping:** Extract first number from release_tag: `r4.1` → cycle `4` → `CHANGELOG/CHANGELOG-r4.md`

**Template:** Generates per-release sections with release header (all APIs and dependencies), per-API sections with ReDoc/Swagger/YAML links, empty Breaking changes/Added/Changed/Fixed/Removed subsections, and a collapsible candidate changes section listing merged PRs (from GitHub compare API).

---

### 2.11 Release Publisher (`release_publisher.py`)

Handles publication of draft releases via the `/publish-release` command.

**Publication steps:**
1. Find draft release by tag
2. Finalize `release-metadata.yaml` (set `release_date` to ISO 8601 UTC timestamp)
3. Commit finalization to snapshot branch
4. Update draft to published (creates tag `rX.Y`)
5. Set `make_latest` explicitly — `"true"` only for a release that is not a pre-release and has no later cycle with a public or maintenance release, otherwise `"false"`; a separate API call from the draft→published transition
6. Create reference tag `source/rX.Y` on main at the source commit SHA

**GitHub API note:** `make_latest` is ignored when sent in the same PATCH as `draft=false`. Publication and latest-marking must be separate API calls.

---

### 2.12 Common Cache Sync

Keeps `code/common/` in sync with the Commonalities release declared under `dependencies.commonalities_release` in `release-plan.yaml`. Detection runs in the `plan` job and the common sync in the `finalize` job. For repositories declaring `commonalities_release >= r4.2` it checks the cache and acts on drift; for earlier releases (which don't consume common files via `$ref`) it reports `common_cache_status = ""` (unchecked) and exits without action.

**Location:** [`common_sync.py`](../scripts/common_sync.py), called from two phase jobs of [release-automation-reusable.yml](../../.github/workflows/release-automation-reusable.yml). The `plan` job runs detection (step *Check common cache sync*) and carries the result in the plan; it blocks `/create-snapshot` while the cache is stale. The `finalize` job runs the common sync when the plan reports `stale`, before the Release Issue sync, so the cache converges on every RA invocation that reaches `finalize` (push, `workflow_dispatch`, slash commands ending in a state update). The module takes a git client and a GitHub client and uses no release-automation types, so it can move to a repository reconcile workflow; the release-state gate stays with the calling job.

**Signal model:** Detection yields `common_cache_status` with three values:

| Value | Meaning |
|-------|---------|
| `""` | Unchecked — repo declares commonalities `< r4.2` or has no cache yet |
| `in_sync` | Cache matches the declared tag |
| `stale` | Drift detected (tag mismatch, missing files, or modified files); `common_cache_details` carries the reason |

**Trigger x state matrix:** Sync-PR creation is state-dependent to avoid mixing concerns with an active release:

| Release state | Push to `release-plan.yaml` or `code/common/**` | `/create-snapshot` | `/discard-snapshot` or `/delete-draft` | `workflow_dispatch` |
|---------------|------------------------------------------------|--------------------|---------------------------------------|---------------------|
| `NOT_PLANNED` / `PLANNED` / `PUBLISHED` | Create / update sync PR | Block (command rejected when stale) | n/a | Create / update sync PR |
| `SNAPSHOT_ACTIVE` / `DRAFT_READY` | Drift warning in Release Issue only | n/a | Create / update sync PR | Create / update sync PR |

**Sync PR model:**
- Per release line: detection checks out the base branch (`main` or `maintenance/rX`) and its plan's `commonalities_release`; the PR targets that branch
- Branch: `sync-common/{tag}` on `main` (e.g., `sync-common/r4.2`), `sync-common/{base_branch}/{tag}` on a maintenance branch (e.g., `sync-common/maintenance/r1/r4.2`); lookup and superseded-PR cleanup stay within the line
- Author: `camara-release-automation` App bot
- No force-push — codeowners may push fix commits to the PR before merge
- Stale PRs (wrong tag after a dependency bump) are closed automatically when a new sync is needed
- Standard CODEOWNERS review applies (one codeowner approval is sufficient; bot is author)

**Data contracts:**
- [`code/common/.sync-manifest.yaml`](../../validation/schemas/sync-manifest-schema.yaml) — records source repository (Commonalities), declared release tag, and per-file git blob SHA-1. Written by the common sync; read by both RA (drift detection in `plan`) and the validation framework (`P-021 check-common-cache-sync`).
- [`tooling_lib/cache_sync.py`](../../tooling_lib/cache_sync.py) — shared drift-detection logic (`SyncStatus`, `SourceStatus`, `check_sync_status`, `git_blob_sha`). Imported by both RA and VF so they produce identical verdicts.

**Notifications:**
- `common_sync_pr_created.md` — bot comment on the Release Issue when a new sync PR is created (fires once per creation, not once per stale-detection)
- `common_sync_failed.md` — bot comment when checkout from Commonalities fails (for example, the declared tag has not yet been published)
- The Release Issue config section shows the `stale` warning on every sync-issue update until the cache converges

**Boundary with validation framework:**
- RA owns detection and the common sync (writes common files, creates/updates sync PR, writes manifest)
- VF's `P-021 check-common-cache-sync` is a read-only safety net. It fires only when codeowners bypass the sync process (e.g., direct edits to `code/common/`) — the design expects it to be silent in normal operation
- The `camara-release-automation` App has `contents: write`; the `camara-validation` App deliberately does not

**References:**
- [Commonalities-Consumption-and-Bundling-Design.md §4](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/SupportingDocuments/Commonalities-Consumption-and-Bundling-Design.md) — cache and sync model
- Upstream tracking: [ReleaseManagement#489](https://github.com/camaraproject/ReleaseManagement/issues/489)

---

## 3. Workflow Architecture

### 3.1 Event Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Trigger Events                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  issue_comment (created)          issues (closed/reopened)              │
│         │                                │                               │
│         ▼                                ▼                               │
│  ┌─────────────────┐            ┌─────────────────┐                     │
│  │ Slash command?  │            │ Release issue?  │                     │
│  │ /create-snapshot│            │ Has state label │                     │
│  │ /discard-snapshot│           └────────┬────────┘                     │
│  │ /delete-draft   │                     │                               │
│  │ /publish-release│                     │                               │
│  └────────┬────────┘                     │                               │
│           │                              │                               │
│           └──────────┬───────────────────┘                               │
│                      │                                                   │
│                      ▼                                                   │
│         pull_request (closed + merged)                                   │
│                      │                                                   │
│                      ▼                                                   │
│            ┌─────────────────┐                                          │
│            │ Base branch is  │                                          │
│            │ release-snapshot│──── Yes ──► Draft release creation       │
│            └─────────────────┘                                          │
│                                                                          │
│         push (main branch, release-plan.yaml changed)                   │
│                      │                                                   │
│                      ▼                                                   │
│            Auto-trigger sync-issue                                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Caller Workflow (API Repositories)

Each API repository has a minimal caller workflow that forwards events to the reusable workflow in `tooling`.

**Triggers:**

| Event | Condition | Purpose |
|-------|-----------|---------|
| `issue_comment` (created) | Slash command on release issue | Command execution |
| `issues` (closed/reopened) | Issue has `release-state:*` label | Closure policy enforcement |
| `pull_request` (closed) | Merged into `release-snapshot/*` branch | Draft release creation |
| `push` (main, `maintenance/**`) | `release-plan.yaml` changed | Auto sync-issue of the pushed line |
| `workflow_dispatch` | Manual trigger, input `action` | `sync-issue` (default): recovery; `create-maintenance-branch` with input `cycle` |

**Concurrency:** Global concurrency group per repository (`release-automation-{repo}`) with `cancel-in-progress: false`. This prevents overlapping workflow runs from producing inconsistent state.

**Permissions:** Caller workflows grant `contents`, `issues` and `pull-requests` write; no OIDC token is read.

**Commands:**

| Command | Description | Required State | Who may execute |
|---------|-------------|----------------|-----------------|
| `/create-snapshot` | Create snapshot and Release PR | PLANNED | Codeowner |
| `/discard-snapshot <reason>` | Discard current snapshot | SNAPSHOT_ACTIVE | Codeowner, Release manager |
| `/delete-draft <reason>` | Delete draft release | DRAFT_READY | Codeowner, Release manager |
| `/publish-release` | Request publication confirmation | DRAFT_READY | Codeowner |
| `/publish-release --confirm <tag>` | Publish release, create sync PR | DRAFT_READY | Codeowner |

**Note:** `sync-issue` is an internal workflow action, not a user-facing slash command. It runs automatically after state changes and on push to main when `release-plan.yaml` changes. Available via `workflow_dispatch` for recovery only.

### 3.3 Reusable Workflow (Tooling Repository)

The reusable workflow (`release-automation-reusable.yml`) has four jobs. `plan` decides, `snapshot` or `act` executes the plan's action, `finalize` reports and syncs. The logic lives in Python modules under `release_automation/scripts/`; the workflow holds the job boundaries, checkouts, tokens and toolchain setup. Jobs pass data as JSON: one `plan` output from `plan`, one `outcome` output from `snapshot` or `act`.

**Workflow/script ref consistency:** Every tooling checkout reads the `job` context of the called reusable workflow: `repository: ${{ job.workflow_repository }}` and `ref: ${{ job.workflow_sha }}`. This binds checkout content to the exact repository and commit of the workflow file that defines the job, whether the caller references a branch, a tag or a SHA, and also when caller and tooling are both forks. There is no caller-side override. Each of the four jobs performs this checkout (path `_tooling`); `snapshot` adds a checkout of the API repository for validation and of the central validation settings.

**Jobs:**

| Job | Runs when | Does |
|-----|-----------|------|
| `plan` | Always | Acknowledges the command, classifies the trigger (`trigger.py`), derives the release state, checks the common cache, assembles the context, applies the command policy (`command_policy.py`), posts the one response (interim status, rejection, configuration error or publish confirmation) |
| `snapshot` | Plan action is `create-snapshot` | Pre-snapshot validation, snapshot branch, release-review branch and Release PR; own job because it needs the validation toolchain (Node) |
| `act` | Any other plan action | `act.py` dispatches `discard-snapshot`, `delete-draft`, `publish-release`, `create-draft`, `publish-on-merge` or `reopen-issue` to the matching module |
| `finalize` | Plan asks for it; also after a failed `snapshot` or `act` | Post-release sync PR, common sync, Release Issue sync and notifications, result comment, published Release Issue (`finalize.py`) |

**Job execution order:**

```mermaid
flowchart TD
    PLAN["plan<br><i>trigger, state, common cache,<br>context, command policy, response</i>"]
    SNAP["snapshot<br><i>/create-snapshot</i>"]
    ACT["act<br><i>discard, delete-draft, publish,<br>draft on merge, auto-reopen</i>"]
    FIN["finalize<br><i>sync PR, common sync, Release Issue,<br>result comment</i>"]

    PLAN -->|action: create-snapshot| SNAP
    PLAN -->|other action| ACT
    PLAN -->|no action: push, dispatch,<br>sync-issue, close| FIN
    PLAN -->|rejected, config error,<br>publish confirmation| STOP([responds and stops])
    SNAP --> FIN
    ACT --> FIN
```

**3-stage feedback model** (slash commands only):

| Stage | Job | Timing | Content |
|-------|-----|--------|---------|
| 1. Ack | `plan` (*Post Acknowledgment*) | ~8 seconds | Brief acknowledgment that command was received |
| 2. Interim | `plan` (*Post Response*, `interim_processing`) | After the command policy allows the command | Processing status with workflow run link |
| 3. Result | `finalize` | After `snapshot` or `act` completes | Final outcome (success/failure details) |

All three stages edit the same comment: `plan` passes the acknowledgment's comment ID to `finalize` as `result_comment_id`. For rejected commands, the acknowledgment is updated directly with the rejection message (skipping interim) and `finalize` does not run.

**Context assembly** (`plan` job):

The *Assemble Context* step of `plan` runs after state derivation and the common cache check. It builds the base BotContext with `build_context()` from the trigger outputs and the derived state, and the command policy stores it in the plan as `base_context`. `snapshot`, `act` and `finalize` take the context from the plan, so there is a single source. A command's outcome fields (for example `release_pr_url`) are passed to `finalize` as delta context for the result comment.

---

## 4. Shared Actions

### 4.1 derive-release-state

Derives current release state from repository artifacts. Takes no inputs — `release_tag` is derived from `release-plan.yaml` (main) or `release-metadata.yaml` (snapshot branch).

**Outputs:** `release_tag`, `state`, `release_type`, `source`, `snapshot_id`, `snapshot_branch`, `release_review_branch`, `release_pr_number`, `src_commit_sha`, `apis_json`, `commonalities_release`, `identity_consent_management_release`, `config_error`, `config_error_type`

**State values:** `planned`, `snapshot-active`, `draft-ready`, `published`, `not-planned`

### 4.2 post-bot-comment

Creates or updates a bot comment with a release-specific marker (`<!-- release-bot:{release_tag} -->`).

**Inputs:** `issue_number`, `release_tag`, `template`, `context` (JSON), `comment_id` (optional — update existing)

**Output:** `comment_id`

### 4.3 update-issue-section

Updates a reserved section in the issue description between `<!-- BEGIN:{section} -->` / `<!-- END:{section} -->` markers.

**Inputs:** `issue_number`, `section` (STATE, CONFIG, ACTIONS), `content`

### 4.4 Release Issue sync

No longer a composite action: the `finalize` job calls `issue_sync.sync_for_workflow()` ([finalize.py](../scripts/finalize.py)). It synchronizes the Release Issue with the derived state (or the state the run's command produced), creates the issue when none exists and the state is PLANNED, and updates sections, labels and title on state changes.

**Returns:** `issue_number`, `issue_action` (`created`, `updated`, `unchanged`, `skipped`, `error`), `issue_url`

### 4.5 create-snapshot

Orchestrates the full snapshot creation flow: validate release plan, calculate API versions, create snapshot branch with transformations + README Release Information, generate release-metadata.yaml, create release-review branch with the CHANGELOG commit, create Release PR.

---

## 5. Data Flow

### 5.1 `/create-snapshot` Success Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                     /create-snapshot Success Flow                       │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. User comments: /create-snapshot                                     │
│                    │                                                    │
│                    ▼                                                    │
│  2. Post ack: "⏳ Processing /create-snapshot..."  (~5s)                │
│                    │                                                    │
│                    ▼                                                    │
│  3. Derive state: PLANNED (valid release-plan.yaml, no snapshot)        │
│                    │                                                    │
│                    ▼                                                    │
│  4. Validate: User is codeowner, command allowed in PLANNED             │
│                    │                                                    │
│                    ▼                                                    │
│  5. Update ack → interim: show processing status + workflow link        │
│                    │                                                    │
│                    ▼                                                    │
│  6. Run validation: Schema + semantic + dependencies                    │
│                    │                                                    │
│                    ▼                                                    │
│  7. Calculate versions: "3.2.0-rc.2" based on release history          │
│                    │                                                    │
│                    ▼                                                    │
│  8. Create snapshot branch: release-snapshot/r4.1-abc1234              │
│     - Apply mechanical transformations                                  │
│     - Update README Release Information section                        │
│     - Generate release-metadata.yaml                                    │
│     - Commit + push snapshot branch                                     │
│                    │                                                    │
│                    ▼                                                    │
│  9. Create release-review branch from snapshot HEAD                     │
│     9a. Generate CHANGELOG draft → CHANGELOG/CHANGELOG-r4.md           │
│     - Push release-review branch                                        │
│                    │                                                    │
│                    ▼                                                    │
│  10. Create Release PR: release-review → snapshot (1 commit diff)       │
│      Title: "Release Review: RepoName r4.1 (RC, Sync26)"               │
│                    │                                                    │
│                    ▼                                                    │
│  11. Update issue:                                                      │
│      - State section: SNAPSHOT_ACTIVE                                   │
│      - Config: Show release configuration                               │
│      - Label: release-state:snapshot-active                             │
│                    │                                                    │
│                    ▼                                                    │
│  12. Update interim → result: "✅ Snapshot Created" message             │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

### 5.2 State Label Transitions

```mermaid
stateDiagram-v2
    [*] --> planned : release-plan.yaml updated<br>(type ≠ none)

    planned --> snapshot_active : /create-snapshot
    snapshot_active --> planned : /discard-snapshot

    snapshot_active --> draft_ready : Merge Release PR
    draft_ready --> planned : /delete-draft

    draft_ready --> published : /publish-release<br>--confirm rX.Y
    published --> [*]

    planned --> not_planned : type → none
    not_planned --> planned : type → valid value

    state planned {
        [*] : release-state#colon;planned
    }
    state snapshot_active {
        [*] : release-state#colon;snapshot-active
    }
    state draft_ready {
        [*] : release-state#colon;draft-ready
    }
    state published {
        [*] : release-state#colon;published
    }
    state not_planned {
        [*] : release-state#colon;not-planned
    }
```

**Note:** Release Issues are workflow-owned artifacts. They are created automatically when a valid `release-plan.yaml` is detected (with `target_release_type` ≠ "none") and carry a hidden marker `<!-- release-automation:workflow-owned -->`. Manually created issues are ignored by the automation.

**Issue closure behavior:**
- Closing in PLANNED state has no semantic effect; the issue is treated as historical
- Automation will create a new Release Issue if needed (no open workflow-owned issue exists)
- Auto-reopen only applies when snapshot or draft is active (prevents orphaned artifacts)
- NOT_PLANNED is derived from `target_release_type: none`, not from issue closure

**Plan changes during a snapshot:** An active snapshot is not affected by a later `release-plan.yaml` edit on main — it carries its own `release-metadata.yaml`. Validation blocks `release-plan.yaml` edits while a snapshot is active, and only `/create-snapshot` is gated on the common-file cache check.

### 5.3 Context Data Flow

Data flows from artifacts through derive-state into the unified BotContext for all consumers:

```
release-plan.yaml (main branch)
    │
    ├─► derive-state ──► release_tag, state, release_type
    │                     target_api_version, target_api_status (per API)
    │
release-metadata.yaml (snapshot branch, if exists)
    │
    ├─► derive-state ──► src_commit_sha, snapshot_id, snapshot_branch,
    │                     release_review_branch, release_pr_number,
    │                     api_version, api_title (per API),
    │                     commonalities_release, identity_consent_management_release
    │
    └─► derive-state merges both sources into apis_json
              │
              ▼
    ┌──────────────────────┐
    │  Assemble Context    │◄── trigger outputs (command, user, trigger_type)
    │  └─ build_context()  │◄── derive-state outputs (all above)
    │  (plan job)          │◄── command action outcome (release_pr_url, draft_release_url, ...)
    │                      │◄── workflow env (workflow_run_url)
    └────────┬─────────────┘
             │
             ▼
    ┌─────────────────┐
    │   BotContext     │──► bot_responder.render() ──► bot comments
    │   (complete,    │──► issue_manager ──► issue description, config section
    │    no missing   │
    │    keys)        │
    └────────┬────────┘
             │
             │  (during create-snapshot only, from snapshot_creator.py)
             │
             ├──► readme_updater.py ──► README Release Information section
             │
             └──► changelog_generator.py ──► CHANGELOG/CHANGELOG-r{cycle}.md
```

**Fresh vs stale data:** When create-snapshot runs in the same workflow, its outputs (release_pr_url, api versions) are fresh. On subsequent workflow runs (e.g., issue close/reopen), derive-state reads the same data from persisted artifacts — this is functionally equivalent, not stale.

---

## 6. Error Handling

### 6.1 Error Categories

| Category | Example | Response Template | Recovery |
|----------|---------|-------------------|----------|
| Configuration | Invalid release-plan.yaml | `config_error` | Fix config, re-trigger |
| Validation | Missing test file | `snapshot_failed` | Fix on main, retry |
| Permission | Non-maintainer / non-codeowner | `command_rejected` | Contact codeowner |
| State | `/create-snapshot` when snapshot active | `command_rejected` | Discard first |
| GitHub API | Branch creation fails | `internal_error` | Retry or escalate |

### 6.2 Graceful Degradation

Snapshot creation includes cleanup on failure: if an error occurs after branches are created, partial state (snapshot branch, release-review branch) is cleaned up before reporting the error. The `snapshot_failed` message includes the workflow run URL for debugging.

---

## 7. Security Considerations

### 7.1 Permission Model

| Action | Required Permission |
|--------|---------------------|
| `/create-snapshot` | Codeowner |
| `/discard-snapshot` | Codeowner or RM team |
| `/delete-draft` | Codeowner or RM team |
| `/publish-release` | Codeowner |
| Merge Release PR | Codeowner + RM reviewer approval |

Permission checks use the GitHub API (`GET /repos/{owner}/{repo}/collaborators/{user}/permission`). The `/publish-release` command additionally verifies CODEOWNERS file presence.

### 7.2 Branch Protection

| Branch Pattern | Protection |
|----------------|------------|
| `release-snapshot/*` | Push: automation only; Delete: automation only |
| `release-review/*` | Push: codeowners + automation; Delete: automation |

**Release PR approval requirements:**
- At least one **codeowner** approval required
- At least one **Release Management reviewer** approval required
- Enforced via repository rulesets on `release-snapshot/*` branches

Repository rulesets enforce these protections. GitHub Actions is configured as a bypass actor to allow workflow operations while blocking direct human access. See [repository-setup.md](repository-setup.md#repository-rulesets) for the ruleset definitions, links to the declared payloads, and the verification checklist.

### 7.3 Secrets

- `GITHUB_TOKEN`: Default workflow token (sufficient for same-repo operations)
- No additional secrets required for MVP

---

## 8. Release Plan Changes in Pull Requests

When `release-plan.yaml` changes in a PR, CAMARA Validation (the validation workflow of the API repository) runs the release-plan checks. After the PR merges and `release-plan.yaml` lands on main, the push trigger runs the release automation workflow.

### 8.1 Active Release Check

Rule P-033 (`check-release-plan-active-release-state`) blocks the PR with an error while a release is active: a `release-snapshot/<release_tag>-*` branch exists, or the derived release state is `snapshot-active` or `draft-ready`. The release automation workflow derives the state; the validation check consumes it offline.

### 8.2 State Transition Cases

| Current State | release-plan.yaml Change | CAMARA Validation (PR) | release-automation Action |
|---------------|--------------------------|------------------------|---------------------------|
| No issue | Valid plan (type ≠ none) | Pass | Create issue (PLANNED) |
| PLANNED | Plan updated | Pass | Update issue |
| PLANNED | type → none | Pass | Set NOT_PLANNED, suggest close |
| SNAPSHOT_ACTIVE | Any change | **Block (P-033)** | — |
| DRAFT_READY | Any change | **Block (P-033)** | — |
| PUBLISHED | Any change | Pass (new release cycle) | Create new issue if type ≠ none |

---

## 9. Performance Targets

| Operation | Target | Approach |
|-----------|--------|----------|
| Ack comment | < 5 seconds | First steps of `plan`, before any checkout or Python setup |
| State derivation | < 10 seconds | Direct GitHub API calls |
| Full `/create-snapshot` | < 3 minutes | Three runners (`plan`, `snapshot`, `finalize`); only `snapshot` sets up Node and the validation toolchain |
| Result comment | < 5 seconds | Template rendering + API call in `finalize` |

Indicative timings from single runs on a test repository, measured from the command to the result comment and including the caller run: `/create-snapshot` about 110 seconds, `/discard-snapshot` about 85 seconds (`plan` 25, `act` 15, `finalize` 22). Differences of about 15 seconds between runs are noise.

---

## References

- [CAMARA-Release-Creation-Detailed-Design.md](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/SupportingDocuments/CAMARA-Release-Creation-Detailed-Design.md) — Source design document
- [release-metadata-schema.yaml](../../validation/schemas/release-metadata-schema.yaml) — Release metadata schema
- [release-plan-schema.yaml](../../validation/schemas/release-plan-schema.yaml) — Release plan schema
- [transformations.yaml](../config/transformations.yaml) — Mechanical transformation rules
