### ✅ Snapshot created: `{{snapshot_id}}`

**State:** `snapshot-active`{{#release_pr_url}} | **Release PR:** {{release_pr_url}}{{/release_pr_url}}{{#src_commit_sha}} | **Base commit:** `{{src_commit_sha}}`{{/src_commit_sha}}

<details>
<summary>Release configuration</summary>

**APIs:**
| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}{{/commonalities_release}}

**Branches:**
- Snapshot: `{{snapshot_branch}}`
- Review: `{{release_review_branch}}`
</details>

**Valid actions:**
- Review and merge {{#release_pr_url}}[Release PR]({{release_pr_url}}){{/release_pr_url}}{{^release_pr_url}}Release PR{{/release_pr_url}} to create draft release
- `/discard-snapshot <reason>` to discard and create a new snapshot from updated `main`
