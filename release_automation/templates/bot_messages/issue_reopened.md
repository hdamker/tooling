**🔄 Issue reopened — State: `{{state}}`**
{{#state_snapshot_active}}
This issue is required while a snapshot is active — release commands are managed through this issue.
{{/state_snapshot_active}}
{{#state_draft_ready}}
This issue is required while a draft release exists — release commands are managed through this issue.
{{/state_draft_ready}}
{{#state_snapshot_active}}
**Release PR:** [#{{release_pr_number}}]({{release_pr_url}})
{{/state_snapshot_active}}
{{#state_draft_ready}}
**Draft release:** [`{{release_tag}}`]({{draft_release_url}})
{{/state_draft_ready}}

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

**Valid actions:**{{#state_snapshot_active}}<br>→ **Merge [Release PR]({{release_pr_url}}) to create draft release**<br>→ `/discard-snapshot <reason>` — discard and return to `planned`{{/state_snapshot_active}}{{#state_draft_ready}}<br>→ **`/publish-release --confirm {{release_tag}}` — publish the release**<br>→ `/delete-draft <reason>` — delete draft and return to `planned`{{/state_draft_ready}}

The issue closes automatically when the release is published.
