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
    Manages Release Issue content - updating reserved sections,
    maintaining snapshot history table, and generating standardized titles.

    Reserved sections in issue body are marked with HTML comments:
        <!-- BEGIN:SECTION_NAME -->
        content here
        <!-- END:SECTION_NAME -->

    Supported sections:
        - STATE: Current release state and timestamp
        - HISTORY: Snapshot history table
        - CONFIG: Release configuration (APIs, dependencies, etc.)
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
            - "Release r4.1 (RC) — Fall26"
            - "Release r4.1 (alpha)"
            - "Release r4.1 (public)"

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_type: Release type from release-plan.yaml
            meta_release: Optional meta-release name (e.g., "Fall26")

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

    def generate_state_section(self, state: str) -> str:
        """
        Generate content for the STATE section.

        Args:
            state: Current release state (e.g., "PLANNED", "SNAPSHOT_ACTIVE")

        Returns:
            Formatted state section content
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"**State**: {state.upper()}\n**Last Updated**: {timestamp}"

    def generate_config_section(
        self,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str]
    ) -> str:
        """
        Generate content for the CONFIG section.

        Displays release configuration including:
        - Release tag and type
        - Meta-release (if applicable)
        - API versions table

        Args:
            release_plan: Parsed release-plan.yaml content
            api_versions: Dict mapping API name to calculated version

        Returns:
            Formatted config section content
        """
        repo = release_plan.get("repository", {})

        lines = [
            f"**Release Tag**: `{repo.get('target_release_tag', 'unknown')}`",
            f"**Release Type**: {repo.get('target_release_type', 'unknown')}",
        ]

        meta_release = repo.get("meta_release")
        if meta_release:
            lines.append(f"**Meta-Release**: {meta_release}")

        # Add APIs table
        apis = release_plan.get("apis", [])
        if apis:
            lines.append("")
            lines.append("**APIs**:")
            lines.append("| API | Target Version | Calculated Version |")
            lines.append("|-----|----------------|-------------------|")

            for api in apis:
                name = api.get("api_name", "unknown")
                target = api.get("target_api_version", "—")
                calculated = api_versions.get(name, "—")
                lines.append(f"| {name} | {target} | `{calculated}` |")

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

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_type: Release type
            meta_release: Optional meta-release name

        Returns:
            Complete issue body with empty sections
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        meta_line = f" | **Meta-Release**: {meta_release}" if meta_release else ""

        return f"""## Release: {release_tag}

**Type**: {release_type}{meta_line}

## Release Highlights

_Add release highlights here before creating snapshot._

---
<!-- AUTOMATION MANAGED SECTION - DO NOT EDIT BELOW THIS LINE -->

## Current State
<!-- BEGIN:STATE -->
**State**: PLANNED
**Last Updated**: {timestamp}
<!-- END:STATE -->

## Snapshot History
<!-- BEGIN:HISTORY -->
| Snapshot | Status | Created | Discarded | Reason | Review Branch |
|----------|--------|---------|-----------|--------|---------------|
<!-- END:HISTORY -->

## Configuration
<!-- BEGIN:CONFIG -->
_Configuration will be shown after first /create-snapshot_
<!-- END:CONFIG -->
"""
