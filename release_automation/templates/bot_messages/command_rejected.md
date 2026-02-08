**❌ Command rejected: `/{{command}}` — State: `{{state}}`**
{{error_message}}

**Valid actions:**
{{#state_snapshot_active}}
- Merge the Release PR to create a draft release
- `/discard-snapshot <reason>` — discard and return to `planned`
{{/state_snapshot_active}}
{{#state_draft_ready}}
- `/publish-release --confirm {{release_tag}}` — publish the release
- `/delete-draft <reason>` — delete draft and return to `planned`
{{/state_draft_ready}}
{{^state_snapshot_active}}{{^state_draft_ready}}
- `/create-snapshot` — create a release snapshot
{{/state_draft_ready}}{{/state_snapshot_active}}
