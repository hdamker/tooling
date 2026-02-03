## Draft Release Created

**Release:** `{{release_tag}}`{{#meta_release}} ({{meta_release}}){{/meta_release}}
**State:** `draft-ready`

### Draft Release

{{#draft_release_url}}
**URL:** {{draft_release_url}}
{{/draft_release_url}}

The Release PR has been merged and a draft release has been created.

### API Versions

{{#apis}}
- **{{api_name}}**: `{{api_version}}`
{{/apis}}

---

**Next steps:**
1. Review the draft release notes
2. Publish the release when ready

Use `/delete-draft` to delete the draft and return to `planned` state.
