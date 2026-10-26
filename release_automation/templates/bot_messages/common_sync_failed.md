**⚠️ Common file sync failed**
Could not sync `code/common/` files from Commonalities `{{commonalities_release}}`: the release tag may not exist yet.

The `/create-snapshot` command remains blocked until common files are in sync. Once the Commonalities release is published, run the sync again: `/sync-issue` here, the CAMARA Release Automation workflow with action `sync-issue` on `{{base_branch}}` (Actions, Run workflow), or a push to `release-plan.yaml` on `{{base_branch}}`.

{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}
