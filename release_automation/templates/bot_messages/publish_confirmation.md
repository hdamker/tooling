### 📋 Confirm publication: `{{release_tag}}`

**State:** `draft-ready`

<details>
<summary>Release configuration</summary>

**APIs:**
| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}{{/commonalities_release}}
</details>

**To publish this release, use:**
```
/publish-release --confirm {{release_tag}}
```

**Valid actions:**
- `/publish-release --confirm {{release_tag}}` to publish the release
- `/delete-draft <reason>` to delete the draft and return to `planned`
