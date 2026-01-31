"""
Unit tests for the version calculator.

These tests verify version extension calculation for all scenarios:
- First release (no history)
- Subsequent releases (increment extension)
- Version gaps
- Public releases (no extension)
- Multiple APIs
"""

import pytest
from unittest.mock import Mock

from release_automation.scripts.github_client import Release
from release_automation.scripts.version_calculator import VersionCalculator


@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient with default behavior."""
    client = Mock()
    client.get_releases.return_value = []
    client.get_file_content.return_value = None
    return client


@pytest.fixture
def calculator(mock_github_client):
    """Create a VersionCalculator with mocked client."""
    return VersionCalculator(mock_github_client)


class TestCalculateVersion:
    """Tests for calculate_version method."""

    def test_public_release_returns_base_version(self, calculator):
        """Public status returns target version unchanged."""
        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="public"
        )
        assert result == "3.2.0"

    def test_first_rc_release_gets_extension_1(
        self, calculator, mock_github_client
    ):
        """First RC release for a version gets extension .1."""
        mock_github_client.get_releases.return_value = []

        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="rc"
        )

        assert result == "3.2.0-rc.1"

    def test_second_rc_release_gets_extension_2(
        self, calculator, mock_github_client
    ):
        """Second RC release increments extension."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r4.1", name="Release r4.1", draft=False,
                    prerelease=True, html_url="")
        ]
        mock_github_client.get_file_content.return_value = """
repository:
  release_tag: r4.1
apis:
  - api_name: location-verification
    api_version: 3.2.0-rc.1
"""

        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="rc"
        )

        assert result == "3.2.0-rc.2"

    def test_first_alpha_release_gets_extension_1(
        self, calculator, mock_github_client
    ):
        """First alpha release gets extension .1."""
        mock_github_client.get_releases.return_value = []

        result = calculator.calculate_version(
            api_name="device-status",
            target_version="1.0.0",
            target_status="alpha"
        )

        assert result == "1.0.0-alpha.1"

    def test_handles_version_gaps(self, calculator, mock_github_client):
        """Gaps in extension numbers are handled correctly."""
        # Simulate .1 and .3 exist, .2 was skipped
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r3.0", name="", draft=False, prerelease=True, html_url=""),
            Release(tag_name="r3.2", name="", draft=False, prerelease=True, html_url="")
        ]

        def get_content(path, ref):
            if ref == "r3.0":
                return """
apis:
  - api_name: test-api
    api_version: 2.0.0-rc.1
"""
            elif ref == "r3.2":
                return """
apis:
  - api_name: test-api
    api_version: 2.0.0-rc.3
"""
            return None

        mock_github_client.get_file_content.side_effect = get_content

        result = calculator.calculate_version(
            api_name="test-api",
            target_version="2.0.0",
            target_status="rc"
        )

        # Should return .4 (max existing is 3)
        assert result == "2.0.0-rc.4"

    def test_different_api_not_counted(self, calculator, mock_github_client):
        """Versions from different APIs are not counted."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r4.1", name="", draft=False, prerelease=True, html_url="")
        ]
        mock_github_client.get_file_content.return_value = """
apis:
  - api_name: other-api
    api_version: 3.2.0-rc.1
"""

        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="rc"
        )

        # Other API's version doesn't count
        assert result == "3.2.0-rc.1"

    def test_different_status_not_counted(self, calculator, mock_github_client):
        """Versions with different status are not counted."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r4.0", name="", draft=False, prerelease=True, html_url="")
        ]
        mock_github_client.get_file_content.return_value = """
apis:
  - api_name: location-verification
    api_version: 3.2.0-alpha.1
"""

        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="rc"
        )

        # Alpha version doesn't count for RC
        assert result == "3.2.0-rc.1"

    def test_different_base_version_not_counted(
        self, calculator, mock_github_client
    ):
        """Versions with different base version are not counted."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r3.0", name="", draft=False, prerelease=True, html_url="")
        ]
        mock_github_client.get_file_content.return_value = """
apis:
  - api_name: location-verification
    api_version: 3.1.0-rc.5
