**❌ Command failed: `/{{command}}` — State: `{{state}}`**
{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}

{{#error_message}}
> {{error_message}}
{{/error_message}}

Fix the cause on `{{base_branch}}` and retry `/{{command}}`, or contact Release Management for unexpected errors.

{{valid_actions}}
