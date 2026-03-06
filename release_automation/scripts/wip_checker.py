"""
Pre-snapshot wip version checker for CAMARA release automation.

Validates that all API files on the source branch use 'wip' versions
before snapshot creation applies version transformations. This is an
interim check that will be replaced by the validation framework v1.
"""

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class WipViolation:
    """A single wip version violation."""
    file: str
    check_type: str
    actual: str
    expected: str
    line_number: Optional[int] = None


@dataclass
class WipCheckResult:
    """Result of wip version compliance check."""
    compliant: bool
    violations: List[WipViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def format_error_message(self) -> str:
        """Format violations into a single-line error message.

        Single-line because GitHub Actions GITHUB_OUTPUT truncates
        at newlines when using key=value format.
        """
        parts = []
        for v in self.violations:
            file_ref = v.file
            if v.line_number is not None:
                file_ref = f"{v.file}:{v.line_number}"
            parts.append(
                f"{file_ref}: {v.check_type} is '{v.actual}', "
                f"expected '{v.expected}'"
            )
        return (
            "Pre-snapshot wip version check failed: "
            + " | ".join(parts)
        )


# Server URL pattern: {apiRoot}/<api-name>/<version>
SERVER_URL_PATTERN = re.compile(r'^\{apiRoot\}/[\w-]+/(v[\w.-]+)$')

# Feature header: "Feature: ..., vX.Y.Z"
FEATURE_VERSION_PATTERN = re.compile(r'Feature:.*,\s*(v[\w.-]+)', re.IGNORECASE)

# Resource URL in Gherkin steps
RESOURCE_URL_PATTERN = re.compile(
    r'(?:the resource|the path)\s+["\x27`]([^"\x27`]+)["\x27`]',
    re.IGNORECASE,
)

# Extract version segment from URL path
URL_VERSION_PATTERN = re.compile(r'(?:^|/)[\w-]+/(v[\w.-]+)/', re.IGNORECASE)


def check_wip_versions(
    repo_path: str,
    release_plan: Dict[str, Any],
) -> WipCheckResult:
    """
    Check that all API files use wip versions.

    Args:
        repo_path: Path to cloned repository root
        release_plan: Parsed release-plan.yaml

    Returns:
        WipCheckResult with violations list
    """
    violations: List[WipViolation] = []
    warnings: List[str] = []

    # Check OpenAPI specs for each API in the release plan
    for api in release_plan.get("apis", []):
        api_name = api.get("api_name")
        if not api_name:
            continue

        spec_path = os.path.join(
            repo_path, "code", "API_definitions", f"{api_name}.yaml"
        )
        if not os.path.exists(spec_path):
            warnings.append(
                f"OpenAPI spec not found: code/API_definitions/{api_name}.yaml"
            )
            continue

        violations.extend(_check_openapi_file(spec_path, repo_path))

    # Check all feature files
    test_dir = os.path.join(repo_path, "code", "Test_definitions")
    if os.path.isdir(test_dir):
        feature_files = glob.glob(os.path.join(test_dir, "*.feature"))
        for feature_path in sorted(feature_files):
            violations.extend(_check_feature_file(feature_path, repo_path))
    else:
        warnings.append("No code/Test_definitions/ directory found")

    return WipCheckResult(
        compliant=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )


def _check_openapi_file(
    file_path: str,
    repo_path: str,
) -> List[WipViolation]:
    """Check a single OpenAPI YAML file for wip compliance."""
    violations: List[WipViolation] = []
    rel_path = os.path.relpath(file_path, repo_path)

    try:
        with open(file_path, "r") as f:
            doc = yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        return violations

    if not isinstance(doc, dict):
        return violations

    # Check info.version
    info_version = doc.get("info", {}).get("version")
    if info_version is not None and str(info_version) != "wip":
        violations.append(WipViolation(
            file=rel_path,
            check_type="info.version",
            actual=str(info_version),
            expected="wip",
        ))

    # Check servers[].url
    servers = doc.get("servers", [])
    if isinstance(servers, list):
        for server in servers:
            url = server.get("url", "") if isinstance(server, dict) else ""
            if not isinstance(url, str):
                continue
            match = SERVER_URL_PATTERN.match(url)
            if match:
                version_segment = match.group(1)
                if version_segment != "vwip":
                    violations.append(WipViolation(
                        file=rel_path,
                        check_type="server URL version",
                        actual=version_segment,
                        expected="vwip",
                    ))

    return violations


def _check_feature_file(
    file_path: str,
    repo_path: str,
) -> List[WipViolation]:
    """Check a single Gherkin .feature file for wip compliance."""
    violations: List[WipViolation] = []
    rel_path = os.path.relpath(file_path, repo_path)

    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except IOError:
        return violations

    for i, line in enumerate(lines):
        line_number = i + 1

        # Check Feature header version
        feature_match = FEATURE_VERSION_PATTERN.search(line)
        if feature_match:
            version = feature_match.group(1)
            if version.lower() != "vwip":
                violations.append(WipViolation(
                    file=rel_path,
                    check_type="feature header version",
                    actual=version,
                    expected="vwip",
                    line_number=line_number,
                ))

        # Check resource/path URLs
        for resource_match in RESOURCE_URL_PATTERN.finditer(line):
            url = resource_match.group(1)
            version_match = URL_VERSION_PATTERN.search(url)
            if version_match:
                version = version_match.group(1)
                if version.lower() != "vwip":
                    violations.append(WipViolation(
                        file=rel_path,
                        check_type="resource URL version",
                        actual=version,
                        expected="vwip",
                        line_number=line_number,
                    ))

    return violations
