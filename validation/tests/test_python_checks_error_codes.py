"""Unit tests for error code checks (P-017, P-018)."""

from __future__ import annotations

from pathlib import Path

import yaml

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.error_code_checks import (
    check_conflict_deprecated,
    check_contextcode_format,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(api_name: str = "quality-on-demand") -> ValidationContext:
    api = ApiContext(
        api_name=api_name,
        target_api_version="1.0.0",
        target_api_status="public",
        target_api_maturity="stable",
        api_pattern="request-response",
        spec_file=f"code/API_definitions/{api_name}.yaml",
    )
    return ValidationContext(
        repository="TestRepo",
        branch_type="main",
        trigger_type="dispatch",
        profile="advisory",
        stage="enabled",
        target_release_type=None,
        commonalities_release="r4.1",
        commonalities_version=None,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(api,),
        workflow_run_url="",
        tooling_ref="",
    )


def _write_spec(
    tmp_path: Path,
    api_name: str = "quality-on-demand",
    spec_content: dict | None = None,
) -> None:
    if spec_content is None:
        spec_content = {"openapi": "3.0.3", "info": {"title": "Test", "version": "wip"}, "paths": {}}
    spec_dir = tmp_path / "code" / "API_definitions"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{api_name}.yaml").write_text(
        yaml.dump(spec_content, default_flow_style=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# P-017: check-conflict-deprecated
# ---------------------------------------------------------------------------


class TestCheckConflictDeprecated:
    def test_no_conflict_ok(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "ErrorCode": {"type": "string", "enum": ["INVALID_ARGUMENT", "NOT_FOUND"]}
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        assert check_conflict_deprecated(tmp_path, _make_context()) == []

    def test_conflict_in_enum_warn(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "ErrorInfo": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "enum": ["INVALID_ARGUMENT", "CONFLICT"]},
                        },
                    }
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        findings = check_conflict_deprecated(tmp_path, _make_context())
        assert len(findings) == 1
        assert findings[0]["level"] == "warn"
        assert "deprecated" in findings[0]["message"].lower()

    def test_conflict_in_top_level_enum(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "Code409": {"type": "string", "enum": ["ABORTED", "ALREADY_EXISTS", "CONFLICT"]}
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        findings = check_conflict_deprecated(tmp_path, _make_context())
        assert len(findings) >= 1
        assert all(f["level"] == "warn" for f in findings)

    def test_missing_spec(self, tmp_path: Path):
        assert check_conflict_deprecated(tmp_path, _make_context()) == []

    def test_no_schemas(self, tmp_path: Path):
        spec = {"openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {}}
        _write_spec(tmp_path, spec_content=spec)
        assert check_conflict_deprecated(tmp_path, _make_context()) == []


# ---------------------------------------------------------------------------
# P-018: check-contextcode-format
# ---------------------------------------------------------------------------


class TestCheckContextcodeFormat:
    def test_no_contextcode_ok(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {"schemas": {"Foo": {"properties": {"bar": {"type": "string"}}}}},
        }
        _write_spec(tmp_path, spec_content=spec)
        assert check_contextcode_format(tmp_path, _make_context()) == []

    def test_valid_screaming_snake_ok(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "Outcome": {
                        "properties": {
                            "contextCode": {
                                "type": "string",
                                "enum": [
                                    "COMMON.REGIONAL_PRIVACY_RESTRICTION",
                                    "CARRIER_BILLING.PAYMENT_DENIED",
                                    "NOT_AVAILABLE",
                                ],
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        assert check_contextcode_format(tmp_path, _make_context()) == []

    def test_invalid_camel_case_hint(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "Outcome": {
                        "properties": {
                            "contextCode": {
                                "type": "string",
                                "enum": ["apiName.specificCode", "VALID_CODE"],
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        findings = check_contextcode_format(tmp_path, _make_context())
        assert len(findings) == 1
        assert findings[0]["level"] == "hint"
        assert "apiName.specificCode" in findings[0]["message"]

    def test_contextcode_without_enum_hint(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "Outcome": {
                        "properties": {
                            "contextCode": {"type": "string"},
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        findings = check_contextcode_format(tmp_path, _make_context())
        assert len(findings) == 1
        assert findings[0]["level"] == "hint"
        assert "no enum" in findings[0]["message"]

    def test_missing_spec(self, tmp_path: Path):
        assert check_contextcode_format(tmp_path, _make_context()) == []

    def test_mixed_valid_invalid(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.3", "info": {"title": "T", "version": "wip"}, "paths": {},
            "components": {
                "schemas": {
                    "Outcome": {
                        "properties": {
                            "contextCode": {
                                "type": "string",
                                "enum": ["VALID_CODE", "invalid-code", "ALSO.VALID"],
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path, spec_content=spec)
        findings = check_contextcode_format(tmp_path, _make_context())
        assert len(findings) == 1  # Only invalid-code
        assert "invalid-code" in findings[0]["message"]
