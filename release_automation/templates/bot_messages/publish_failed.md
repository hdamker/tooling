### ❌ Publication failed: `/publish-release`

**State:** `draft-ready` (unchanged)

{{#error_message}}
```
{{error_message}}
```
{{/error_message}}
{{^error_message}}
Unexpected error — check the workflow logs for details.
{{/error_message}}

**Valid actions:**
- Check [workflow logs]({{workflow_run_url}}) for details
- Retry: `/publish-release --confirm {{release_tag}}`
- `/delete-draft <reason>` — delete draft if corrupted and start over
