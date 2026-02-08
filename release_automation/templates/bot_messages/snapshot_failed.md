**❌ Snapshot failed — State: `planned`**
{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}

{{#error_message}}
```
{{error_message}}
```
{{/error_message}}

**Valid actions:**
- Fix issues on `main`
- `/create-snapshot` — retry after fixes are merged
