"""Tests for command_policy.py: Trigger × ReleaseInfoResult → Plan | Rejection.

Expected messages and check order reproduce the former inline `Validate Command`
github-script step of release-automation-reusable.yml.
"""

import json

import pytest

from release_automation.scripts import command_policy as policy
from release_automation.scripts.command_policy import (
    CommonCache,
    Plan,
    Rejection,
    evaluate,
)
from release_automation.scripts.github_client import GitHubClientError
from release_automation.scripts.state_manager import (
    ConfigurationError,
    ReleaseInfoResult,
    ReleaseState,
)
from release_automation.scripts.trigger import Trigger


COMMANDS = ["create-snapshot", "discard-snapshot", "delete-draft", "sync-issue", "publish-release"]

ALLOWED = {
    ReleaseState.PLANNED: {"create-snapshot", "sync-issue"},
    ReleaseState.SNAPSHOT_ACTIVE: {"discard-snapshot", "sync-issue"},
    ReleaseState.DRAFT_READY: {"delete-draft", "publish-release", "sync-issue"},
    ReleaseState.PUBLISHED: {"sync-issue"},
    ReleaseState.NOT_PLANNED: {"sync-issue"},
}

VALID_COMMANDS_TEXT = {
    ReleaseState.PLANNED: "Valid commands: /create-snapshot, /sync-issue",
    ReleaseState.SNAPSHOT_ACTIVE: "Valid commands: /discard-snapshot, /sync-issue",
    ReleaseState.DRAFT_READY: "Valid commands: /delete-draft, /publish-release, /sync-issue",
    ReleaseState.PUBLISHED: "Valid commands: /sync-issue",
    ReleaseState.NOT_PLANNED: "Valid commands: /sync-issue",
}

CODEOWNERS = "# Code owners\n\n*  @Alice @bob\n/code/ @carol\n* @dave\n"


class FakeClient:
    """GitHubClient stand-in for the two reads the policy makes."""

    def __init__(self, permissions=None, codeowners=CODEOWNERS, permission_error=None,
                 codeowners_error=None):
        self.permissions = permissions or {}
        self.codeowners = codeowners
        self.permission_error = permission_error
        self.codeowners_error = codeowners_error
        self.calls = []

    def get_collaborator_permission(self, username):
        self.calls.append(("permission", username))
        if self.permission_error:
            raise GitHubClientError(self.permission_error)
        return self.permissions.get(username, "none")

    def get_file_content(self, path, ref="main", strict=False):
        self.calls.append(("file", path, ref, strict))
        if self.codeowners_error:
            raise GitHubClientError(self.codeowners_error)
        return self.codeowners


def slash(command, user="alice", args="", confirm_tag=""):
    return Trigger(
        trigger_type="slash_command",
        command=command,
        command_args=args,
        issue_number="42",
        user=user,
        should_continue=True,
        confirm_tag=confirm_tag,
    )


def info(state, release_tag="r1.2", release_type="pre-release-alpha"):
    return ReleaseInfoResult(
        success=True, release_tag=release_tag, state=state, release_type=release_type
    )


WRITE = FakeClient(permissions={"alice": "write"})


# ── allowed-commands-per-state table ─────────────────────────────────────────


@pytest.mark.parametrize("state", list(ALLOWED))
@pytest.mark.parametrize("command", COMMANDS)
def test_state_command_matrix(state, command):
    client = FakeClient(permissions={"alice": "admin"})
    trigger = slash(command, confirm_tag="r1.2" if command == "publish-release" else "")

    result = evaluate(trigger, info(state), client=client)

    if command in ALLOWED[state]:
        assert isinstance(result, Plan)
        assert result.command == command
    else:
        assert result == Rejection(
            error_message=(
                f"Command /{command} is not allowed in state '{state.value}'. "
                f"{VALID_COMMANDS_TEXT[state]}"
            ),
            response="command_rejected",
        )
        # The table is checked before any API call.
        assert client.calls == []


def test_state_without_commands():
    result = evaluate(slash("sync-issue"), ReleaseInfoResult(success=True, state=None), client=WRITE)

    assert result.error_message == (
        "Command /sync-issue is not allowed in state ''. No commands available in this state"
    )


# ── common-cache gate on /create-snapshot ────────────────────────────────────


