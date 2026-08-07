"""Bundler component-renaming conflict check.

Runs Redocly's bundler with ``--component-renaming-conflicts-severity=error``
against the current API definition to detect a name shared between a local
component and a different-content component pulled in via an external
``$ref``. Redocly silently renames the loser to ``<Name>-2``; this only
reports the cases where the two definitions actually differ (a same-content
proxy/alias is never flagged).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import make_finding

_ENGINE_RULE = "check-component-renaming-conflict"
_EXECUTION_ERROR_RULE = "component-renaming-conflict-execution-error"
_EXTERNAL_REF_RE = re.compile(r'\$ref\s*:\s*["\']?\.\.')
_CONFLICT_RE = re.compile(
    r'\[\d+\]\s+\S+:\d+:\d+\s+at\s+\S+\s*\n+'
    r"Two schemas are referenced with the same name but different content\. "
    r'Renamed (?P<name>\S+) to \S+-2\.'
)
_TIMEOUT_SECONDS = 60


def check_component_renaming_conflict(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Detect bundler component-renaming collisions for the current API.

    API-scoped check — the adapter calls this once per API context.
    """
    if not context.apis:
        return []

    api = context.apis[0]
    spec_file = api.spec_file or f"code/API_definitions/{api.api_name}.yaml"
    full_path = repo_path / spec_file
    if not full_path.is_file():
        return []

    content = full_path.read_text(encoding="utf-8")
    if not _EXTERNAL_REF_RE.search(content):
        return []

    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = subprocess.run(
                [
                    "redocly", "bundle", spec_file,
                    "--component-renaming-conflicts-severity=error",
                    "-o", str(Path(tmp) / "bundled.yaml"),
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                # GitHub Actions sets GITHUB_ACTIONS unconditionally, which
                # redocly's color library treats as reason enough to force
                # ANSI color into captured (non-TTY) output; NO_COLOR
                # suppresses it. Verified against a real Actions run.
                env={**os.environ, "NO_COLOR": "1"},
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            return [
                make_finding(
                    engine_rule=_EXECUTION_ERROR_RULE,
                    level="error",
                    message=f"Component-renaming-conflict probe could not run: {exc}",
                    path=spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            ]

    if result.returncode == 0:
        return []

    output = result.stdout + result.stderr
    matches = list(_CONFLICT_RE.finditer(output))
    if not matches:
        return []

    return [
        make_finding(
            engine_rule=_ENGINE_RULE,
            level="error",
            message=(
                f"Bundling collides on the name '{m.group('name')}': the local "
                f"definition keeps it, and the different-content component "
                f"pulled in via an external $ref is silently renamed to "
                f"'{m.group('name')}-2' at its use sites. Give the local "
                f"'{m.group('name')}' a distinct, API-specific name — the "
                f"common definition isn't yours to rename. If it isn't "
                f"actually needed locally, reference the common component "
                f"directly instead."
            ),
            path=spec_file,
            line=1,
            api_name=api.api_name,
        )
        for m in matches
    ]
