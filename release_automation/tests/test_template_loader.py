"""Tests for template_loader module."""

import pytest
from pathlib import Path

from release_automation.scripts.template_loader import render_template, TemplateLoader


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_render_release_review_pr_rc_template(self):
        """Test rendering the release review PR template for RC release."""
        context = {
            "release_tag": "r4.1",
            "snapshot_id": "r4.1-abc1234",
            "snapshot_branch_url": "https://github.com/org/repo/tree/release-snapshot/r4.1-abc1234",
            "short_type": "rc",
            "is_rc": True,
            "apis": [
                {"api_name": "QualityOnDemand", "api_version": "v1.0.0", "status_label": "rc"},
                {"api_name": "DeviceLocation", "api_version": "v2.0.0", "status_label": "rc"},
            ],
            "commonalities_release": "r3.4",
            "identity_consent_management_release": "r3.3",
        }

        result = render_template("release_review_pr", context)

        assert "## Release r4.1 (rc)" in result
        assert "| API | Version | Status |" in result
        assert "| QualityOnDemand | `v1.0.0` | rc |" in result
        assert "| DeviceLocation | `v2.0.0` | rc |" in result
        assert "### Codeowner Review" in result
        assert "### Release Management Review" in result
        assert "**Verify snapshot content (during automation introduction phase only):**" in result
        assert "**Update this PR:**" in result
        assert "**Confirm readiness:**" in result
        assert "All relevant changes copied into Added" in result
        assert "declared Commonalities version" in result
        assert "Commonalities r3.4" in result
        assert "mandatory release assets for the APIs are present per the API status and confirmed" in result
        assert "README update looks correct" in result
        assert "### Valid actions" in result
        assert "Snapshot: [`r4.1-abc1234`]" in result
        assert "<details>" in result
        assert "Required release assets per API status" in result

    def test_render_release_review_pr_alpha_template(self):
        """Test rendering the release review PR template for alpha release."""
        context = {
            "release_tag": "r3.2",
            "snapshot_id": "r3.2-def5678",
            "short_type": "alpha",
            "is_alpha": True,
            "apis": [
                {"api_name": "NumberVerification", "api_version": "v0.3.0-alpha.1", "status_label": "alpha"},
            ],
        }

        result = render_template("release_review_pr", context)

        assert "## Release r3.2 (alpha)" in result
        assert "| NumberVerification | `v0.3.0-alpha.1` | alpha |" in result
        assert "API definitions are consistent with the declared API version" in result
        assert "API documentation (`info.description`) is up to date" in result
        assert "All relevant changes copied into Added" in result
        # Alpha should NOT have rc/public-specific items
        assert "Enhanced test cases" not in result

    def test_render_release_review_pr_initial_public_template(self):
        """Test rendering the release review PR template for initial public release."""
        context = {
            "release_tag": "r5.0",
            "snapshot_id": "r5.0-xyz9999",
            "short_type": "public",
            "is_initial_public": True,
            "apis": [
                {"api_name": "TestAPI", "api_version": "v0.5.0", "status_label": "initial public"},
            ],
            "commonalities_release": "r4.0",
        }

        result = render_template("release_review_pr", context)

        assert "## Release r5.0 (public)" in result
        assert "| TestAPI | `v0.5.0` | initial public |" in result
        assert "API Description is set" in result
        assert "mandatory release assets for the APIs are present per the API status and confirmed" in result
        # Initial public should NOT have stable-public-only items
        assert "Enhanced test cases" not in result
        assert "User stories" not in result

    def test_render_release_review_pr_stable_public_template(self):
        """Test rendering the release review PR template for stable public release."""
        context = {
            "release_tag": "r6.1",
            "snapshot_id": "r6.1-aaa1111",
            "short_type": "maintenance",
            "is_stable_public": True,
            "apis": [
                {"api_name": "TestAPI", "api_version": "v1.0.0", "status_label": "stable public"},
            ],
            "commonalities_release": "r5.0",
        }

        result = render_template("release_review_pr", context)

        assert "## Release r6.1 (maintenance)" in result
        assert "| TestAPI | `v1.0.0` | stable public |" in result
        assert "Enhanced test cases cover rainy day scenarios" in result
        assert "User stories are current" in result
        assert "API Description is up to date" in result
        assert "mandatory release assets for the APIs are present per the API status and confirmed" in result

    def test_render_release_review_pr_no_apis(self):
        """Test rendering with no APIs (edge case)."""
        context = {
            "release_tag": "r5.0",
            "snapshot_id": "r5.0-xyz9999",
            "short_type": "rc",
            "apis": [],
        }

        result = render_template("release_review_pr", context)

        assert "## Release r5.0 (rc)" in result
        assert "Snapshot: [`r5.0-xyz9999`]" in result

    def test_render_release_review_pr_with_release_issue_link(self):
        """Test that release issue URL renders as a link in valid actions."""
        context = {
            "release_tag": "r4.1",
            "snapshot_id": "r4.1-abc1234",
            "short_type": "rc",
            "is_rc": True,
            "apis": [],
            "release_issue_url": "https://github.com/org/repo/issues/42",
        }

        result = render_template("release_review_pr", context)

        assert "[Release Issue](https://github.com/org/repo/issues/42)" in result

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
        # Template expects many fields but we only provide release_tag
        context = {"release_tag": "r1.0"}

        # Should not raise - missing tags are ignored
        result = render_template("release_review_pr", context)

        assert "## Release r1.0" in result
        # Missing snapshot_id should render as empty in link
        assert "Snapshot: [``]" in result


class TestTemplateLoader:
    """Tests for TemplateLoader class."""

    def test_loader_render_release_review_pr(self):
        """Test TemplateLoader.render for release review PR."""
        loader = TemplateLoader("pr_bodies")
        context = {
            "release_tag": "r4.2",
            "snapshot_id": "r4.2-111222",
            "short_type": "rc",
            "is_rc": True,
            "apis": [{"api_name": "TestAPI", "api_version": "v1.0.0", "status_label": "rc"}],
        }

        result = loader.render("release_review_pr", context)

        assert "## Release r4.2 (rc)" in result
        assert "| TestAPI | `v1.0.0` | rc |" in result

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
