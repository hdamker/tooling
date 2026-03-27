**🚀 Release published — State: `published`**
Release published.{{#has_sync_pr}} This issue will be closed automatically.{{/has_sync_pr}}{{^has_sync_pr}} This issue remains open — manual follow-up required.{{/has_sync_pr}}
**Release:** [`{{release_tag}}`]({{release_url}}){{#has_sync_pr}} · Post-release sync PR: [#{{sync_pr_number}}]({{sync_pr_url}}) (requires codeowner merge){{/has_sync_pr}}
{{#has_publish_warnings}}
⚠️ **Post-release warnings:** {{publish_warnings}} ([view log]({{workflow_run_url}}))
{{/has_publish_warnings}}

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>
