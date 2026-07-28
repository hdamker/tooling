# What a validation result obligates your team to do

CAMARA Validation reports every problem as an error, a warning, or a hint. This page
explains what each of those obligates your team to do, and why the same rule can report a
different severity on your API today than it did last month — with no code change on your
side.

## What you do

- **Error.** Fix it. Errors block `/create-snapshot`, so an error left on `main` blocks
  your next release.
- **Warning.** Fix it, or record why you're not fixing it yet. If your team decides not to
  fix a warning immediately, open an issue with a copy of the relevant workflow-summary
  lines and the reason for deferring. That issue is your team's record for later — there is
  no automated tracking of deferred warnings today.
- **Hint.** Check it. A hint is not necessarily wrong — some hints exist because the check
  can't always tell for certain (for example, whether a component is genuinely unused). Read
  the message, decide, and fix it if it applies.

A passing CAMARA Validation check means no errors blocked the run. It does not mean there
are no warnings or hints — review those in the workflow summary before merging or before a
release.

## Why the same rule can report differently over time

Most rules don't have one fixed severity for the life of your API. They get stricter as
your API matures, tracking the status you declare in `release-plan.yaml` (`draft` → `alpha`
→ `rc` → `public`):

- Early on, a rule may not fire at all, or only as a hint — so drafting an API doesn't mean
  wading through a wall of findings.
- By `rc` — the point where implementers start building against your API — most rules that
  will eventually block have already become at least a warning.
- Severity never goes backward as your API matures. If a rule warned at `rc`, it will not
  quietly drop to a hint at `public`.

This means a finding can move from "hint" to "warning" to "error" between two pull requests
that don't touch the affected rule at all — because `release-plan.yaml` moved your API's
status forward. That's expected, not a bug: check your API's current status when a
severity looks like it jumped.

Some rules are also a little more lenient on a `0.x` (initial) API than on a `1.x+`
(stable) one, because a stable API can sometimes only fix a problem with a breaking version
change — an initial API can just fix it in place.

## Where to check a specific rule

If you need to know why a specific rule is reporting at its current severity, open the
[Validation FAQ](faq.md) entry for that rule code, if one exists. The workflow summary
always shows the rule code next to each finding.

## Related

- [Validation on pull requests](pull-requests.md) — what to do about a result on your PR
- [Where to see validation results](where-to-see-results.md)
- [Validation FAQ](faq.md)
