"""
CHANGELOG generator for CAMARA release automation.

Generates structured CHANGELOG draft sections for release-review branches.
Each release section includes API documentation links, dependency versions,
and candidate changes from merged PRs.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pystache


TITLE_TEMPLATE = "# Changelog {repo_name}"

PREAMBLE = """\
**Please be aware that the project will have frequent updates to the main \
branch. There are no compatibility guarantees associated with code in any \
branch, including main, until it has been released. For example, changes may \
be reverted before a release is published. For the best results, use the \
latest published release.**

The below sections record the changes for each API version in each release \
as follows:

* for an alpha release, the delta with respect to the previous release
* for the first release-candidate, all changes since the last public release
* for subsequent release-candidate(s), only the delta to the previous release-candidate
* for a public release, the consolidated changes since the previous public release
"""

# Backward compatibility
HEADER_TEMPLATE = TITLE_TEMPLATE + "\n\n" + PREAMBLE

TOC_START_MARKER = "<!-- TOC:START -->"
TOC_END_MARKER = "<!-- TOC:END -->"

RELEASE_TYPE_MAP = {
    "pre-release-alpha": "pre-release",
    "pre-release-rc": "release candidate",
    "public-release": "public release",
    "maintenance-release": "maintenance release",
}


class ChangelogGenerator:
    """
    Generates CHANGELOG sections for CAMARA API releases.

    Produces per-release-cycle files in a CHANGELOG/ directory using
    Mustache templates. Per-API documentation links are pre-formatted
    by Python and injected via triple-mustache.

    Example usage:
        generator = ChangelogGenerator()
        content = generator.generate_draft(
            release_tag="r4.1",
            metadata=metadata_dict,
            repo_name="QualityOnDemand",
            previous_release="r3.2",
            candidate_prs=[{"title": "Add feature", "author": "user", "url": "..."}],
        )
        path = generator.write_changelog("/tmp/repo", content, "r4.1", "QualityOnDemand")
    """

    DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "changelog"

    def __init__(self, template_dir: Optional[str] = None):
        """Initialize with path to templates directory.

        Args:
            template_dir: Custom template directory path.
                         Defaults to release_automation/templates/changelog/
        """
        self.template_dir = Path(template_dir) if template_dir else self.DEFAULT_TEMPLATE_DIR
        self.renderer = pystache.Renderer(
            missing_tags='strict',
            escape=lambda x: x,  # Don't HTML-escape (markdown context)
        )

    def generate_draft(
        self,
        release_tag: str,
        metadata: Dict[str, Any],
        repo_name: str,
        candidate_changes: Optional[str] = None,
    ) -> str:
        """Generate CHANGELOG section content for a release.

        Args:
            release_tag: Target release tag (e.g., "r4.1")
            metadata: Generated release-metadata.yaml dict containing:
                - repository.release_type (e.g., "pre-release-alpha")
                - apis[].api_name, api_version, api_title, api_file_name
                - dependencies.commonalities_release, identity_consent_management_release
            repo_name: Repository name (e.g., "QualityOnDemand")
            candidate_changes: Pre-formatted markdown body from GitHub's
                generate-notes API (includes PR list and full changelog link).
                None if unavailable.

        Returns:
            Rendered template string (release section content)
        """
        # Extract API info for template
        apis = metadata.get("apis", [])
        api_list = [
            {"api_title": api.get("api_title", api.get("api_name", "")),
             "api_version": api.get("api_version", "")}
            for api in apis
        ]

        # Pre-format API sections
        formatted_sections = []
        for api in apis:
            formatted_sections.append(
                self.format_api_section(api, release_tag, repo_name)
            )
        formatted_api_sections = "\n\n".join(formatted_sections)

        # Get dependency versions
        deps = metadata.get("dependencies", {})
        commonalities = deps.get("commonalities_release", "")
        icm = deps.get("identity_consent_management_release", "")

        # Get release type description
        release_type = metadata.get("repository", {}).get("release_type", "")
        release_type_description = self._get_release_type_description(release_type)

        # Build template context
        context = {
            "release_tag": release_tag,
            "release_type_description": release_type_description,
            "apis": api_list,
            "commonalities_release": commonalities,
            "icm_release": icm,
            "formatted_api_sections": formatted_api_sections,
            "repo_name": repo_name,
            "candidate_changes": candidate_changes if candidate_changes else False,
        }

        template_path = self.template_dir / "release_section.mustache"
        template_content = template_path.read_text()
        return self.renderer.render(template_content, context)

    def write_changelog(
        self, work_dir: str, content: str, release_tag: str, repo_name: str
    ) -> str:
        """Write CHANGELOG section to the appropriate per-cycle file.

        File naming: r4.1 -> cycle 4 -> CHANGELOG/CHANGELOG-r4.md

        Behavior:
            - If file exists: prepend new section after the header block
            - If file is new: create with header + section

        Args:
            work_dir: Repository working directory
            content: Rendered release section content
            release_tag: Release tag for cycle extraction
            repo_name: Repository name for header generation

        Returns:
            Relative path to the written file (e.g., "CHANGELOG/CHANGELOG-r4.md")
        """
        cycle = self._get_cycle(release_tag)
        changelog_dir = Path(work_dir) / "CHANGELOG"
        changelog_dir.mkdir(exist_ok=True)

        filename = f"CHANGELOG-r{cycle}.md"
        filepath = changelog_dir / filename
        relative_path = f"CHANGELOG/{filename}"

        if filepath.exists():
            existing = filepath.read_text()
            # Find end of header block (first "# r" heading after the preamble)
            # Insert new section after header, before existing release sections
            header_end = self._find_header_end(existing)
            new_content = existing[:header_end] + content + "\n" + existing[header_end:]
            filepath.write_text(new_content)
        else:
            header = self._generate_header(repo_name)
            filepath.write_text(header + "\n" + content + "\n")

        # Regenerate TOC after content changes
        self._update_toc(filepath)

        return relative_path

    def _find_header_end(self, content: str) -> int:
        """Find the position where release sections start in an existing file.

        The header block ends at the first level-1 heading that looks like
        a release tag (e.g., '# r3.2'). New sections are inserted before this.
        """
        lines = content.split("\n")
        pos = 0
        for line in lines:
            if re.match(r"^# r\d+\.", line):
                return pos
            pos += len(line) + 1  # +1 for newline
        # If no release heading found, append at end
        return len(content)

    def _get_cycle(self, release_tag: str) -> str:
        """Extract cycle number from release_tag.

        Args:
            release_tag: e.g., "r4.1", "r3.2", "r10.1"

        Returns:
            Cycle string, e.g., "4", "3", "10"
        """
        match = re.match(r"r(\d+)\.", release_tag)
        if not match:
            raise ValueError(f"Cannot extract cycle from release_tag: {release_tag}")
        return match.group(1)

    def _get_release_type_description(self, release_type: str) -> str:
        """Map release_type to human-readable description.

        Args:
            release_type: e.g., "alpha", "rc", "public"

        Returns:
            Human-readable description, e.g., "pre-release"
        """
        return RELEASE_TYPE_MAP.get(release_type, release_type)

    def _generate_header(self, repo_name: str) -> str:
        """Generate the file header for new CHANGELOG files.

        Includes empty TOC markers between title and preamble.
        The TOC content is populated by _update_toc() after sections
        are written.

        Args:
            repo_name: Repository name (e.g., "QualityOnDemand")

        Returns:
            Header text including title, TOC markers, and recording rules.
        """
        title = TITLE_TEMPLATE.format(repo_name=repo_name)
        return f"{title}\n\n{TOC_START_MARKER}\n{TOC_END_MARKER}\n\n{PREAMBLE}"

    @staticmethod
    def _heading_to_anchor(heading_text: str) -> str:
        """Convert heading text to a GitHub-compatible anchor ID.

        GitHub anchor rules: lowercase, remove dots/special chars
        (except hyphens), replace spaces with hyphens.

        Examples:
            "r3.2"         -> "r32"
            "r10.1"        -> "r101"
            "v0.10.0-rc2"  -> "v0100-rc2"
        """
        text = heading_text.lower()
        text = text.replace(".", "")
        text = text.replace(" ", "-")
        text = re.sub(r"[^a-z0-9\-]", "", text)
        return text

    @staticmethod
    def _extract_toc_entries(content: str) -> List[Dict[str, Any]]:
        """Extract TOC entries from file content by scanning level-1 headings.

        Finds all ``# rX.Y`` headings and determines if the release is a
        public release (bold in TOC) by checking the "This {type} contains"
        line in the few lines following the heading.

        Returns:
            List of dicts ordered by appearance (newest first):
            ``[{"heading": "r4.2", "is_public": True}, ...]``
        """
        lines = content.split("\n")
        entries: List[Dict[str, Any]] = []
        for i, line in enumerate(lines):
            match = re.match(r"^# (r\d+\.\d+)\s*$", line)
            if not match:
                continue
            heading = match.group(1)
            is_public = False
            for j in range(i + 1, min(i + 6, len(lines))):
                if re.search(
                    r"This (public release|maintenance release) contains",
                    lines[j],
                ):
                    is_public = True
                    break
            entries.append({"heading": heading, "is_public": is_public})
        return entries

    @staticmethod
    def _format_toc(entries: List[Dict[str, Any]]) -> str:
        """Format TOC entries into markdown.

        Public/maintenance releases are bold, pre-releases are plain.

        Returns:
            TOC section string including ``## Table of Contents`` heading,
            or empty string if no entries.
        """
        if not entries:
            return ""
        lines = ["## Table of Contents"]
        for entry in entries:
            heading = entry["heading"]
            anchor = ChangelogGenerator._heading_to_anchor(heading)
            link = f"[{heading}](#{anchor})"
            if entry["is_public"]:
                lines.append(f"- **{link}**")
            else:
                lines.append(f"- {link}")
        return "\n".join(lines) + "\n"

    def _update_toc(self, filepath: Path) -> None:
        """Regenerate the TOC in-place for the given CHANGELOG file.

        If TOC markers exist, replaces content between them.
        If no markers found (legacy file), inserts TOC after the title line.
        """
        content = filepath.read_text()
        entries = self._extract_toc_entries(content)
        toc_text = self._format_toc(entries)

        start_idx = content.find(TOC_START_MARKER)
        end_idx = content.find(TOC_END_MARKER)

        if start_idx != -1 and end_idx != -1:
            # Replace between markers
            end_of_end_marker = end_idx + len(TOC_END_MARKER)
            if end_of_end_marker < len(content) and content[end_of_end_marker] == "\n":
                end_of_end_marker += 1
            new_content = (
                content[:start_idx]
                + TOC_START_MARKER + "\n"
                + toc_text
                + TOC_END_MARKER + "\n"
                + content[end_of_end_marker:]
            )
        else:
            # Fallback: insert after title line
            first_newline = content.index("\n")
            new_content = (
                content[:first_newline + 1]
                + "\n" + TOC_START_MARKER + "\n"
                + toc_text
                + TOC_END_MARKER + "\n"
                + content[first_newline + 1:]
            )

        filepath.write_text(new_content)

    @staticmethod
    def format_api_section(
        api: Dict[str, str],
        release_tag: str,
        repo_name: str,
        org: str = "camaraproject",
    ) -> str:
        """Format a single API's CHANGELOG section with links.

        Pre-generates the complex multi-line structure including heading,
        description, documentation links, and change category stubs.

        Args:
            api: Dict with api_name, api_version, api_title, api_file_name
            release_tag: For URL construction
            repo_name: For URL construction
            org: GitHub organization

        Returns:
            Formatted markdown section for this API
        """
        title = api.get("api_title", api.get("api_name", ""))
        version = api.get("api_version", "")
        file_name = api.get("api_file_name", api.get("api_name", ""))
        yaml_path = f"code/API_definitions/{file_name}.yaml"

        base_url = f"https://github.com/{org}/{repo_name}"
        raw_url = f"https://raw.githubusercontent.com/{org}/{repo_name}"

        lines = [
            f"## {title} {version}",
            "",
            f"**{title} {version} is ...**",
            "",
            "- API definition **with inline documentation**:",
            f"  - [View it on ReDoc](https://redocly.github.io/redoc/"
            f"?url={raw_url}/{release_tag}/{yaml_path}&nocors)",
            f"  - [View it on Swagger Editor](https://camaraproject.github.io/swagger-ui/"
            f"?url={raw_url}/{release_tag}/{yaml_path})",
            f"  - OpenAPI [YAML spec file]({base_url}/blob/{release_tag}/{yaml_path})",
            "",
            "### Added",
            "",
            "* _To be filled during release review_",
            "",
            "### Changed",
            "",
            "* _To be filled during release review_",
            "",
            "### Fixed",
            "",
            "* _To be filled during release review_",
            "",
            "### Removed",
            "",
            "* _To be filled during release review_",
        ]

        return "\n".join(lines)