def test_stale_cache_blocks_create_snapshot_with_sync_pr_hint():
    cache = CommonCache(
        status="stale",
        details="Commonalities: expected r4.2, manifest has r4.1",
        sync_pr_url="https://github.com/o/r/pull/9",
    )
    client = FakeClient(permissions={"alice": "write"})

    result = evaluate(slash("create-snapshot"), info(ReleaseState.PLANNED), cache, client=client)

    assert result == Rejection(
        error_message=(
            "Common file cache is stale: Commonalities: expected r4.2, manifest has r4.1. "
            "Merge the sync PR: https://github.com/o/r/pull/9"
        ),
        response="command_rejected",
    )
    # The cache gate comes before the permission check.
    assert client.calls == []


def test_stale_cache_without_sync_pr():
    cache = CommonCache(status="stale", details="code/common/ directory is missing")

    result = evaluate(slash("create-snapshot"), info(ReleaseState.PLANNED), cache, client=WRITE)

    assert result.error_message == (
        "Common file cache is stale: code/common/ directory is missing. "
        "Run workflow_dispatch to trigger sync, or close and reopen the Release Issue."
    )


@pytest.mark.parametrize("status", ["in_sync", ""])
def test_cache_not_stale_allows_create_snapshot(status):
    result = evaluate(
        slash("create-snapshot"), info(ReleaseState.PLANNED), CommonCache(status=status),
        client=WRITE,
    )

    assert isinstance(result, Plan)


def test_stale_cache_does_not_gate_other_commands():
    cache = CommonCache(status="stale", details="x")

    result = evaluate(slash("sync-issue"), info(ReleaseState.PLANNED), cache, client=WRITE)

    assert isinstance(result, Plan)


# ── permission check ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("permission", ["admin", "maintain", "write"])
def test_write_or_higher_may_run_commands(permission):
    client = FakeClient(permissions={"alice": permission})

    result = evaluate(slash("discard-snapshot"), info(ReleaseState.SNAPSHOT_ACTIVE), client=client)

    assert isinstance(result, Plan)
    assert client.calls == [("permission", "alice")]


@pytest.mark.parametrize("permission", ["triage", "read", "none"])
def test_below_write_is_rejected(permission):
    client = FakeClient(permissions={"alice": permission})

    result = evaluate(slash("sync-issue"), info(ReleaseState.PLANNED), client=client)

    assert result == Rejection(
        error_message=(
            "You must have write access or higher to run release commands. "
            f"Your current permission: {permission}"
        ),
        response="command_rejected",
    )


def test_permission_lookup_failure_denies():
    client = FakeClient(permission_error="gh command failed: HTTP 502")

    result = evaluate(slash("sync-issue"), info(ReleaseState.PLANNED), client=client)

    assert result.error_message == "Failed to verify permissions: gh command failed: HTTP 502"


def test_trusted_bot_is_treated_as_write_without_lookup():
    client = FakeClient()

    result = evaluate(
        slash("create-snapshot", user="camara-validation[bot]"), info(ReleaseState.PLANNED),
        client=client,
    )

    assert isinstance(result, Plan)
    assert client.calls == []


# ── publisher authorization (/publish-release) ───────────────────────────────


def publish(user="alice", confirm_tag="r1.2"):
    return slash("publish-release", user=user, args=f"--confirm {confirm_tag}", confirm_tag=confirm_tag)


@pytest.mark.parametrize("user", ["alice", "bob", "ALICE"])
def test_codeowner_with_write_may_publish(user):
    client = FakeClient(permissions={user: "write"})

    result = evaluate(publish(user=user), info(ReleaseState.DRAFT_READY), client=client)

    assert isinstance(result, Plan)
    assert ("file", "CODEOWNERS", "main", True) in client.calls


def test_only_first_star_line_counts():
    # dave is on the second "*" line, carol on a path line: neither may publish.
    for user in ("dave", "carol"):
        client = FakeClient(permissions={user: "write"})

        result = evaluate(publish(user=user), info(ReleaseState.DRAFT_READY), client=client)

        assert result == Rejection(
            error_message=(
                f"Only codeowners or admins can publish releases. @{user} is not listed in CODEOWNERS."
            ),
            response="command_rejected",
        )


@pytest.mark.parametrize("permission", ["maintain", "admin"])
def test_maintain_and_admin_bypass_codeowners(permission):
    client = FakeClient(permissions={"zed": permission})

    result = evaluate(publish(user="zed"), info(ReleaseState.DRAFT_READY), client=client)

    assert isinstance(result, Plan)
    assert client.calls == [("permission", "zed")]


