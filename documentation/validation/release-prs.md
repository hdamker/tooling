# Validation on a Release PR

A Release PR is the pull request opened by `/create-snapshot` for review of generated release content. CAMARA Validation runs on it just as it does on a normal pull request.

## What you see

The Release PR shows the same check entries, annotations, and workflow summary as a normal pull request. For where validation results are shown on a Release PR, see [Where to see validation results](where-to-see-results.md).

## What this check means

The Release PR is a **transparency check** on release content. It helps reviewers see problems before publication. It does not make the Release PR the right place to fix API specifications or test definitions.

## What you can change in the Release PR

You may review or refine reviewable release content according to the release process — the changelog entry. The README release information is a mechanical change committed with the snapshot before the Release PR opens; it is not editable there.

## What you must not change there

Do not fix API definition, test definition, or other source files directly on the Release PR or the snapshot branch. The snapshot branch is automation-owned and protected. Fix source problems on `main` or the applicable maintenance branch, then discard and recreate the snapshot.

## What you do when validation reports an API problem

The fix path is the same as for any other validation problem at release time:

1. Fix the source on `main` or the applicable maintenance branch via a normal pull request, and merge it.
2. Post `/discard-snapshot <reason>` on the Release Issue to discard the active snapshot.
3. Post `/create-snapshot` to create a new snapshot. CAMARA Validation runs again before the new snapshot is created.

## What to open next

- For the places where results appear and their limits: [Where to see validation results](where-to-see-results.md).
- For the snapshot creation step itself: [Validation during snapshot creation](release-snapshots.md).
- For the full release process flow: [Release process: lifecycle](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/release-process/lifecycle.md).

## Related

- [Where to see validation results](where-to-see-results.md)
- [Validation during snapshot creation](release-snapshots.md)
- [Validation on pull requests](pull-requests.md)
- [Validation problem messages](problem-messages.md)
- [Validation FAQ](faq.md)
