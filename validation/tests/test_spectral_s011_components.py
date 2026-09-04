"""Tests for S-011 `camara-properties-descriptions` JSONPath scope.

Verifies that the rule's `given` excludes `components.callbacks.*` (Callback Objects
have no `description` field; firing S-011 on them is the bug from tooling#296 — a
codeowner who tries to satisfy it triggers the built-in `oas3-schema` error
because the added key is interpreted as a runtime expression whose value must
be a Path Item Object).

Runs the real Spectral CLI against in-memory YAML, same pattern as
test_spectral_gap_rules.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from validation.engines.spectral_adapter import parse_spectral_output

# ---------------------------------------------------------------------------
# Paths & helpers (copied from test_spectral_gap_rules.py to keep this file
# self-contained; the helpers are small enough that a shared conftest would
# be more abstraction than the codebase currently uses)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RULESET = _REPO_ROOT / "linting" / "config" / ".spectral-r4.yaml"
_NODE_MODULES = _REPO_ROOT / "validation" / "node_modules"


def _run_spectral(yaml_content: str) -> list[dict]:
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


def _run_spectral_multi_file(entry_content: str, sibling_files: dict[str, str]) -> list[dict]:
    """Like :func:`_run_spectral`, but writes the entry spec alongside sibling
    files (e.g. a common-schema file) in the same directory, so a relative
    `$ref` between them resolves the way it does in a real repo checkout.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        entry_path = Path(tmp_dir) / "entry.yaml"
        entry_path.write_text(entry_content)
        for name, content in sibling_files.items():
            (Path(tmp_dir) / name).write_text(content)

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
                str(entry_path),
                "-r", str(_RULESET),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
        return []


def _codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


def _findings_for(findings: list[dict], code: str) -> list[dict]:
    return [f for f in findings if f["code"] == code]


# ---------------------------------------------------------------------------
# Spec template — fully described baseline so S-011 fires only on whatever we
# deliberately leave broken in each test
# ---------------------------------------------------------------------------

_BASE_SPEC = """\
openapi: 3.0.3
info:
  title: S-011 Components Test
  description: Fixture for S-011 components scope
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
        description: API root
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
                $ref: "#/components/schemas/ErrorInfo"
        "403":
          description: Forbidden
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorInfo"
"""

_COMPONENTS_BASE = """\
components:
  securitySchemes:
    openId:
      type: openIdConnect
      openIdConnectUrl: https://example.com/.well-known/openid-configuration
      description: OpenID Connect security scheme
  schemas:
    ErrorInfo:
      type: object
      description: Error envelope
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


def test_callback_in_components_does_not_fire_s011():
    """Named callbacks under `components.callbacks` must not trigger S-011.

    Callback Objects (OAS 3.x) are maps of runtime expressions to Path Item
    Objects — they have no `description` field. tooling#296.
    """
    spec = _BASE_SPEC + _COMPONENTS_BASE + """\
  callbacks:
    onResourceEvent:
      "{$request.body#/sink}":
        post:
          summary: Notification
          description: Notification callback
          operationId: onResourceEvent
          requestBody:
            description: Notification body
            required: true
            content:
              application/json:
                schema:
                  $ref: "#/components/schemas/ErrorInfo"
          responses:
            "204":
              description: Acknowledged
"""
    findings = _run_spectral(spec)
    s011 = _findings_for(findings, "camara-properties-descriptions")
    callback_findings = [f for f in s011 if "callbacks" in f.get("path", [])]
    assert callback_findings == [], (
        f"S-011 must not fire on components.callbacks.*; got {callback_findings}"
    )


def test_schema_property_missing_description_still_fires_s011():
    """Behavior preservation: a schema property without `description` still triggers S-011."""
    spec = _BASE_SPEC + """\
components:
  schemas:
    Foo:
      type: object
      description: Foo
      properties:
        bar:
          type: string
"""
    findings = _run_spectral(spec)
    assert "camara-properties-descriptions" in _codes(findings), (
        "S-011 must still fire on schema properties missing description"
    )


def test_parameter_in_components_missing_description_still_fires_s011():
    """Behavior preservation: a named parameter without `description` still triggers S-011.

    Mirrors the existing regression-branch fixture for `components.parameters.ResourceId`.
    """
    spec = _BASE_SPEC + _COMPONENTS_BASE + """\
  parameters:
    MyParam:
      name: myParam
      in: path
      required: true
      schema:
        type: string
"""
    findings = _run_spectral(spec)
    s011 = _findings_for(findings, "camara-properties-descriptions")
    param_findings = [
        f for f in s011
        if "parameters" in f.get("path", []) and "MyParam" in f.get("path", [])
    ]
    assert param_findings, (
        f"S-011 must still fire on components.parameters.* lacking description; "
        f"got S-011 findings = {s011}"
    )


def test_broken_ref_to_existing_common_file_does_not_fire_s011():
    """Broken-`$ref` cascade artifact: a `$ref` under
    `components.<type>.<Name>.properties.<prop>` pointing to a missing
    JSON pointer in a common file that itself exists makes Spectral hoist
    a synthetic `components.schemas` node and fire S-011 against it. That
    2-segment finding must be dropped by the adapter's resolver-artifact
    guard — asserted here through the real adapter pipeline
    (`parse_spectral_output`), not just raw Spectral output, since the
    guard lives in the adapter rather than the ruleset.
    """
    entry = _BASE_SPEC.replace(
        '$ref: "#/components/schemas/ErrorInfo"',
        '$ref: "#/components/schemas/Wrapper"',
    ) + """\
components:
  securitySchemes:
    openId:
      type: openIdConnect
      openIdConnectUrl: https://example.com/.well-known/openid-configuration
      description: OpenID Connect security scheme
  schemas:
    Wrapper:
      type: object
      description: Wrapper
      properties:
        config:
          $ref: "./common.yaml#/components/schemas/Config"
"""
    common = """\
components:
  schemas:
    Foo:
      type: object
      description: Foo
      properties:
        bar:
          type: string
          description: bar prop
"""
    raw_findings = _run_spectral_multi_file(entry, {"common.yaml": common})

    # Sanity check the cascade actually reproduced (else the test proves nothing).
    raw_s011 = _findings_for(raw_findings, "camara-properties-descriptions")
    assert any(f.get("path") == ["components", "schemas"] for f in raw_s011), (
        f"expected reproduction not observed; raw S-011 findings = {raw_s011}"
    )

    findings = parse_spectral_output(json.dumps(raw_findings))
    s011 = [f for f in findings if f["engine_rule"] == "camara-properties-descriptions"]
    assert s011 == [], (
        f"S-011 must not survive the broken-ref cascade artifact; got {s011}"
    )
