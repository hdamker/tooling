"""
README release information updater for CAMARA release automation.

Updates the "Release Information" section in repository README files
by replacing content between delimiter comments with rendered templates.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pystache


class ReadmeUpdateError(Exception):
    """Raised when README update fails (e.g., missing delimiters)."""
    pass


class ReadmeUpdater:
    """
    Updates the Release Information section in repository README files.

    Content between START and END delimiters is replaced with rendered
    Mustache templates appropriate for the current release state.

    Example usage:
        updater = ReadmeUpdater()
        apis = [{"file_name": "quality-on-demand", "version": "v1.1.0"}]
        formatted = ReadmeUpdater.format_api_links(apis, "QualityOnDemand", "r3.2")
        changed = updater.update_release_info("README.md", "public_release", {
            "repo_name": "QualityOnDemand",
            "latest_public_release": "r3.2",
            "github_url": "https://github.com/camaraproject/QualityOnDemand/releases/tag/r3.2",
            "meta_release": "Spring25",
            "formatted_apis": formatted,
        })
    """

    DELIMITER_START = "<!-- CAMARA:RELEASE-INFO:START -->"
    DELIMITER_END = "<!-- CAMARA:RELEASE-INFO:END -->"

    VALID_STATES = {
        "no_release": "release-info-no-release",
        "prerelease_only": "release-info-prerelease-only",
        "public_release": "release-info-public",
        "public_with_prerelease": "release-info-public-with-prerelease",
    }

    DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "readme"

    def __init__(self, template_dir: Optional[str] = None):
        """Initialize with path to templates directory.

        Args:
            template_dir: Custom template directory path.
                         Defaults to release_automation/templates/readme/
        """
        self.template_dir = Path(template_dir) if template_dir else self.DEFAULT_TEMPLATE_DIR
        self.renderer = pystache.Renderer(
            missing_tags='ignore',  # Templates may omit optional fields
            escape=lambda x: x,     # Don't HTML-escape (markdown context)
        )

    def update_release_info(
        self, readme_path: str, release_state: str, data: Dict[str, Any]
    ) -> bool:
        """Update Release Information section in README.

        Args:
            readme_path: Path to README.md file
            release_state: One of: no_release, prerelease_only,
                          public_release, public_with_prerelease
            data: Template data dict with release info fields

        Returns:
            True if file was modified, False if content unchanged

        Raises:
            ReadmeUpdateError: If delimiters are missing from README
            ValueError: If release_state is invalid
            FileNotFoundError: If readme_path does not exist
        """
        if release_state not in self.VALID_STATES:
            raise ValueError(
                f"Invalid release_state: '{release_state}'. "
                f"Must be one of: {', '.join(self.VALID_STATES.keys())}"
            )

        readme = Path(readme_path)
        content = readme.read_text()

        self._check_delimiters(content)

        rendered = self._render_template(release_state, data)
        new_content = self._replace_delimited_content(content, rendered)

        if new_content == content:
            return False

        readme.write_text(new_content)
        return True

    def _check_delimiters(self, content: str) -> None:
        """Verify START and END delimiters exist in content.

        Raises:
            ReadmeUpdateError: With actionable message if delimiters are missing.
        """
        has_start = self.DELIMITER_START in content
        has_end = self.DELIMITER_END in content

        if not has_start and not has_end:
            raise ReadmeUpdateError(
                "README is missing both release information delimiters. "
                f"Add '{self.DELIMITER_START}' and '{self.DELIMITER_END}' "
                "markers to your README.md to define the release information section."
            )
        if not has_start:
            raise ReadmeUpdateError(
                f"README is missing the start delimiter '{self.DELIMITER_START}'. "
                "Both START and END delimiters are required."
            )
        if not has_end:
            raise ReadmeUpdateError(
                f"README is missing the end delimiter '{self.DELIMITER_END}'. "
                "Both START and END delimiters are required."
            )

    def _render_template(self, release_state: str, data: Dict[str, Any]) -> str:
        """Select and render the appropriate Mustache template.

        Args:
            release_state: Valid release state key
            data: Template context data

        Returns:
            Rendered template string
        """
        template_name = self.VALID_STATES[release_state]
        template_path = self.template_dir / f"{template_name}.mustache"

        if not template_path.exists():
            raise ReadmeUpdateError(
                f"Template not found: {template_name}.mustache "
                f"(looked in {self.template_dir})"
            )

        template_content = template_path.read_text()
        return self.renderer.render(template_content, data)

    def _replace_delimited_content(self, content: str, new_content: str) -> str:
        """Replace text between START and END delimiters with new content.

        Preserves delimiter lines. Returns full file content with replacement.
        """
        pattern = re.compile(
            re.escape(self.DELIMITER_START) + r"\n.*?" + re.escape(self.DELIMITER_END),
            re.DOTALL,
        )
        replacement = f"{self.DELIMITER_START}\n{new_content}{self.DELIMITER_END}"
        return pattern.sub(replacement, content)

    @staticmethod
    def format_api_links(
        apis: List[Dict[str, str]],
        repo_name: str,
        release_tag: str,
        org: str = "camaraproject",
    ) -> str:
        """Format API list with YAML/ReDoc/Swagger links as pre-rendered markdown.

        This generates the complex multi-line structure that Mustache cannot handle.

        Args:
            apis: List of dicts with 'file_name' and 'version' keys
            repo_name: Repository name (e.g., "QualityOnDemand")
            release_tag: Release tag for URL construction (e.g., "r3.2")
            org: GitHub organization

        Returns:
            Pre-formatted markdown string with API entries and links.
        """
        if not apis:
            return ""

        lines = []
        for api in apis:
            file_name = api["file_name"]
            version = api["version"]
            base = f"https://github.com/{org}/{repo_name}"
            raw = f"https://raw.githubusercontent.com/{org}/{repo_name}"
            yaml_path = f"code/API_definitions/{file_name}.yaml"

            lines.append(f"  * **{file_name} {version}**")
            lines.append(
                f"  [[YAML]]({base}/blob/{release_tag}/{yaml_path})"
                f"  [[ReDoc]](https://redocly.github.io/redoc/"
                f"?url={raw}/{release_tag}/{yaml_path}&nocors)"
                f"  [[Swagger]](https://camaraproject.github.io/swagger-ui/"
                f"?url={raw}/{release_tag}/{yaml_path})"
            )

        return "\n".join(lines) + "\n"
