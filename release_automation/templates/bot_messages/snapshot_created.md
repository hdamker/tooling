**✅ Snapshot created — State: `snapshot-active`**
**Release review PR:** [#{{release_pr_number}}]({{release_pr_url}}) · Snapshot: [`{{snapshot_id}}`]({{snapshot_branch_url}}){{#src_commit_sha}} · Base: `{{src_commit_sha}}`{{/src_commit_sha}}

<details><summary>Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

**Valid actions:**
- Merge [Release PR]({{release_pr_url}}) to create draft release
- `/discard-snapshot <reason>` — discard and create a new snapshot from updated `main`
