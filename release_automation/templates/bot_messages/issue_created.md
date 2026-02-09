**📋 Release issue created — State: `planned`**
{{#trigger_workflow_dispatch}}
Created via workflow dispatch from [`release-plan.yaml`]({{release_plan_url}}).
{{/trigger_workflow_dispatch}}
{{#trigger_issue_close}}
Created to replace closed [#{{closed_issue_number}}]({{closed_issue_url}}).
{{/trigger_issue_close}}
{{#trigger_release_plan_change}}
Created after [`release-plan.yaml`]({{release_plan_url}}) update (PR [#{{trigger_pr_number}}]({{trigger_pr_url}})).
{{/trigger_release_plan_change}}

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

**Valid actions (post a comment):**<br>→ **`/create-snapshot` — begin the release process**
