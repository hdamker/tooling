"""Path-gating plan for the tooling repository CI workflow."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable


@dataclass(frozen=True)
class ToolingCiPlan:
    """Boolean plan for path-gated Tooling CI jobs."""

    npm: bool
    javascript: bool
    validation: bool
    release_automation: bool


def plan_for_changed_files(changed_files: Iterable[str]) -> ToolingCiPlan:
    """Return the Tooling CI checks needed for *changed_files*."""

    paths = [path.strip() for path in changed_files if path.strip()]
    run_all = "__all__" in paths

    def matches(*patterns: str) -> bool:
        return run_all or any(
            fnmatch(path, pattern) for path in paths for pattern in patterns
        )

    workflow_changed = matches(".github/workflows/tooling-ci.yml")
    broad = workflow_changed or matches("requirements.txt", "tooling_lib/**")
    npm = workflow_changed or matches(
        "validation/package.json",
        "validation/package-lock.json",
    )
    javascript = workflow_changed or matches("linting/config/lint_function/*.js")
    validation = broad or npm or matches(
        "validation/**",
        "linting/**",
        "shared-actions/run-validation/**",
        "shared-actions/validate-release-plan/**",
        "validation/workflows/**",
        ".github/workflows/validation.yml",
        ".github/workflows/validation-regression.yml",
        ".github/workflows/validation-settings-ci.yml",
        "config/validation-settings.yaml",
    )
    release_automation = broad or matches(
        "release_automation/**",
        "release_automation/workflows/**",
        "shared-actions/create-snapshot/**",
        "shared-actions/derive-release-state/**",
        "shared-actions/post-bot-comment/**",
        "shared-actions/run-validation/**",
        "shared-actions/sync-release-issue/**",
        "shared-actions/update-issue-section/**",
        ".github/workflows/release-automation-reusable.yml",
        ".github/workflows/release-automation-regression.yml",
    )

    return ToolingCiPlan(
        npm=npm,
        javascript=javascript,
        validation=validation,
        release_automation=release_automation,
    )
