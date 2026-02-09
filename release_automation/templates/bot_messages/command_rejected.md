**❌ Command rejected: `/{{command}}` — State: `{{state}}`**
{{error_message}}

**Valid actions:**{{#state_snapshot_active}}<br>→ **Merge the Release PR to create a draft release**<br>→ `/discard-snapshot <reason>` — discard and return to `planned`{{/state_snapshot_active}}{{#state_draft_ready}}<br>→ **`/publish-release --confirm {{release_tag}}` — publish the release**<br>→ `/delete-draft <reason>` — delete draft and return to `planned`{{/state_draft_ready}}{{^state_snapshot_active}}{{^state_draft_ready}}<br>→ **`/create-snapshot` — create a release snapshot**{{/state_draft_ready}}{{/state_snapshot_active}}
