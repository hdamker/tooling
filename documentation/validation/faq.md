# CAMARA Validation FAQ

This page explains common validation problems that need extra context. It is not a full rule catalog — for the complete list of validation results, open the workflow summary linked from the CAMARA Validation check on a pull request.

Each entry is a collapsible block under its category. Expand it to read the explanation. The rule code in square brackets is shown on the entry summary, so it stays searchable on this page; quoting it when you ask for support also helps others identify the same problem quickly. The validation workflow summary links directly to the relevant entry's anchor.

## API definition problems

<a name="s-002-get-delete-request-body"></a>
<details>
<summary>[S-002] Why is a GET or DELETE request body rejected?</summary>

Applies to: `[S-002] GET / DELETE must not have a request body`

GET and DELETE operations must not declare a request body. The information that a body would carry should be expressed differently:

- For GET, use path parameters or query parameters.
- For DELETE, use path parameters; if a body is genuinely required to express what is being deleted, choose a different method.

**What you do:** open the API definition file shown in the message and remove the `requestBody` from the GET or DELETE operation, or change the operation to a method that accepts a body.

</details>

<a name="s-222-operation-tag"></a>
<details>
<summary>[S-222] Why does my operation tag need to be listed globally?</summary>

Applies to: `[S-222] Operation tag not defined in tags list`

A tag used on an operation must also be declared in the OpenAPI document's top-level `tags` list. The global list is what describes the tag for readers and tooling; an undeclared tag breaks documentation rendering and grouping.

**What you do:** either add the missing tag to the document's top-level `tags` section with a description, or correct the tag on the operation to one that is already declared globally.

</details>

<a name="s-211-unused-component"></a>
<details>
<summary>[S-211] Why is a component reported as unused?</summary>

Applies to: `[S-211] Component may be unused`

The check follows regular OpenAPI references and local `discriminator.mapping` targets. It reports a warning when a reusable component is not reached through either mechanism.

**What you do:** remove the obsolete component, or add the missing `$ref` or discriminator mapping that connects it to the API definition.

</details>

<a name="p-037-yaml-parser-conformance"></a>
<details>
<summary>[P-037] Why does YAML parser conformance fail when yamllint passes?</summary>

Applies to: `[P-037] OpenAPI YAML fails parser conformance`

This rule parses each OpenAPI YAML definition with a YAML parser used by
common JavaScript tooling. It can report a problem even when yamllint, PyYAML,
or Spectral accepted the same file, because those tools do not all use the same
YAML parser or the same strictness level.

The message includes the first parser error reported for the file, with the
source line and column. For example, `deficient indentation` usually means that
a construct such as a flow mapping or quoted multiline scalar is indented in a
way that tolerant parsers accepted but stricter YAML parsers reject.

YAML flow style is sometimes called "JSON-like" because it uses `{}`, `[]`,
colons, and commas. It is still YAML syntax, not strict JSON syntax. For
example, YAML flow collections can allow constructs that JSON does not, while
multiline flow collections still interact with YAML indentation rules. To avoid
parser portability problems in OpenAPI examples, prefer plain block-style YAML
over JSON-like flow-style mappings or sequences.

**What you do:** open the reported API definition file at the line shown in the
message and rewrite the YAML in plain block style. Keep the data unchanged; the
fix is normally just formatting the affected mapping, sequence, or scalar so
stricter YAML parsers can load it.

</details>

## Test definition problems

<a name="p-006-missing-test-files"></a>
<details>
<summary>[P-006] Why are missing test files sometimes a hint, warning, or error?</summary>

Applies to: `[P-006] Missing test definition file for API`

The severity of this rule depends on the API's release type and maturity:

- For alpha releases, test files are optional. The rule reports a hint.
- For a **0.x** API (version below 1.0.0) targeting a release candidate or public release, the rule reports a **warning**.
- For a **stable** (≥1.0.0) API targeting a release candidate or public release, the rule reports an **error**.

**What you do:** add the expected test definition file under `code/Test_definitions/`. The CAMARA Testing Guidelines describe the expected file layout. Address this before the next release type, even when the rule is currently a hint or warning.

</details>

## Release-plan problems

<a name="p-002-api-file-exists"></a>
<details>
<summary>[P-002] Why can a draft API be listed before the API file exists?</summary>

Applies to: `[P-002] API definition file must match release-plan api_name`

`release-plan.yaml` can list an API as `target_api_status: draft` before the API definition file exists in `code/API_definitions/`. This is the intended way to declare a new API: list it as `draft` first, then add the file later. The rule reports this as a **hint** while the entry is `draft`, so the missing file does not block the run.

If the same entry is listed at any other status (`alpha`, `rc`, `public`, `stable`, ...) the rule reports an **error**, because at those statuses the API definition file is required.

**What you do:** if you are starting a new API, keep the entry at `target_api_status: draft` until the API definition file is committed. Promote the status to `alpha` (or higher) only when the file is present in `code/API_definitions/` with a matching filename.

</details>

<a name="p-022-release-plan-exclusivity"></a>
<details>
<summary>[P-022] Why must <code>release-plan.yaml</code> change in its own pull request?</summary>

Applies to: `[P-022] release-plan.yaml must change in its own PR`

`release-plan.yaml` declares release intent. Mixing release-intent changes with API or test definition changes makes review and validation ambiguous: a reviewer cannot tell which API change goes with which release intent.

**What you do:** split the pull request. Keep `release-plan.yaml` changes in a dedicated pull request, and move the other listed files to a separate pull request.

</details>

## Commonalities and shared files

