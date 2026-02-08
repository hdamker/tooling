### 🔄 Issue reopened automatically

This issue was reopened because active release artifacts exist. The issue cannot be closed while a {{#state_snapshot_active}}snapshot{{/state_snapshot_active}}{{#state_draft_ready}}draft release{{/state_draft_ready}} is active.

**Current state:** `{{state}}`

**Valid actions:**
{{#state_snapshot_active}}
- Merge the Release PR to create a draft release
- `/discard-snapshot <reason>` to discard and return to `planned`
{{/state_snapshot_active}}
{{#state_draft_ready}}
- Publish the draft release in GitHub Releases
- `/delete-draft <reason>` to delete and return to `planned`
{{/state_draft_ready}}

The issue will close automatically when the release is published.
