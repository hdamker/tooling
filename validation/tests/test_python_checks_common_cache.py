"""Unit tests for validation.engines.python_checks.common_cache_checks (P-021).

The core sync logic is tested exhaustively in
``tooling_lib/tests/test_cache_sync.py``.  These tests verify the VF
wrapper: context-to-expected-releases mapping and SyncStatus-to-findings
conversion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import yaml

from validation.context import ValidationContext
from validation.context.context_builder import ApiContext
from validation.engines.python_checks.common_cache_checks import (
    check_common_cache_sync,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _make_context(
    commonalities_release: Optional[str] = None,
) -> ValidationContext:
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
        apis=(),
        workflow_run_url="",
        tooling_ref="",
    )


def _write_manifest(tmp_path: Path, sources: list) -> None:
    common_dir = tmp_path / "code" / "common"
    common_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": sources}
    (common_dir / ".sync-manifest.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False), encoding="utf-8"
    )


def _write_common_file(tmp_path: Path, filename: str, content: str) -> str:
    common_dir = tmp_path / "code" / "common"
    common_dir.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    (common_dir / filename).write_text(content, encoding="utf-8")
    return _blob_sha(data)


# ---------------------------------------------------------------------------
# Tests — context-to-expected mapping
# ---------------------------------------------------------------------------


class TestContextMapping:

    def test_no_commonalities_release_returns_empty(self, tmp_path: Path):
        ctx = _make_context(commonalities_release=None)
        assert check_common_cache_sync(tmp_path, ctx) == []

    def test_commonalities_release_populates_expected(self, tmp_path: Path):
        """When commonalities_release is set, the check runs."""
        ctx = _make_context(commonalities_release="r4.2")
        # No code/common/ dir → should produce a finding.
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        assert "directory" in findings[0]["message"].lower()


# ---------------------------------------------------------------------------
# Tests — SyncStatus-to-findings conversion
# ---------------------------------------------------------------------------


class TestFindingsConversion:

    def test_no_common_dir(self, tmp_path: Path):
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        f = findings[0]
        assert f["engine_rule"] == "check-common-cache-sync"
        assert f["level"] == "warn"
        assert "directory" in f["message"].lower()
        assert f["path"] == "code/common"

    def test_no_manifest(self, tmp_path: Path):
        (tmp_path / "code" / "common").mkdir(parents=True)
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        assert "manifest" in findings[0]["message"].lower()
        assert findings[0]["path"] == "code/common/.sync-manifest.yaml"

    def test_all_in_sync(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "ok")
        _write_manifest(
            tmp_path,
            [
                {
                    "repository": "Commonalities",
                    "release": "r4.2",
                    "files": {"CAMARA_common.yaml": sha},
                }
            ],
        )
        ctx = _make_context(commonalities_release="r4.2")
        assert check_common_cache_sync(tmp_path, ctx) == []

    def test_tag_mismatch_finding(self, tmp_path: Path):
        sha = _write_common_file(tmp_path, "CAMARA_common.yaml", "data")
        _write_manifest(
            tmp_path,
            [
                {
                    "repository": "Commonalities",
                    "release": "r4.1",
                    "files": {"CAMARA_common.yaml": sha},
                }
            ],
        )
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        assert "r4.2" in findings[0]["message"]
        assert "r4.1" in findings[0]["message"]

    def test_missing_file_finding(self, tmp_path: Path):
        (tmp_path / "code" / "common").mkdir(parents=True, exist_ok=True)
        _write_manifest(
            tmp_path,
            [
                {
                    "repository": "Commonalities",
                    "release": "r4.2",
                    "files": {"CAMARA_common.yaml": "a" * 40},
                }
            ],
        )
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        assert "missing" in findings[0]["message"].lower()
        assert findings[0]["path"] == "code/common/CAMARA_common.yaml"

    def test_modified_file_finding(self, tmp_path: Path):
        original_sha = _blob_sha(b"original")
        _write_common_file(tmp_path, "CAMARA_common.yaml", "modified")
        _write_manifest(
            tmp_path,
            [
                {
                    "repository": "Commonalities",
                    "release": "r4.2",
                    "files": {"CAMARA_common.yaml": original_sha},
                }
            ],
        )
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert len(findings) == 1
        assert "modified" in findings[0]["message"].lower()

    def test_all_findings_are_warn(self, tmp_path: Path):
        """Every finding from P-021 is 'warn' (post-filter handles escalation)."""
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert all(f["level"] == "warn" for f in findings)

    def test_all_findings_have_engine_rule(self, tmp_path: Path):
        ctx = _make_context(commonalities_release="r4.2")
        findings = check_common_cache_sync(tmp_path, ctx)
        assert all(
            f["engine_rule"] == "check-common-cache-sync" for f in findings
        )
