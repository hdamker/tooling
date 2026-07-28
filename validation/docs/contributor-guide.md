# Contributor guide to CAMARA Validation

For anyone adding or modifying a validation check in the `tooling` repository. This is
developer/admin documentation — for the user-facing docs contributors and codeowners read
when validation runs on their PR, see [documentation/validation/](../../documentation/validation/)
and its own [user-documentation-guidelines.md](user-documentation-guidelines.md).

## Pipeline overview

Every run chains the same five stages (`validation/orchestrator.py`):

```text
config gate -> context builder -> engines -> post-filter -> output
```

- **Config gate** (`validation/config/`) decides whether validation runs at all for this
  trigger (stage: `disabled`/`advisory`/`enabled`).
- **Context builder** (`validation/context/`) resolves `ValidationContext` (repo/branch/
  trigger/commonalities-release) and, per API, `ApiContext` (`target_api_status`,
  `target_api_maturity`, `api_pattern`, …) from `release-plan.yaml` /
  `release-metadata.yaml`.
- **Engines** (`validation/engines/`) run the four check engines — Spectral, yamllint,
  Gherkin/GPLint, and Python — and emit raw findings.
- **Post-filter** (`validation/postfilter/`) resolves each finding's final severity from
  rule metadata and the context (see below), and applies applicability/suppression.
- **Output** (`validation/output/`) renders annotations, the Check Run payload, the PR
  comment, the commit status, and the workflow-summary/diagnostics artifacts.

For the full design behind this pipeline, see [architecture-overview.md](architecture-overview.md).

## Rule metadata and severity

Every rule is one entry in `validation/rules/*-rules.yaml` (`spectral-rules.yaml`,
`gherkin-rules.yaml`, `python-rules.yaml`, `yamllint-rules.yaml`), validated against
[`validation/schemas/rule-metadata-schema.yaml`](../schemas/rule-metadata-schema.yaml).
Key fields:

- `id` — stable `<engine-prefix>-<nnn>` (`S-`/`G-`/`P-`/`Y-`/`M-`), never reused once
  assigned (see ID assignment in [`rules/README.md`](../rules/README.md)).
- `engine` / `engine_rule` — which engine and which native rule/check produced the finding.
- `applicability` — conditions under which the rule fires at all (AND across fields, OR
  within an array value).
- `conditional_level` — `default` plus ordered `overrides` (first match wins) resolving
  the finding's severity (`error`/`warn`/`hint`/`muted`).

**Severity convention:** write `conditional_level.default` as the rule's `public`/`stable`
obligation (usually `error`); overrides only *demote* for an earlier `target_api_status`
or an `initial` API — never escalate above the default. This keeps severity monotonic
across an API's lifecycle by construction, gives every reader the same anchor to reason
from, and avoids a rule quietly escalating past what its default implies. P-026/P-027 and
P-006/P-007/P-008 in `python-rules.yaml` are worked examples to mirror.

## Adding or changing a Python check

Python checks live in `validation/engines/python_checks/`, one module per topic area
(`test_checks.py`, `subscription_checks.py`, …). Each check function has the signature
`(repo_path, context) -> List[dict]` and returns findings built with `make_finding()`
from [`_types.py`](../engines/python_checks/_types.py).

1. Write the check function in the appropriate module (or a new one). Scope it
   `CheckScope.API` (runs once per API in `context.apis`) or `CheckScope.REPO` (runs once).
2. Register it in [`python_checks/__init__.py`](../engines/python_checks/__init__.py): import
   the function and append a `CheckDescriptor("check-kebab-case-name", scope, fn)` to
   `CHECKS`. Execution order follows list order.
3. Add a metadata entry to `python-rules.yaml`: new `id` (next free `P-nnn`), `engine:
   python`, `engine_rule` matching the descriptor name, `conditional_level` per the
   convention above, and `applicability` if the rule doesn't apply everywhere.
4. Add or update the `rule-inventory.yaml` entry if the rule was previously tracked as
   `gap` or `manual`, or add a doc-comment describing intent above the rule block in
   `python-rules.yaml` (existing rules follow this pattern).
5. Write tests in `validation/tests/test_python_checks_<area>.py` for the check function
   itself, and — if the rule's severity shape is non-trivial (splits by status/maturity) —
   add real-metadata regression tests in
   [`test_postfilter_levels.py`](../tests/test_postfilter_levels.py) using `_rule_by_id`
   against the loaded `python-rules.yaml`, mirroring
   `TestCompletenessRuleMaturityGrading` / `TestTestFileRulesStatusRamp`.
6. Run the scoped test path: `python3 -m pytest validation/tests/test_python_checks_<area>.py
   validation/tests/test_postfilter_levels.py validation/tests/test_rule_metadata_integrity.py`.

Adding or changing a Spectral, Gherkin, or yamllint rule follows the same rule-metadata
step (2–4 above), but the check logic itself lives in that engine's native config
(`linting/config/.spectral-r4.yaml`, `.gplintrc`, `.yamllint.yaml`) or adapter
(`validation/engines/*_adapter.py`), not in `python_checks/`.

## Regression testing

Unit tests verify one check in isolation. Regression testing verifies the framework's
end-to-end verdict against real CAMARA-style API specs on branches in
`camaraproject/ReleaseTest`, so a rule change doesn't silently start firing where it
shouldn't or stop firing where it should. Read
[`regression-testing.md`](regression-testing.md) before touching a rule that has an entry
in `rule-inventory.yaml`'s `tested_rules` map, and before recapturing any
`regression-expected.yaml` fixture.

## Documentation to update alongside a rule change

- `rule-inventory.yaml` — `tested_rules` mapping if a regression branch pins the rule;
  `status` if a `gap`/`manual` rule became `implemented`.
- A `faq.md` entry under [documentation/validation/](../../documentation/validation/) —
  only when the rule's severity is context-dependent or its short message alone isn't
  enough for a contributor to act (see [user-documentation-guidelines.md](user-documentation-guidelines.md)).
  This is public, user-facing documentation — do not put implementation detail there.
- [`severity-obligations.md`](../../documentation/validation/severity-obligations.md)
  only if the change affects the general severity model, not for an individual rule.

## Related

- [architecture-overview.md](architecture-overview.md) — how this implementation maps to the ReleaseManagement design documents
- [regression-testing.md](regression-testing.md)
- [`rules/README.md`](../rules/README.md) — rule ID assignment
- [`schemas/rule-metadata-schema.yaml`](../schemas/rule-metadata-schema.yaml)
