# API Readiness Checklist

This document defines the release assets that API teams must provide for each release, and how readiness is verified during the release process.

## Purpose

Before an API repository can be released, codeowners must ensure that certain assets are in place and meet quality expectations appropriate for the declared target API status. This checklist:

- Defines the required release assets and their expected locations
- Specifies which assets are mandatory (M) or optional (O) per API status level
- Clarifies the division of responsibility: **codeowners prepare** the assets, **automation validates** what it can, and **release management reviewers** verify the rest

This document replaces the deprecated per-API `API-Readiness-Checklist.md` files. Readiness is now tracked through `release-plan.yaml` configuration, preparation prerequisites in the Release Issue, and the review checklist in the Release PR.

## Release Assets

| Nr | Asset | Description | Location | Automated? |
|----|-------|-------------|----------|------------|
| 1 | Release Plan | `release-plan.yaml` updated with target release tag, release type, API versions, statuses, and dependencies | `release-plan.yaml` | Schema validated on PR |
| 2 | API Definition(s) | One `{api-name}.yaml` per API, following applicable ICM guidelines | `code/API_definitions/` | Spectral linting on PR; file existence checked on `/create-snapshot` |
| 3 | Commonalities compliance | API definitions follow the Commonalities version declared in `release-plan.yaml` dependencies | In API definitions | Partially (Spectral rules cover structure; design guidelines require manual review) |
| 4 | API Documentation | API description in the YAML `info.description` field; additional documentation as needed | In YAML `info` section or `documentation/` | Partial (`info.description` presence checked) |
| 5 | User Stories | At least one user story per API demonstrating the intended use | `documentation/API_documentation/` | No |
| 6 | Test Cases (basic) | Sunny day scenarios and main error cases; at least one `.feature` file per API | `code/Test_definitions/` | File existence only |
| 7 | Test Cases (enhanced) | Rainy day scenarios, edge cases, and error handling coverage | `code/Test_definitions/` | No |
| 8 | API description link | Link to CAMARA Wiki API description page for external visibility | Wiki URL in API Readiness Checklist | No |

## Requirements by API Status

The following matrix defines which assets are mandatory (M) or optional (O) for each target API status level:

| Nr | Asset | alpha | rc | initial public | stable public |
|----|-------|:-----:|:--:|:--------------:|:------------:|
| 1 | Release Plan | M | M | M | M |
| 2 | API Definition(s) | M | M | M | M |
| 3 | Commonalities compliance | O | M | M | M |
| 4 | API Documentation | M | M | M | M |
| 5 | User Stories | O | O | O | M |
| 6 | Test Cases (basic) | O | M | M | M |
| 7 | Test Cases (enhanced) | O | O | O | M |
| 8 | API description link | O | O | M | M |

**Why this progression:**

- **Alpha**: The API is under active development. Only the API definition and basic documentation are required. Teams are iterating on the design and gathering feedback.
- **Release Candidate (rc)**: The API is feature-complete and ready for implementation testing. Commonalities compliance and basic test cases become mandatory to ensure interoperability.
- **Initial Public**: The API is ready for first implementations by external parties. An API description link is added for external visibility.
- **Stable Public**: The API is production-grade. All assets are mandatory, including enhanced test cases and user stories, to support production deployments.

## Preparation Prerequisites

Before issuing `/create-snapshot` on the Release Issue, codeowners must verify the following on the `main` branch. All corrections must be made on `main` first — once a snapshot is created, the snapshot branch only contains CHANGELOG and metadata changes.

- **Release configuration matches intent**: Check that API names, target versions, target statuses, and release type in `release-plan.yaml` are correct
- **Dependency versions are current**: Commonalities and ICM dependency versions in `release-plan.yaml` should reference the latest recommended releases
- **CI checks are green**: Spectral linting and PR validation should pass on `main`
- **All intended PRs are merged**: Implementation work should be complete on `main`
- **SemVer is correct**: Breaking changes are only allowed in initial versions (v0.x) or new major versions
- **Readiness assets are provided**: All mandatory assets for the declared target release type are in place (see matrix above)

These items appear as a preparation checklist in the Release Issue while it is in PLANNED state. They are reminders, not automated gates — the codeowner is responsible for verifying them before proceeding.

> **Note**: During development on `main`, API version fields in the YAML definitions must stay as `wip`. The release automation transformer replaces them with the correct version numbers during snapshot creation.

## Review Process

During the Release PR review (SNAPSHOT ACTIVE state), two types of reviewers verify different aspects:

### Codeowner Review

Codeowners verify content accuracy:

- CHANGELOG entries are complete and accurate (automation prepares entries from merged PRs; codeowners must review and complete them)
- API version numbers match the intent declared in `release-plan.yaml`
- API definitions are correct and complete for the target status
- Test cases cover the intended API behavior
- Documentation is adequate for the target audience

### Release Management Review

Release management reviewers verify process compliance:

- `release-metadata.yaml` content is correct
- API version transformations were applied correctly (server URLs, references, version fields)
- Version conventions are followed (SemVer, URL format matching API maturity)
- All mandatory readiness assets for the declared release type are present

The Release PR contains a status-specific review checklist that reflects the requirements for the repository's release type.

## Migration from Per-API Checklist Files

The legacy per-API `API-Readiness-Checklist.md` files (one per API repository) are deprecated. API teams should remove these files from their repositories.

Readiness is now tracked through:
1. `release-plan.yaml` — declares intent (target versions, statuses, dependencies)
2. Release Issue preparation prerequisites — codeowner self-check before snapshot creation
3. Release PR review checklist — reviewer verification of the snapshot content

<!-- NOTE: The following mapping section is included for review purposes.
     It may be removed from the final published version. -->

### Legacy Item Mapping

| Legacy # | Legacy Item | Disposition |
|----------|-------------|-------------|
| 1 | API Definition | Retained as #2 |
| 2 | Design Guidelines (Commonalities) | Retained as #3 (explicit row) |
| 3 | ICM Guidelines | Folded into #2 description (less direct impact on API spec) |
| 4 | API Versioning | Automated (release automation validates version format) |
| 5 | API Documentation | Retained as #4 |
| 6 | User Stories | Retained as #5 |
| 7 | Basic Test Cases | Retained as #6 |
| 8 | Enhanced Test Cases | Retained as #7 |
| 9 | Test Result Statement | Dropped (team will discuss alternatives) |
| 10 | Release Numbering | Automated (release automation manages release tags) |
| 11 | CHANGELOG Updated | Prepared by automation (codeowners review and complete) |
| 12 | Previous Release Certified | Dropped (certification process not established) |

## See Also

- [Release Process Lifecycle](../release-process/lifecycle.md) — step-by-step release guide
- [How Automation Works](../automation/how-automation-works.md) — what the system does for you
- [Terminology](../release-process/terminology.md) — definitions of key terms
- [release-plan.yaml Reference](../metadata/release-plan.md) — configuration file format
