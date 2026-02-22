"""
Issue manager for CAMARA release automation.

This module provides functionality for managing Release Issue content,
including updating reserved sections, maintaining snapshot history,
and generating standardized titles.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class SnapshotHistoryEntry:
    """
    Represents an entry in the snapshot history table.

    Note: HISTORY section is deferred to backlog (not MVP).
    This dataclass is preserved for future implementation.

    Attributes:
        snapshot_id: Unique identifier (e.g., "r4.1-abc1234")
        status: Either "Current" or "Discarded"
        created_at: ISO timestamp when snapshot was created
        discarded_at: ISO timestamp when discarded (if applicable)
        reason: Reason for discarding (if applicable)
        release_review_branch: The release-review branch name
    """
    snapshot_id: str
    status: str  # "Current" or "Discarded"
    created_at: str
    discarded_at: Optional[str] = None
    reason: Optional[str] = None
    release_review_branch: str = ""


class IssueManager:
    """
    Manages Release Issue content - updating reserved sections
    and generating standardized titles.

    Reserved sections in issue body are marked with HTML comments:
        <!-- BEGIN:SECTION_NAME -->
        content here
        <!-- END:SECTION_NAME -->

    Supported sections:
        - STATE: Current release state, timestamp, and active artifact links
        - CONFIG: Release configuration (APIs, dependencies)
        - ACTIONS: Valid actions for the current state

    Note: HISTORY section has been deferred to backlog (not MVP).
    The comment trail serves as the audit log.
    """

    # Pattern for matching sections (use .format(name=section_name))
    SECTION_PATTERN = r"<!-- BEGIN:{name} -->\n(.*?)\n<!-- END:{name} -->"

    # Release type display names for titles
    TYPE_DISPLAY_NAMES = {
        "pre-release-alpha": "alpha",
        "pre-release-rc": "RC",
        "public-release": "public",
        "public": "public",
        "maintenance-release": "maintenance",
        "none": "",
    }

    def update_section(self, body: str, section: str, content: str) -> str:
        """
        Update content between section markers in issue body.

        The section markers are:
            <!-- BEGIN:{section} -->
            {old content}
            <!-- END:{section} -->

        Args:
            body: The current issue body
            section: Section name (e.g., "STATE", "HISTORY", "CONFIG")
            content: New content to place between markers

        Returns:
            Updated issue body with new section content
        """
        pattern = self.SECTION_PATTERN.format(name=section)
        replacement = f"<!-- BEGIN:{section} -->\n{content}\n<!-- END:{section} -->"

        updated, count = re.subn(pattern, replacement, body, flags=re.DOTALL)

        if count == 0:
            # Section not found - return original body unchanged
            return body

        return updated

    def get_section_content(self, body: str, section: str) -> Optional[str]:
        """
        Extract the content of a section from the issue body.

        Args:
            body: The issue body
            section: Section name (e.g., "STATE", "HISTORY", "CONFIG")

        Returns:
            Section content if found, None otherwise
        """
        pattern = self.SECTION_PATTERN.format(name=section)
        match = re.search(pattern, body, flags=re.DOTALL)
        return match.group(1) if match else None

    def append_to_history(self, body: str, entry: SnapshotHistoryEntry) -> str:
        """
        Add a new entry to the snapshot history table.

        Note: HISTORY section is deferred to backlog (not MVP).
        This method is preserved for future implementation.

        The entry is inserted after the table header row.

        Args:
            body: The current issue body
            entry: Snapshot history entry to add

        Returns:
            Updated issue body with new history row
        """
        # Format the new row
        discarded = entry.discarded_at or "—"
        reason = entry.reason or "—"

        new_row = (
            f"| `{entry.snapshot_id}` | **{entry.status}** | "
            f"{entry.created_at} | {discarded} | {reason} | "
            f"`{entry.release_review_branch}` |"
        )

        # Find the HISTORY section and the table header
        # Table format:
        # | Snapshot | Status | Created | Discarded | Reason | Review Branch |
        # |----------|--------|---------|-----------|--------|---------------|
        # | ... rows ... |

        history_content = self.get_section_content(body, "HISTORY")
        if history_content is None:
            return body

        # Find the header separator line (|---...|) and insert after it
        lines = history_content.split('\n')
        insert_index = None

        for i, line in enumerate(lines):
            # Look for the separator line (contains |---|)
            if re.match(r'\s*\|[-|]+\|\s*$', line):
                insert_index = i + 1
                break

        if insert_index is None:
            # No table found, just append at the end
            new_content = history_content.rstrip() + '\n' + new_row
        else:
            # Insert the new row after the separator
            lines.insert(insert_index, new_row)
            new_content = '\n'.join(lines)

        return self.update_section(body, "HISTORY", new_content)

    def mark_snapshot_discarded(
        self,
        body: str,
        snapshot_id: str,
        reason: str
    ) -> str:
        """
        Update an existing snapshot entry from 'Current' to 'Discarded'.

        Note: HISTORY section is deferred to backlog (not MVP).
        This method is preserved for future implementation.

        Finds the row with the matching snapshot_id and updates:
        - Status: Current → Discarded
        - Discarded: — → current timestamp
        - Reason: — → provided reason

        Args:
            body: The current issue body
            snapshot_id: The snapshot ID to update
            reason: Reason for discarding

        Returns:
            Updated issue body with modified history row
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        # Pattern to match the specific row
        # | `snapshot_id` | **Current** | created_at | — | — | `branch` |
        pattern = (
            rf"\| `{re.escape(snapshot_id)}` \| \*\*Current\*\* \| "
            rf"([^|]+) \| — \| — \| ([^|]+) \|"
        )

        replacement = (
            f"| `{snapshot_id}` | Discarded | "
            f"\\1| {timestamp} | {reason} | \\2|"
        )

        return re.sub(pattern, replacement, body)

    def generate_title(
        self,
        release_tag: str,
        release_type: str,
        meta_release: Optional[str] = None
    ) -> str:
        """
        Generate a standardized issue title for a release.

        Format: "Release {tag} ({type}) — {meta_release}"

        Examples:
            - "Release r4.1 (RC) — Sync26"
            - "Release r4.1 (alpha)"
            - "Release r4.1 (public)"

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_type: Release type from release-plan.yaml
            meta_release: Optional meta-release name (e.g., "Sync26")

        Returns:
            Formatted issue title
        """
        title = f"Release {release_tag}"

        # Add type suffix if known
        type_display = self.TYPE_DISPLAY_NAMES.get(release_type, release_type)
        if type_display:
            title += f" ({type_display})"

        # Add meta-release if provided
        if meta_release:
            title += f" — {meta_release}"

        return title

    def should_update_title(
        self,
        current_title: str,
        release_plan: Dict[str, Any]
    ) -> bool:
        """
        Check if the issue title needs updating based on release-plan.yaml.

        Args:
            current_title: The current issue title
            release_plan: Parsed release-plan.yaml content

        Returns:
            True if title should be updated, False otherwise
        """
        repo_config = release_plan.get("repository", {})
        expected_title = self.generate_title(
            release_tag=repo_config.get("target_release_tag", ""),
            release_type=repo_config.get("target_release_type", ""),
            meta_release=repo_config.get("meta_release")
        )
        return current_title != expected_title

    def generate_state_section(
        self,
        state: str,
        snapshot_id: str = "",
        release_pr_url: str = "",
        draft_release_url: str = "",
        snapshot_branch_url: str = ""
    ) -> str:
        """
        Generate content for the STATE section.

        Args:
            state: Current release state (e.g., "planned", "snapshot-active")
            snapshot_id: Active snapshot ID (if any)
            release_pr_url: Release PR URL (if any)
            draft_release_url: Draft release URL (if any)
            snapshot_branch_url: URL to snapshot branch tree view (if any)

        Returns:
            Formatted state section content
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state_lower = state.lower().replace("_", "-")

        lines = [f"**State:** `{state_lower}` | **Last Updated:** {timestamp}"]

        # Add active artifact links based on state
        if state_lower == "snapshot-active" and snapshot_id:
            lines.append("")
            snapshot_link = f"[{snapshot_id}]({snapshot_branch_url})" if snapshot_branch_url else f"`{snapshot_id}`"
            lines.append(f"**Active snapshot:** {snapshot_link}")
            if release_pr_url:
                lines.append(f"**Release PR:** {release_pr_url}")

        elif state_lower == "draft-ready":
            if draft_release_url:
                lines.append("")
                lines.append(f"**Draft release:** {draft_release_url}")

        return "\n".join(lines)

    def generate_actions_section(self, state: str, release_pr_url: str = "", release_tag: str = "") -> str:
        """
        Generate content for the ACTIONS section showing valid actions.

        Args:
            state: Current release state
            release_pr_url: Release PR URL (for snapshot-active state)
            release_tag: Release tag (for draft-ready publish command)

        Returns:
            Formatted actions section content
        """
        state_lower = state.lower().replace("_", "-")

        if state_lower == "planned":
            return "**Valid actions:**<br>→ **`/create-snapshot` — begin the release process**"

        elif state_lower == "snapshot-active":
            pr_text = f"[Release PR]({release_pr_url})" if release_pr_url else "Release PR"
            return (
                f"**Valid actions:**<br>→ **Merge {pr_text} to create draft release**"
                "<br>→ `/discard-snapshot <reason>` — discard and return to `planned`"
            )

        elif state_lower == "draft-ready":
            tag_text = f" {release_tag}" if release_tag else ""
            return (
                f"**Valid actions:**<br>→ **`/publish-release --confirm{tag_text}` — publish the release**"
                "<br>→ `/delete-draft <reason>` — delete draft and return to `planned`"
            )

        elif state_lower == "not-planned":
            return (
                "**Valid actions:**<br>→ **Update `release-plan.yaml` with a planned release type to resume**"
                "<br>→ Close this issue — a new one will be created when a release is planned"
            )

        return ""

    def generate_config_section(
        self,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        commonalities_release: str = "",
        icm_release: str = ""
    ) -> str:
        """
        Generate content for the CONFIG section.

        Displays release configuration including:
        - APIs table with target and calculated versions
        - Dependencies (Commonalities, ICM)

        Args:
            release_plan: Parsed release-plan.yaml content
            api_versions: Dict mapping API name to calculated version
            commonalities_release: Required Commonalities version
            icm_release: Required ICM version

        Returns:
            Formatted config section content
        """
        lines = []

        # Add APIs table
        apis = release_plan.get("apis", [])
        if apis:
            lines.append("| API | Target | Calculated |")
            lines.append("|-----|--------|------------|")

            for api in apis:
                name = api.get("api_name", "unknown")
                target = api.get("target_api_version", "—")
                calculated = api_versions.get(name, "—")
                lines.append(f"| {name} | {target} | `{calculated}` |")

        # Add dependencies
        deps = []
        if commonalities_release:
            deps.append(f"Commonalities {commonalities_release}")
        if icm_release:
            deps.append(f"ICM {icm_release}")

        if deps:
            lines.append("")
            lines.append(f"**Dependencies:** {', '.join(deps)}")
        elif not apis:
            lines.append("_No APIs or dependencies configured_")

        return "\n".join(lines)

    def generate_issue_body_template(
        self,
        release_tag: str,
        release_type: str,
        meta_release: Optional[str] = None
    ) -> str:
        """
        Generate a complete issue body template for a new Release Issue.

        This creates the initial structure with all reserved sections.
        The HISTORY section has been deferred to backlog (not MVP).

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_type: Release type
            meta_release: Optional meta-release name

        Returns:
            Complete issue body with empty sections
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return f"""<!-- release-automation:workflow-owned -->
<!-- release-automation:release-tag:{release_tag} -->

### Release Highlights

_Add release highlights here before creating snapshot._

---
<!-- AUTOMATION MANAGED SECTION - DO NOT EDIT BELOW THIS LINE -->

### Release Status
<!-- BEGIN:STATE -->
**State:** `planned` | **Last Updated:** {timestamp}
<!-- END:STATE -->

<!-- BEGIN:CONFIG -->
_Configuration from release-plan.yaml will be shown here._
<!-- END:CONFIG -->

<!-- BEGIN:ACTIONS -->
**Valid actions:**<br>→ **`/create-snapshot` — begin the release process**
<!-- END:ACTIONS -->
"""

    def generate_published_state_section(
        self,
        release_tag: str,
        release_url: str,
        reference_tag: str,
        sync_pr_url: Optional[str] = None
    ) -> str:
        """
        Generate content for the STATE section in published state.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_url: URL to the published release
            reference_tag: Reference tag (e.g., "src/r4.1")
            sync_pr_url: Optional URL to the post-release sync PR

        Returns:
            Formatted state section content
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        lines = [
            f"**State:** `published` | **Last Updated:** {timestamp}",
            "",
            f"**Release:** [{release_tag}]({release_url})",
            f"**Reference tag:** `{reference_tag}`",
        ]

        if sync_pr_url:
            lines.append(f"**Sync PR:** {sync_pr_url}")

        return "\n".join(lines)

    def generate_published_actions_section(self) -> str:
        """
        Generate content for the ACTIONS section in published state.

        Returns:
            Formatted actions section content (no actions available)
        """
        return "**Valid actions:** No further actions available — release is published"
