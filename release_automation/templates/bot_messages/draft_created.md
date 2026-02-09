**📦 Draft release created — State: `draft-ready`**
Triggered by merge of [Release PR #{{release_pr_number}}]({{release_pr_url}}).
**Draft release:** [`{{release_tag}}`]({{draft_release_url}})

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

**Valid actions:**<br>→ **`/publish-release --confirm {{release_tag}}` — publish the release**<br>→ `/delete-draft <reason>` — delete the draft and return to `planned`
