### ⚠️ Confirmation required: `/publish-release`

**State:** `draft-ready`
**Draft release:** [`{{release_tag}}`]({{draft_release_url}})
**Base commit:** `{{src_commit_sha_short}}`

To publish this release, copy and run:
```text
/publish-release --confirm {{release_tag}}
```

<details>
<summary>Release configuration</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | {{api_version}} |
{{/apis}}

{{#commonalities_release}}**Dependencies:** {{commonalities_release}}{{#identity_consent_management_release}}, {{identity_consent_management_release}}{{/identity_consent_management_release}}{{/commonalities_release}}
</details>

**Valid actions:**
- `/publish-release --confirm {{release_tag}}` — publish the release
- `/delete-draft <reason>` — delete draft and return to PLANNED
