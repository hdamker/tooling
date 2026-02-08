**🚀 Release published — State: `published`**
Release published. This issue will be closed automatically.
**Release:** [`{{release_tag}}`]({{release_url}}) · Post-release sync PR: [#{{sync_pr_number}}]({{sync_pr_url}}) (requires codeowner merge)

<details><summary><b>Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>
