"""Shared OpenAPI spec traversal helpers for Python checks.

Provides utilities for navigating CAMARA OpenAPI spec structures:
local $ref resolution, schema property collection, event type
extraction, and enum value search.

Design constraints:
  - Only resolves local $ref (starting with ``#/``).
  - Follows ``allOf`` one level deep — sufficient for CAMARA patterns.
  - No external I/O — operates on parsed spec dicts only.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local $ref resolution
# ---------------------------------------------------------------------------


def resolve_local_ref(spec: dict, ref: str) -> Optional[dict]:
    """Resolve a local JSON Reference within a parsed OpenAPI spec.

    Handles ``#/components/schemas/Foo`` style references by walking
    the spec dict along the path segments.

    Returns ``None`` if the reference is external, malformed, or the
    target path does not exist.
    """
    if not ref or not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    current: object = spec
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current if isinstance(current, dict) else None


# ---------------------------------------------------------------------------
# Schema property collection
# ---------------------------------------------------------------------------


def collect_schema_properties(
    spec: dict, schema: dict
) -> Dict[str, dict]:
    """Collect all property definitions from a schema.

    Walks direct ``properties`` and follows ``allOf`` compositions one
    level deep (resolving ``$ref`` within ``allOf`` entries).

    Returns a dict mapping property names to their schema definitions.
    """
    props: Dict[str, dict] = {}

    # Direct properties
    direct = schema.get("properties")
    if isinstance(direct, dict):
        props.update(direct)

    # allOf compositions
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for entry in all_of:
            if not isinstance(entry, dict):
                continue
            # Resolve $ref if present
            if "$ref" in entry:
                resolved = resolve_local_ref(spec, entry["$ref"])
                if resolved is not None:
                    sub_props = resolved.get("properties")
                    if isinstance(sub_props, dict):
                        props.update(sub_props)
            else:
                sub_props = entry.get("properties")
                if isinstance(sub_props, dict):
                    props.update(sub_props)

    return props


# ---------------------------------------------------------------------------
# Event type extraction
# ---------------------------------------------------------------------------


def extract_event_types_from_spec(spec: dict) -> List[str]:
    """Extract all event type enum values from a CAMARA subscription spec.

    Searches ``components/schemas`` for schemas whose name contains
    ``EventType`` (case-insensitive) and collects their ``enum`` values.

    This covers the standard CAMARA patterns:
      - ``SubscriptionEventType`` (API-specific events for subscription requests)
      - ``EventTypeNotification`` (all events including lifecycle)
      - ``ApiEventType`` (template pattern)
      - ``SubscriptionLifecycleEventType`` (template pattern)

    Returns a deduplicated list of event type strings.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return []

    event_types: set[str] = set()
    for schema_name, schema_def in schemas.items():
        if not isinstance(schema_def, dict):
            continue
        if "eventtype" not in schema_name.lower():
            continue
        enum_values = schema_def.get("enum")
        if isinstance(enum_values, list):
            for val in enum_values:
                if isinstance(val, str):
                    event_types.add(val)

    return sorted(event_types)


# ---------------------------------------------------------------------------
# Enum value search
# ---------------------------------------------------------------------------


def find_enum_value_in_schemas(
    spec: dict, target: str
) -> List[Tuple[str, List[str]]]:
    """Search all component schemas for a specific enum value.

    Walks ``components/schemas`` and checks every ``enum`` list
    (including nested ``properties`` and ``allOf`` compositions).

    Args:
        spec: Parsed OpenAPI spec dict.
        target: The enum value to search for (exact match).

    Returns:
        List of ``(schema_path, enum_values)`` tuples where *target*
        was found.  *schema_path* is a dot-separated location string.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return []

    results: List[Tuple[str, List[str]]] = []
    for schema_name, schema_def in schemas.items():
        if not isinstance(schema_def, dict):
            continue
        _search_enum_recursive(
            spec, schema_def, f"components.schemas.{schema_name}",
            target, results,
        )
    return results


def _search_enum_recursive(
    spec: dict,
    node: dict,
    path: str,
    target: str,
    results: List[Tuple[str, List[str]]],
) -> None:
    """Recursively search a schema node for enums containing *target*."""
    # Check direct enum
    enum_values = node.get("enum")
    if isinstance(enum_values, list) and target in enum_values:
        results.append((path, list(enum_values)))

    # Check properties
    props = node.get("properties")
    if isinstance(props, dict):
        for prop_name, prop_def in props.items():
            if isinstance(prop_def, dict):
                _search_enum_recursive(
                    spec, prop_def, f"{path}.{prop_name}",
                    target, results,
                )

    # Check allOf entries
    all_of = node.get("allOf")
    if isinstance(all_of, list):
        for i, entry in enumerate(all_of):
            if not isinstance(entry, dict):
                continue
            if "$ref" in entry:
                resolved = resolve_local_ref(spec, entry["$ref"])
                if resolved is not None:
                    _search_enum_recursive(
                        spec, resolved, f"{path}.allOf[{i}]",
                        target, results,
                    )
            else:
                _search_enum_recursive(
                    spec, entry, f"{path}.allOf[{i}]",
                    target, results,
                )


# ---------------------------------------------------------------------------
# Property name search
# ---------------------------------------------------------------------------


def find_properties_by_name(
    spec: dict, property_name: str
) -> List[Tuple[str, dict]]:
    """Find all schemas in ``components/schemas`` containing a named property.

    Walks top-level schemas and their ``allOf`` compositions (one level).

    Args:
        spec: Parsed OpenAPI spec dict.
        property_name: The property name to search for.

    Returns:
        List of ``(schema_name, property_schema)`` tuples.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return []

    results: List[Tuple[str, dict]] = []
    for schema_name, schema_def in schemas.items():
        if not isinstance(schema_def, dict):
            continue
        all_props = collect_schema_properties(spec, schema_def)
        if property_name in all_props:
            results.append((schema_name, all_props[property_name]))

    return results


# ---------------------------------------------------------------------------
# Response schema iteration
# ---------------------------------------------------------------------------


def iter_response_schemas(
    spec: dict, path_prefix: str = ""
) -> Iterable[Tuple[str, str, str, dict]]:
    """Yield response schemas from OpenAPI paths.

    For each path matching *path_prefix*, yields
    ``(path, method, status_code, resolved_schema)`` for every
    response that has ``content.application/json.schema``.

    Schema ``$ref`` is resolved one level.

    Args:
        spec: Parsed OpenAPI spec dict.
        path_prefix: Only yield from paths containing this string.
            Empty string matches all paths.
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return

    for path_key, path_item in paths.items():
        if path_prefix and path_prefix not in path_key:
            continue
        if not isinstance(path_item, dict):
            continue

        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue

            for status_code, response_def in responses.items():
                if not isinstance(response_def, dict):
                    continue

                # Resolve response-level $ref
                if "$ref" in response_def:
                    resolved = resolve_local_ref(spec, response_def["$ref"])
                    if resolved is None:
                        continue
                    response_def = resolved

                content = response_def.get("content", {})
                if not isinstance(content, dict):
                    continue

                json_content = content.get("application/json")
                if not isinstance(json_content, dict):
                    continue

                schema = json_content.get("schema")
                if not isinstance(schema, dict):
                    continue

                # Resolve schema-level $ref
                if "$ref" in schema:
                    resolved = resolve_local_ref(spec, schema["$ref"])
                    if resolved is not None:
                        schema = resolved

                # Handle array responses (e.g. GET /subscriptions)
                if schema.get("type") == "array":
                    items = schema.get("items")
                    if isinstance(items, dict):
                        if "$ref" in items:
                            resolved = resolve_local_ref(spec, items["$ref"])
                            if resolved is not None:
                                yield (path_key, method, status_code, resolved)
                        else:
                            yield (path_key, method, status_code, items)
                    continue

                yield (path_key, method, status_code, schema)