"""

        result = calculator.calculate_version(
            api_name="location-verification",
            target_version="3.2.0",
            target_status="rc"
        )

        # 3.1.0 doesn't count for 3.2.0
        assert result == "3.2.0-rc.1"


class TestFindExistingExtensions:
    """Tests for find_existing_extensions method."""

    def test_returns_empty_list_when_no_releases(
        self, calculator, mock_github_client
    ):
        """No releases means empty extension list."""
        mock_github_client.get_releases.return_value = []

        result = calculator.find_existing_extensions(
            api_name="test-api",
            target_version="1.0.0",
            target_status="rc"
        )

        assert result == []

    def test_returns_extensions_from_multiple_releases(
        self, calculator, mock_github_client
    ):
        """Finds extensions across multiple releases."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r3.0", name="", draft=False, prerelease=True, html_url=""),
            Release(tag_name="r3.1", name="", draft=False, prerelease=True, html_url="")
        ]

        def get_content(path, ref):
            if ref == "r3.0":
                return """
apis:
  - api_name: test-api
    api_version: 1.0.0-rc.1
"""
            elif ref == "r3.1":
                return """
apis:
  - api_name: test-api
    api_version: 1.0.0-rc.2
"""
            return None

        mock_github_client.get_file_content.side_effect = get_content

        result = calculator.find_existing_extensions(
            api_name="test-api",
            target_version="1.0.0",
            target_status="rc"
        )

        assert sorted(result) == [1, 2]

    def test_ignores_releases_without_metadata(
        self, calculator, mock_github_client
    ):
        """Releases without metadata are skipped."""
        mock_github_client.get_releases.return_value = [
            Release(tag_name="r2.0", name="", draft=False, prerelease=False, html_url=""),
            Release(tag_name="r3.0", name="", draft=False, prerelease=True, html_url="")
        ]

        def get_content(path, ref):
            if ref == "r2.0":
                return None  # No metadata
            elif ref == "r3.0":
                return """
apis:
  - api_name: test-api
    api_version: 1.0.0-rc.1
"""
            return None

        mock_github_client.get_file_content.side_effect = get_content

        result = calculator.find_existing_extensions(
            api_name="test-api",
            target_version="1.0.0",
            target_status="rc"
        )

        assert result == [1]


class TestCalculateVersionsForPlan:
    """Tests for calculate_versions_for_plan method."""

    def test_calculates_versions_for_all_apis(
        self, calculator, mock_github_client
    ):
        """Calculates versions for all APIs in plan."""
        mock_github_client.get_releases.return_value = []

        release_plan = {
            "apis": [
                {
                    "api_name": "location-verification",
                    "target_api_version": "3.2.0",
                    "target_api_status": "rc"
                },
                {
                    "api_name": "location-retrieval",
                    "target_api_version": "1.0.0",
                    "target_api_status": "public"
                }
            ]
        }

        result = calculator.calculate_versions_for_plan(release_plan)

        assert result == {
            "location-verification": "3.2.0-rc.1",
            "location-retrieval": "1.0.0"
        }

    def test_defaults_to_public_status(self, calculator, mock_github_client):
        """APIs without status default to public."""
        mock_github_client.get_releases.return_value = []

        release_plan = {
            "apis": [
                {
                    "api_name": "simple-api",
                    "target_api_version": "1.0.0"
                    # No target_api_status
                }
            ]
        }

        result = calculator.calculate_versions_for_plan(release_plan)

        assert result == {"simple-api": "1.0.0"}

    def test_handles_empty_plan(self, calculator):
        """Empty API list returns empty dict."""
        result = calculator.calculate_versions_for_plan({"apis": []})
        assert result == {}


class TestParseExtension:
    """Tests for _parse_extension private method."""

    def test_parses_valid_extension(self, calculator):
        """Correctly parses version with extension."""
        result = calculator._parse_extension(
            version="3.2.0-rc.5",
            target_version="3.2.0",
            target_status="rc"
        )
        assert result == 5

    def test_returns_none_for_mismatched_version(self, calculator):
        """Returns None when base version doesn't match."""
        result = calculator._parse_extension(
            version="3.1.0-rc.5",
            target_version="3.2.0",
            target_status="rc"
        )
        assert result is None

    def test_returns_none_for_mismatched_status(self, calculator):
        """Returns None when status doesn't match."""
        result = calculator._parse_extension(
            version="3.2.0-alpha.5",
            target_version="3.2.0",
            target_status="rc"
        )
        assert result is None

    def test_returns_none_for_public_version(self, calculator):
        """Returns None for public version (no extension)."""
        result = calculator._parse_extension(
            version="3.2.0",
            target_version="3.2.0",
            target_status="rc"
        )
        assert result is None

    def test_returns_none_for_invalid_format(self, calculator):
        """Returns None for invalid version format."""
        result = calculator._parse_extension(
            version="invalid-version",
            target_version="3.2.0",
            target_status="rc"
        )
        assert result is None
