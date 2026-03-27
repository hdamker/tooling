"""
Unit tests for the README release information updater.

Tests cover delimiter checking, template rendering, content replacement,
API link formatting, and full integration scenarios.
"""

import pytest
from pathlib import Path

from release_automation.scripts.readme_updater import (
    ReadmeUpdater,
    ReadmeUpdateError,
)


# --- Fixtures ---


@pytest.fixture
def updater():
    """Create a ReadmeUpdater with the actual template directory."""
    return ReadmeUpdater()


@pytest.fixture
def readme_with_delimiters(tmp_path):
    """Create a README file with release info delimiters."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# My API\n\nSome introduction.\n\n"
        "<!-- CAMARA:RELEASE-INFO:START -->\n"
        "## Release Information\n\n"
        "Old release info here.\n"
        "<!-- CAMARA:RELEASE-INFO:END -->\n\n"
        "## Contributing\n\nContribution guidelines.\n"
    )
    return str(readme)


@pytest.fixture
def readme_no_delimiters(tmp_path):
    """Create a README file without delimiters."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# My API\n\nSome introduction.\n\n"
        "## Release Information\n\n"
        "Manual release info.\n\n"
        "## Contributing\n\nContribution guidelines.\n"
    )
    return str(readme)


@pytest.fixture
def public_release_data():
    """Data dict for a public release scenario."""
    return {
        "repo_name": "QualityOnDemand",
        "latest_public_release": "r3.2",
        "github_url": "https://github.com/camaraproject/QualityOnDemand/releases/tag/r3.2",
        "meta_release": "Spring25",
        "formatted_apis": (
            "  * **quality-on-demand v1.1.0**\n"
            "  [[YAML]](https://github.com/camaraproject/QualityOnDemand/blob/r3.2/"
            "code/API_definitions/quality-on-demand.yaml)"
            "  [[ReDoc]](https://redocly.github.io/redoc/"
            "?url=https://raw.githubusercontent.com/camaraproject/QualityOnDemand/"
            "r3.2/code/API_definitions/quality-on-demand.yaml&nocors)"
            "  [[Swagger]](https://camaraproject.github.io/swagger-ui/"
            "?url=https://raw.githubusercontent.com/camaraproject/QualityOnDemand/"
            "r3.2/code/API_definitions/quality-on-demand.yaml)\n"
        ),
    }


@pytest.fixture
def prerelease_data():
    """Data dict for a prerelease-only scenario."""
    return {
        "repo_name": "QualityOnDemand",
        "newest_prerelease": "r4.1-rc.1",
        "prerelease_github_url": "https://github.com/camaraproject/QualityOnDemand/releases/tag/r4.1-rc.1",
        "prerelease_type": "release candidate",
        "formatted_prerelease_apis": (
            "  * **quality-on-demand v1.2.0-rc.1**\n"
            "  [[YAML]](https://github.com/camaraproject/QualityOnDemand/blob/r4.1-rc.1/"
            "code/API_definitions/quality-on-demand.yaml)\n"
        ),
    }


# --- Delimiter Checking ---


class TestDelimiterChecking:
    """Tests for delimiter validation."""

    def test_both_delimiters_present_passes(self, updater):
        """No error when both delimiters are present."""
        content = (
            "before\n"
            "<!-- CAMARA:RELEASE-INFO:START -->\n"
            "middle\n"
            "<!-- CAMARA:RELEASE-INFO:END -->\n"
            "after\n"
        )
        # Should not raise
        updater._check_delimiters(content)

    def test_missing_start_delimiter_raises_error(self, updater):
        """ReadmeUpdateError when only END delimiter exists."""
        content = "before\n<!-- CAMARA:RELEASE-INFO:END -->\nafter\n"
        with pytest.raises(ReadmeUpdateError, match="missing the start delimiter"):
            updater._check_delimiters(content)

    def test_missing_end_delimiter_raises_error(self, updater):
        """ReadmeUpdateError when only START delimiter exists."""
        content = "before\n<!-- CAMARA:RELEASE-INFO:START -->\nafter\n"
        with pytest.raises(ReadmeUpdateError, match="missing the end delimiter"):
            updater._check_delimiters(content)

    def test_missing_both_delimiters_raises_error(self, updater):
        """ReadmeUpdateError when neither delimiter exists."""
        content = "before\nsome content\nafter\n"
        with pytest.raises(ReadmeUpdateError, match="missing both"):
            updater._check_delimiters(content)


