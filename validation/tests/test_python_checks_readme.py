"""Unit tests for validation.engines.python_checks.readme_checks."""

from __future__ import annotations

from pathlib import Path

from validation.context import ValidationContext
from validation.engines.python_checks.readme_checks import (
    check_readme_placeholder_removal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> ValidationContext:
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
        target_release_type=None,
        commonalities_release=None,
        icm_release=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


def _make_api_defs(tmp_path: Path) -> Path:
    api_dir = tmp_path / "code" / "API_definitions"
    api_dir.mkdir(parents=True)
    return api_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckReadmePlaceholderRemoval:
    def test_placeholder_with_specs(self, tmp_path: Path):
        """Placeholder README + spec files → finding."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "README.MD").write_text(
            "Here you can add your definition file(s). "
            "Delete this README.MD file after the first file is added.\n"
        )
        (api_dir / "quality-on-demand.yaml").touch()

        findings = check_readme_placeholder_removal(tmp_path, _make_context())
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert findings[0]["engine_rule"] == "check-readme-placeholder-removal"
        assert "README.MD" in findings[0]["path"]

    def test_placeholder_variant_with_specs(self, tmp_path: Path):
        """Second placeholder variant also detected."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "README.MD").write_text(
            "Here you can add your definitions and delete this README.MD file\n"
        )
        (api_dir / "my-api.yaml").touch()

        findings = check_readme_placeholder_removal(tmp_path, _make_context())
        assert len(findings) == 1

    def test_placeholder_no_specs(self, tmp_path: Path):
        """Placeholder README but no spec files → no finding (expected state)."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "README.MD").write_text(
            "Here you can add your definition file(s). "
            "Delete this README.MD file after the first file is added.\n"
        )

        assert check_readme_placeholder_removal(tmp_path, _make_context()) == []

    def test_no_readme(self, tmp_path: Path):
        """No README at all → no finding."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "quality-on-demand.yaml").touch()

        assert check_readme_placeholder_removal(tmp_path, _make_context()) == []

    def test_real_readme_content(self, tmp_path: Path):
        """README with real content (not placeholder) → no finding."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "README.md").write_text(
            "# API Definitions\n\nThis directory contains the OpenAPI specs.\n"
        )
        (api_dir / "quality-on-demand.yaml").touch()

        assert check_readme_placeholder_removal(tmp_path, _make_context()) == []

    def test_case_insensitive_filename(self, tmp_path: Path):
        """Lowercase readme.md is also detected."""
        api_dir = _make_api_defs(tmp_path)
        (api_dir / "readme.md").write_text(
            "Delete this README.MD file after adding specs.\n"
        )
        (api_dir / "my-api.yml").touch()

        findings = check_readme_placeholder_removal(tmp_path, _make_context())
        assert len(findings) == 1
        assert "readme.md" in findings[0]["path"]

    def test_no_api_defs_directory(self, tmp_path: Path):
        """No API_definitions directory → no finding."""
        assert check_readme_placeholder_removal(tmp_path, _make_context()) == []
