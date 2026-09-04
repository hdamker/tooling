"""Self-test for the Commonalities canonical ``info-description-templates.yaml``.

Validates that every entry in the canonical file wraps its ``content`` with a
matching ``<!-- CAMARA:MANDATORY:<key>:BEGIN -->`` / ``:END -->`` pair where
the template name in the markers matches the top-level YAML key.  Guards
against accidental marker corruption in future Commonalities edits — the rule
implementation relies on this invariant being upheld.

Skipped when the upstream Commonalities mirror is not present, so developer
environments without the workspace's full mirror can still run the test suite.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml


_MARKER_BEGIN_RE = re.compile(
    r"<!--\s*CAMARA:MANDATORY:([a-z][a-z0-9-]*):BEGIN\s*-->"
)
_MARKER_END_RE = re.compile(
    r"<!--\s*CAMARA:MANDATORY:([a-z][a-z0-9-]*):END\s*-->"
)


def _template_entries(canonical: dict) -> dict[str, dict]:
    """Return only canonical entries that carry mandatory template content."""
    return {
        name: entry
        for name, entry in canonical.items()
        if isinstance(entry, dict) and isinstance(entry.get("content"), str)
    }


_ARTIFACT_RELPATH = Path("artifacts/common/info-description-templates.yaml")

# Relative locations of a `Commonalities` checkout to probe when no explicit
# path is given, tried in order under each ancestor of this test file. Covers a
# plain sibling clone as well as nested layouts used by multi-repo checkouts.
_COMMONALITIES_LAYOUTS = (
    Path("Commonalities"),
    Path("upstream/traversals/Commonalities"),
    Path("upstream/Commonalities"),
)


def _resolve_canonical_path() -> Path | None:
    """Locate ``artifacts/common/info-description-templates.yaml`` locally.

    ``CAMARA_COMMONALITIES_ROOT`` wins when set and must point at a
    ``Commonalities`` checkout. Otherwise walk up from this test file probing
    the layouts in :data:`_COMMONALITIES_LAYOUTS` under each ancestor. Returns
    ``None`` when no checkout is reachable, which skips the test — the normal
    case in CI, where this file has no counterpart on disk.
    """
    env_root = os.environ.get("CAMARA_COMMONALITIES_ROOT")
    if env_root:
        explicit = Path(env_root) / _ARTIFACT_RELPATH
        if explicit.is_file():
            return explicit

    cursor = Path(__file__).resolve()
    for _ in range(8):
        cursor = cursor.parent
        for layout in _COMMONALITIES_LAYOUTS:
            guess = cursor / layout / _ARTIFACT_RELPATH
            if guess.is_file():
                return guess
    return None


_CANONICAL_PATH = _resolve_canonical_path()


@pytest.mark.skipif(
    _CANONICAL_PATH is None,
    reason=(
        "Commonalities checkout not reachable "
        "(set CAMARA_COMMONALITIES_ROOT to one)"
    ),
)
class TestInfoDescriptionTemplatesCanonical:
    """Invariants on ``artifacts/common/info-description-templates.yaml``."""

    @pytest.fixture(scope="class")
    def canonical(self) -> dict:
        assert _CANONICAL_PATH is not None
        data = yaml.safe_load(_CANONICAL_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict), "canonical file root must be a mapping"
        return data

    def test_every_entry_has_content_field(self, canonical: dict) -> None:
        templates = _template_entries(canonical)
        assert templates, "canonical file must contain template entries"
        for name, entry in templates.items():
            assert isinstance(entry, dict), (
                f"template {name!r} is not a mapping"
            )
            assert isinstance(entry.get("content"), str), (
                f"template {name!r} missing string `content` field"
            )

    def test_markers_match_key_and_appear_once(self, canonical: dict) -> None:
        for name, entry in _template_entries(canonical).items():
            content = entry["content"]
            begins = _MARKER_BEGIN_RE.findall(content)
            ends = _MARKER_END_RE.findall(content)
            assert begins == [name], (
                f"template {name!r}: BEGIN markers {begins!r} do not match "
                f"single canonical name {name!r}"
            )
            assert ends == [name], (
                f"template {name!r}: END markers {ends!r} do not match "
                f"single canonical name {name!r}"
            )

    def test_begin_precedes_end(self, canonical: dict) -> None:
        for name, entry in _template_entries(canonical).items():
            content = entry["content"]
            begin_match = _MARKER_BEGIN_RE.search(content)
            end_match = _MARKER_END_RE.search(content)
            assert begin_match is not None and end_match is not None
            assert begin_match.start() < end_match.start(), (
                f"template {name!r}: BEGIN marker appears after END marker"
            )

    def test_expected_universal_templates_present(self, canonical: dict) -> None:
        """The three universal templates must exist in the canonical file."""
        required = {
            "authorization-and-authentication",
            "additional-error-responses",
            "request-body-strictness",
        }
        missing = required - set(canonical.keys())
        assert not missing, f"canonical file missing universal templates: {missing}"
