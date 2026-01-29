## Snapshot Discarded

**Release:** `{{release_tag}}`
**Snapshot ID:** `{{snapshot_id}}`
**Discarded by:** @{{user}}

{{#reason}}
**Reason:** {{reason}}
{{/reason}}

### Cleanup Summary

- Snapshot branch `{{snapshot_branch}}` has been deleted
- Release PR has been closed
- Release-review branch `{{release_review_branch}}` has been **preserved** for reference

### State

The release is now back in `planned` state.

---

**Next steps:**
1. Make any needed changes to main branch
2. Run `/create-snapshot` to create a new snapshot
