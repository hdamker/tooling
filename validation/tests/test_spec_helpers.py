"""Unit tests for validation.engines.python_checks._spec_helpers."""

from __future__ import annotations

from validation.engines.python_checks._spec_helpers import (
    collect_schema_properties,
    extract_event_types_from_spec,
    find_enum_value_in_schemas,
    find_properties_by_name,
    iter_response_schemas,
    resolve_local_ref,
)


# ---------------------------------------------------------------------------
# resolve_local_ref
# ---------------------------------------------------------------------------


class TestResolveLocalRef:
    def test_simple_ref(self):
        spec = {"components": {"schemas": {"Foo": {"type": "object"}}}}
        result = resolve_local_ref(spec, "#/components/schemas/Foo")
        assert result == {"type": "object"}

    def test_nested_ref(self):
        spec = {"components": {"responses": {"NotFound": {"description": "nf"}}}}
        result = resolve_local_ref(spec, "#/components/responses/NotFound")
        assert result == {"description": "nf"}

    def test_missing_path(self):
        spec = {"components": {"schemas": {}}}
        assert resolve_local_ref(spec, "#/components/schemas/Missing") is None

    def test_external_ref(self):
        assert resolve_local_ref({}, "../common/Foo.yaml#/bar") is None

    def test_empty_ref(self):
        assert resolve_local_ref({}, "") is None

    def test_non_dict_target(self):
        spec = {"components": {"schemas": {"Foo": "not-a-dict"}}}
        assert resolve_local_ref(spec, "#/components/schemas/Foo") is None


# ---------------------------------------------------------------------------
# collect_schema_properties
# ---------------------------------------------------------------------------


class TestCollectSchemaProperties:
    def test_direct_properties(self):
        spec = {}
        schema = {"properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
        props = collect_schema_properties(spec, schema)
        assert set(props.keys()) == {"name", "age"}

    def test_allof_inline(self):
        spec = {}
        schema = {
            "allOf": [
                {"properties": {"base": {"type": "string"}}},
                {"properties": {"extra": {"type": "integer"}}},
            ]
        }
        props = collect_schema_properties(spec, schema)
        assert set(props.keys()) == {"base", "extra"}

    def test_allof_with_ref(self):
        spec = {
            "components": {
                "schemas": {
                    "Base": {"properties": {"id": {"type": "string"}}}
                }
            }
        }
        schema = {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"properties": {"extra": {"type": "integer"}}},
            ]
        }
        props = collect_schema_properties(spec, schema)
        assert set(props.keys()) == {"id", "extra"}

    def test_mixed_direct_and_allof(self):
        spec = {}
        schema = {
            "properties": {"direct": {"type": "string"}},
            "allOf": [{"properties": {"composed": {"type": "integer"}}}],
        }
        props = collect_schema_properties(spec, schema)
        assert set(props.keys()) == {"direct", "composed"}

    def test_external_ref_in_allof(self):
        """External $ref in allOf is skipped (returns None from resolve)."""
        spec = {}
        schema = {
            "allOf": [
                {"$ref": "../common/Foo.yaml#/components/schemas/Bar"},
                {"properties": {"local": {"type": "string"}}},
            ]
        }
        props = collect_schema_properties(spec, schema)
        assert set(props.keys()) == {"local"}

    def test_empty_schema(self):
        assert collect_schema_properties({}, {}) == {}


# ---------------------------------------------------------------------------
# extract_event_types_from_spec
# ---------------------------------------------------------------------------


