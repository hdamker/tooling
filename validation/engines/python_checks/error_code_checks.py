"""Error code and contextCode checks.

Validates error code deprecation (CONFLICT) and contextCode naming
conventions introduced in Commonalities r4.x.

Design doc references:
  - Design Guide section 3.2: error response table (CONFLICT deprecated)
  - Design Guide section 3.1.3: contextCode SCREAMING_SNAKE_CASE
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._spec_helpers import find_enum_value_in_schemas, find_properties_by_name
from ._types import load_yaml_safe, make_finding

# contextCode values: API_NAME.SPECIFIC_CODE or PLAIN_CODE
# Both parts in SCREAMING_SNAKE_CASE.
_SCREAMING_SNAKE_RE = re.compile(
    r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*"
    r"(\.[A-Z][A-Z0-9]*(_[A-Z0-9]+)*)?$"
)


# ---------------------------------------------------------------------------
# P-017 (DG-018): check-conflict-deprecated
# ---------------------------------------------------------------------------


def check_conflict_deprecated(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Warn if the CONFLICT error code is used.

    Design Guide section 3.2: "CONFLICT — Duplication of an existing
    resource (This Error Code is DEPRECATED)".

    Searches all component schema enums for the value ``"CONFLICT"``.
    Applicability (post-filter): ``commonalities_release >= r4.0``.
    """
    api = context.apis[0]
    spec = load_yaml_safe(repo_path / api.spec_file)
    if spec is None:
        return []

    matches = find_enum_value_in_schemas(spec, "CONFLICT")
    if not matches:
        return []

    findings: List[dict] = []
    for schema_path, _ in matches:
        findings.append(
            make_finding(
                engine_rule="check-conflict-deprecated",
                level="warn",
                message=(
                    f"Error code 'CONFLICT' is deprecated in Commonalities "
                    f"r4.x — use 'ALREADY_EXISTS' or a specific error code "
                    f"(found in {schema_path})"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# P-018 (DG-011): check-contextcode-format
# ---------------------------------------------------------------------------


def check_contextcode_format(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate contextCode enum values follow SCREAMING_SNAKE_CASE.

    Design Guide section 3.1.3: "API-specific codes following CAMARA
    conventions (API_NAME.SPECIFIC_CODE in SCREAMING_SNAKE_CASE)".

    The contextCode field is optional. This check only fires when a
    ``contextCode`` property is found in the spec.
    Applicability (post-filter): ``commonalities_release >= r4.0``.
    """
    api = context.apis[0]
    spec = load_yaml_safe(repo_path / api.spec_file)
    if spec is None:
        return []

    results = find_properties_by_name(spec, "contextCode")
    if not results:
        return []

    findings: List[dict] = []
    for schema_name, prop_schema in results:
        enum_values = prop_schema.get("enum")
        if not isinstance(enum_values, list):
            # contextCode without enum — recommend adding one
            findings.append(
                make_finding(
                    engine_rule="check-contextcode-format",
                    level="hint",
                    message=(
                        f"contextCode in {schema_name} has no enum "
                        f"constraint — enum is recommended per Design "
                        f"Guide section 3.1.3"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )
            continue

        # Validate each enum value
        for val in enum_values:
            if not isinstance(val, str):
                continue
            if not _SCREAMING_SNAKE_RE.match(val):
                findings.append(
                    make_finding(
                        engine_rule="check-contextcode-format",
                        level="hint",
                        message=(
                            f"contextCode value '{val}' in {schema_name} "
                            f"does not follow SCREAMING_SNAKE_CASE format "
                            f"(expected API_NAME.SPECIFIC_CODE)"
                        ),
                        path=api.spec_file,
                        line=1,
                        api_name=api.api_name,
                    )
                )

    return findings
