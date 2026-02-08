**⚠️ Confirmation required — State: `draft-ready`**
Publication requires explicit confirmation. Copy/paste: `/publish-release --confirm {{release_tag}}`. Confirm tag must match the draft release tag.
**Draft release:** [`{{release_tag}}`]({{draft_release_url}}) · Base: `{{src_commit_sha_short}}`

<details><summary>Release {{release_tag}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}})</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
</details>

**Valid actions:**
- `/publish-release --confirm {{release_tag}}` — publish the release
- `/delete-draft <reason>` — delete draft and return to `planned`
