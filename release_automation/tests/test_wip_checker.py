"""
Unit tests for wip_checker module.

Tests validate that the pre-snapshot wip version check correctly
identifies API files with non-wip versions.
"""

import os
import pytest

from release_automation.scripts.wip_checker import (
    WipCheckResult,
    WipViolation,
    check_wip_versions,
    _check_openapi_file,
    _check_feature_file,
)


# --- Helper to create file structures ---

def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _make_openapi(tmp_path, api_name, info_version="wip", server_url=None):
    """Create a minimal OpenAPI spec file."""
    spec = f"""openapi: 3.0.3
info:
  title: Test API
  version: {info_version}
"""
    if server_url is not None:
        spec += f"""servers:
  - url: "{server_url}"
"""
    spec_path = tmp_path / "code" / "API_definitions" / f"{api_name}.yaml"
    _write_file(str(spec_path), spec)
    return spec_path


def _make_feature(tmp_path, filename, content):
    """Create a .feature file in Test_definitions."""
    feature_path = tmp_path / "code" / "Test_definitions" / filename
    _write_file(str(feature_path), content)
    return feature_path


def _make_plan(*api_names):
    """Create a minimal release plan dict."""
    return {
        "apis": [{"api_name": name} for name in api_names],
    }


# --- OpenAPI info.version checks ---

class TestOpenApiInfoVersion:
    def test_compliant_wip_version(self, tmp_path):
        _make_openapi(tmp_path, "test-api", info_version="wip")
        violations = _check_openapi_file(
            str(tmp_path / "code" / "API_definitions" / "test-api.yaml"),
            str(tmp_path),
        )
        assert len(violations) == 0

    def test_non_wip_info_version(self, tmp_path):
        _make_openapi(tmp_path, "test-api", info_version="0.11.0")
        violations = _check_openapi_file(
            str(tmp_path / "code" / "API_definitions" / "test-api.yaml"),
            str(tmp_path),
        )
        assert len(violations) == 1
        assert violations[0].check_type == "info.version"
        assert violations[0].actual == "0.11.0"
        assert violations[0].expected == "wip"

    def test_missing_info_version(self, tmp_path):
        """No info.version key at all — not a violation."""
        spec_path = tmp_path / "code" / "API_definitions" / "test-api.yaml"
        _write_file(str(spec_path), "openapi: 3.0.3\ninfo:\n  title: Test\n")
        violations = _check_openapi_file(str(spec_path), str(tmp_path))
        assert len(violations) == 0


# --- OpenAPI server URL checks ---

class TestOpenApiServerUrl:
    def test_compliant_vwip_server_url(self, tmp_path):
        _make_openapi(
            tmp_path, "test-api",
            server_url="{apiRoot}/test-api/vwip",
        )
        violations = _check_openapi_file(
            str(tmp_path / "code" / "API_definitions" / "test-api.yaml"),
            str(tmp_path),
        )
        assert len(violations) == 0

    def test_non_wip_server_url(self, tmp_path):
        _make_openapi(
            tmp_path, "test-api",
            server_url="{apiRoot}/test-api/v0.11",
        )
        violations = _check_openapi_file(
            str(tmp_path / "code" / "API_definitions" / "test-api.yaml"),
            str(tmp_path),
        )
        server_violations = [v for v in violations if v.check_type == "server URL version"]
        assert len(server_violations) == 1
        assert server_violations[0].actual == "v0.11"
        assert server_violations[0].expected == "vwip"

    def test_no_servers_section(self, tmp_path):
        _make_openapi(tmp_path, "test-api")  # no server_url
        violations = _check_openapi_file(
            str(tmp_path / "code" / "API_definitions" / "test-api.yaml"),
            str(tmp_path),
        )
        assert len(violations) == 0

    def test_multiple_servers_one_non_wip(self, tmp_path):
        spec_content = """openapi: 3.0.3
info:
  title: Test API
  version: wip
servers:
  - url: "{apiRoot}/test-api/vwip"
  - url: "{apiRoot}/test-api/v1"
"""
        spec_path = tmp_path / "code" / "API_definitions" / "test-api.yaml"
        _write_file(str(spec_path), spec_content)
        violations = _check_openapi_file(str(spec_path), str(tmp_path))
        server_violations = [v for v in violations if v.check_type == "server URL version"]
        assert len(server_violations) == 1
        assert server_violations[0].actual == "v1"

    def test_non_standard_url_format_ignored(self, tmp_path):
        """Server URL not matching {apiRoot} pattern is silently skipped."""
        spec_content = """openapi: 3.0.3
info:
  title: Test API
  version: wip
servers:
  - url: "https://example.com/api/v1"
"""
        spec_path = tmp_path / "code" / "API_definitions" / "test-api.yaml"
        _write_file(str(spec_path), spec_content)
        violations = _check_openapi_file(str(spec_path), str(tmp_path))
        assert len(violations) == 0


# --- Feature file checks ---

