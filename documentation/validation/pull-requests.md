# Validation on pull requests

CAMARA Validation runs on pull requests to `main` in onboarded API repositories. If the repository releases from a maintenance branch, validation may also run there according to the repository's workflow configuration. This page describes what you see, what you do about it, and what codeowners should check before merge.

## What you see

When you open or update a pull request, CAMARA Validation appears in the checks list, with annotations attached to the changed lines. The complete validation report is the workflow summary linked from the check.

For where validation results are shown and the differences between same-repository and fork pull requests, see [Where to see validation results](where-to-see-results.md). For the format of each problem message, see [Validation problem messages](problem-messages.md).

## What you do

1. Open the workflow summary linked from the CAMARA Validation check.
2. Look at **errors** first. Errors should be fixed before merge. During the pilot, GitHub may not technically block every pull request merge on validation errors, but errors will block the release process at `/create-snapshot` and should not be left on `main` intentionally.
3. For each error, read the source file and line shown in the message and fix it in your branch. Use the rule code (for example `[S-002]`) to look up extra guidance in the [Validation FAQ](faq.md) when the short message is not enough.
4. Push the change. The check re-runs automatically.
5. Look at **warnings and hints** before requesting review. They are not errors, but many of them turn into errors at a later release type — fixing them in the same pull request is usually cheaper than returning to them later.

## What can block you

A few common patterns to be aware of when reviewing the validation results:

- **Errors** in API definitions, test files, or `release-plan.yaml`. Fix the source file before merge — leaving them on `main` will block `/create-snapshot`.
- **Warnings that will become errors at a later release type.** Common example: missing test files are a hint on alpha releases, a warning at release candidate, and an error at public release. Plan to fix them before the next release type is reached.
- **Hints pointing at items to verify**, not items that always need to change. Read the message before acting.
- A problem in a **cached common file** under `code/common/`. Do not edit the cached file locally — see [Bundled API definitions](bundled-api-definitions.md) and the FAQ entry for `[P-021]`.
- A change to **`release-plan.yaml`** mixed with other changes. Rule `[P-022]` requires `release-plan.yaml` updates to be in their own pull request — split the pull request if needed.

When the short message is not enough to act, look up the rule code in the [Validation FAQ](faq.md).

## Codeowner guidance

Codeowners should not intentionally merge errors to `main` unless the repository has explicitly accepted the resulting release-process risk. The release process at `/create-snapshot` will block until the errors are gone. Warnings and hints are not blocking, but a codeowner reviewing for merge should at least scan the workflow summary and confirm the warnings make sense in context — many of them indicate something that will block a later release type.

For what each severity obligates your team to do, and why the same rule can report differently as your API's status advances, see [What a validation result obligates your team to do](severity-obligations.md).

## What to open next

- For where each kind of result appears: [Where to see validation results](where-to-see-results.md).
- For the shape of an individual problem message: [Validation problem messages](problem-messages.md).
- For specific recurring problems: [Validation FAQ](faq.md).

## Related

- [Where to see validation results](where-to-see-results.md)
- [Validation problem messages](problem-messages.md)
- [What a validation result obligates your team to do](severity-obligations.md)
- [Validation FAQ](faq.md)
- [Bundled API definitions](bundled-api-definitions.md)
- [Validation during snapshot creation](release-snapshots.md)
- [Release process: lifecycle](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/release-process/lifecycle.md)
