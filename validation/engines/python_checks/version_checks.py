"""Version-related checks.

Validates info.version format (wip vs semver by branch type), server URL
version segment construction, and server URL api-name alignment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from validation.context import ValidationContext

from ._types import load_yaml_safe, make_finding

# Matches a semantic version (optionally with pre-release label).
# Examples: "1.0.0", "0.2.0-alpha.2", "1.0.0-rc.1"
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*))?$"
)

# Extracts the version segment from a server URL path.
# Matches the last path component starting with "v".
# e.g. "https://example.com/qod/v1" -> "v1"
#      "{apiRoot}/quality-on-demand/v0.2alpha2" -> "v0.2alpha2"
_URL_VERSION_RE = re.compile(r"/(?P<version>v[a-z0-9.]+)/?$", re.IGNORECASE)

# Extracts the api-name segment from a server URL (segment before version).
# e.g. "{apiRoot}/quality-on-demand/v1" -> "quality-on-demand"
_URL_API_NAME_RE = re.compile(r"/(?P<api_name>[^/]+)/v[a-z0-9.]+/?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Version segment builder
# ---------------------------------------------------------------------------


def build_version_segment(info_version: str) -> Optional[str]:
    """Build the CAMARA URL version segment from info.version.

    Mapping rules:
      - ``"wip"`` -> ``"vwip"``
      - ``"1.0.0"`` -> ``"v1"`` (stable: major only)
      - ``"0.1.0"`` -> ``"v0.1"`` (initial: major.minor)
      - ``"0.2.0-alpha.2"`` -> ``"v0.2alpha2"`` (pre-release appended,
        dots/hyphens stripped)
      - ``"1.0.0-rc.1"`` -> ``"v1rc1"``

    Returns:
        The version segment string, or ``None`` if *info_version* is
        not a recognised format.
    """
    if info_version == "wip":
        return "vwip"

    m = _SEMVER_RE.match(info_version)
    if not m:
        return None

    major = int(m.group("major"))
    minor = int(m.group("minor"))
    pre = m.group("pre") or ""

    # Strip dots and hyphens from pre-release label.
    pre_clean = re.sub(r"[.\-]", "", pre)

    if major >= 1:
        # Stable: v{major}
        base = f"v{major}"
    else:
        # Initial: v{major}.{minor}
        base = f"v{major}.{minor}"

    return f"{base}{pre_clean}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_info_version_format(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate info.version format based on branch type.

    On main: must be ``"wip"``.
    On release/maintenance: must be a valid semantic version (not wip).
    On feature branches: no constraint (skip).
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file

    spec = load_yaml_safe(spec_path)
    if spec is None:
        # File missing or unparseable — filename check reports this.
        return []

    info_version = spec.get("info", {}).get("version")
    if info_version is None:
        return [
            make_finding(
                engine_rule="check-info-version-format",
                level="error",
                message="info.version is missing",
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        ]

    info_version = str(info_version).strip()

    if context.branch_type == "main":
        if info_version != "wip":
            return [
                make_finding(
                    engine_rule="check-info-version-format",
                    level="error",
                    message=(
                        f"info.version must be 'wip' on main branch, "
                        f"found '{info_version}'"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            ]
    elif context.branch_type in ("release", "maintenance"):
        if info_version == "wip":
            return [
                make_finding(
                    engine_rule="check-info-version-format",
                    level="error",
                    message=(
                        "info.version must not be 'wip' on "
                        f"{context.branch_type} branch"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            ]
        if not _SEMVER_RE.match(info_version):
            return [
                make_finding(
                    engine_rule="check-info-version-format",
                    level="error",
                    message=(
                        f"info.version '{info_version}' is not a valid "
                        f"semantic version on {context.branch_type} branch"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            ]

    # Feature branches: no constraint.
    return []


def check_server_url_version(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate server URL version segment matches info.version.

    Extracts the version path segment from each server URL and compares
    it against the expected segment derived from info.version using the
    CAMARA version mapping rules.
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file

    spec = load_yaml_safe(spec_path)
    if spec is None:
        return []

    info_version = str(spec.get("info", {}).get("version", "")).strip()
    if not info_version:
        return []  # Missing version is caught by check_info_version_format.

    expected_segment = build_version_segment(info_version)
    if expected_segment is None:
        return []  # Unrecognised format is caught by check_info_version_format.

    servers = spec.get("servers", [])
    if not isinstance(servers, list):
        return []

    findings: List[dict] = []
    for i, server in enumerate(servers):
        url = server.get("url", "") if isinstance(server, dict) else ""
        m = _URL_VERSION_RE.search(url)
        if m is None:
            findings.append(
                make_finding(
                    engine_rule="check-server-url-version",
                    level="error",
                    message=(
                        f"Server URL '{url}' has no recognisable version "
                        f"segment (expected '.../{expected_segment}')"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )
            continue

        actual_segment = m.group("version").lower()
        if actual_segment != expected_segment.lower():
            findings.append(
                make_finding(
                    engine_rule="check-server-url-version",
                    level="error",
                    message=(
                        f"Server URL version segment '{actual_segment}' does "
                        f"not match expected '{expected_segment}' "
                        f"(derived from info.version '{info_version}')"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings


def check_server_url_api_name(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate server URL api-name segment matches context api_name.

    The api-name in the server URL (path segment before the version)
    must match the ``api_name`` from release-plan.yaml.
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file

    spec = load_yaml_safe(spec_path)
    if spec is None:
        return []

    servers = spec.get("servers", [])
    if not isinstance(servers, list):
        return []

    findings: List[dict] = []
    for server in servers:
        url = server.get("url", "") if isinstance(server, dict) else ""
        m = _URL_API_NAME_RE.search(url)
        if m is None:
            # No api-name segment found — version check already flags bad URLs.
            continue

        url_api_name = m.group("api_name")

        # Skip hostname-like segments (contain dots) — not an api-name.
        if "." in url_api_name:
            continue

        if url_api_name != api.api_name:
            findings.append(
                make_finding(
                    engine_rule="check-server-url-api-name",
                    level="error",
                    message=(
                        f"Server URL api-name segment '{url_api_name}' does "
                        f"not match api_name '{api.api_name}' from "
                        f"release-plan.yaml"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings
