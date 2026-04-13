"""Subscription API checks.

Validates naming conventions, event type formats, and response schema
constraints specific to CAMARA subscription APIs.

Design doc references:
  - Event Subscription Guide section 2.2: explicit subscription naming
  - Event Subscription Guide section 2.3: event type format
  - Event Subscription Guide section 2.2.3: sinkCredential in responses
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from validation.context import ValidationContext

from ._spec_helpers import (
    collect_schema_properties,
    extract_event_types_from_spec,
    iter_response_schemas,
    resolve_local_ref,
)
from ._types import load_yaml_safe, make_finding

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Event type format: org.camaraproject.<api-name>.<vN>.<event-name>
_EVENT_TYPE_RE = re.compile(
    r"^org\.camaraproject\."
    r"(?P<api_name>[a-z0-9][a-z0-9-]*)"
    r"\.(?P<event_version>v\d+)"
    r"\.(?P<event_name>[a-z][a-z0-9-]*)$"
)


# ---------------------------------------------------------------------------
# P-014 (DG-088): check-subscription-filename
# ---------------------------------------------------------------------------


def check_subscription_filename(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate subscription API filename ends with '-subscriptions'.

    Event Subscription Guide section 2.2: "it is mandatory to append
    the keyword 'subscriptions' at the end of the API name."

    Only applies to explicit-subscription APIs.
    """
    api = context.apis[0]

    if api.api_pattern != "explicit-subscription":
        return []

    if api.api_name.endswith("-subscriptions"):
        return []

    return [
        make_finding(
            engine_rule="check-subscription-filename",
            level="warn",
            message=(
                f"Explicit subscription API name '{api.api_name}' should "
                f"end with '-subscriptions' (e.g. "
                f"'{api.api_name}-subscriptions')"
            ),
            path=api.spec_file,
            line=1,
            api_name=api.api_name,
        )
    ]


# ---------------------------------------------------------------------------
# P-015 (DG-086): check-event-type-format
# ---------------------------------------------------------------------------


def check_event_type_format(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate event type values follow the CAMARA format.

    Event Subscription Guide section 2.3: event type MUST follow
    ``org.camaraproject.<api-name>.<event-version>.<event-name>``.
    Event version format is ``vN`` (v0, v1, etc.).

    Applies to explicit-subscription and implicit-subscription APIs.
    """
    api = context.apis[0]

    if api.api_pattern not in ("explicit-subscription", "implicit-subscription"):
        return []

    spec = load_yaml_safe(repo_path / api.spec_file)
    if spec is None:
        return []

    event_types = extract_event_types_from_spec(spec)
    if not event_types:
        return [
            make_finding(
                engine_rule="check-event-type-format",
                level="hint",
                message=(
                    f"No event type enum values found in {api.spec_file} "
                    f"— subscription APIs should define EventType schemas"
                ),
                path=api.spec_file,
                line=1,
                api_name=api.api_name,
            )
        ]

    findings: List[dict] = []
    for event_type in event_types:
        m = _EVENT_TYPE_RE.match(event_type)
        if m is None:
            findings.append(
                make_finding(
                    engine_rule="check-event-type-format",
                    level="error",
                    message=(
                        f"Event type '{event_type}' does not match expected "
                        f"format 'org.camaraproject.<api-name>.<vN>.<event-name>'"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )
            continue

        # Verify api-name segment matches the API name from context
        type_api_name = m.group("api_name")
        if type_api_name != api.api_name:
            findings.append(
                make_finding(
                    engine_rule="check-event-type-format",
                    level="error",
                    message=(
                        f"Event type '{event_type}' has api-name segment "
                        f"'{type_api_name}' which does not match API name "
                        f"'{api.api_name}'"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# P-016 (DG-092): check-sinkcredential-not-in-response
# ---------------------------------------------------------------------------


def check_sinkcredential_not_in_response(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Validate sinkCredential does not appear in subscription responses.

    Event Subscription Guide section 2.2.3: "The sinkCredential MUST
    NOT be present in POST and GET responses."

    Inspects 2xx response schemas for paths containing ``/subscriptions``
    and checks for ``sinkCredential`` in their properties (including
    ``allOf`` compositions).
    """
    api = context.apis[0]

    if api.api_pattern != "explicit-subscription":
        return []

    spec = load_yaml_safe(repo_path / api.spec_file)
    if spec is None:
        return []

    findings: List[dict] = []
    seen_schemas: set[str] = set()

    for path, method, status_code, schema in iter_response_schemas(
        spec, "/subscriptions"
    ):
        # Only check 2xx success responses
        if not status_code.startswith("2"):
            continue

        # Collect properties from the resolved schema
        all_props = collect_schema_properties(spec, schema)
        if "sinkCredential" in all_props:
            # Deduplicate: same underlying schema may appear in multiple
            # responses (e.g. POST 201 and GET 200 both use Subscription)
            schema_id = id(schema)
            if schema_id in seen_schemas:
                continue
            seen_schemas.add(schema_id)

            findings.append(
                make_finding(
                    engine_rule="check-sinkcredential-not-in-response",
                    level="error",
                    message=(
                        f"sinkCredential found in {method.upper()} "
                        f"{path} {status_code} response schema — "
                        f"sinkCredential MUST NOT appear in responses"
                    ),
                    path=api.spec_file,
                    line=1,
                    api_name=api.api_name,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# P-020: check-cloudevent-via-ref
# ---------------------------------------------------------------------------


def check_cloudevent_via_ref(
    repo_path: Path, context: ValidationContext
) -> List[dict]:
    """Warn when CloudEvent is defined inline instead of via $ref.

    Subscription APIs should consume the shared CloudEvent schema from
    CAMARA_event_common.yaml via ``$ref`` (or ``allOf`` + ``$ref``) rather
    than maintaining a local inline copy. Inline copies drift from the
    Commonalities source and block bundling-based reuse.

    Detection: the rule fires when ``components.schemas.CloudEvent`` is
    present and has a top-level ``properties`` key. The ``$ref``-only
    form and the ``allOf: [{$ref: ...}]`` migration form have no
    top-level ``properties`` and are not flagged.
    """
    api = context.apis[0]

    if api.api_pattern not in ("explicit-subscription", "implicit-subscription"):
        return []

    if api.spec_file.endswith("CAMARA_event_common.yaml"):
        return []

    spec = load_yaml_safe(repo_path / api.spec_file)
    if spec is None:
        return []

    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return []

    cloudevent = schemas.get("CloudEvent")
    if not isinstance(cloudevent, dict):
        return []

    if "properties" not in cloudevent:
        return []

    return [
        make_finding(
            engine_rule="check-cloudevent-via-ref",
            level="warn",
            message=(
                f"CloudEvent is defined inline in {api.spec_file}. "
                f"Consume the shared schema from CAMARA_event_common.yaml "
                f"via $ref instead of maintaining a local copy."
            ),
            path=api.spec_file,
            line=1,
            api_name=api.api_name,
        )
    ]
