"""
Labels that release automation applies.

Template repositories don't copy labels, so a new API repository has none of
these; release automation creates a missing label before it applies it. An
existing label is never modified (project-wide labels are maintained centrally).

Each label is looked up by name: the repository label list pages at 30 and
some repositories carry more than 100 labels, so listing and diffing would
miss labels and try to recreate them.
"""

from typing import List, Sequence

from .github_client import GitHubClientError

# (name, color hex without '#', description)
LABELS = [
    ("release-issue", "5319E7", "Release tracking issue managed by automation"),
    ("release-state:planned", "0E8A16", "Release is planned"),
    ("release-state:snapshot-active", "FBCA04", "Release snapshot is active"),
    ("release-state:draft-ready", "1D76DB", "Draft release is ready"),
    ("release-state:published", "0E8A16", "Release has been published"),
    ("release-state:not-planned", "C2C9D1", "No release is currently planned"),
    ("common-sync", "C5DEF5", "Sync of code/common from Commonalities"),
    ("automated", "D1D5DB", "Created by automation"),
    ("post-release", "BFD4F2", "Post-release sync of README and CHANGELOG"),
]

_BY_NAME = {name: (color, description) for name, color, description in LABELS}

RELEASE_ISSUE_LABELS = [
    name for name, _, _ in LABELS
    if name == "release-issue" or name.startswith("release-state:")
]


def _create_if_missing(gh, name: str) -> bool:
    color, description = _BY_NAME[name]
    if gh.get_label(name) is not None:
        return False
    gh.create_label(name, color, description)
    return True


def ensure_labels(gh, names: Sequence[str]) -> List[str]:
    """Create the named labels that don't exist yet; returns the created names."""
    return [name for name in names if _create_if_missing(gh, name)]


def add_pr_labels(gh, pr_number: int, names: Sequence[str]) -> None:
    """Label a PR, creating missing labels first; failures are warnings."""
    for name in names:
        try:
            _create_if_missing(gh, name)
        except GitHubClientError as e:
            print(f"::warning::Could not create label {name}: {e}")
    try:
        gh.add_pr_labels(pr_number, list(names))
    except GitHubClientError as e:
        print(f"::warning::Could not add labels {', '.join(names)} to #{pr_number}: {e}")
