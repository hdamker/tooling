### ❌ Snapshot creation failed (state unchanged: `planned`)

**Release:** `{{release_tag}}`

{{#error_message}}
```
{{error_message}}
```
{{/error_message}}

{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}

**Valid actions:**
- Fix the issue on `main` branch
- Run `/create-snapshot` to try again