class TestExtractEventTypes:
    def test_subscription_event_type(self):
        spec = {
            "components": {
                "schemas": {
                    "SubscriptionEventType": {
                        "type": "string",
                        "enum": [
                            "org.camaraproject.device-status.v0.roaming-on",
                            "org.camaraproject.device-status.v0.roaming-off",
                        ],
                    }
                }
            }
        }
        result = extract_event_types_from_spec(spec)
        assert len(result) == 2
        assert "org.camaraproject.device-status.v0.roaming-on" in result

    def test_multiple_event_type_schemas(self):
        """Both SubscriptionEventType and EventTypeNotification are found."""
        spec = {
            "components": {
                "schemas": {
                    "SubscriptionEventType": {
                        "type": "string",
                        "enum": ["org.camaraproject.foo.v0.bar"],
                    },
                    "EventTypeNotification": {
                        "type": "string",
                        "enum": [
                            "org.camaraproject.foo.v0.bar",
                            "org.camaraproject.foo.v0.subscription-ended",
                        ],
                    },
                }
            }
        }
        result = extract_event_types_from_spec(spec)
        assert len(result) == 2  # deduplicated

    def test_api_event_type_template_pattern(self):
        """Template uses ApiEventType schema name."""
        spec = {
            "components": {
                "schemas": {
                    "ApiEventType": {
                        "type": "string",
                        "enum": [
                            "org.camaraproject.api-name.v0.event-type1",
                            "org.camaraproject.api-name.v0.event-type2",
                        ],
                    },
                    "SubscriptionLifecycleEventType": {
                        "type": "string",
                        "enum": [
                            "org.camaraproject.api-name.v0.subscription-started",
                            "org.camaraproject.api-name.v0.subscription-ended",
                        ],
                    },
                }
            }
        }
        result = extract_event_types_from_spec(spec)
        assert len(result) == 4

    def test_no_event_type_schemas(self):
        spec = {"components": {"schemas": {"Foo": {"type": "object"}}}}
        assert extract_event_types_from_spec(spec) == []

    def test_no_components(self):
        assert extract_event_types_from_spec({}) == []

    def test_schema_without_enum(self):
        spec = {
            "components": {
                "schemas": {
                    "EventTypeNotification": {"type": "string"}
                }
            }
        }
        assert extract_event_types_from_spec(spec) == []


# ---------------------------------------------------------------------------
# find_enum_value_in_schemas
# ---------------------------------------------------------------------------


class TestFindEnumValueInSchemas:
    def test_find_in_top_level_enum(self):
        spec = {
            "components": {
                "schemas": {
                    "ErrorCode": {"type": "string", "enum": ["INVALID", "CONFLICT", "NOT_FOUND"]}
                }
            }
        }
        results = find_enum_value_in_schemas(spec, "CONFLICT")
        assert len(results) == 1
        assert "ErrorCode" in results[0][0]

    def test_find_in_nested_property(self):
        spec = {
            "components": {
                "schemas": {
                    "ErrorInfo": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": ["INVALID", "CONFLICT"],
                            }
                        },
                    }
                }
            }
        }
        results = find_enum_value_in_schemas(spec, "CONFLICT")
        assert len(results) == 1
        assert "code" in results[0][0]

    def test_not_found(self):
        spec = {
            "components": {
                "schemas": {
                    "ErrorCode": {"type": "string", "enum": ["INVALID", "NOT_FOUND"]}
                }
            }
        }
        assert find_enum_value_in_schemas(spec, "CONFLICT") == []

    def test_find_in_allof_ref(self):
        spec = {
            "components": {
                "schemas": {
                    "Base": {
                        "properties": {
                            "status": {"type": "string", "enum": ["OK", "CONFLICT"]}
                        }
                    },
                    "Extended": {
                        "allOf": [{"$ref": "#/components/schemas/Base"}]
                    },
                }
            }
        }
        results = find_enum_value_in_schemas(spec, "CONFLICT")
        # Found in Base directly and in Extended via allOf
        assert len(results) >= 1

    def test_empty_spec(self):
        assert find_enum_value_in_schemas({}, "CONFLICT") == []


# ---------------------------------------------------------------------------
# find_properties_by_name
# ---------------------------------------------------------------------------


