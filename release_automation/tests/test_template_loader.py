"""Tests for template_loader module."""

import pytest
from pathlib import Path

from release_automation.scripts.template_loader import render_template, TemplateLoader


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_render_release_review_pr_template(self):
        """Test rendering the (status-independent) release review PR template."""
        context = {
            "release_tag": "r4.1",
            "snapshot_id": "r4.1-abc1234",
            "snapshot_branch_url": "https://github.com/org/repo/tree/release-snapshot/r4.1-abc1234",
            "short_type": "rc",
            "apis": [
                {"api_name": "QualityOnDemand", "api_version": "v1.0.0", "status_label": "rc"},
                {"api_name": "DeviceLocation", "api_version": "v2.0.0", "status_label": "rc"},
            ],
            "commonalities_release": "r3.4",
            "identity_consent_management_release": "r3.3",
        }

        result = render_template("release_review_pr", context)

        assert "## Release Review: r4.1 rc" in result
        assert "| API | Version | Status | Comparison target |" in result
        assert "| QualityOnDemand | `v1.0.0` | rc | `N/A` |" in result
        assert "| DeviceLocation | `v2.0.0` | rc | `N/A` |" in result
        assert "### Codeowner Actions" in result
        assert "### Release Management Actions" in result
        # Three status-independent codeowner actions
        assert "**Update the CHANGELOG**" in result
        assert (
            "Copy all API-consumer-relevant changes from the provided list into the appropriate "
            "Breaking changes / Added / Changed / Fixed / Removed sections for each API. List "
            "breaking changes both in Breaking changes and in their normal change category."
            in result
        )
        assert "**Document deferred validation warnings (and hints)**" in result
        assert "**The release is ready for Release Management review**" in result
        # API Readiness Checklist link lives once, in the asset-table footer
        assert "documentation/readiness/api-readiness-checklist.md" in result
        assert "Commonalities r3.4" in result
        assert "Mandatory release assets are present for each API according to its status" in result
        assert "All remaining validation warnings are documented in issues and the reasons for deferral are defensible" in result
        assert "Content findings needing a `main` PR are collected as sub-issues of one issue titled `Release r4.1 review findings`" in result
        assert "Assign the Release Management reviewer(s) as assignee(s) of this PR" in result
        assert "The following actions and checks are done by a Release Management reviewer before approving the PR" in result
        assert "### Valid next actions for codeowners" in result
        assert "Snapshot: [`r4.1-abc1234`]" in result
        assert "<details>" in result
        assert "Required release assets per API status" in result
        # Removed in RM#554: status-conditional checklist, version-match box,
        # and the automation-introduction-phase snapshot-content note
        assert "Confirm API release readiness" not in result
        assert "API version(s) used in all files match" not in result
        assert "During the automation introduction phase" not in result

    def test_render_release_review_pr_body_is_status_independent(self):
        """The Codeowner/RM action blocks are identical regardless of release status."""
        bodies = []
        for short_type, status_label, version in [
            ("alpha", "alpha", "v0.3.0-alpha.1"),
            ("rc", "rc", "v1.0.0-rc.1"),
            ("public", "initial public", "v0.5.0"),
            ("maintenance", "stable public", "v1.0.0"),
        ]:
            result = render_template(
                "release_review_pr",
                {
                    "release_tag": "r4.1",
                    "snapshot_id": "r4.1-abc1234",
                    "short_type": short_type,
                    "apis": [
                        {"api_name": "TestAPI", "api_version": version, "status_label": status_label},
                    ],
                },
            )
            # The slice between the actions heading and the asset table must not vary by status
            actions = result[result.index("### Codeowner Actions"):result.index("<details>")]
            bodies.append(actions)

        assert len(set(bodies)) == 1, "Codeowner/RM action blocks differ across release statuses"

    def test_render_release_review_pr_no_apis(self):
        """Test rendering with no APIs (edge case)."""
        context = {
            "release_tag": "r5.0",
            "snapshot_id": "r5.0-xyz9999",
            "short_type": "rc",
            "apis": [],
        }

        result = render_template("release_review_pr", context)

        assert "## Release Review: r5.0 rc" in result
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

        assert "## Release Review: r1.0" in result
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

        assert "## Release Review: r4.2 rc" in result
        assert "| TestAPI | `v1.0.0` | rc | `N/A` |" in result

    def test_render_release_review_pr_includes_comparison_baseline_column(self):
        context = {
            "release_tag": "r4.2",
            "snapshot_id": "r4.2-111222",
            "short_type": "rc",
            "apis": [
                {
                    "api_name": "TestAPI",
                    "api_version": "v1.2.0-rc.2",
                    "status_label": "rc",
                    "comparison_baseline": "v1.2.0-rc.1",
                },
                {
                    "api_name": "NewAPI",
                    "api_version": "v0.1.0-alpha.1",
                    "status_label": "alpha",
                },
            ],
        }

        result = render_template("release_review_pr", context)

        assert "| API | Version | Status | Comparison target |" in result
        assert "| TestAPI | `v1.2.0-rc.2` | rc | `v1.2.0-rc.1` |" in result
        assert "| NewAPI | `v0.1.0-alpha.1` | alpha | `N/A` |" in result

    def test_render_release_review_pr_seeded_from_note_when_no_baseline(self):
        """Seeded API with no resolvable baseline (N/A) gets a check-the-predecessor note."""
        context = {
            "release_tag": "r1.1",
            "snapshot_id": "r1.1-abc1234",
            "short_type": "rc",
            "apis": [
                {
                    "api_name": "qos-profiles",
                    "api_version": "1.2.0-rc.4",
                    "status_label": "rc",
                    "seeded_from_repository": "QualityOnDemand",
                    "seeded_from_release_tag": "r4.1",
                },
            ],
        }

        result = render_template("release_review_pr", context)

        assert "| qos-profiles | `1.2.0-rc.4` | rc | `N/A` |" in result
        assert "qos-profiles" in result.split("Comparison target |")[1]
        assert "QualityOnDemand" in result
        assert "r4.1" in result

    def test_render_release_review_pr_no_seeded_from_note_when_baseline_resolved(self):
        """A resolved comparison_baseline suppresses the note even if the API was seeded."""
        context = {
            "release_tag": "r1.2",
            "snapshot_id": "r1.2-def5678",
            "short_type": "rc",
            "apis": [
                {
                    "api_name": "qos-profiles",
                    "api_version": "1.2.0-rc.5",
                    "status_label": "rc",
                    "comparison_baseline": "1.2.0-rc.4",
                    "seeded_from_repository": "QualityOnDemand",
                    "seeded_from_release_tag": "r4.1",
                },
            ],
        }

        result = render_template("release_review_pr", context)

        assert "QualityOnDemand" not in result

    def test_render_release_review_pr_no_seeded_from_note_when_not_seeded(self):
        """No seeded_from data on the API means no note, regardless of N/A."""
        context = {
            "release_tag": "r4.2",
            "snapshot_id": "r4.2-111222",
            "short_type": "rc",
            "apis": [
                {"api_name": "fresh-api", "api_version": "0.1.0-alpha.1", "status_label": "alpha"},
            ],
        }

        result = render_template("release_review_pr", context)

        assert "seeded from" not in result.lower()

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
