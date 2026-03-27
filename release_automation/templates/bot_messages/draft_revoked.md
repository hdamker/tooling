**🗑️ Draft deleted — State: `planned`**
{{#has_reason}}**Reason:** {{reason}}{{/has_reason}}
**Preserved:** [`{{release_review_branch}}`]({{release_review_branch_url}}) · **Deleted:** draft release, snapshot branch

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

**Valid actions:**<br>→ **`/create-snapshot` — new snapshot from updated `main`**
