"""
Bot responder for CAMARA release automation.

This module provides template-based message rendering for bot comments
posted during the release automation workflow.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pystache

from .bot_context import build_context


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

    def render_comment(
        self,
        template_name: str,
        base_context: Any,
        delta: Dict[str, Any],
        release_tag: str,
    ) -> str:
        """
        Render a bot comment from the run's base context plus a per-comment delta.

        Args:
            template_name: Name of the template file (without .md extension)
            base_context: Context assembled by the plan job (ignored unless a dict)
            delta: Variables of this comment; they override the base context
            release_tag: Release tag for the marker

        Returns:
            Rendered message with marker prepended
        """
        return self.render_with_marker(
            template_name, merge_comment_context(base_context, delta), release_tag
        )

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


def merge_comment_context(base_context: Any, delta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Base context updated by delta, with apis_json (JSON string or list) turned
    into apis, completed to the full schema by build_context().
    """
    raw = dict(base_context) if isinstance(base_context, dict) else {}
    raw.update(delta)
    if "apis_json" in raw:
        apis = raw.pop("apis_json")
        if isinstance(apis, str):
            try:
                apis = json.loads(apis)
            except (json.JSONDecodeError, TypeError):
                apis = []
        raw["apis"] = apis if isinstance(apis, list) else []
    return build_context(**raw)


def post_comment(
    gh,
    template_name: str,
    issue_number: Any,
    base_context: Any,
    delta: Dict[str, Any],
    release_tag: str,
    comment_id: str = "",
) -> int:
    """Render a bot comment and post it, or replace comment_id's body; returns the comment id."""
    body = BotResponder().render_comment(template_name, base_context, delta, release_tag)
    if comment_id:
        gh.update_comment(int(comment_id), body)
        print(f"Updated comment {comment_id} ({template_name})")
        return int(comment_id)
    new_id = gh.create_comment(int(issue_number), body)
    print(f"Created comment {new_id} on #{issue_number} ({template_name})")
    return new_id
