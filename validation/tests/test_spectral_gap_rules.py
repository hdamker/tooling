"""Tests for Phase 2a Spectral gap rules (S-018..S-035).

Tests create minimal OpenAPI YAML fixtures, run Spectral with the r4 ruleset,
and verify that expected rules fire (or don't fire) on them.  Each test targets
a specific rule by checking for its rule code in the Spectral JSON output.

Requires: Node.js + Spectral CLI (installed via validation/package.json).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths & helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RULESET = _REPO_ROOT / "linting" / "config" / ".spectral-r4.yaml"
_NODE_MODULES = _REPO_ROOT / "validation" / "node_modules"


def _run_spectral(yaml_content: str) -> list[dict]:
    """Write *yaml_content* to a temp file, lint it with Spectral, return findings."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        tmp_path = f.name

    env = {
        "PATH": subprocess.os.environ.get("PATH", ""),
        "NODE_PATH": str(_NODE_MODULES),
        "HOME": subprocess.os.environ.get("HOME", ""),
    }
    result = subprocess.run(
        [
            "node",
            str(_NODE_MODULES / ".bin" / "spectral"),
            "lint",
            tmp_path,
            "-r", str(_RULESET),
            "--format", "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    Path(tmp_path).unlink(missing_ok=True)
    if result.stdout.strip():
        return json.loads(result.stdout)
    return []


def _codes(findings: list[dict]) -> set[str]:
    """Extract the set of rule codes from Spectral findings."""
    return {f["code"] for f in findings}


def _findings_for(findings: list[dict], code: str) -> list[dict]:
    """Filter findings to a specific rule code."""
    return [f for f in findings if f["code"] == code]


# ---------------------------------------------------------------------------
# Minimal valid spec (passes all rules)
# ---------------------------------------------------------------------------

_VALID_SPEC = """\
openapi: 3.0.3
info:
  title: Test API
  description: A test API
  version: wip
  license:
    name: Apache 2.0
    url: https://www.apache.org/licenses/LICENSE-2.0.html
  x-camara-commonalities: 0.7.0
externalDocs:
  description: Product documentation at CAMARA
  url: https://github.com/camaraproject/TestAPI
servers:
  - url: "{apiRoot}/test-api/vwip"
    variables:
      apiRoot:
        default: http://localhost:9091
        description: "API root, defined by the service provider, e.g. `api.example.com` or `api.example.com/somepath`"
tags:
  - name: Test API
security:
  - openId:
    - test-api:read
paths:
  /test:
    get:
      tags:
        - Test API
      summary: Get test
      description: Get test description
      operationId: getTest
      responses:
        "200":
          description: OK
        "401":
          description: Unauthorized
          content:
            application/json:
              schema:
                allOf:
                  - $ref: "#/components/schemas/ErrorInfo"
                  - type: object
                    properties:
                      code:
                        enum:
                          - UNAUTHENTICATED
        "403":
          description: Forbidden
          content:
            application/json:
              schema:
                allOf:
                  - $ref: "#/components/schemas/ErrorInfo"
                  - type: object
                    properties:
                      code:
                        enum:
                          - PERMISSION_DENIED
components:
  securitySchemes:
    openId:
      type: openIdConnect
      openIdConnectUrl: https://example.com/.well-known/openid-configuration
  schemas:
    ErrorInfo:
      type: object
      required:
        - status
        - code
        - message
      properties:
        status:
          type: integer
          format: int32
          minimum: 100
          maximum: 599
          description: HTTP response status code
        code:
          type: string
          maxLength: 96
          description: A human-readable code to describe the error
        message:
          type: string
          maxLength: 512
          description: A human-readable description of what the event represents
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def valid_findings():
    """Findings from the minimal valid spec — baseline for 'no false positives'."""
    return _run_spectral(_VALID_SPEC)


class TestGroupA:
    """Group A: Simple field checks."""

    def test_valid_spec_no_license_findings(self, valid_findings):
        codes = _codes(valid_findings)
        assert "camara-license-name" not in codes
        assert "camara-license-url-value" not in codes

    def test_license_name_wrong(self):
        spec = _VALID_SPEC.replace("name: Apache 2.0", "name: MIT")
        findings = _run_spectral(spec)
        assert "camara-license-name" in _codes(findings)

    def test_license_url_wrong(self):
        spec = _VALID_SPEC.replace(
            "url: https://www.apache.org/licenses/LICENSE-2.0.html",
            "url: https://opensource.org/licenses/MIT",
        )
        findings = _run_spectral(spec)
        assert "camara-license-url-value" in _codes(findings)

    def test_no_contact_passes(self, valid_findings):
        assert "camara-no-contact" not in _codes(valid_findings)

    def test_contact_present_fails(self):
        spec = _VALID_SPEC.replace(
            "  x-camara-commonalities: 0.7.0",
            "  contact:\n    name: Foo\n  x-camara-commonalities: 0.7.0",
        )
        findings = _run_spectral(spec)
        assert "camara-no-contact" in _codes(findings)

    def test_tag_title_case_passes(self, valid_findings):
        assert "camara-tag-name-title-case" not in _codes(valid_findings)

    def test_tag_title_case_fails(self):
        spec = _VALID_SPEC.replace("name: Test API", "name: test api")
        findings = _run_spectral(spec)
        assert "camara-tag-name-title-case" in _codes(findings)

    def test_api_root_default_passes(self, valid_findings):
        assert "camara-api-root-default" not in _codes(valid_findings)

    def test_api_root_default_fails(self):
        spec = _VALID_SPEC.replace(
            "default: http://localhost:9091",
            "default: http://localhost:8080",
        )
        findings = _run_spectral(spec)
        assert "camara-api-root-default" in _codes(findings)

    def test_api_root_description_passes(self, valid_findings):
        assert "camara-api-root-description" not in _codes(valid_findings)

    def test_response_403_passes(self, valid_findings):
        assert "camara-response-403" not in _codes(valid_findings)

    def test_response_403_missing(self):
        # Remove the 403 response block
        spec = _VALID_SPEC.replace(
            '        "403":\n'
            "          description: Forbidden\n"
            "          content:\n"
            "            application/json:\n"
            "              schema:\n"
            "                allOf:\n"
            '                  - $ref: "#/components/schemas/ErrorInfo"\n'
            "                  - type: object\n"
            "                    properties:\n"
            "                      code:\n"
            "                        enum:\n"
            "                          - PERMISSION_DENIED",
            "",
        )
        findings = _run_spectral(spec)
        assert "camara-response-403" in _codes(findings)


class TestGroupB:
    """Group B: Error code checks."""

    def test_valid_error_codes_pass(self, valid_findings):
        codes = _codes(valid_findings)
        assert "camara-error-code-not-numeric" not in codes
        assert "camara-error-code-screaming-snake-case" not in codes
        assert "camara-error-code-api-specific-format" not in codes

    def test_numeric_error_code_fails(self):
        # Must quote the value so YAML parses it as a string, not integer
        spec = _VALID_SPEC.replace("- UNAUTHENTICATED", '- "401"')
        findings = _run_spectral(spec)
        assert "camara-error-code-not-numeric" in _codes(findings)

    def test_non_screaming_snake_case_fails(self):
        spec = _VALID_SPEC.replace("- UNAUTHENTICATED", "- unauthenticated")
        findings = _run_spectral(spec)
        assert "camara-error-code-screaming-snake-case" in _codes(findings)

    def test_api_specific_code_valid(self):
        spec = _VALID_SPEC.replace(
            "- PERMISSION_DENIED", "- TEST_API.PERMISSION_DENIED"
        )
        findings = _run_spectral(spec)
        assert "camara-error-code-api-specific-format" not in _codes(findings)

    def test_api_specific_code_bad_format(self):
        spec = _VALID_SPEC.replace(
            "- PERMISSION_DENIED", "- test.permission_denied"
        )
        findings = _run_spectral(spec)
        assert "camara-error-code-api-specific-format" in _codes(findings)


class TestGroupC:
    """Group C: Subscription schema checks."""

    _SUBSCRIPTION_SPEC = """\
    openapi: 3.0.3
    info:
      title: Test Subscriptions
      description: Test
      version: wip
      license:
        name: Apache 2.0
        url: https://www.apache.org/licenses/LICENSE-2.0.html
      x-camara-commonalities: 0.7.0
    externalDocs:
      description: Product documentation at CAMARA
      url: https://github.com/camaraproject/TestAPI
    servers:
      - url: "{apiRoot}/test-subscriptions/vwip"
        variables:
          apiRoot:
            default: http://localhost:9091
            description: "API root, defined by the service provider, e.g. `api.example.com` or `api.example.com/somepath`"
    tags:
      - name: Test Subscription
    security:
      - openId:
        - test:read
    paths:
      /subscriptions:
        post:
          tags:
            - Test Subscription
          summary: Create subscription
          description: Create a subscription
          operationId: createSubscription
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: "#/components/schemas/SubscriptionRequest"
          callbacks:
            notifications:
              "{$request.body#/sink}":
                post:
                  summary: Notification callback
                  description: Notification callback
                  operationId: postNotification
                  requestBody:
                    required: true
                    content:
                      application/cloudevents+json:
                        schema:
                          $ref: "#/components/schemas/CloudEvent"
                  responses:
                    "204":
                      description: No Content
                  security:
                    - {}
          responses:
            "201":
              description: Created
            "401":
              description: Unauthorized
            "403":
              description: Forbidden
    components:
      securitySchemes:
        openId:
          type: openIdConnect
          openIdConnectUrl: https://example.com/.well-known/openid-configuration
      schemas:
        Protocol:
          type: string
          enum:
            - HTTP
          description: Delivery protocol
        SubscriptionRequest:
          type: object
          required:
            - sink
            - protocol
          properties:
            protocol:
              $ref: "#/components/schemas/Protocol"
            sink:
              type: string
              format: uri
              maxLength: 2048
              pattern: "^https:\\\\/\\\\/.+$"
              description: The address to which events shall be delivered
        CloudEvent:
          type: object
          required:
            - id
            - source
            - specversion
            - type
            - time
          properties:
            id:
              type: string
              description: Event identifier
              minLength: 1
            source:
              type: string
              format: uri-reference
              minLength: 1
              description: Event source
            type:
              type: string
              description: Event type
              minLength: 1
            specversion:
              type: string
              description: CloudEvents version
              enum:
                - "1.0"
            datacontenttype:
              type: string
              description: Content type
              enum:
                - application/json
            time:
              type: string
              format: date-time
              description: "Timestamp. It must follow [RFC 3339](https://datatracker.ietf.org/doc/html/rfc3339#section-5.6) and must have time zone."
            data:
              type: object
              description: Event payload
    """

    def test_specversion_valid(self):
        findings = _run_spectral(self._SUBSCRIPTION_SPEC)
        assert "camara-cloudevent-specversion" not in _codes(findings)

    def test_specversion_wrong(self):
        spec = self._SUBSCRIPTION_SPEC.replace(
            'enum:\n                - "1.0"',
            'enum:\n                - "2.0"',
        )
        findings = _run_spectral(spec)
        assert "camara-cloudevent-specversion" in _codes(findings)

    def test_protocol_http_only_passes(self):
        findings = _run_spectral(self._SUBSCRIPTION_SPEC)
        assert "camara-subscription-protocol-http" not in _codes(findings)

    def test_protocol_non_http_fails(self):
        spec = self._SUBSCRIPTION_SPEC.replace(
            "enum:\n            - HTTP\n          description: Delivery protocol",
            "enum:\n            - HTTP\n            - MQTT3\n          description: Delivery protocol",
        )
        findings = _run_spectral(spec)
        assert "camara-subscription-protocol-http" in _codes(findings)

    def test_sink_https_passes(self):
        findings = _run_spectral(self._SUBSCRIPTION_SPEC)
        assert "camara-subscription-sink-https" not in _codes(findings)

    def test_notification_content_type_passes(self):
        findings = _run_spectral(self._SUBSCRIPTION_SPEC)
        assert "camara-notification-content-type" not in _codes(findings)

    def test_notification_content_type_wrong(self):
        spec = self._SUBSCRIPTION_SPEC.replace(
            "application/cloudevents+json:", "application/json:"
        )
        findings = _run_spectral(spec)
        assert "camara-notification-content-type" in _codes(findings)


class TestGroupD:
    """Group D: Custom JS function rules."""

    def test_datetime_rfc3339_passes(self):
        # 4-space indent puts schema under components.schemas (sibling of ErrorInfo)
        spec = _VALID_SPEC + (
            "    TimestampSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        createdAt:\n"
            "          type: string\n"
            "          format: date-time\n"
            '          description: "Created timestamp. It must follow [RFC 3339](https://datatracker.ietf.org/doc/html/rfc3339#section-5.6) and must have time zone."\n'
        )
        findings = _run_spectral(spec)
        assert "camara-datetime-rfc3339-description" not in _codes(findings)

    def test_datetime_rfc3339_fails(self):
        spec = _VALID_SPEC + (
            "    TimestampSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        createdAt:\n"
            "          type: string\n"
            "          format: date-time\n"
            '          description: "A timestamp"\n'
        )
        findings = _run_spectral(spec)
        assert "camara-datetime-rfc3339-description" in _codes(findings)

    def test_duration_rfc3339_fails(self):
        spec = _VALID_SPEC + (
            "    DurationSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        maxDuration:\n"
            "          type: string\n"
            "          format: duration\n"
            '          description: "How long it takes"\n'
        )
        findings = _run_spectral(spec)
        assert "camara-duration-rfc3339-description" in _codes(findings)

    def test_required_properties_pass(self, valid_findings):
        assert "camara-required-properties-exist" not in _codes(valid_findings)

    def test_required_properties_fail(self):
        spec = _VALID_SPEC + (
            "    BadSchema:\n"
            "      type: object\n"
            "      required:\n"
            "        - name\n"
            "        - age\n"
            "        - missing_field\n"
            "      properties:\n"
            "        name:\n"
            "          type: string\n"
            "          description: Name\n"
            "        age:\n"
            "          type: integer\n"
            "          format: int32\n"
            "          minimum: 0\n"
            "          maximum: 200\n"
            "          description: Age\n"
        )
        findings = _run_spectral(spec)
        assert "camara-required-properties-exist" in _codes(findings)

    def test_required_properties_allof_no_false_positive(self):
        """allOf fragments with required but no properties should not fire."""
        spec = _VALID_SPEC + (
            "    ExtendedError:\n"
            "      allOf:\n"
            '        - $ref: "#/components/schemas/ErrorInfo"\n'
            "        - type: object\n"
            "          required:\n"
            "            - detail\n"
            "          properties:\n"
            "            detail:\n"
            "              type: string\n"
            "              description: Additional detail\n"
        )
        findings = _run_spectral(spec)
        allof_findings = [
            f for f in _findings_for(findings, "camara-required-properties-exist")
            if "ExtendedError" in str(f.get("path", []))
        ]
        assert len(allof_findings) == 0

    def test_array_items_description_passes(self):
        spec = _VALID_SPEC + (
            "    ListSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        items_list:\n"
            "          type: array\n"
            "          description: A list\n"
            "          items:\n"
            "            type: string\n"
            "            description: An item\n"
        )
        findings = _run_spectral(spec)
        items_findings = [
            f for f in _findings_for(findings, "camara-array-items-description")
            if "ListSchema" in str(f.get("path", []))
        ]
        assert len(items_findings) == 0

    def test_array_items_description_fails(self):
        spec = _VALID_SPEC + (
            "    ListSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        items_list:\n"
            "          type: array\n"
            "          description: A list\n"
            "          items:\n"
            "            type: string\n"
        )
        findings = _run_spectral(spec)
        assert "camara-array-items-description" in _codes(findings)

    def test_array_items_ref_skipped(self):
        """$ref items should be skipped (target schema has own description)."""
        spec = _VALID_SPEC + (
            "    ListSchema:\n"
            "      type: object\n"
            "      properties:\n"
            "        errors:\n"
            "          type: array\n"
            "          description: List of errors\n"
            "          items:\n"
            '            $ref: "#/components/schemas/ErrorInfo"\n'
        )
        findings = _run_spectral(spec)
        items_findings = [
            f for f in _findings_for(findings, "camara-array-items-description")
            if "ListSchema" in str(f.get("path", []))
        ]
        assert len(items_findings) == 0