# --- Template Rendering ---


class TestTemplateRendering:
    """Tests for template selection and rendering."""

    def test_render_no_release_template(self, updater):
        """No-release template renders without variables."""
        result = updater._render_template("no_release", {})
        assert "no (pre)releases yet" in result
        assert "## Release Information" in result

    def test_render_prerelease_only_template(self, updater, prerelease_data):
        """Prerelease-only template renders with prerelease variables."""
        result = updater._render_template("prerelease_only", prerelease_data)
        assert "r4.1-rc.1" in result
        assert "release candidate" in result
        assert "latest pre-release" in result

    def test_render_public_release_template(self, updater, public_release_data):
        """Public release template renders with release variables."""
        result = updater._render_template("public_release", public_release_data)
        assert "r3.2" in result
        assert "(Spring25)" in result
        assert "latest public release" in result
        assert "releases/latest" in result

    def test_render_public_release_without_meta_release(self, updater, public_release_data):
        """Public release template omits parentheses when meta_release is empty."""
        public_release_data["meta_release"] = ""
        result = updater._render_template("public_release", public_release_data)
        assert "r3.2" in result
        assert "()" not in result

    def test_render_public_with_prerelease_template(self, updater, public_release_data, prerelease_data):
        """Public+prerelease template renders both sections."""
        data = {**public_release_data, **prerelease_data}
        result = updater._render_template("public_with_prerelease", data)
        assert "r3.2" in result
        assert "r4.1-rc.1" in result
        assert "Upcoming Release Preview" in result
        assert "NOTE" in result


# --- Content Replacement ---


class TestContentReplacement:
    """Tests for delimited content replacement."""

    def test_replace_existing_content(self, updater):
        """Replaces content between delimiters."""
        content = (
            "before\n"
            "<!-- CAMARA:RELEASE-INFO:START -->\n"
            "old content\n"
            "<!-- CAMARA:RELEASE-INFO:END -->\n"
            "after\n"
        )
        result = updater._replace_delimited_content(content, "new content\n")
        assert "new content" in result
        assert "old content" not in result

    def test_preserve_surrounding_content(self, updater):
        """Content before and after delimiters is preserved."""
        content = (
            "# Title\n\n"
            "<!-- CAMARA:RELEASE-INFO:START -->\n"
            "old\n"
            "<!-- CAMARA:RELEASE-INFO:END -->\n\n"
            "## Footer\n"
        )
        result = updater._replace_delimited_content(content, "new\n")
        assert result.startswith("# Title\n\n")
        assert result.endswith("## Footer\n")

    def test_delimiters_preserved_in_output(self, updater):
        """Both START and END delimiters remain in the output."""
        content = (
            "<!-- CAMARA:RELEASE-INFO:START -->\n"
            "old\n"
            "<!-- CAMARA:RELEASE-INFO:END -->\n"
        )
        result = updater._replace_delimited_content(content, "new\n")
        assert "<!-- CAMARA:RELEASE-INFO:START -->" in result
        assert "<!-- CAMARA:RELEASE-INFO:END -->" in result


# --- API Link Formatting ---


