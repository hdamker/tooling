"""
Issue manager for CAMARA release automation.

This module provides functionality for managing Release Issue content,
including updating reserved sections and generating standardized titles.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import config
from .commands import actions_for
from .release_line import MAIN_BRANCH


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

    def generate_title(
        self,
        release_tag: str,
        release_type: str,
        meta_release: Optional[str],
        base_branch: str,
    ) -> str:
        """
        Generate a standardized issue title for a release.

        Format: "Release {tag} ({type}) — {meta_release}", followed by
        " ({base_branch})" for a release from a maintenance branch

        Examples:
            - "Release r4.1 (RC) — Sync26"
            - "Release r4.1 (alpha)"
            - "Release r4.1 (public)"

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_type: Release type from release-plan.yaml
            meta_release: Optional meta-release name (e.g., "Sync26")
            base_branch: Line of the release; named unless it is main

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

        if base_branch != MAIN_BRANCH:
            title += f" ({base_branch})"

        return title

    def should_update_title(
        self,
        current_title: str,
        release_plan: Dict[str, Any],
        base_branch: str,
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
            meta_release=repo_config.get("meta_release"),
            base_branch=base_branch,
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
        return actions_for(state.lower().replace("_", "-"), release_tag, release_pr_url)

    def generate_config_section(
        self,
        release_plan: Dict[str, Any],
        api_versions: Dict[str, str],
        commonalities_release: str = "",
        icm_release: str = "",
        common_cache_status: str = "",
        common_cache_details: str = "",
        common_sync_pr_url: str = "",
    ) -> str:
        """
        Generate content for the CONFIG section.

        Displays release configuration including:
        - APIs table with target and calculated versions
        - Dependencies (Commonalities, ICM)
        - Common file cache staleness warning if applicable

        Args:
            release_plan: Parsed release-plan.yaml content
            api_versions: Dict mapping API name to calculated version
            commonalities_release: Required Commonalities version
            icm_release: Required ICM version
            common_cache_status: "stale", "in_sync", or "" (unchecked)
            common_cache_details: Human-readable staleness description
            common_sync_pr_url: URL of open sync-common PR if any

        Returns:
            Formatted config section content
        """
        lines = []

        # Add release type
        release_type = release_plan.get("repository", {}).get(
            "target_release_type", ""
        )
        short_type = config.SHORT_TYPE_MAP.get(release_type, release_type)
        if short_type:
            lines.append(f"**Release type:** {short_type}")
            lines.append("")

        # Add APIs table with status column
        apis = release_plan.get("apis", [])
        if apis:
            lines.append("| API | Status | Target | Calculated |")
            lines.append("|-----|--------|--------|------------|")

            for api in apis:
                name = api.get("api_name", "unknown")
                status = api.get("target_api_status", "—")
                target = api.get("target_api_version", "—")
                calculated = api_versions.get(name, "—")
                lines.append(f"| {name} | {status} | {target} | `{calculated}` |")

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

        # Add common file cache staleness warning
        if common_cache_status == "stale":
            lines.append("")
            detail = f" \u2014 {common_cache_details}" if common_cache_details else ""
            if common_sync_pr_url:
                lines.append(
                    f"\u26a0\ufe0f **Common file cache stale**{detail}. "
                    f"[Sync PR]({common_sync_pr_url}) pending."
                )
            else:
                lines.append(
                    f"\u26a0\ufe0f **Common file cache stale**{detail}. "
                    f"Run `workflow_dispatch` to trigger sync."
                )

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
        from .template_loader import render_template

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return render_template("release_issue", {
            "release_tag": release_tag,
            "timestamp": timestamp,
            "readiness_url": (
                "https://github.com/camaraproject/ReleaseManagement"
                "/blob/main/documentation/readiness"
                "/api-readiness-checklist.md"
            ),
        }, template_dir="issue_bodies")

    def generate_published_state_section(
        self,
        release_tag: str,
        release_url: str,
        reference_tag: str,
        repo: str,
        sync_pr_url: str = "",
        warnings: str = "",
        main_sync_pr_url: str = "",
    ) -> str:
        """
        Generate content for the STATE section in published state.

        Args:
            release_tag: Release tag (e.g., "r4.1")
            release_url: URL to the published release
            reference_tag: Reference tag (e.g., "src/r4.1"); the line stays when empty
            repo: Repository "owner/name" for the reference tag link
            sync_pr_url: URL of the post-release sync PR, if one was created
            warnings: "; "-joined post-publish warnings (post_publish_warnings())
            main_sync_pr_url: Case B: URL of the sync PR into main

        Returns:
            Formatted state section content
        """
        lines = [
            "**State:** `published`",
            "",
            f"✅ **Release published:** [{release_tag}]({release_url})",
            f"📌 **Reference tag:** [`{reference_tag}`](https://github.com/{repo}/tree/{reference_tag})",
        ]
        if sync_pr_url:
            lines.append(f"🔄 **Sync PR:** [View PR]({sync_pr_url})")
        if main_sync_pr_url:
            lines.append(f"🔄 **Sync PR into main:** [View PR]({main_sync_pr_url})")
        if warnings:
            lines.append(f"⚠️ **Warnings:** {warnings}")
        return "\n".join(lines)

    def generate_published_actions_section(self, sync_status: str) -> str:
        """
        Generate content for the ACTIONS section in published state.

        Args:
            sync_status: Post-release sync status (created | failed | no_changes | other)

        Returns:
            No-actions text when the sync PR was created, manual follow-up otherwise
        """
        if sync_status == "created":
            return "_No actions available - release is published._"
        if sync_status == "failed":
            return (
                "**Manual action required:** Create post-release sync PR manually "
                "(update README and CHANGELOG on main), then close this issue."
            )
        if sync_status == "no_changes":
            return (
                "**Manual action required:** Verify README and CHANGELOG on main are correct, "
                "then close this issue."
            )
        return "**Manual action required:** Verify post-release sync status, then close this issue."
