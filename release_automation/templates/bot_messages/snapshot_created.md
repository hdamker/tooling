**✅ Snapshot created — State: `snapshot-active`**
**Release PR:** [#{{release_pr_number}}]({{release_pr_url}}) · Snapshot: [`{{snapshot_id}}`]({{snapshot_branch_url}}) · Review: [`{{release_review_branch}}`]({{release_review_branch_url}}) · Base: `{{src_commit_sha}}`

<details><summary>Release {{release_tag}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}})</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
</details>

**Valid actions:**
- Merge [Release PR]({{release_pr_url}}) to create draft release
- `/discard-snapshot <reason>` — discard and create a new snapshot from updated `main`
