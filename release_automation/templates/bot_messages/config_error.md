### ❌ Configuration error

**Command:** `/{{command}}`

```
{{error_message}}
```

{{#is_missing_file}}
**How to fix:**
1. Create `release-plan.yaml` in the repository root
2. See the [release-plan.yaml reference](documentation/SupportingDocuments/release-plan-template.yaml)
3. Required fields: `repository.target_release_tag`, `repository.target_release_type`
4. Commit and push to `main`, then run the command again
{{/is_missing_file}}

{{#is_malformed_yaml}}
**How to fix:**
1. Fix the YAML syntax in `release-plan.yaml`
2. Common issues: incorrect indentation (use 2 spaces), missing colons, unquoted special characters
3. Validate with your usual YAML validation tooling
4. Commit and push the fix, then run the command again
{{/is_malformed_yaml}}

{{#is_missing_field}}
**How to fix:**
1. Add the missing field to `release-plan.yaml`:
   ```yaml
   repository:
     target_release_tag: r4.1
     target_release_type: initial
   ```
2. Commit and push the fix, then run the command again
{{/is_missing_field}}

---

{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}
