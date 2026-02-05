### 🗑️ Snapshot discarded: `{{snapshot_id}}`

**State:** `snapshot-active` → `planned`{{#reason}} | **Reason:** {{reason}}{{/reason}}

**Cleanup:**
- Snapshot branch `{{snapshot_branch}}` deleted
- Release PR closed
- Review branch `{{release_review_branch}}` preserved for reference

**Valid actions:**
- `/create-snapshot` to create a new snapshot from updated `main`
