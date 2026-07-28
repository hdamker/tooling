# CAMARA Tooling documentation

This documentation helps CAMARA API contributors, codeowners, and release coordinators use shared tooling in API repositories.

## CAMARA Validation

CAMARA Validation checks API definitions, test files, and release planning files in CAMARA API repositories. Results appear on pull requests and on Release Issues, so contributors and codeowners can see what needs to change before code reaches a release.

### Working on a pull request

- [Find the validation results](validation/where-to-see-results.md)
- [Fix validation problems on a pull request](validation/pull-requests.md)
- [Understand error, warning, and hint messages](validation/problem-messages.md)
- [Understand what a result obligates your team to do](validation/severity-obligations.md)
- [Read guidance for common validation problems](validation/faq.md)

### Preparing a release

- [Fix a failed `/create-snapshot` run](validation/release-snapshots.md)
- [Understand validation on a Release PR](validation/release-prs.md)
- [Preview the bundled API definition](validation/bundled-api-definitions.md)

### Checking manually

- [Run validation manually](validation/manual-runs.md)

## Release Automation

Release Automation drives the CAMARA release process from `/create-snapshot` to `/publish-release`. The user-facing documentation lives in the [ReleaseManagement repository](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/README.md).

It also supports synchronization of cached `code/common/` files used by validation and API definitions. See the CAMARA Validation FAQ entry for `[P-021]` when a validation result reports that `code/common/` is missing or out of sync.

## Future tooling area

Reserved for later user-facing documentation about other shared tooling in CAMARA API repositories.
