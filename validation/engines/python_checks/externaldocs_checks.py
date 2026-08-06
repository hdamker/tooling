"""externalDocs repository and description checks (Design Guide §5.4).

Design Guide §5.4 (ExternalDocs Object) is a hard SHALL: ``externalDocs.url``
must be ``https://github.com/camaraproject/{apiRepository}`` for the
repository hosting the API, and ``externalDocs.description`` must read
"Product documentation at CAMARA". No carve-out for intentional
cross-repository references — a full sweep of upstream/apis/* found zero
legitimate cases; every mismatch was a stale copy-paste or repo rename.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._types import load_yaml_safe, make_finding

_URL_ENGINE_RULE = "check-externaldocs-repository"
_DESCRIPTION_ENGINE_RULE = "check-externaldocs-description"

_EXPECTED_DESCRIPTION = "Product documentation at CAMARA"


def check_externaldocs(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate externalDocs.url and externalDocs.description.

    Per-API check. Emits two distinct engine_rule values from the same
    externalDocs node so the postfilter can give them different
    severities (P-038 warn, P-039 hint):

    - P-038 (check-externaldocs-repository): externalDocs missing
      entirely, or url is not exactly
      https://github.com/camaraproject/{repo-name}.
    - P-039 (check-externaldocs-description): description is not
      exactly "Product documentation at CAMARA". Only checked when
      externalDocs is present — a missing object is a single P-038
      finding, not P-038 + P-039.

    Match is strict exact-string (no trailing-slash tolerance, no
    case-insensitive description match) — matches the Design Guide
    template literally.
    """
    api = context.apis[0]
    spec_path = repo_path / api.spec_file
    spec = load_yaml_safe(spec_path)

    if spec is None:
        return []

    repo_name = context.repository.rsplit("/", 1)[-1]
    expected_url = f"https://github.com/camaraproject/{repo_name}"

    external_docs = spec.get("externalDocs")

    if not isinstance(external_docs, dict):
        return [
            make_finding(
                engine_rule=_URL_ENGINE_RULE,
                level="warn",
                message=(
                    f"externalDocs is missing in {api.spec_file} — "
                    f"expected url '{expected_url}'"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        ]

    findings: List[dict] = []

    url = external_docs.get("url")
    if url != expected_url:
        actual = "is missing" if url is None else f"is '{url}'"
        findings.append(
            make_finding(
                engine_rule=_URL_ENGINE_RULE,
                level="warn",
                message=(
                    f"externalDocs.url in {api.spec_file} {actual} — "
                    f"expected '{expected_url}'"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        )

    description = external_docs.get("description")
    if description != _EXPECTED_DESCRIPTION:
        actual = "is missing" if description is None else f"is '{description}'"
        findings.append(
            make_finding(
                engine_rule=_DESCRIPTION_ENGINE_RULE,
                level="hint",
                message=(
                    f"externalDocs.description in {api.spec_file} {actual} "
                    f"— expected '{_EXPECTED_DESCRIPTION}'"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        )

    return findings
