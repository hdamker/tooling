"""Unit tests for validation.context.api_pattern_detector."""

from pathlib import Path

import pytest
import yaml

from validation.context.api_pattern_detector import (
    PATTERN_EXPLICIT_SUBSCRIPTION,
    PATTERN_IMPLICIT_SUBSCRIPTION,
    PATTERN_REQUEST_RESPONSE,
    detect_api_pattern,
    detect_api_pattern_from_file,
)


# ---------------------------------------------------------------------------
# TestDetectApiPattern
# ---------------------------------------------------------------------------


class TestDetectApiPattern:
    def test_request_response_api(self):
        spec = {
            "paths": {
                "/sessions": {"post": {"operationId": "createSession"}},
                "/sessions/{id}": {"get": {"operationId": "getSession"}},
            }
        }
        assert detect_api_pattern(spec) == PATTERN_REQUEST_RESPONSE

    def test_explicit_subscription_has_subscriptions_path(self):
        spec = {
            "paths": {
                "/subscriptions": {"post": {"operationId": "createSubscription"}},
                "/subscriptions/{id}": {"delete": {"operationId": "deleteSubscription"}},
            }
        }
        assert detect_api_pattern(spec) == PATTERN_EXPLICIT_SUBSCRIPTION

    def test_implicit_subscription_has_callbacks(self):
        spec = {
            "paths": {
                "/sessions": {
                    "post": {
                        "operationId": "createSession",
                        "callbacks": {
                            "sessionNotification": {
                                "{$request.body#/sink}": {
                                    "post": {"operationId": "notify"}
                                }
                            }
                        },
                    }
                }
            }
        }
        assert detect_api_pattern(spec) == PATTERN_IMPLICIT_SUBSCRIPTION

    def test_empty_spec(self):
        assert detect_api_pattern({}) == PATTERN_REQUEST_RESPONSE

    def test_no_paths(self):
        spec = {"info": {"title": "Test"}, "components": {"schemas": {}}}
        assert detect_api_pattern(spec) == PATTERN_REQUEST_RESPONSE

    def test_explicit_wins_over_implicit(self):
        """When both subscription path and callbacks exist, explicit wins."""
        spec = {
            "paths": {
                "/subscriptions": {"post": {"operationId": "createSub"}},
                "/sessions": {
                    "post": {
                        "operationId": "createSession",
                        "callbacks": {"cb": {}},
                    }
                },
            }
        }
        assert detect_api_pattern(spec) == PATTERN_EXPLICIT_SUBSCRIPTION


# ---------------------------------------------------------------------------
# TestDetectApiPatternFromFile
# ---------------------------------------------------------------------------


class TestDetectApiPatternFromFile:
    def test_real_spec_file(self, tmp_path):
        spec = {
            "openapi": "3.0.3",
            "paths": {
                "/subscriptions": {"post": {"operationId": "createSubscription"}}
            },
        }
        spec_path = tmp_path / "api.yaml"
        spec_path.write_text(yaml.dump(spec), encoding="utf-8")
        assert detect_api_pattern_from_file(spec_path) == PATTERN_EXPLICIT_SUBSCRIPTION

    def test_missing_file_returns_default(self, tmp_path):
        assert (
            detect_api_pattern_from_file(tmp_path / "nonexistent.yaml")
            == PATTERN_REQUEST_RESPONSE
        )
