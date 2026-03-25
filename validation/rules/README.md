# Rule Metadata

Rule definitions mapping engine-level checks to framework-level applicability,
conditional severity, and fix guidance.

Schema: [../schemas/rule-metadata-schema.yaml](../schemas/rule-metadata-schema.yaml)

## Files

- `spectral-rules.yaml` — Spectral rule metadata (WP-06.14)
- `gherkin-rules.yaml` — gherkin-lint rule metadata (WP-06.14)
- `python-rules.yaml` — Python check rule metadata (WP-06.14)

## ID Assignment

Rule IDs are three-digit, zero-padded, sequentially assigned:

- `001`–`099`: Spectral rules
- `100`–`149`: gherkin-lint rules
- `150`–`199`: Python checks
- `200`+: reserved for future engines

Once assigned, an ID is never reused even if the rule is retired.