class TestApiLinkFormatting:
    """Tests for format_api_links static method."""

    def test_format_single_api(self):
        """Formats a single API with YAML/ReDoc/Swagger links."""
        apis = [{"file_name": "quality-on-demand", "version": "v1.1.0"}]
        result = ReadmeUpdater.format_api_links(apis, "QualityOnDemand", "r3.2")
        assert "**quality-on-demand v1.1.0**" in result
        assert "[[YAML]]" in result
        assert "[[ReDoc]]" in result
        assert "[[Swagger]]" in result

    def test_format_multiple_apis(self):
        """Formats multiple APIs with separate entries."""
        apis = [
            {"file_name": "quality-on-demand", "version": "v1.1.0"},
            {"file_name": "qos-profiles", "version": "v0.2.0"},
        ]
        result = ReadmeUpdater.format_api_links(apis, "QualityOnDemand", "r3.2")
        assert "quality-on-demand v1.1.0" in result
        assert "qos-profiles v0.2.0" in result

    def test_format_zero_apis_returns_empty(self):
        """Empty API list returns empty string."""
        result = ReadmeUpdater.format_api_links([], "QualityOnDemand", "r3.2")
        assert result == ""

    def test_format_api_links_url_patterns(self):
        """Verifies correct URL construction for each link type."""
        apis = [{"file_name": "my-api", "version": "v1.0.0"}]
        result = ReadmeUpdater.format_api_links(apis, "TestRepo", "r4.1", org="myorg")
        assert "https://github.com/myorg/TestRepo/blob/r4.1/code/API_definitions/my-api.yaml" in result
        assert "https://redocly.github.io/redoc/?url=https://raw.githubusercontent.com/myorg/TestRepo/r4.1/code/API_definitions/my-api.yaml&nocors" in result
        assert "https://camaraproject.github.io/swagger-ui/?url=https://raw.githubusercontent.com/myorg/TestRepo/r4.1/code/API_definitions/my-api.yaml" in result


# --- Full Integration ---


class TestUpdateReleaseInfo:
    """Integration tests for update_release_info."""

    def test_update_public_release(self, updater, readme_with_delimiters, public_release_data):
        """Full update with public release data modifies README."""
        changed = updater.update_release_info(
            readme_with_delimiters, "public_release", public_release_data
        )
        assert changed is True
        content = Path(readme_with_delimiters).read_text()
        assert "r3.2" in content
        assert "Spring25" in content
        assert "Old release info" not in content
        # Surrounding content preserved
        assert "# My API" in content
        assert "## Contributing" in content

    def test_update_no_release(self, updater, readme_with_delimiters):
        """Update with no_release state works."""
        changed = updater.update_release_info(
            readme_with_delimiters, "no_release", {}
        )
        assert changed is True
        content = Path(readme_with_delimiters).read_text()
        assert "no (pre)releases yet" in content

    def test_idempotent_update_returns_false(self, updater, readme_with_delimiters, public_release_data):
        """Running update twice with same data returns False on second call."""
        updater.update_release_info(
            readme_with_delimiters, "public_release", public_release_data
        )
        changed = updater.update_release_info(
            readme_with_delimiters, "public_release", public_release_data
        )
        assert changed is False

    def test_invalid_state_raises_value_error(self, updater, readme_with_delimiters):
        """Invalid release_state raises ValueError."""
        with pytest.raises(ValueError, match="Invalid release_state"):
            updater.update_release_info(
                readme_with_delimiters, "invalid_state", {}
            )

    def test_missing_delimiters_raises_error(self, updater, readme_no_delimiters):
        """Missing delimiters raises ReadmeUpdateError."""
        with pytest.raises(ReadmeUpdateError):
            updater.update_release_info(
                readme_no_delimiters, "no_release", {}
            )

    def test_triple_mustache_preserves_markdown(self, updater, readme_with_delimiters):
        """Triple-mustache renders API links without HTML escaping."""
        data = {
            "repo_name": "TestRepo",
            "newest_prerelease": "r4.1-rc.1",
            "prerelease_github_url": "https://example.com",
            "prerelease_type": "release candidate",
            "formatted_prerelease_apis": "  * **api v1.0** [[YAML]](http://example.com)\n",
        }
        updater.update_release_info(
            readme_with_delimiters, "prerelease_only", data
        )
        content = Path(readme_with_delimiters).read_text()
        # Triple-mustache should preserve the markdown without escaping
        assert "[[YAML]](http://example.com)" in content
