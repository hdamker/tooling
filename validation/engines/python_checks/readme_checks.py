"""README placeholder checks.

Detects template placeholder README files that should be removed once
real API specification files have been added.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding

_API_DEFS_DIR = "code/API_definitions"

# Key phrase present in both known CAMARA template variants:
#   "Here you can add your definition file(s). Delete this README.MD ..."
#   "Here you can add your definitions and delete this README.MD file"
_PLACEHOLDER_PHRASE = "delete this readme"


def check_readme_placeholder_removal(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Check that the template placeholder README is removed.

    Repo-level check.  If ``code/API_definitions/`` contains both a
    README file with placeholder text *and* real ``.yaml``/``.yml`` spec
    files, the placeholder should be deleted.
    """
    api_dir = repo_path / _API_DEFS_DIR
    if not api_dir.is_dir():
        return []

    # Find README file (case-insensitive)
    readme_file = None
    for entry in api_dir.iterdir():
        if entry.is_file() and entry.name.lower() == "readme.md":
            readme_file = entry
            break

    if readme_file is None:
        return []

    # Check if spec files exist alongside the README
    has_specs = any(
        f.is_file() and f.suffix in (".yaml", ".yml")
        for f in api_dir.iterdir()
    )
    if not has_specs:
        return []

    # Read and check for placeholder content
    try:
        content = readme_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    if _PLACEHOLDER_PHRASE not in content.lower():
        return []

    return [
        make_finding(
            engine_rule="check-readme-placeholder-removal",
            level="warn",
            message=(
                f"Placeholder README '{readme_file.name}' should be removed "
                f"from {_API_DEFS_DIR}/ — API specification files are present"
            ),
            path=f"{_API_DEFS_DIR}/{readme_file.name}",
            line=1,
        )
    ]
