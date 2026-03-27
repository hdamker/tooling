"""
Simple template loader for PR body templates.

Provides a lightweight utility for loading and rendering Mustache templates
for pull request bodies. Separate from BotResponder (which handles issue
comments with markers).
"""

from pathlib import Path
from typing import Any, Dict, Optional

import pystache


def render_template(
    template_name: str,
    context: Dict[str, Any],
    template_dir: str = "pr_bodies"
) -> str:
    """Render a Mustache template from the templates directory.

    Args:
        template_name: Name of the template file (without .mustache extension)
        context: Dictionary of template variables
        template_dir: Subdirectory under templates/ (default: "pr_bodies")

    Returns:
        Rendered template content

    Raises:
        FileNotFoundError: If template file does not exist
    """
    base_dir = Path(__file__).parent.parent / "templates" / template_dir
    template_path = base_dir / f"{template_name}.mustache"

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    renderer = pystache.Renderer(
        missing_tags='ignore',  # PR bodies may have optional fields
        escape=lambda x: x,     # Don't HTML-escape (markdown context)
    )

    template_content = template_path.read_text()
    return renderer.render(template_content, context)


class TemplateLoader:
    """Template loader class for PR body templates.

    Alternative to the render_template function when you need to load
    multiple templates from the same directory.

    Example:
        loader = TemplateLoader("pr_bodies")
        body = loader.render("release_review_pr", {"release_tag": "r4.1"})
    """

    def __init__(self, template_dir: str = "pr_bodies"):
        """Initialize template loader.

        Args:
            template_dir: Subdirectory under templates/
        """
        self.template_dir = Path(__file__).parent.parent / "templates" / template_dir
        self.renderer = pystache.Renderer(
            missing_tags='ignore',
            escape=lambda x: x,
        )

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with the given context.

        Args:
            template_name: Name of the template file (without .mustache extension)
            context: Dictionary of template variables

        Returns:
            Rendered template content

        Raises:
            FileNotFoundError: If template file does not exist
        """
        template_path = self.template_dir / f"{template_name}.mustache"

        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        template_content = template_path.read_text()
        return self.renderer.render(template_content, context)
