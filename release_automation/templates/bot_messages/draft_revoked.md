## Draft Release Deleted

**Release:** `{{release_tag}}`
**Deleted by:** @{{user}}

{{#reason}}
**Reason:** {{reason}}
{{/reason}}

### Cleanup Summary

- Draft release has been deleted
- Snapshot branch has been deleted
- Release-review branch has been renamed to `{{release_review_branch}}-discarded`
- Release tag has **not** been created

### State

The release is now back in `planned` state.

---

**Next steps:**
1. Make any needed changes to main branch
2. Run `/create-snapshot` to start the release process again
