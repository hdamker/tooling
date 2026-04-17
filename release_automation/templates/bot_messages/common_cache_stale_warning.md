**⚠️ Common file cache stale — State: `{{state}}`**
{{common_cache_details}}

The cached Commonalities files in `code/common/` do not match `{{commonalities_release}}` declared in `release-plan.yaml`.

{{#has_common_sync_pr}}[Sync PR]({{common_sync_pr_url}}) is pending — merge it when ready to update the common files on main.{{/has_common_sync_pr}}
{{^has_common_sync_pr}}Run `workflow_dispatch` to trigger sync, or `/discard-snapshot` to return to planned state.{{/has_common_sync_pr}}

{{#state_snapshot_active}}_The active snapshot uses the common files from when it was created. To pick up updated files, discard the snapshot and create a new one after merging the sync PR._{{/state_snapshot_active}}
{{#state_draft_ready}}_The draft release uses the common files from when the snapshot was created. Consider whether the common files need updating before publishing._{{/state_draft_ready}}
