# Architecture overview: design documents to implementation

Maps the ReleaseManagement design documents for CAMARA Validation to where each concept
lives in this repository's implementation. Use this as a bridge, not a replacement for
either side — read the linked design section for *why*, and the linked source for the
current *how*.

Design source of truth:

- [Validation Framework — Requirements](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/SupportingDocuments/CAMARA-Validation-Framework-Requirements.md)
- [Validation Framework — Detailed Design](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/SupportingDocuments/CAMARA-Validation-Framework-Detailed-Design.md)

Both documents may move ahead of the current implementation; where they disagree with the
code, treat the code as current state and the design docs as intent — file a gap rather
than assuming either is wrong.

## Pipeline stages

| Design concept | Design doc section | Implementation |
|---|---|---|
| Rule metadata model | Detailed Design §1 | `validation/rules/*-rules.yaml`, schema in `validation/schemas/rule-metadata-schema.yaml` |
| Condition evaluation (applicability, conditional level) | Detailed Design §1.2; Requirements §2.2 | `validation/postfilter/condition_evaluator.py`, `validation/postfilter/level_resolver.py` |
| Execution contexts (per-repo / per-API) | Requirements §2.3 | `validation/context/context_builder.py` → `ValidationContext` / `ApiContext` |
| Check inventory across engines | Detailed Design §2; Requirements §4 | `validation/rules/rule-inventory.yaml` (registry) plus each engine's own rule file |
| Bundling pipeline (`$ref` resolution) | Detailed Design §3; Requirements §6 | `validation/bundling/` |
| Rule architecture / processing model | Requirements §5 | `validation/orchestrator.py` (chains context → engines → post-filter → output) |
| Artifact and findings surfacing | Detailed Design §4; Requirements §7–8 | `validation/output/` (annotations, Check Run, PR comment, commit status, workflow summary, diagnostics artifact) |
| Caller workflow / GitHub App / token resolution | Detailed Design §5; Requirements §9 | `validation/workflows/validation-caller.yml` (template consumed by API repos), `.github/workflows/validation.yml` (this repo's own run), `validation/config/config_gate.py` |
| Rollout sequencing across API repos | Detailed Design §6 | outside this repo — the caller workflow installed per API repository |

## The four use-case audiences

Requirements §1 defines five use-case groups; each has a corresponding piece of this
implementation and documentation, not just the pipeline above:

| Audience | Requirements | Where they land here |
|---|---|---|
| Contributor | §1.1 | [documentation/validation/](../../documentation/validation/) (task pages), `faq.md` |
| Codeowner | §1.2 | [documentation/validation/severity-obligations.md](../../documentation/validation/severity-obligations.md) |
| Release Automation | §1.3 | integration points in `validation/config/config_gate.py` and the reusable workflow's `release-automation` trigger type |
| Rule developer | §1.4 | [contributor-guide.md](contributor-guide.md) |
| CAMARA Admin | §1.5 | `.github/workflows/`, App installation/permissions (Detailed Design §5.2, §5.4) |

## Rule metadata: the field vocabulary

Requirements §2.2 and Detailed Design §1 define the rule model in the abstract
(`applicability`, `conditional_level`, condition fields). The concrete field vocabulary
and how it is evaluated is authoritative in the schema and evaluator, not the design
docs — [`rule-metadata-schema.yaml`](../schemas/rule-metadata-schema.yaml) and
[`condition_evaluator.py`](../postfilter/condition_evaluator.py). When the two disagree
on a specific field's allowed values, the schema wins; file a design-doc update rather
than reinterpreting the schema.

## Why this split exists

The design documents describe intent, tradeoffs, and rejected alternatives — useful when
deciding *whether* to change something. The code and its own docs
([contributor-guide.md](contributor-guide.md), [regression-testing.md](regression-testing.md))
describe the current, buildable state — what to change and how to verify it. Keeping them
separate means a design discussion doesn't need a PR to this repository, and a
same-shape rule addition doesn't need a design-document round-trip.

## Related

- [contributor-guide.md](contributor-guide.md)
- [documentation/validation/severity-obligations.md](../../documentation/validation/severity-obligations.md)
- [regression-testing.md](regression-testing.md)
- [`rules/README.md`](../rules/README.md)
