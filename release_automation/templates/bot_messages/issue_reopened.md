## Issue Reopened Automatically

This Release Issue was automatically reopened because the release process is still active.

**Release:** `{{release_tag}}`
**State:** `{{state}}`

### Why This Happened

{{#state_snapshot_active}}
A snapshot is currently active. The issue cannot be closed while a snapshot exists.

Use `/discard-snapshot` to discard the snapshot before closing this issue.
{{/state_snapshot_active}}

{{#state_draft_ready}}
A draft release exists. The issue cannot be closed while a draft is pending.

Either:
- Publish the draft release to complete the release
- Use `/delete-draft` to delete the draft
{{/state_draft_ready}}

---

**To close this issue:**
1. Complete or cancel the release process
2. The issue will close automatically when the release reaches `published` or `cancelled` state
