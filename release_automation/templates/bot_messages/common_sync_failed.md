**⚠️ Common file sync failed**
Could not sync `code/common/` files from Commonalities `{{commonalities_release}}`: the release tag may not exist yet.

The `/create-snapshot` command remains blocked until common files are in sync. Once the Commonalities release is published, trigger sync via `workflow_dispatch` or push to `release-plan.yaml`.

{{#workflow_run_url}}[View workflow logs]({{workflow_run_url}}){{/workflow_run_url}}
