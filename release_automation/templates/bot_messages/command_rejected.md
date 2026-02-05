### ❌ Command rejected: `/{{command}}`

**Current state:** `{{state}}`

{{error_message}}

**Valid actions in `{{state}}` state:**
{{#state_snapshot_active}}
- Merge the Release PR to create a draft release
- `/discard-snapshot <reason>` to discard and return to `planned`
{{/state_snapshot_active}}
{{#state_draft_ready}}
- Publish the draft release in GitHub Releases
- `/delete-draft <reason>` to delete and return to `planned`
{{/state_draft_ready}}
{{^state_snapshot_active}}{{^state_draft_ready}}
- `/create-snapshot` to create a release snapshot
{{/state_draft_ready}}{{/state_snapshot_active}}

---

{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}