def test_trusted_bot_is_held_to_codeowners_for_publish():
    client = FakeClient()

    result = evaluate(
        publish(user="camara-validation[bot]"), info(ReleaseState.DRAFT_READY), client=client
    )

    assert result.error_message == (
        "Only codeowners or admins can publish releases. "
        "@camara-validation[bot] is not listed in CODEOWNERS."
    )


@pytest.mark.parametrize(
    "content",
    [
        None,  # no CODEOWNERS file
        "# only comments\n\n",  # no "*" line
        "*\n",  # "*" line without owners
        "*\t@alice\n",  # tab after "*" is not the "* " form
    ],
)
def test_no_codeowners_list_falls_back_to_permission(content):
    client = FakeClient(permissions={"erin": "write"}, codeowners=content)

    result = evaluate(publish(user="erin"), info(ReleaseState.DRAFT_READY), client=client)

    assert isinstance(result, Plan)


def test_codeowners_read_failure_denies():
    client = FakeClient(permissions={"alice": "write"}, codeowners_error="gh command failed: HTTP 500")

    result = evaluate(publish(), info(ReleaseState.DRAFT_READY), client=client)

    assert result.error_message == "Failed to verify codeowner status: gh command failed: HTTP 500"


def test_team_entries_are_compared_as_written():
    client = FakeClient(permissions={"alice": "write"}, codeowners="* @camaraproject/release-management\n")

    result = evaluate(publish(), info(ReleaseState.DRAFT_READY), client=client)

    assert isinstance(result, Rejection)


# ── /publish-release --confirm ───────────────────────────────────────────────


def test_publish_without_confirm_asks_for_confirmation():
    client = FakeClient(permissions={"alice": "write"})

    result = evaluate(publish(confirm_tag=""), info(ReleaseState.DRAFT_READY), client=client)

    assert isinstance(result, Plan)
    assert result.response == "publish_confirmation"
    assert result.confirm_tag == ""


def test_publish_with_matching_confirm_tag():
    result = evaluate(publish(), info(ReleaseState.DRAFT_READY), client=WRITE)

    assert isinstance(result, Plan)
    assert result.response == "interim_processing"
    assert result.confirm_tag == "r1.2"


def test_publish_with_wrong_confirm_tag():
    result = evaluate(publish(confirm_tag="r1.1"), info(ReleaseState.DRAFT_READY), client=WRITE)

    assert result == Rejection(
        error_message=(
            "Confirm tag `r1.1` does not match expected release tag `r1.2`. "
            "Use: /publish-release --confirm r1.2"
        ),
        response="command_rejected",
    )


def test_confirm_tag_checked_after_publisher_authorization():
    client = FakeClient(permissions={"dave": "write"})

    result = evaluate(publish(user="dave", confirm_tag="r9.9"), info(ReleaseState.DRAFT_READY), client=client)

    assert "not listed in CODEOWNERS" in result.error_message


# ── plan fields ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "release_type",
    ["pre-release-alpha", "pre-release-rc", "public-release", "maintenance-release", "", None],
)
def test_initial_policy_is_draft_on_main_for_every_type(release_type):
    result = evaluate(
        slash("sync-issue"), info(ReleaseState.PLANNED, release_type=release_type), client=WRITE
    )

    assert result.base_branch == "main"
    assert result.publish_mode == "draft"


def test_publish_modes_cover_all_release_types():
    assert set(policy.PUBLISH_MODES) == set(policy.config.SHORT_TYPE_MAP)
    assert set(policy.PUBLISH_MODES.values()) <= {"on_merge", "draft"}
    assert set(policy.PUBLISHERS) == set(policy.config.SHORT_TYPE_MAP)


@pytest.mark.parametrize("command", ["create-snapshot", "discard-snapshot", "delete-draft", "sync-issue"])
def test_slash_command_plan_responds_with_interim(command):
    state = next(s for s, cmds in ALLOWED.items() if command in cmds)

    result = evaluate(slash(command, args="why"), info(state), client=WRITE)

    assert result == Plan(
        trigger_type="slash_command",
        command=command,
        release_tag="r1.2",
        state=state.value,
        release_type="pre-release-alpha",
        response="interim_processing",
    )


