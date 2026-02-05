"""Tests for template_loader module."""

import pytest
from pathlib import Path

from release_automation.scripts.template_loader import render_template, TemplateLoader


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_render_release_review_pr_template(self):
        """Test rendering the release review PR template."""
        context = {
            "release_tag": "r4.1",
            "snapshot_id": "r4.1-abc1234",
            "apis": [
                {"api_name": "QualityOnDemand", "api_version": "v1.0.0"},
                {"api_name": "DeviceLocation", "api_version": "v2.0.0"},
            ],
        }

        result = render_template("release_review_pr", context)

        assert "## Release r4.1" in result
        assert "- **QualityOnDemand**: `v1.0.0`" in result
        assert "- **DeviceLocation**: `v2.0.0`" in result
        assert "Snapshot ID: `r4.1-abc1234`" in result
        assert "### Review checklist" in result
        assert "- [ ] Verify API version numbers are correct" in result

    def test_render_release_review_pr_single_api(self):
        """Test rendering with a single API."""
        context = {
            "release_tag": "r3.2",
            "snapshot_id": "r3.2-def5678",
            "apis": [
                {"api_name": "NumberVerification", "api_version": "v0.3.0-alpha.1"},
            ],
        }

        result = render_template("release_review_pr", context)

        assert "## Release r3.2" in result
        assert "- **NumberVerification**: `v0.3.0-alpha.1`" in result
        assert "Snapshot ID: `r3.2-def5678`" in result

    def test_render_release_review_pr_no_apis(self):
        """Test rendering with no APIs (edge case)."""
        context = {
            "release_tag": "r5.0",
            "snapshot_id": "r5.0-xyz9999",
            "apis": [],
        }

        result = render_template("release_review_pr", context)

        assert "## Release r5.0" in result
        assert "Snapshot ID: `r5.0-xyz9999`" in result
        # No API entries
        assert "- **" not in result

    def test_render_sync_pr_template(self):
        """Test rendering the sync PR template."""
        context = {"release_tag": "r4.1"}

        result = render_template("sync_pr", context)

        assert "## Post-Release Sync" in result
        assert "release `r4.1`" in result
        assert "CHANGELOG.md updates" in result
        assert "README.md release info section" in result
        assert "Review required" in result

    def test_render_template_not_found(self):
        """Test rendering a non-existent template raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            render_template("nonexistent_template", {})

        assert "Template not found" in str(exc_info.value)

    def test_render_template_missing_context_keys(self):
        """Test rendering with missing context keys (should be ignored)."""
        # Template expects release_tag, snapshot_id, apis but we only provide release_tag
        context = {"release_tag": "r1.0"}

        # Should not raise - missing tags are ignored
        result = render_template("release_review_pr", context)

        assert "## Release r1.0" in result
        # Missing snapshot_id should be blank
        assert "Snapshot ID: ``" in result


class TestTemplateLoader:
    """Tests for TemplateLoader class."""

    def test_loader_render_release_review_pr(self):
        """Test TemplateLoader.render for release review PR."""
        loader = TemplateLoader("pr_bodies")
        context = {
            "release_tag": "r4.2",
            "snapshot_id": "r4.2-111222",
            "apis": [{"api_name": "TestAPI", "api_version": "v1.0.0"}],
        }

        result = loader.render("release_review_pr", context)

        assert "## Release r4.2" in result
        assert "- **TestAPI**: `v1.0.0`" in result

    def test_loader_render_sync_pr(self):
        """Test TemplateLoader.render for sync PR."""
        loader = TemplateLoader("pr_bodies")
        context = {"release_tag": "r3.3"}

        result = loader.render("sync_pr", context)

        assert "release `r3.3`" in result

    def test_loader_template_not_found(self):
        """Test TemplateLoader.render with non-existent template."""
        loader = TemplateLoader("pr_bodies")

        with pytest.raises(FileNotFoundError):
            loader.render("does_not_exist", {})

    def test_loader_custom_template_dir(self):
        """Test TemplateLoader with custom template directory."""
        # Use bot_messages directory which we know exists
        loader = TemplateLoader("bot_messages")

        # This should fail because internal_error.md is not .mustache
        # But the loader looks for .mustache files
        with pytest.raises(FileNotFoundError):
            loader.render("internal_error", {})
