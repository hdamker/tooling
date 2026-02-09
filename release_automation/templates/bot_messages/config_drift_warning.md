**⚠️ Configuration drift — State: `{{state}}`**
[`release-plan.yaml`]({{release_plan_url}}) was updated on main{{#trigger_pr_number}} (PR [#{{trigger_pr_number}}]({{trigger_pr_url}})){{/trigger_pr_number}} but the change is not reflected in the active {{#state_snapshot_active}}snapshot{{/state_snapshot_active}}{{#state_draft_ready}}draft release{{/state_draft_ready}}.

<details><summary><b>Snapshot Configuration:</b> Release {{release_tag}}{{#short_type}} ({{short_type}}{{#has_meta_release}}, {{meta_release}}{{/has_meta_release}}){{/short_type}}</summary>

| API | Version |
|-----|---------|
{{#apis}}
| {{api_name}} | `{{api_version}}` |
{{/apis}}

{{#commonalities_release}}**Dependencies:** Commonalities {{commonalities_release}}{{#identity_consent_management_release}}, ICM {{identity_consent_management_release}}{{/identity_consent_management_release}}
{{/commonalities_release}}
</details>

{{#state_snapshot_active}}
**Valid actions (post a comment):**<br>→ `/discard-snapshot <reason>` — discard snapshot, then `/create-snapshot` to pick up the new configuration<br>→ Merge [Release PR]({{release_pr_url}}) — continue to create the release with the snapshot configuration

_To apply the updated `release-plan.yaml`, discard the current snapshot and create a new one. To continue with the existing snapshot configuration, merge the Release PR._
{{/state_snapshot_active}}
{{#state_draft_ready}}
**Valid actions (post a comment):**<br>→ `/delete-draft <reason>` — delete draft, then `/create-snapshot` to pick up the new configuration<br>→ `/publish-release --confirm {{release_tag}}` — publish the release with the snapshot configuration

_To apply the updated `release-plan.yaml`, delete the draft and create a new snapshot. To continue with the existing snapshot configuration, publish the release._
{{/state_draft_ready}}
