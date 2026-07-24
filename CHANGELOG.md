# Changelog tooling

## Table of Contents

- **[v0.8.1](#v081)**
- **[v0.8.0](#v080)**
- **[v0.7.1](#v071)**
- **[v0.7.0](#v070)**
- **[v0.6.0](#v060)**
- **[v0.5.0](#v050)**
- **[v0.4.0](#v040)**
- **[v0.3.0](#v030)**
- **[v0.2.3](#v023)**
- **[v0.2.2](#v022)**
- **[v0.2.1](#v021)**
- **[v0.2.0](#v020)**

# v0.8.1

## Release Notes

**v0.8.1 is a patch release for the CAMARA tooling repository.**

This release fixes two P-025 false positives found while evaluating the blast radius of the `v0.8.0` S-211 fix: a scenario-step line that reuses the API name as a resource-path segment later in the same line (e.g. `/qos-profiles/vwip/qos-profiles/{name}`), and a `#` comment documenting the raw operation being misread as a scenario step. No new rule ID.

### Fixed

* Fix two P-025 false positives on real-world feature-file lines by @hdamker in https://github.com/camaraproject/tooling/pull/395

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.8.0...v0.8.1

# v0.8.0

## Release Notes

**v0.8.0 is a minor release for the CAMARA tooling repository.**

This release adds x-correlator documentation checks (new rules S-039 and S-040) and rewrites the behavior of three existing rules: discriminator-aware unused-component detection (S-211), a per-field `sinkCredential` writeOnly check (P-016), and S-036 parameter casing to allow the Design-Guide-defined filtering-operation suffixes (`.gte`, `.gt`, `.lte`, `.lt`).

### Added

* Check x-correlator documentation — new rules S-039 (request header undocumented) and S-040 (response header undocumented) by @LarryHu0217 in https://github.com/camaraproject/tooling/pull/376

### Changed

* Make unused-component detection discriminator-aware (S-211) by @LarryHu0217 in https://github.com/camaraproject/tooling/pull/378
* Migrate P-006/P-007/P-008 severity ramp to `target_api_status` (no behavior change) by @hdamker in https://github.com/camaraproject/tooling/pull/381
* Rewrite P-016 as a per-field `sinkCredential` writeOnly check by @hdamker in https://github.com/camaraproject/tooling/pull/383
* Allow Design-Guide-defined filtering-operation suffixes (`.gte`, `.gt`, `.lte`, `.lt`) in S-036 parameter casing by @hdamker in https://github.com/camaraproject/tooling/pull/389
* Bump @redocly/cli from 2.37.0 to 2.39.0 by @dependabot in https://github.com/camaraproject/tooling/pull/374
* Bump actions/setup-python from 6 to 7 by @dependabot in https://github.com/camaraproject/tooling/pull/384
* Bump actions/setup-node from 6 to 7 by @dependabot in https://github.com/camaraproject/tooling/pull/385
* Bump @stoplight/spectral-cli from 6.16.1 to 6.16.2 by @dependabot in https://github.com/camaraproject/tooling/pull/386
* Bump fast-uri, brace-expansion to patched versions (security) by @hdamker in https://github.com/camaraproject/tooling/pull/391

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.7.1...v0.8.0

# v0.7.1

## Release Notes

**v0.7.1 is a patch release for the CAMARA tooling repository.**

This release consolidates the fixes and refinements that landed on `main` after
v0.7.0: two validation false-negative fixes (feature-file API-name matching and
hyphenated URL version segments), an S-038 wording alignment and int64 safe-range
lint refinement, a Release Review PR template change (RM reviewer-assignment
action and readiness-note rewording), and dependency bumps. No new rule ID.

### Added

* Review PR template: readiness-note fix and RM reviewer-assignment action by @hdamker in https://github.com/camaraproject/tooling/pull/372

### Changed

* Align S-038 wording with the OpenAPI Format Registry framing by @hdamker in https://github.com/camaraproject/tooling/pull/370
* Bump js-yaml from 5.0.0 to 5.2.1 by @dependabot in https://github.com/camaraproject/tooling/pull/363
* Bump @redocly/cli from 2.34.0 to 2.37.0 by @dependabot in https://github.com/camaraproject/tooling/pull/364
* Bump @stoplight/spectral-cli from 6.16.0 to 6.16.1 by @dependabot in https://github.com/camaraproject/tooling/pull/362

### Fixed

* Match feature files to the longest API name in scope by @hdamker in https://github.com/camaraproject/tooling/pull/366
* Flag hyphenated URL version segments by @hdamker in https://github.com/camaraproject/tooling/pull/369

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.7.0...v0.7.1

# v0.7.0

## Release Notes

**v0.7.0 is a validation-behavior release for the CAMARA tooling repository.**

This release consolidates the changes that landed on `main` after v0.6.0. It
adds a YAML parser conformance warning (P-037), locks published release-plan
attribution, keeps annotation bodies readable, and bumps the checkout action
used across workflows. The validation-behavior changes are visible to CAMARA API
repositories.

### Added

* Add YAML parser conformance warning (P-037) by @hdamker in https://github.com/camaraproject/tooling/pull/353
* Cover info-description marker spacer tolerance by @hdamker in https://github.com/camaraproject/tooling/pull/354
* Pin P-037 to the YAML-fundamentals and subscriptions regression branches, and add `CHANGELOG.md` and `VERSION.yaml` for the v0.7.0 release PR

### Changed

* Lock published release-plan attribution by @hdamker in https://github.com/camaraproject/tooling/pull/357
* Bump actions/checkout from 6 to 7 by @dependabot in https://github.com/camaraproject/tooling/pull/355

### Fixed

* Keep colons readable in annotation bodies by @hdamker in https://github.com/camaraproject/tooling/pull/358

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.6.0...v0.7.0

# v0.6.0

## Release Notes

**v0.6.0 is a validation and release-automation stabilization release for the
CAMARA tooling repository.**

This release consolidates the changes that landed on `main` after v0.5.0. It
updates validation rules and dependency policy, strengthens tooling CI, extends
Release Review output, and adds repository-level release metadata.

### Added

* Add published-history release-plan checks (P-035 and P-036) by @hdamker in https://github.com/camaraproject/tooling/pull/347
* Add release-plan cross-field validation checks by @hdamker in https://github.com/camaraproject/tooling/pull/338
* Add API comparison baselines to Release Review by @hdamker in https://github.com/camaraproject/tooling/pull/336
* Add breaking-changes changelog sections by @hdamker in https://github.com/camaraproject/tooling/pull/337
* Add PR-time validation and release checks for tooling changes by @hdamker in https://github.com/camaraproject/tooling/pull/334
* Add `CHANGELOG.md`, `VERSION.yaml`, and updated README release information for the v0.6.0 release PR

### Changed

* Replace gherkin-lint with GPLint by @hdamker in https://github.com/camaraproject/tooling/pull/340
* Align tooling CI with Node 24 by @hdamker in https://github.com/camaraproject/tooling/pull/341
* Align validation Python runtime policy by @hdamker in https://github.com/camaraproject/tooling/pull/345
* Bump @redocly/cli from 2.31.6 to 2.34.0 in `/validation` by @dependabot in https://github.com/camaraproject/tooling/pull/343
* Document the `v0` tag as retired legacy linting and keep `v1-rc` as the active consumption line in README release information

### Fixed

* Close stale release issues after tag changes by @hdamker in https://github.com/camaraproject/tooling/pull/327
* Reject unsafe integer schema values by @hdamker in https://github.com/camaraproject/tooling/pull/335
* Retry regression bot comment reads by @hdamker in https://github.com/camaraproject/tooling/pull/346

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.5.0...v0.6.0

# v0.5.0

## Release Notes

**v0.5.0 is a maintenance and stabilization release for the CAMARA tooling
repository after the v0.4.0 consolidation of CAMARA Validation and Release
Automation V1.**

The release contains follow-up fixes that had already landed on `main`, with a
focus on validation rule behavior, Release Review PR output, release automation
idempotency, dependency maintenance, and README wording that marked the legacy
`v0` linting line as deprecated. `v1-rc` remained the active consumption line
for CAMARA API repositories.

### Added

* Link findings to the FAQ via `documentation_url` by @hdamker in https://github.com/camaraproject/tooling/pull/310
* Update regression inventory for r4.3 by @hdamker in https://github.com/camaraproject/tooling/pull/314
* Pin P-021 and P-031 to the missing-canonical regression branch by @hdamker in https://github.com/camaraproject/tooling/pull/315
* Flag leftover API readiness checklists by @hdamker in https://github.com/camaraproject/tooling/pull/321

### Changed

* Explain P-026 and P-027 handling in the validation FAQ by @hdamker in https://github.com/camaraproject/tooling/pull/309
* Adjust S-016 prerelease severity by @hdamker in https://github.com/camaraproject/tooling/pull/313
* Source canonical fallback on Release Review PRs by @hdamker in https://github.com/camaraproject/tooling/pull/317
* Grade S-307 by maturity and align S-016 draft behavior by @hdamker in https://github.com/camaraproject/tooling/pull/325
* Generate the first changelog sentence and default sections to N/A by @hdamker in https://github.com/camaraproject/tooling/pull/312
* Redesign Release Review PR bodies and label passing-with-warnings runs by @hdamker in https://github.com/camaraproject/tooling/pull/318
* Render codeowner action details as lists, not code blocks by @hdamker in https://github.com/camaraproject/tooling/pull/326
* Bump @redocly/cli from 2.31.4 to 2.31.5 in `/validation` by @dependabot in https://github.com/camaraproject/tooling/pull/311
* Bump @redocly/cli from 2.31.5 to 2.31.6 in `/validation` by @dependabot in https://github.com/camaraproject/tooling/pull/319
* Document `v0` as deprecated legacy linting and clarify that active repositories use `v1-rc` by @hdamker in https://github.com/camaraproject/tooling/pull/333

### Fixed

* Warn when `info.description` canonical file is missing by @hdamker in https://github.com/camaraproject/tooling/pull/308
* Guard `camara-security-no-secrets` against null nodes by @hdamker in https://github.com/camaraproject/tooling/pull/323
* Rebuild sync-common branches idempotently by @hdamker in https://github.com/camaraproject/tooling/pull/306
* Bump protobufjs override and add scoped brace-expansion override by @hdamker in https://github.com/camaraproject/tooling/pull/304
* Drop redundant @redocly/cli brace-expansion override by @hdamker in https://github.com/camaraproject/tooling/pull/320
* Pin @stoplight/spectral-rulesets to 1.22.2 by @hdamker in https://github.com/camaraproject/tooling/pull/329

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.4.0...v0.5.0

# v0.4.0

## Release Notes

**v0.4.0 consolidated the CAMARA Validation Framework v1 into the tooling
repository alongside the existing CAMARA Release Automation system.**

Validation provides PR-time and snapshot-time checks on CAMARA API repositories,
covering API definitions, test files, release-plan and release-metadata files,
and bundled release artifacts through a single reusable GitHub Actions workflow.

The validation framework was developed on the `validation-framework` branch
across more than 70 PRs and validated end-to-end on `camaraproject/ReleaseTest`
through the `v1-rc` tag before it was merged to `main` in #260. The merge also
established the single-branch model for both validation and release automation.

### Added

* Merge the `validation-framework` branch into `main` by @hdamker in https://github.com/camaraproject/tooling/pull/260
* Add version-specific Spectral rulesets and annotation deduplication by @hdamker in https://github.com/camaraproject/tooling/pull/143
* Integrate OWASP API Security Top 10 2023 rules by @hdamker in https://github.com/camaraproject/tooling/pull/145
* Add CAMARA-specific Spectral and Python gap rules by @hdamker in https://github.com/camaraproject/tooling/pull/147 and https://github.com/camaraproject/tooling/pull/148
* Add release-plan, Commonalities, metadata, info.description, and common-cache validation rules across the validation framework stabilization PRs
* Add Redocly-based bundling for external `$ref` handling during validation and snapshot creation
* Add broken-spec regression fixtures, scheduled/manual regression workflows, and the Release Automation Regression canary
* Add codeowner-facing validation documentation under `documentation/validation/`

### Changed

* Rewrite the release automation branching model for the single-branch model by @hdamker in https://github.com/camaraproject/tooling/pull/268
* Retarget dependencies, Dependabot, and regression infrastructure to `main`
* Improve workflow summaries, annotations, PR comments, and validation user documentation
* Continue Release Automation hardening for common file cache sync, post-release sync behavior, branch cleanup, shell safety, and workflow consolidation

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.3.0...v0.4.0

# v0.3.0

## Release Notes

**v0.3.0 added the CAMARA Release Automation system to the tooling repository.**

This system provides end-to-end release workflow automation for CAMARA API
repositories, handling release planning, snapshot creation, review PR
generation, changelog updates, and publication through a single reusable GitHub
Actions workflow.

The release automation was developed on the `release-automation` branch across
more than 30 PRs and validated on multiple API repositories via the `ra-v1-rc`
tag before merging to `main`.

### Added

* Add the core release automation workflow by @hdamker in https://github.com/camaraproject/tooling/pull/67
* Add GitHub App identity handling for protected branch operations and bot commits
* Add release issue and Release Review PR generation, state synchronization, snapshot creation, draft publication, pointer branches, and post-release sync
* Add release-plan validation improvements, changelog generation, README release-info handling, and snapshot/publish cleanup behavior

### Changed

* Harden workflow checkout/ref selection, command parsing, branch operations, and shell handling
* Merge the `release-automation` branch into `main` by @hdamker in https://github.com/camaraproject/tooling/pull/135

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.2.3...v0.3.0

# v0.2.3

## Release Notes

### Added

* Add workflow to update floating tags by @hdamker in https://github.com/camaraproject/tooling/pull/92

### Changed

* Bump `actions/checkout` from 4 to 6 by @dependabot in https://github.com/camaraproject/tooling/pull/100
* Simplify `release-plan.yaml` result reporting in PR validation by @hdamker in https://github.com/camaraproject/tooling/pull/127
* Update README for v0.2.3 by @hdamker in https://github.com/camaraproject/tooling/pull/129

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.2.2...v0.2.3

# v0.2.2

## Release Notes

### Added

* Add API file existence checking in PR validation and support SignalYY/SyncYY meta-release names by @hdamker in https://github.com/camaraproject/tooling/pull/85

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.2.1...v0.2.2

# v0.2.1

## Release Notes

### Added

* Add a release automation reusable workflow placeholder by @hdamker in https://github.com/camaraproject/tooling/pull/68

### Changed

* Raise the `requests` version floor to `>=2.32.4` by @hdamker in https://github.com/camaraproject/tooling/pull/62
* Remove the `none` option from `release_track` in the validation schema by @hdamker in https://github.com/camaraproject/tooling/pull/66
* Bump `tj-actions/changed-files` from 47.0.0 to 47.0.2 by @dependabot in https://github.com/camaraproject/tooling/pull/64

### Fixed

* Handle 403 responses gracefully on fork PRs in PR validation by @hdamker in https://github.com/camaraproject/tooling/pull/80

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.2.0...v0.2.1

# v0.2.0

## Release Notes

### Added

* Add release-plan validation support by @hdamker in https://github.com/camaraproject/tooling/pull/48
* Synchronize linting rules with Commonalities by @rartych in https://github.com/camaraproject/tooling/pull/59

### Changed

* Bump `actions/upload-artifact` from 4 to 6 by @dependabot in https://github.com/camaraproject/tooling/pull/56
* Bump `actions/setup-python` from 4 to 6 by @dependabot in https://github.com/camaraproject/tooling/pull/54
* Bump `actions/github-script` from 7.0.1 to 8.0.0 by @dependabot in https://github.com/camaraproject/tooling/pull/58
* Bump `actions/checkout` from 4 to 6 by @dependabot in https://github.com/camaraproject/tooling/pull/55

**Full Changelog**: https://github.com/camaraproject/tooling/compare/v0.1.1...v0.2.0
