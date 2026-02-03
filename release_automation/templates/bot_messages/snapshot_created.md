## Snapshot Created

**Release:** `{{release_tag}}`{{#meta_release}} ({{meta_release}}){{/meta_release}}
**Snapshot ID:** `{{snapshot_id}}`
**State:** `{{state}}`

### Created Branches

| Branch | Purpose |
|--------|---------|
| `{{snapshot_branch}}` | Contains transformed API definitions |
| `{{release_review_branch}}` | For review changes before merge |

### Release PR

{{#release_pr_url}}
**PR:** {{release_pr_url}}

Review the Release PR and merge when ready to create a draft release.
{{/release_pr_url}}
{{^release_pr_url}}
*Release PR creation pending...*
{{/release_pr_url}}

### API Versions

{{#apis}}
- **{{api_name}}**: `{{api_version}}`
{{/apis}}

---

**Next steps:**
1. Review the Release PR
2. Merge to create a draft release
3. Publish the draft release when ready

Use `/discard-snapshot` to discard this snapshot and start over.
