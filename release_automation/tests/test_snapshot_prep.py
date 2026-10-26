"""Tests for snapshot_prep.py: the glue steps of the snapshot job around pre-snapshot validation."""

from pathlib import Path

import pytest

from release_automation.scripts import snapshot_prep
from release_automation.scripts.snapshot_prep import (
    gate_validation,
    main,
    validate_settings,
)

TOOLING_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = TOOLING_ROOT / "validation" / "schemas" / "validation-settings-schema.yaml"
SETTINGS = TOOLING_ROOT / "config" / "validation-settings.yaml"


def parse_outputs(path: Path) -> dict:
    """Parse a GITHUB_OUTPUT file in heredoc form."""
    outputs, lines = {}, path.read_text().splitlines()
    i = 0
    while i < len(lines):
        name, _, delimiter = lines[i].partition("<<")
        i += 1
        value = []
        while lines[i] != delimiter:
            value.append(lines[i])
            i += 1
        i += 1
        outputs[name] = "\n".join(value)
    return outputs


# ── settings ─────────────────────────────────────────────────────────────────


def test_settings_valid(capsys):
    assert validate_settings(SETTINGS, SCHEMA) == 0

    assert f"Validation settings: {SETTINGS} (main) — schema-valid" in capsys.readouterr().out


def test_settings_missing(tmp_path, capsys):
    assert validate_settings(tmp_path / "absent.yaml", SCHEMA) == 1

    assert "::error title=Validation settings missing::" in capsys.readouterr().out


def test_settings_schema_missing(tmp_path, capsys):
    assert validate_settings(SETTINGS, tmp_path / "absent.yaml") == 1

    assert "::error title=Validation settings schema missing::" in capsys.readouterr().out


def test_settings_invalid(tmp_path, capsys):
    bad = tmp_path / "settings.yaml"
    bad.write_text("version: not-a-number\n")

    assert validate_settings(bad, SCHEMA) == 1

    out = capsys.readouterr().out
    assert "::error title=Validation settings invalid::version:" in out
    assert "::error::Aborting before snapshot creation" in out


# ── gate ─────────────────────────────────────────────────────────────────────


def test_gate_fails_with_summary_and_run_link(tmp_path, capsys):
    out_file = tmp_path / "out"

    code = gate_validation("2 errors", "https://github.com/o/r/actions/runs/9", str(out_file))

    assert code == 1
    assert "::error::Pre-snapshot validation failed — fix issues on main before re-running /create-snapshot" in capsys.readouterr().out
    assert parse_outputs(out_file) == {
        "success": "false",
        "error_message": "Pre-snapshot validation failed: 2 errors. [View workflow logs](https://github.com/o/r/actions/runs/9)",
    }


# ── main ─────────────────────────────────────────────────────────────────────


def test_main_gate_reads_the_environment(tmp_path):
    out_file = tmp_path / "out"
    env = {
        "VALIDATION_SUMMARY": "1 error",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "camaraproject/Example",
        "GITHUB_RUN_ID": "42",
        "GITHUB_OUTPUT": str(out_file),
    }

    assert main(["gate"], env) == 1

    assert parse_outputs(out_file)["error_message"] == (
        "Pre-snapshot validation failed: 1 error. "
        "[View workflow logs](https://github.com/camaraproject/Example/actions/runs/42)"
    )


def test_main_bot_identity_writes_name_and_email(tmp_path, monkeypatch):
    class Users:
        def get_user(self, login):
            return {"id": 5, "login": login}

    monkeypatch.setattr(snapshot_prep, "_github_client", lambda env: Users())
    out_file = tmp_path / "out"
    env = {"RELEASE_APP_SLUG": "camara-release", "APP_TOKEN_USED": "true", "GITHUB_OUTPUT": str(out_file)}

    assert main(["bot-identity"], env) == 0

    assert parse_outputs(out_file) == {
        "bot_name": "camara-release[bot]",
        "bot_email": "5+camara-release[bot]@users.noreply.github.com",
    }


def test_main_bot_identity_failure_is_an_error(tmp_path, monkeypatch, capsys):
    class Users:
        def get_user(self, login):
            raise RuntimeError("gh command failed: 404")

    monkeypatch.setattr(snapshot_prep, "_github_client", lambda env: Users())
    env = {"APP_TOKEN_USED": "false", "GITHUB_OUTPUT": str(tmp_path / "out")}

    assert main(["bot-identity"], env) == 1

    assert "::error::Could not resolve the bot identity: gh command failed: 404" in capsys.readouterr().out