<a name="p-020-cloudevent-ref"></a>
<details>
<summary>[P-020] Why should CloudEvent use <code>$ref</code> instead of an inline schema?</summary>

Applies to: `[P-020] CloudEvent should be $ref, not inline`

Subscription APIs should reuse the shared CloudEvent schema from `CAMARA_event_common.yaml` rather than maintaining a local inline copy. A `$ref` keeps the API in step with the shared definition; an inline copy drifts over time and produces inconsistent client behaviour across APIs.

**What you do:** replace the local CloudEvent schema with `$ref: './CAMARA_event_common.yaml#/components/schemas/CloudEvent'`. Where you also need an API-specific event type, use `allOf` combining the `$ref` with an API-specific `ApiEventType` schema. The implicit-events API template in the Commonalities artifacts directory shows the recommended pattern.

</details>

<a name="p-021-common-cache-sync"></a>
<details>
<summary>[P-021] Why is <code>code/common/</code> missing or out of sync?</summary>

Applies to: `[P-021] code/common/ is missing or out of sync`

`code/common/` contains cached copies of shared schemas owned by the [Commonalities](https://github.com/camaraproject/Commonalities) repository. They are managed by automation; if the cache drifts from what the API definitions and the active Commonalities release require, this rule fires.

**What you do:** the recovery depends on what is wrong:

- If your pull request manually edits `code/common/`, revert those edits. The cached files will be re-synchronised by automation.
- If your branch is missing files that should be present, merge `main` into your branch — `main` carries the latest synchronised files.
- If `main` is also behind, merge the auto-created sync pull request, or dispatch the release-automation sync workflow on the repository.

A real issue with the *content* of a cached common file is fixed upstream in [Commonalities](https://github.com/camaraproject/Commonalities), not in the API repository.

This rule is a warning by default, and an error during release automation runs.

</details>

<a name="p-026-p-027-info-description-mandatory"></a>
<details>
<summary>[P-026]/[P-027] What should I do about missing or drifted mandatory <code>info.description</code> blocks?</summary>

Applies to: `[P-026] Mandatory info.description template missing`, `[P-027] info.description mandatory template content drift`

CAMARA API specifications must include mandatory `info.description` text blocks from the API Design Guide and the Identity and Consent Management profile. Starting with Commonalities r4.3, the mandatory text blocks are synchronized into each API repository as `code/common/info-description-templates.yaml`. The API definition marks each mandatory text block with `<!-- BEGIN: ... -->` and `<!-- END: ... -->` delimiters, and validation compares the delimited content with that synced `code/common/info-description-templates.yaml` file.

The severity depends on the API status in `release-plan.yaml`:

- `target_api_status: alpha`: P-026/P-027 are hints. The blocks should be added or corrected before the API progresses to rc.
- `target_api_status: rc`: P-026/P-027 are warnings. The API can still use the r4.3 sync PR to receive the `code/common/info-description-templates.yaml` file, but codeowners should fix the warnings before the rc pre-release.
- `target_api_status: public`: P-026/P-027 are errors. The API is expected to contain the mandatory blocks verbatim; validation fails and will block the release until they are fixed.

**What you do:** on main, copy the reported template from `code/common/info-description-templates.yaml` into the affected API file's `info.description`, keeping the BEGIN/END delimiters and the copied text unchanged. For P-027, replace the whole drifted delimited block with the matching block from the local `code/common/info-description-templates.yaml` file.

If the finding appears when merging the automated Commonalities r4.3 sync PR itself, first check the API status in `release-plan.yaml`. For alpha or rc APIs, merge the sync PR so the repository receives the required `code/common/info-description-templates.yaml`, then open a follow-up API PR to copy the common mandatory blocks into the API's `info.description`. For an API already declared `public`, P-026/P-027 are reported as errors and block the release. Fix the missing or drifted blocks before the release. If the API is in fact not yet ready for a public release, one option is to set `target_api_status` back to `rc` in `release-plan.yaml`, which lowers the findings to warnings.

Do not edit `code/common/info-description-templates.yaml` in the API repository. That file is owned by Commonalities and updated by the common-file synchronization.

</details>

<a name="p-040-component-renaming-conflict"></a>
<details>
<summary>[P-040] Why does bundling rename a component I didn't touch?</summary>

Applies to: `[P-040] Component-renaming collision during bundling`

Two different components — one defined locally, one pulled in from a common file via an
external `$ref` — are competing for the same name with different content. When the spec is
bundled, the local definition keeps the name; the externally-referenced one is renamed to
`<Name>-2`, and every use site that resolved to it is silently repointed at the renamed copy.
This is not a bundler quirk to ignore: a reader of the bundled spec sees the wrong schema at
those use sites.

This only fires for a genuine conflict — same name, **different** content. A local component
that intentionally proxies a common one under the same name, with identical content, is not
flagged.

**What you do:** rename the *local* definition to a distinct, API-specific name — you can't
rename the common definition, since Commonalities owns it. If the local definition isn't
actually needed (it has no reason to diverge from the common one), delete it and reference the
common component directly instead.

</details>

## Related

- [Validation problem messages](problem-messages.md) — the shape of each message
- [Where to see validation results](where-to-see-results.md) — where messages appear in GitHub
- [Validation on pull requests](pull-requests.md) — what a contributor or codeowner does
- [Validation during snapshot creation](release-snapshots.md) — what happens at `/create-snapshot`
- [Validation on a Release PR](release-prs.md) — what changes on a Release PR
- [Bundled API definitions](bundled-api-definitions.md)
