"""
Bot responder for CAMARA release automation.

This module provides template-based message rendering for bot comments
posted during the release automation workflow.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pystache


class BotResponderError(Exception):
    """Base exception for bot responder errors."""
    pass


class TemplateNotFoundError(BotResponderError):
    """Raised when a template file is not found."""
    pass


class BotResponder:
    """
    Renders bot messages from Mustache templates.

    Templates are stored in the templates/bot_messages directory and
    use Mustache syntax for variable interpolation and conditionals.

    Example usage:
        responder = BotResponder()
        message = responder.render("snapshot_created", {
            "release_tag": "r4.1",
            "snapshot_id": "r4.1-abc1234",
            "release_pr_url": "https://github.com/..."
        })
    """

    # Default template directory relative to this file
    DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "bot_messages"

    # Marker format for identifying bot comments
    MARKER_FORMAT = "<!-- release-bot:{release_tag} -->"

    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize the bot responder.

        Args:
            template_dir: Optional custom template directory.
                         Defaults to templates/bot_messages relative to this module.
        """
        self.template_dir = template_dir or self.DEFAULT_TEMPLATE_DIR
        self.renderer = pystache.Renderer(
            missing_tags='strict',  # Raise error on missing variables
            escape=lambda x: x,     # Don't HTML-escape (we're rendering markdown)
        )

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Render a bot message template with the given context.

        Args:
            template_name: Name of the template file (without .md extension)
            context: Dictionary of variables to interpolate into the template

        Returns:
            Rendered message content

        Raises:
            TemplateNotFoundError: If the template file doesn't exist
            pystache.common.MissingTags: If required variables are missing
        """
        template_path = self.template_dir / f"{template_name}.md"

        if not template_path.exists():
            raise TemplateNotFoundError(
                f"Template not found: {template_name} "
                f"(looked in {self.template_dir})"
            )

        template_content = template_path.read_text()
        content = self.renderer.render(template_content, context)
        # Collapse 3+ consecutive newlines to max one blank line.
        # Handles Mustache conditional artifacts (false sections leave empty lines).
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()

    def render_with_marker(
        self,
        template_name: str,
        context: Dict[str, Any],
        release_tag: str
    ) -> str:
        """
        Render a template with an HTML comment marker for identification.

        The marker allows the workflow to find and update existing bot
        comments rather than creating duplicates.

        Args:
            template_name: Name of the template file (without .md extension)
            context: Dictionary of variables to interpolate
            release_tag: Release tag for the marker (e.g., "r4.1")

        Returns:
            Rendered message with marker prepended
        """
        content = self.render(template_name, context)
        marker = self.MARKER_FORMAT.format(release_tag=release_tag)
        return f"{marker}\n{content}"

    def list_templates(self) -> List[str]:
        """
        List all available template names.

        Returns:
            List of template names (without .md extension)
        """
        if not self.template_dir.exists():
            return []

        return [
            f.stem for f in self.template_dir.glob("*.md")
            if f.is_file()
        ]

    @staticmethod
    def extract_marker_tag(content: str) -> Optional[str]:
        """
        Extract the release tag from a bot comment marker.

        Args:
            content: Comment content that may contain a marker

        Returns:
            Release tag if marker found, None otherwise
        """
        import re
        pattern = r"<!-- release-bot:([^\s]+) -->"
        match = re.search(pattern, content)
        return match.group(1) if match else None
