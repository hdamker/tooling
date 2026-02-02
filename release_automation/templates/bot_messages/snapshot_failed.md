## Snapshot Creation Failed

**Release:** `{{release_tag}}`
**State:** `{{state}}`

### Errors

{{#errors}}
- {{.}}
{{/errors}}
{{#error_message}}
- {{error_message}}
{{/error_message}}

{{#warnings}}
### Warnings

{{#warnings}}
- {{.}}
{{/warnings}}
{{/warnings}}

### Configuration

```yaml
target_release_tag: {{release_tag}}
target_release_type: {{release_type}}
```

---

**How to fix:**
1. Address the errors listed above
2. Update `release-plan.yaml` if needed
3. Push fixes to main branch
4. Run `/create-snapshot` again
