### 🚀 Release published: `{{release_tag}}`

**State:** `published`
**Release:** {{release_url}}
**Reference tag:** [`src/{{release_tag}}`]({{reference_tag_url}})

<details>
<summary>Release summary</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | {{api_version}} |
{{/apis}}

{{#commonalities_release}}**Dependencies:** {{commonalities_release}}{{#identity_consent_management_release}}, {{identity_consent_management_release}}{{/identity_consent_management_release}}{{/commonalities_release}}
</details>

{{#sync_pr_url}}
**Post-release sync:** {{sync_pr_url}} (requires Codeowner approval and merge)
{{/sync_pr_url}}

**Valid actions:** None (release is published).

_This Release Issue will be closed automatically._