def test_main_rejects_an_unknown_step():
    with pytest.raises(SystemExit):
        main(["nonsense"], {})


# ── create: the snapshot of the plan's release ───────────────────────────────

from release_automation.scripts import snapshot_creator as creator_mod  # noqa: E402
from release_automation.scripts.snapshot_creator import SnapshotResult  # noqa: E402
from release_automation.tests.fake_github import FakeGitHub  # noqa: E402
from release_automation.tests.plans import make_plan  # noqa: E402

PLAN_YAML = "repository:\n  target_release_tag: r1.8\n  target_release_type: maintenance-release\n"


def run_create(tmp_path, monkeypatch, gh, result=None, plan_fields=None):
    seen = {}

    def fake_create(self, release_plan, config):
        seen.update(release_plan=release_plan, config=config, bot=(self.bot_name, self.bot_email))
        return result

    monkeypatch.setattr(creator_mod.SnapshotCreator, "create_snapshot", fake_create)
    out_file = tmp_path / "out"
    plan = make_plan(**{"release_tag": "r1.8", "state": "planned", "base_branch": "maintenance/r1",
                        "release_issue_number": "7", "action": "create-snapshot", **(plan_fields or {})})
    env = {"PLAN_JSON": plan.to_json(), "GITHUB_REPOSITORY": "camaraproject/Example", "GITHUB_TOKEN": "t",
           "TOOLING_PATH": str(TOOLING_ROOT), "BOT_NAME": "bot[bot]", "BOT_EMAIL": "1+bot[bot]@x", "GITHUB_OUTPUT": str(out_file)}
    monkeypatch.setattr(snapshot_prep, "_github_client", lambda env: gh)
    code = main(["create"], env)
    return code, parse_outputs(out_file), seen


def test_main_create_runs_the_creator_on_the_plans_release(tmp_path, monkeypatch):
    gh = FakeGitHub(files={("maintenance/r1", "release-plan.yaml"): PLAN_YAML})
    result = SnapshotResult(success=True, snapshot_id="r1.8-abc1234", snapshot_branch="release-snapshot/r1.8-abc1234",
                            release_review_branch="release-review/r1.8-abc1234", release_pr_number=12,
                            release_pr_url="https://github.com/camaraproject/Example/pull/12",
                            api_versions={"qod": "1.0.1"}, warnings=["w"], notes=["n"])

    code, out, seen = run_create(tmp_path, monkeypatch, gh, result)

    assert code == 0
    assert out == {
        "success": "true", "snapshot_id": "r1.8-abc1234", "snapshot_branch": "release-snapshot/r1.8-abc1234",
        "release_review_branch": "release-review/r1.8-abc1234", "release_pr_number": "12",
        "release_pr_url": "https://github.com/camaraproject/Example/pull/12", "error_message": "",
        "apis_json": '[{"api_name": "qod", "api_version": "1.0.1"}]',
    }
    # The plan's tag, base branch and Release Issue, the plan file of the base branch (F12: no main default)
    config = seen["config"]
    assert (config.release_tag, config.base_branch, config.release_issue_number, config.dry_run) == ("r1.8", "maintenance/r1", 7, False)
    assert seen["release_plan"]["repository"]["target_release_tag"] == "r1.8"
    assert seen["bot"] == ("bot[bot]", "1+bot[bot]@x")


def test_main_create_reports_a_failed_creation(tmp_path, monkeypatch, capsys):
    gh = FakeGitHub(files={("maintenance/r1", "release-plan.yaml"): PLAN_YAML})
    result = SnapshotResult(success=False, snapshot_id="r1.8-abc1234", errors=["Transformations failed", "x"])

    code, out, _ = run_create(tmp_path, monkeypatch, gh, result)

    assert code == 1
    assert (out["success"], out["snapshot_id"], out["error_message"]) == ("false", "r1.8-abc1234", "Transformations failed; x")
    assert "::error::Snapshot creation failed: Transformations failed; x" in capsys.readouterr().out


def test_main_create_without_a_release_plan_fails_before_creating(tmp_path, monkeypatch):
    code, out, seen = run_create(tmp_path, monkeypatch, FakeGitHub())

    assert code == 1 and seen == {}
    assert (out["success"], out["error_message"]) == ("false", "release-plan.yaml not found")