class TestFeatureFile:
    def test_compliant_feature_header(self, tmp_path):
        _make_feature(tmp_path, "test.feature",
            'Feature: CAMARA Test API, vwip - createSession\n')
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        assert len(violations) == 0

    def test_non_wip_feature_header(self, tmp_path):
        _make_feature(tmp_path, "test.feature",
            'Feature: CAMARA Test API, v0.11.0 - createSession\n')
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        header_violations = [v for v in violations if v.check_type == "feature header version"]
        assert len(header_violations) == 1
        assert header_violations[0].actual == "v0.11.0"
        assert header_violations[0].expected == "vwip"
        assert header_violations[0].line_number == 1

    def test_compliant_resource_url(self, tmp_path):
        content = (
            'Feature: CAMARA Test API, vwip - test\n'
            '  Scenario: Get session\n'
            '    Given the resource "/test-api/vwip/sessions"\n'
        )
        _make_feature(tmp_path, "test.feature", content)
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        assert len(violations) == 0

    def test_non_wip_resource_url(self, tmp_path):
        content = (
            'Feature: CAMARA Test API, vwip - test\n'
            '  Scenario: Get session\n'
            '    Given the resource "/test-api/v0.11/sessions"\n'
        )
        _make_feature(tmp_path, "test.feature", content)
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        url_violations = [v for v in violations if v.check_type == "resource URL version"]
        assert len(url_violations) == 1
        assert url_violations[0].actual == "v0.11"
        assert url_violations[0].line_number == 3

    def test_multiple_violations_in_one_file(self, tmp_path):
        content = (
            'Feature: CAMARA Test API, v1.0.0 - test\n'
            '  Scenario: Get session\n'
            '    Given the resource "/test-api/v1/sessions"\n'
        )
        _make_feature(tmp_path, "test.feature", content)
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        assert len(violations) == 2
        types = {v.check_type for v in violations}
        assert "feature header version" in types
        assert "resource URL version" in types

    def test_path_keyword_also_matched(self, tmp_path):
        content = (
            'Feature: CAMARA Test API, vwip - test\n'
            '  Scenario: Get session\n'
            '    Given the path "/test-api/v0.5/sessions"\n'
        )
        _make_feature(tmp_path, "test.feature", content)
        violations = _check_feature_file(
            str(tmp_path / "code" / "Test_definitions" / "test.feature"),
            str(tmp_path),
        )
        assert len(violations) == 1
        assert violations[0].check_type == "resource URL version"


# --- Aggregate check_wip_versions tests ---

class TestCheckWipVersions:
    def test_all_compliant(self, tmp_path):
        _make_openapi(tmp_path, "test-api", info_version="wip",
                      server_url="{apiRoot}/test-api/vwip")
        _make_feature(tmp_path, "test.feature",
            'Feature: CAMARA Test API, vwip - test\n'
            '  Scenario: test\n'
            '    Given the resource "/test-api/vwip/sessions"\n')
        result = check_wip_versions(str(tmp_path), _make_plan("test-api"))
        assert result.compliant is True
        assert len(result.violations) == 0

    def test_mixed_violations(self, tmp_path):
        _make_openapi(tmp_path, "test-api", info_version="0.11.0",
                      server_url="{apiRoot}/test-api/v0.11")
        _make_feature(tmp_path, "test.feature",
            'Feature: CAMARA Test API, v0.11.0 - test\n')
        result = check_wip_versions(str(tmp_path), _make_plan("test-api"))
        assert result.compliant is False
        assert len(result.violations) == 3

    def test_missing_openapi_file_warning(self, tmp_path):
        # Create Test_definitions dir but no API spec
        os.makedirs(str(tmp_path / "code" / "Test_definitions"), exist_ok=True)
        result = check_wip_versions(str(tmp_path), _make_plan("missing-api"))
        assert result.compliant is True
        assert any("not found" in w for w in result.warnings)

    def test_no_test_definitions_warning(self, tmp_path):
        _make_openapi(tmp_path, "test-api", info_version="wip")
        result = check_wip_versions(str(tmp_path), _make_plan("test-api"))
        assert result.compliant is True
        assert any("Test_definitions" in w for w in result.warnings)

    def test_empty_apis_list(self, tmp_path):
        _make_feature(tmp_path, "test.feature",
            'Feature: CAMARA Test API, v1.0.0 - test\n')
        result = check_wip_versions(str(tmp_path), {"apis": []})
        assert result.compliant is False
        assert len(result.violations) == 1

    def test_multiple_apis(self, tmp_path):
        _make_openapi(tmp_path, "api-one", info_version="wip",
                      server_url="{apiRoot}/api-one/vwip")
        _make_openapi(tmp_path, "api-two", info_version="1.0.0",
                      server_url="{apiRoot}/api-two/v1")
        os.makedirs(str(tmp_path / "code" / "Test_definitions"), exist_ok=True)
        result = check_wip_versions(
            str(tmp_path), _make_plan("api-one", "api-two")
        )
        assert result.compliant is False
        # api-two has info.version + server URL violations
        assert len(result.violations) == 2


# --- Error message formatting ---

class TestFormatErrorMessage:
    def test_format_includes_all_violations(self):
        result = WipCheckResult(
            compliant=False,
            violations=[
                WipViolation(
                    file="code/API_definitions/test.yaml",
                    check_type="info.version",
                    actual="0.11.0",
                    expected="wip",
                ),
                WipViolation(
                    file="code/Test_definitions/test.feature",
                    check_type="feature header version",
                    actual="v0.11.0",
                    expected="vwip",
                    line_number=3,
                ),
            ],
        )
        msg = result.format_error_message()
        assert "\n" not in msg  # Must be single-line for GITHUB_OUTPUT
        assert "Pre-snapshot wip version check failed" in msg
        assert "code/API_definitions/test.yaml: info.version is '0.11.0'" in msg
        assert "code/Test_definitions/test.feature:3: feature header version is 'v0.11.0'" in msg
        assert " | " in msg  # Violations separated by pipe
