# Rule Metadata

Rule definitions mapping engine-level checks to framework-level applicability,
conditional severity, and fix guidance.

Schema: [../schemas/rule-metadata-schema.yaml](../schemas/rule-metadata-schema.yaml)

## Files

- `spectral-rules.yaml` — Spectral rule metadata
- `gherkin-rules.yaml` — gherkin-lint rule metadata
- `python-rules.yaml` — Python check rule metadata

## ID Assignment

Rule IDs use an engine prefix and a three-digit sequential number:

- `S-nnn`: Spectral rules (e.g. `S-001`, `S-042`)
- `P-nnn`: Python checks (e.g. `P-001`, `P-012`)
- `G-nnn`: gherkin-lint rules (e.g. `G-001`)
- `Y-nnn`: yamllint rules (e.g. `Y-001`)
- `M-nnn`: manual rules — documented but not machine-checkable

Once assigned, an ID is never reused even if the rule is retired.
