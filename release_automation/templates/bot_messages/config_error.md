## Configuration Error

**Command:** `{{command}}`
**Requested by:** @{{user}}

### Error

**Type:** `{{error_type}}`

{{error_message}}

### How to Fix

{{#is_missing_file}}
1. Create `release-plan.yaml` in the repository root
2. Use the [template from ReleaseManagement](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/SupportingDocuments/release-plan-template.yaml)
3. Required fields:
   - `repository.target_release_tag` (e.g., `r4.1`)
   - `repository.target_release_type` (e.g., `initial`, `patch`, or `none`)
4. Commit and push to main branch
5. Run the command again
{{/is_missing_file}}

{{#is_malformed_yaml}}
1. Fix the YAML syntax in `release-plan.yaml`
2. Common issues:
   - Incorrect indentation (use 2 spaces)
   - Missing colons after keys
   - Unquoted special characters
3. Validate locally with an online YAML validator or `yaml-lint`
4. Commit and push the fix
5. Run the command again
{{/is_malformed_yaml}}

{{#is_missing_field}}
1. Add the missing field to `release-plan.yaml`
2. Required structure:
   ```yaml
   repository:
     target_release_tag: r4.1
     target_release_type: initial
   ```
3. Commit and push the fix
4. Run the command again
{{/is_missing_field}}

---

[View workflow run]({{workflow_run_url}}) | For help, see the [Release Documentation](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/README.md).