# ── non-slash triggers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "trigger",
    [
        Trigger(trigger_type="issue_close", issue_number="42", user="x", should_continue=True),
        Trigger(trigger_type="issue_reopen", issue_number="42", user="x", should_continue=True),
        Trigger(trigger_type="pr_merge", user="x", should_continue=True),
        Trigger(trigger_type="workflow_dispatch", command="sync-issue", user="x", should_continue=True),
        Trigger(trigger_type="release_plan_change", command="sync-issue", user="x", should_continue=True),
        Trigger(trigger_type="push", command="sync-issue", user="x", should_continue=True),
    ],
)
@pytest.mark.parametrize("state", list(ALLOWED))
def test_non_slash_triggers_are_not_validated(trigger, state):
    client = FakeClient()

    result = evaluate(trigger, info(state), CommonCache(status="stale", details="x"), client=client)

    assert result == Plan(
        trigger_type=trigger.trigger_type,
        command=trigger.command,
        release_tag="r1.2",
        state=state.value,
        release_type="pre-release-alpha",
        response="",
    )
    assert client.calls == []


# ── configuration errors ─────────────────────────────────────────────────────


CONFIG_ERROR = ReleaseInfoResult(
    success=False,
    config_error=ConfigurationError(
        error_type="malformed_yaml", message="release-plan.yaml: bad indent", file_path="release-plan.yaml"
    ),
)


def test_config_error_on_slash_command_responds_with_config_error():
    client = FakeClient()

    result = evaluate(slash("create-snapshot"), CONFIG_ERROR, client=client)

    assert result == Rejection(
        error_message="release-plan.yaml: bad indent",
        response="config_error",
        error_type="malformed_yaml",
    )
    assert client.calls == []


def test_config_error_on_other_trigger_fails_without_comment():
    result = evaluate(
        Trigger(trigger_type="push", command="sync-issue", should_continue=True), CONFIG_ERROR,
        client=FakeClient(),
    )

    assert result == Rejection(
        error_message="release-plan.yaml: bad indent", response="", error_type="malformed_yaml"
    )


# ── JSON form ────────────────────────────────────────────────────────────────


def test_plan_and_rejection_serialise_to_json():
    plan = evaluate(publish(confirm_tag=""), info(ReleaseState.DRAFT_READY), client=WRITE)
    rejection = evaluate(slash("delete-draft"), info(ReleaseState.PLANNED), client=WRITE)

    assert json.loads(plan.to_json()) == {
        "allowed": True,
        "trigger_type": "slash_command",
        "command": "publish-release",
        "release_tag": "r1.2",
        "state": "draft-ready",
        "release_type": "pre-release-alpha",
        "confirm_tag": "",
        "base_branch": "main",
        "publish_mode": "draft",
        "response": "publish_confirmation",
    }
    assert json.loads(rejection.to_json()) == {
        "allowed": False,
        "error_message": rejection.error_message,
        "response": "command_rejected",
        "error_type": "",
    }


# ── main(): env → GITHUB_OUTPUT ──────────────────────────────────────────────


def run_main(tmp_path, monkeypatch, trigger, env, client):
    output_path = tmp_path / "output"
    output_path.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("TRIGGER_JSON", json.dumps(trigger.__dict__))
    for name in ("STATE", "RELEASE_TAG", "RELEASE_TYPE", "CONFIG_ERROR", "CONFIG_ERROR_TYPE",
                 "COMMON_CACHE_STATUS", "COMMON_CACHE_DETAILS", "COMMON_SYNC_PR_URL"):
        monkeypatch.setenv(name, env.get(name, ""))
    policy.main(client=client)

    from release_automation.tests.test_trigger import read_outputs
    return read_outputs(output_path)


def test_main_writes_allowed_plan(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, publish(confirm_tag=""),
        {"STATE": "draft-ready", "RELEASE_TAG": "r1.2", "RELEASE_TYPE": "public-release"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert out["allowed"] == "true"
    assert out["error_message"] == ""
    assert json.loads(out["plan"])["response"] == "publish_confirmation"


def test_main_writes_rejection_with_cache_inputs(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("create-snapshot"),
        {"STATE": "planned", "RELEASE_TAG": "r1.2", "COMMON_CACHE_STATUS": "stale",
         "COMMON_CACHE_DETAILS": "d", "COMMON_SYNC_PR_URL": "https://x/pull/1"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert out["allowed"] == "false"
    assert out["error_message"] == "Common file cache is stale: d. Merge the sync PR: https://x/pull/1"
    assert json.loads(out["plan"])["allowed"] is False


def test_main_config_error(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("sync-issue"),
        {"CONFIG_ERROR": "release-plan.yaml not found", "CONFIG_ERROR_TYPE": "missing_file"},
        FakeClient(),
    )

    assert json.loads(out["plan"]) == {
        "allowed": False,
        "error_message": "release-plan.yaml not found",
        "response": "config_error",
        "error_type": "missing_file",
    }
