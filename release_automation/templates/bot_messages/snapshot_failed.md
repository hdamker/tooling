## Snapshot Creation Failed

**Release:** `{{release_tag}}`
**State:** `{{state}}`

### Error

{{#error_message}}
{{error_message}}
{{/error_message}}

**Workflow run:** [View logs]({{workflow_run_url}})

---

**How to fix:**
1. Address the error listed above
2. Update `release-plan.yaml` if needed
3. Push fixes to main branch
4. Run `/create-snapshot` again
