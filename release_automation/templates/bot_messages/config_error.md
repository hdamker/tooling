**❌ Configuration error**

```
{{error_message}}
```

{{#is_missing_file}}
Fix on `main`: create `release-plan.yaml` in the repository root. See the [release-plan.yaml reference](documentation/SupportingDocuments/release-plan-template.yaml). Required fields: `repository.target_release_tag`, `repository.target_release_type`.
{{/is_missing_file}}
{{#is_malformed_yaml}}
Fix on `main`: correct the YAML syntax in `release-plan.yaml`. Common issues: incorrect indentation (use 2 spaces), missing colons, unquoted special characters.
{{/is_malformed_yaml}}
{{#is_missing_field}}
Fix on `main`: add the missing field to `release-plan.yaml`. Required: `repository.target_release_tag`, `repository.target_release_type`.
{{/is_missing_field}}
{{#is_release_line}}
A cycle with a `maintenance/rX` branch is released from that branch only. Set `target_release_tag` in `release-plan.yaml` on `{{base_branch}}` to a tag of its own line.
{{/is_release_line}}

{{#release_plan_url}}[`release-plan.yaml`]({{release_plan_url}}){{/release_plan_url}}{{#workflow_run_url}} · [View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}
