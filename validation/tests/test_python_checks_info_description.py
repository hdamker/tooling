"""Unit tests for mandatory info.description content checks (P-026..P-031)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from validation.context import ApiContext, ValidationContext
from validation.engines.python_checks.info_description_checks import (
    _normalize_paragraphs,
    check_info_description_templates,
)


# ---------------------------------------------------------------------------
# Canonical fixture (one universal + one opt-in template — enough to exercise
# missing / drift / duplicate / unknown-name behaviours).  Mirrors the shape
# of code/common/info-description-templates.yaml in Commonalities.
# ---------------------------------------------------------------------------


_CANONICAL_YAML = textwrap.dedent(
    """\
    authorization-and-authentication:
      content: |
        <!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->
        # Authorization and authentication

        Paragraph one of the authorization template.

        Paragraph two of the authorization template.
        <!-- CAMARA:MANDATORY:authorization-and-authentication:END -->

    additional-error-responses:
      content: |
        <!-- CAMARA:MANDATORY:additional-error-responses:BEGIN -->
        # Additional CAMARA error responses

        Error responses paragraph one.

        Error responses paragraph two.
        <!-- CAMARA:MANDATORY:additional-error-responses:END -->

    request-body-strictness:
      content: |
        <!-- CAMARA:MANDATORY:request-body-strictness:BEGIN -->
        # Request body strictness

        Strictness paragraph one.
        <!-- CAMARA:MANDATORY:request-body-strictness:END -->

    identifying-device-from-access-token:
      content: |
        <!-- CAMARA:MANDATORY:identifying-device-from-access-token:BEGIN -->
        # Identifying the device from the access token

        Appendix A paragraph one.

        Appendix A paragraph two.
        <!-- CAMARA:MANDATORY:identifying-device-from-access-token:END -->
    """
)


# Block bodies (BEGIN/END plus inner content) used to compose spec
# fixtures.  Indented to match column-4 inside an OAS description.
_BLOCK_AUTH = textwrap.dedent(
    """\
    <!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->
    # Authorization and authentication

    Paragraph one of the authorization template.

    Paragraph two of the authorization template.
    <!-- CAMARA:MANDATORY:authorization-and-authentication:END -->"""
)

_BLOCK_ERRORS = textwrap.dedent(
    """\
    <!-- CAMARA:MANDATORY:additional-error-responses:BEGIN -->
    # Additional CAMARA error responses

    Error responses paragraph one.

    Error responses paragraph two.
    <!-- CAMARA:MANDATORY:additional-error-responses:END -->"""
)

_BLOCK_STRICTNESS = textwrap.dedent(
    """\
    <!-- CAMARA:MANDATORY:request-body-strictness:BEGIN -->
    # Request body strictness

    Strictness paragraph one.
    <!-- CAMARA:MANDATORY:request-body-strictness:END -->"""
)

_BLOCK_DEVICE = textwrap.dedent(
    """\
    <!-- CAMARA:MANDATORY:identifying-device-from-access-token:BEGIN -->
    # Identifying the device from the access token

    Appendix A paragraph one.

    Appendix A paragraph two.
    <!-- CAMARA:MANDATORY:identifying-device-from-access-token:END -->"""
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    api_name: str = "sample-service",
    target_api_status: str = "rc",
    commonalities_release: str = "r4.3",
    fallback_canonical_path: str | None = None,
) -> ValidationContext:
    api = ApiContext(
        api_name=api_name,
        target_api_version="0.1.0",
        target_api_status=target_api_status,
        target_api_maturity="initial",
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
        commonalities_release=commonalities_release,
        commonalities_version=None,
        icm_release=None,
        base_ref=None,
        is_release_review_pr=False,
        release_plan_changed=None,
        pr_number=None,
        apis=(api,),
        workflow_run_url="",
        tooling_ref="",
        fallback_canonical_path=fallback_canonical_path,
    )


def _write_canonical(repo: Path, canonical_yaml: str = _CANONICAL_YAML) -> None:
    common = repo / "code" / "common"
    common.mkdir(parents=True, exist_ok=True)
    (common / "info-description-templates.yaml").write_text(
        canonical_yaml, encoding="utf-8"
    )


def _write_spec(
    repo: Path,
    api_name: str,
    description_body: str,
    scalar_style: str = "|",
) -> None:
    """Write a minimal spec with a block scalar ``info.description``.

    *description_body* is the content inside ``description:`` — line-anchored
    BEGIN/END markers and any prose, *without* leading indentation.  It is
    indented to column 4 here so the OAS structure parses cleanly.

    Avoids ``textwrap.dedent`` deliberately; the body has variable
    indentation that would confuse dedent's common-prefix calculation.
    """
    # Pad body lines to column 4 (under "  description: |" at column 2).
    # textwrap.indent skips otherwise-empty lines, which is what we want
    # so blank-line paragraph separators stay blank.
    indented = textwrap.indent(description_body, "    ")
    spec = (
        "openapi: 3.0.3\n"
        "info:\n"
        "  title: Test\n"
        "  version: wip\n"
        f"  description: {scalar_style}\n"
        f"{indented}\n"
        "paths: {}\n"
    )
    spec_dir = repo / "code" / "API_definitions"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{api_name}.yaml").write_text(spec, encoding="utf-8")


def _codes(findings: list[dict]) -> list[str]:
    return [f["engine_rule"] for f in findings]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNS27InfoDescriptionMandatory:
    """Behavioural tests for the P-026..P-031 rules."""

    def test_valid_spec_no_findings(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert findings == [], _codes(findings)

    def test_missing_auth_fires_p026(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_ERRORS, _BLOCK_STRICTNESS])  # auth dropped
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        codes = _codes(findings)
        assert codes.count("check-info-description-mandatory-missing") == 1
        # The missing-finding message names the missing template.
        missing = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-missing"
        ]
        assert "authorization-and-authentication" in missing[0]["message"]

    def test_missing_request_body_strictness_fires_p026(
        self, tmp_path: Path
    ) -> None:
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert any(
            "request-body-strictness" in f["message"]
            and f["engine_rule"] == "check-info-description-mandatory-missing"
            for f in findings
        )

    def test_missing_additional_error_responses_fires_p026(
        self, tmp_path: Path
    ) -> None:
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert any(
            "additional-error-responses" in f["message"]
            and f["engine_rule"] == "check-info-description-mandatory-missing"
            for f in findings
        )

    def test_optin_appendix_a_absence_not_flagged(self, tmp_path: Path) -> None:
        """No Appendix A block present — P-026 must NOT fire for it."""
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert not any(
            "identifying-device-from-access-token" in f["message"]
            for f in findings
        )

    def test_drift_paragraph_change_fires_p027(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        drifted_auth = _BLOCK_AUTH.replace(
            "Paragraph one of the authorization template.",
            "Paragraph one with a WRONG word inserted here.",
        )
        body = "\n\n".join([drifted_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert len(drift) == 1
        assert "authorization-and-authentication" in drift[0]["message"]

    def test_drift_whitespace_only_passes(self, tmp_path: Path) -> None:
        """Reflowing a paragraph onto one line must not fire drift."""
        _write_canonical(tmp_path)
        reflowed_auth = _BLOCK_AUTH.replace(
            "Paragraph one of the authorization template.",
            "Paragraph one of  the\n    authorization template.",
        )
        body = "\n\n".join([reflowed_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert drift == []

    def test_begin_marker_spacer_in_spec_passes_with_old_canonical(
        self, tmp_path: Path
    ) -> None:
        """A presentation spacer after BEGIN in the API spec is not drift."""
        _write_canonical(tmp_path)
        spaced_auth = _BLOCK_AUTH.replace(
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "# Authorization and authentication",
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n\n"
            "# Authorization and authentication",
        )
        body = "\n\n".join([spaced_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert drift == []

    def test_begin_marker_missing_blank_line_fires_when_canonical_has_it(
        self, tmp_path: Path
    ) -> None:
        """r4.4 canonical requires the BEGIN spacer; a spec without it (the
        r4.3-era shape) now fires a
        dedicated finding rather than being silently tolerated."""
        spaced_canonical = _CANONICAL_YAML.replace(
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "    # Authorization and authentication",
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "\n"
            "    # Authorization and authentication",
        )
        _write_canonical(tmp_path, spaced_canonical)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert len(drift) == 1
        assert "authorization-and-authentication" in drift[0]["message"]
        assert "blank line" in drift[0]["message"]

    def test_begin_marker_blank_line_present_on_both_passes(
        self, tmp_path: Path
    ) -> None:
        """Canonical and spec both carry the r4.4 BEGIN spacer — no finding."""
        spaced_canonical = _CANONICAL_YAML.replace(
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "    # Authorization and authentication",
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "\n"
            "    # Authorization and authentication",
        )
        _write_canonical(tmp_path, spaced_canonical)
        spaced_auth = _BLOCK_AUTH.replace(
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "# Authorization and authentication",
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n\n"
            "# Authorization and authentication",
        )
        body = "\n\n".join([spaced_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert drift == []

    def test_end_marker_spacer_in_spec_passes_with_old_canonical(
        self, tmp_path: Path
    ) -> None:
        """A presentation spacer before END in the API spec is not drift."""
        _write_canonical(tmp_path)
        spaced_auth = _BLOCK_AUTH.replace(
            "Paragraph two of the authorization template.\n"
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:END -->",
            "Paragraph two of the authorization template.\n\n"
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:END -->",
        )
        body = "\n\n".join([spaced_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert drift == []

    def test_end_marker_spacer_in_canonical_passes_with_old_spec(
        self, tmp_path: Path
    ) -> None:
        """A presentation spacer before END in canonical is not drift."""
        spaced_canonical = _CANONICAL_YAML.replace(
            "    Paragraph two of the authorization template.\n"
            "    <!-- CAMARA:MANDATORY:authorization-and-authentication:END -->",
            "    Paragraph two of the authorization template.\n"
            "\n"
            "    <!-- CAMARA:MANDATORY:authorization-and-authentication:END -->",
        )
        _write_canonical(tmp_path, spaced_canonical)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert drift == []

    def test_begin_marker_missing_blank_line_and_content_drift_both_fire(
        self, tmp_path: Path
    ) -> None:
        """Missing blank line and real content drift are independent findings."""
        spaced_canonical = _CANONICAL_YAML.replace(
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "    # Authorization and authentication",
            "<!-- CAMARA:MANDATORY:authorization-and-authentication:BEGIN -->\n"
            "\n"
            "    # Authorization and authentication",
        )
        _write_canonical(tmp_path, spaced_canonical)
        drifted_auth = _BLOCK_AUTH.replace(
            "Paragraph one of the authorization template.",
            "Paragraph one with a WRONG word inserted here.",
        )
        body = "\n\n".join([drifted_auth, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
            and "authorization-and-authentication" in f["message"]
        ]
        assert len(drift) == 2
        assert any("blank line" in f["message"] for f in drift)
        assert any("drifted from canonical" in f["message"] for f in drift)

    def test_duplicate_marker_pair_fires_p028(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        body = "\n\n".join(
            [_BLOCK_AUTH, _BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS]
        )
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        codes = _codes(findings)
        assert codes.count("check-info-description-mandatory-duplicate") == 1
        # Drift must not also fire on the duplicate — only the first
        # occurrence is compared and it matches canonical.
        assert "check-info-description-mandatory-drift" not in codes

    def test_unknown_template_name_fires_p029(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        bogus = textwrap.dedent(
            """\
            <!-- CAMARA:MANDATORY:foo:BEGIN -->
            # Foo

            Whatever.
            <!-- CAMARA:MANDATORY:foo:END -->"""
        )
        body = "\n\n".join(
            [_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS, bogus]
        )
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        unknown = [
            f for f in findings
            if f["engine_rule"]
            == "check-info-description-mandatory-unknown-template-name"
        ]
        assert len(unknown) == 1
        assert "foo" in unknown[0]["message"]

    def test_folded_scalar_fires_p030(self, tmp_path: Path) -> None:
        """info.description: > should fire folded-scalar regardless of body."""
        _write_canonical(tmp_path)
        # Any body — the markers would be flattened by the YAML parser
        # anyway, but the rule fires on the scalar style alone.
        body = _BLOCK_AUTH
        _write_spec(tmp_path, "sample-service", body, scalar_style=">")
        findings = check_info_description_templates(tmp_path, _make_context())
        codes = _codes(findings)
        assert "check-info-description-folded-scalar" in codes

    def test_block_literal_passes(self, tmp_path: Path) -> None:
        """info.description: | (default in fixtures) must not fire P-030."""
        _write_canonical(tmp_path)
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert "check-info-description-folded-scalar" not in _codes(findings)

    def test_canonical_absent_fires_p031(self, tmp_path: Path) -> None:
        """No canonical file present — warn that template validation is skipped."""
        # Note: do NOT call _write_canonical.
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        assert _codes(findings) == ["check-info-description-canonical-missing"]
        assert "info-description-templates.yaml" in findings[0]["message"]

    def test_local_absent_fallback_present_evaluates_no_p031(
        self, tmp_path: Path
    ) -> None:
        """Release-review context: code/common/ stripped but the workflow has
        injected the source-fetched canonical. P-026..P-030 must evaluate
        against it and P-031 must NOT fire."""
        # No _write_canonical: the repo-local copy is absent (snapshot strip).
        fallback = tmp_path / "fallback" / "info-description-templates.yaml"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(_CANONICAL_YAML, encoding="utf-8")
        # A valid spec carrying all universal blocks → no findings at all.
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        ctx = _make_context(fallback_canonical_path=str(fallback))
        findings = check_info_description_templates(tmp_path, ctx)
        assert "check-info-description-canonical-missing" not in _codes(findings)
        assert findings == []

    def test_local_absent_fallback_present_surfaces_real_finding(
        self, tmp_path: Path
    ) -> None:
        """The injected fallback drives a genuine P-026, not a P-031, when a
        mandatory block is missing on the snapshot."""
        fallback = tmp_path / "fallback" / "info-description-templates.yaml"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(_CANONICAL_YAML, encoding="utf-8")
        # Omit the authorization block → P-026 should fire via the fallback.
        body = "\n\n".join([_BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        ctx = _make_context(fallback_canonical_path=str(fallback))
        codes = _codes(check_info_description_templates(tmp_path, ctx))
        assert "check-info-description-mandatory-missing" in codes
        assert "check-info-description-canonical-missing" not in codes

    def test_local_present_wins_over_fallback(self, tmp_path: Path) -> None:
        """Local copy always wins, even when a fallback path is also set —
        local validation stays offline and unchanged on working branches."""
        _write_canonical(tmp_path)
        # Point the fallback at a deliberately broken file; it must be ignored.
        bad_fallback = tmp_path / "fallback" / "info-description-templates.yaml"
        bad_fallback.parent.mkdir(parents=True, exist_ok=True)
        bad_fallback.write_text("not: [a, valid, catalog", encoding="utf-8")
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        ctx = _make_context(fallback_canonical_path=str(bad_fallback))
        findings = check_info_description_templates(tmp_path, ctx)
        assert findings == []

    def test_local_absent_no_fallback_fires_p031(self, tmp_path: Path) -> None:
        """Main / working-branch contract: no local copy and no injected
        fallback → exactly one P-031 (offline, fires truthfully)."""
        body = "\n\n".join([_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS])
        _write_spec(tmp_path, "sample-service", body)
        ctx = _make_context(fallback_canonical_path=None)
        findings = check_info_description_templates(tmp_path, ctx)
        assert _codes(findings) == ["check-info-description-canonical-missing"]

    def test_appendix_a_drift_fires_when_present(self, tmp_path: Path) -> None:
        """Opt-in template absent = no finding; opt-in template drifted = drift fires."""
        _write_canonical(tmp_path)
        drifted_device = _BLOCK_DEVICE.replace(
            "Appendix A paragraph one.",
            "Appendix A paragraph one — with extra prose.",
        )
        body = "\n\n".join(
            [_BLOCK_AUTH, _BLOCK_ERRORS, _BLOCK_STRICTNESS, drifted_device]
        )
        _write_spec(tmp_path, "sample-service", body)
        findings = check_info_description_templates(tmp_path, _make_context())
        drift = [
            f for f in findings
            if f["engine_rule"] == "check-info-description-mandatory-drift"
        ]
        assert len(drift) == 1
        assert "identifying-device-from-access-token" in drift[0]["message"]


# ---------------------------------------------------------------------------
# Helper-function unit tests
# ---------------------------------------------------------------------------


class TestParagraphNormalisation:
    def test_collapse_internal_whitespace(self) -> None:
        text = "Foo\n  bar\tbaz"
        assert _normalize_paragraphs(text) == ["Foo bar baz"]

    def test_preserve_paragraph_boundaries(self) -> None:
        text = "Para one.\n\nPara two."
        assert _normalize_paragraphs(text) == ["Para one.", "Para two."]

    def test_drop_empty_paragraphs(self) -> None:
        # Leading/trailing blank lines and double blank lines collapse to
        # empty paragraphs which must be dropped (handles BEGIN/END line
        # residue around real content).
        text = "\n\nPara one.\n\n\nPara two.\n"
        assert _normalize_paragraphs(text) == ["Para one.", "Para two."]

    def test_crlf_normalised(self) -> None:
        text = "Para one.\r\n\r\nPara two."
        assert _normalize_paragraphs(text) == ["Para one.", "Para two."]
