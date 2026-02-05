### 📦 Draft release created: `{{release_tag}}`

**State:** `draft-ready`{{#draft_release_url}} | **Draft:** {{draft_release_url}}{{/draft_release_url}}{{#src_commit_sha}} | **Base commit:** `{{src_commit_sha}}`{{/src_commit_sha}}

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

**Valid actions:**
- Publish the draft release in GitHub Releases
- `/delete-draft <reason>` to delete the draft and return to `planned`
