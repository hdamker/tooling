**❌ Publication failed — State: `draft-ready`**
{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}

{{#error_message}}
```
{{error_message}}
```
{{/error_message}}

**Valid actions:**
- Retry: `/publish-release --confirm {{release_tag}}`
- `/delete-draft <reason>` — delete draft and start over