class TestFindPropertiesByName:
    def test_direct_property(self):
        spec = {
            "components": {
                "schemas": {
                    "Subscription": {
                        "properties": {
                            "sinkCredential": {"$ref": "#/components/schemas/SinkCredential"},
                            "sink": {"type": "string"},
                        }
                    }
                }
            }
        }
        results = find_properties_by_name(spec, "sinkCredential")
        assert len(results) == 1
        assert results[0][0] == "Subscription"

    def test_property_via_allof(self):
        spec = {
            "components": {
                "schemas": {
                    "Base": {
                        "properties": {"sinkCredential": {"type": "object"}}
                    },
                    "Extended": {
                        "allOf": [
                            {"$ref": "#/components/schemas/Base"},
                            {"properties": {"extra": {"type": "string"}}},
                        ]
                    },
                }
            }
        }
        results = find_properties_by_name(spec, "sinkCredential")
        assert len(results) == 2  # Found in both Base and Extended

    def test_property_not_found(self):
        spec = {
            "components": {
                "schemas": {
                    "Foo": {"properties": {"bar": {"type": "string"}}}
                }
            }
        }
        assert find_properties_by_name(spec, "sinkCredential") == []

    def test_external_ref_property(self):
        """Property with external $ref is still found by name."""
        spec = {
            "components": {
                "schemas": {
                    "SubscriptionRequest": {
                        "properties": {
                            "sinkCredential": {
                                "$ref": "../common/CAMARA_event_common.yaml#/components/schemas/SinkCredential"
                            }
                        }
                    }
                }
            }
        }
        results = find_properties_by_name(spec, "sinkCredential")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# iter_response_schemas
# ---------------------------------------------------------------------------


class TestIterResponseSchemas:
    def test_simple_response(self):
        spec = {
            "paths": {
                "/subscriptions": {
                    "post": {
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": {"id": {"type": "string"}}}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        results = list(iter_response_schemas(spec, "/subscriptions"))
        assert len(results) == 1
        path, method, code, schema = results[0]
        assert path == "/subscriptions"
        assert method == "post"
        assert code == "201"
        assert "id" in schema.get("properties", {})

    def test_ref_response_schema(self):
        spec = {
            "components": {
                "schemas": {
                    "Subscription": {"type": "object", "properties": {"id": {"type": "string"}}}
                }
            },
            "paths": {
                "/subscriptions/{id}": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Subscription"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        results = list(iter_response_schemas(spec, "/subscriptions"))
        assert len(results) == 1
        assert results[0][3].get("properties", {}).get("id") is not None

    def test_array_response(self):
        """GET /subscriptions returns array — items are yielded."""
        spec = {
            "components": {
                "schemas": {
                    "Subscription": {"type": "object", "properties": {"id": {"type": "string"}}}
                }
            },
            "paths": {
                "/subscriptions": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/Subscription"},
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        results = list(iter_response_schemas(spec, "/subscriptions"))
        assert len(results) == 1
        assert "id" in results[0][3].get("properties", {})

    def test_path_prefix_filter(self):
        spec = {
            "paths": {
                "/subscriptions": {
                    "get": {
                        "responses": {
                            "200": {"content": {"application/json": {"schema": {"type": "object"}}}}
                        }
                    }
                },
                "/other": {
                    "get": {
                        "responses": {
                            "200": {"content": {"application/json": {"schema": {"type": "object"}}}}
                        }
                    }
                },
            }
        }
        results = list(iter_response_schemas(spec, "/subscriptions"))
        assert len(results) == 1

    def test_no_paths(self):
        assert list(iter_response_schemas({}, "/subscriptions")) == []

    def test_error_responses_included(self):
        """Error responses (4xx) are also yielded when matching path."""
        spec = {
            "paths": {
                "/subscriptions": {
                    "post": {
                        "responses": {
                            "201": {
                                "content": {"application/json": {"schema": {"type": "object"}}}
                            },
                            "400": {
                                "content": {"application/json": {"schema": {"type": "object"}}}
                            },
                        }
                    }
                }
            }
        }
        results = list(iter_response_schemas(spec, "/subscriptions"))
        assert len(results) == 2
