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
        action="" if command == "sync-issue" else command,
    )


# ── non-slash triggers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "trigger",
    [
        Trigger(trigger_type="issue_close", issue_number="42", user="x", should_continue=True),
        Trigger(trigger_type="issue_reopen", issue_number="42", user="x", should_continue=True),
        Trigger(trigger_type="pr_merge", user="x", should_continue=True),
        Trigger(trigger_type="workflow_dispatch", command="sync-issue", user="x", should_continue=True),
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
        action=policy.action_for(result),
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
        "action": "",
    }
    assert json.loads(rejection.to_json()) == {
        "allowed": False,
        "error_message": rejection.error_message,
        "response": "command_rejected",
        "error_type": "",
    }


# ── main(): env → GITHUB_OUTPUT ──────────────────────────────────────────────


STATE_KEYS = ("STATE", "RELEASE_TAG", "RELEASE_TYPE", "CONFIG_ERROR", "CONFIG_ERROR_TYPE", "SRC_COMMIT_SHA",
              "SNAPSHOT_BRANCH", "RELEASE_REVIEW_BRANCH", "RELEASE_PR_NUMBER", "RELEASE_ISSUE_NUMBER",
              "COMMONALITIES_RELEASE", "IDENTITY_CONSENT_MANAGEMENT_RELEASE")


def run_main(tmp_path, monkeypatch, trigger, env, client):
    output_path = tmp_path / "output"
    output_path.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("TRIGGER_JSON", json.dumps(trigger.__dict__))
    # STATE_JSON is toJSON(steps.state.outputs) of the derive-release-state step
    monkeypatch.setenv("STATE_JSON", json.dumps({k.lower(): env[k] for k in STATE_KEYS if k in env}))
    for name in ("COMMON_CACHE_STATUS", "COMMON_CACHE_DETAILS", "COMMON_SYNC_PR_URL", "BASE_CONTEXT", "ACK_COMMENT_ID"):
        monkeypatch.setenv(name, env.get(name, ""))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "camaraproject/ReleaseTest2")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    policy.main(client=client)

    from release_automation.tests.test_trigger import read_outputs
    return read_outputs(output_path)


def test_main_writes_allowed_plan(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, publish(confirm_tag=""),
        {"STATE": "draft-ready", "RELEASE_TAG": "r1.2", "RELEASE_TYPE": "public-release"},
        FakeClient(permissions={"alice": "write"}),
    )

    plan = json.loads(out["plan"])
    assert plan["allowed"] is True
    assert plan["response"] == "publish_confirmation"
    assert out["action"] == ""


def test_main_writes_rejection_with_cache_inputs(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("create-snapshot"),
        {"STATE": "planned", "RELEASE_TAG": "r1.2", "COMMON_CACHE_STATUS": "stale",
         "COMMON_CACHE_DETAILS": "d", "COMMON_SYNC_PR_URL": "https://x/pull/1"},
        FakeClient(permissions={"alice": "write"}),
    )

    plan = json.loads(out["plan"])
    assert plan["allowed"] is False
    assert plan["error_message"] == "Common file cache is stale: d. Merge the sync PR: https://x/pull/1"
    assert (out["action"], out["finalize"]) == ("", "false")


def test_main_config_error_plan(tmp_path, monkeypatch):
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


def test_main_publish_confirmation_response(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, publish(confirm_tag=""),
        {"STATE": "draft-ready", "RELEASE_TAG": "r1.2", "SRC_COMMIT_SHA": "abcdef0123456789"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert out["response"] == "publish_confirmation"
    assert out["response_release_tag"] == "r1.2"
    assert json.loads(out["response_context"]) == {
        "draft_release_url": "https://github.com/camaraproject/ReleaseTest2/releases",
        "src_commit_sha_short": "abcdef0",
    }


def test_main_rejection_response_context_is_valid_json(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, publish(confirm_tag='r"1'),
        {"STATE": "draft-ready", "RELEASE_TAG": "r1.2"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert out["response"] == "command_rejected"
    assert json.loads(out["response_context"]) == {"error_message": json.loads(out["plan"])["error_message"]}


def test_main_interim_response(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("sync-issue"), {"STATE": "planned", "RELEASE_TAG": "r1.2"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert (out["response"], out["response_context"], out["response_release_tag"]) == (
        "interim_processing", "{}", "r1.2"
    )


def test_main_config_error_response(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("create-snapshot"),
        {"CONFIG_ERROR": "release-plan.yaml not found", "CONFIG_ERROR_TYPE": "missing_file"},
        FakeClient(),
    )

    assert out["response"] == "config_error"
    assert out["response_release_tag"] == "unknown"
    assert json.loads(out["response_context"]) == {
        "error_type": "missing_file",
        "error_message": "release-plan.yaml not found",
        "command": "create-snapshot",
        "user": "alice",
        "workflow_run_url": "https://github.com/camaraproject/ReleaseTest2/actions/runs/123",
    }


@pytest.mark.parametrize(
    "trigger",
    [
        Trigger(trigger_type="push", command="sync-issue", user="x", should_continue=True),
        Trigger(trigger_type="issue_close", issue_number="42", user="x", should_continue=True),
    ],
)
def test_main_non_slash_trigger_has_no_response(tmp_path, monkeypatch, trigger):
    out = run_main(tmp_path, monkeypatch, trigger, {"STATE": "planned", "RELEASE_TAG": "r1.2"}, FakeClient())

    assert out["response"] == ""
    assert json.loads(out["plan"])["allowed"] is True


def test_main_non_slash_config_error(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch,
        Trigger(trigger_type="push", command="sync-issue", should_continue=True),
        {"CONFIG_ERROR": "bad", "CONFIG_ERROR_TYPE": "malformed_yaml"}, FakeClient(),
    )

    assert (out["response"], out["action"], out["finalize"]) == ("", "", "false")
    assert json.loads(out["plan"])["error_type"] == "malformed_yaml"


# ── finalize gate ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "trigger,state,due",
    [
        (slash("create-snapshot"), ReleaseState.PLANNED, True),
        (slash("sync-issue"), ReleaseState.PUBLISHED, True),
        (publish(confirm_tag="r1.2"), ReleaseState.DRAFT_READY, True),
        # The confirmation request is the whole response; nothing ran to finalize.
        (publish(confirm_tag=""), ReleaseState.DRAFT_READY, False),
        (slash("delete-draft"), ReleaseState.PLANNED, False),
        (Trigger(trigger_type="push", command="sync-issue", should_continue=True), ReleaseState.PLANNED, True),
        (Trigger(trigger_type="pr_merge", should_continue=True), ReleaseState.SNAPSHOT_ACTIVE, True),
        (Trigger(trigger_type="issue_close", issue_number="4", should_continue=True), ReleaseState.DRAFT_READY, True),
    ],
)
def test_finalize_due(trigger, state, due):
    assert policy.finalize_due(evaluate(trigger, info(state), client=WRITE)) is due


@pytest.mark.parametrize("trigger", [slash("create-snapshot"), Trigger(trigger_type="pr_merge", should_continue=True)])
def test_no_finalize_on_config_error(trigger):
    assert policy.finalize_due(evaluate(trigger, CONFIG_ERROR, client=FakeClient())) is False


def test_main_writes_finalize(tmp_path, monkeypatch):
    out = run_main(
        tmp_path, monkeypatch, slash("create-snapshot"),
        {"STATE": "planned", "RELEASE_TAG": "r1.2", "RELEASE_TYPE": "pre-release-alpha"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert out["finalize"] == "true"


# ── action: what snapshot/act execute ────────────────────────────────────────


@pytest.mark.parametrize(
    "trigger,state,action",
    [
        (slash("create-snapshot"), ReleaseState.PLANNED, "create-snapshot"),
        (slash("discard-snapshot"), ReleaseState.SNAPSHOT_ACTIVE, "discard-snapshot"),
        (slash("delete-draft"), ReleaseState.DRAFT_READY, "delete-draft"),
        (slash("publish-release", confirm_tag="r1.2"), ReleaseState.DRAFT_READY, "publish-release"),
        (slash("publish-release"), ReleaseState.DRAFT_READY, ""),  # confirmation request
        (slash("sync-issue"), ReleaseState.PLANNED, ""),
        (slash("create-snapshot"), ReleaseState.SNAPSHOT_ACTIVE, ""),  # rejected
        (Trigger(trigger_type="pr_merge", user="x", should_continue=True), ReleaseState.SNAPSHOT_ACTIVE, "create-draft"),
        (Trigger(trigger_type="issue_close", issue_number="42", should_continue=True), ReleaseState.SNAPSHOT_ACTIVE, "reopen-issue"),
        (Trigger(trigger_type="issue_close", issue_number="42", should_continue=True), ReleaseState.DRAFT_READY, "reopen-issue"),
        (Trigger(trigger_type="issue_close", issue_number="42", should_continue=True), ReleaseState.PLANNED, ""),
        (Trigger(trigger_type="issue_close", issue_number="42", should_continue=True), ReleaseState.PUBLISHED, ""),
        (Trigger(trigger_type="issue_reopen", issue_number="42", should_continue=True), ReleaseState.DRAFT_READY, ""),
        (Trigger(trigger_type="push", command="sync-issue", should_continue=True), ReleaseState.PLANNED, ""),
    ],
)
def test_action(trigger, state, action):
    result = evaluate(trigger, info(state), client=FakeClient(permissions={"alice": "write"}, codeowners=""))

    assert (result.action if result.allowed else "") == action


def test_pr_merge_publishes_on_merge_when_the_policy_says_so(monkeypatch):
    monkeypatch.setitem(policy.PUBLISH_MODES, "pre-release-rc", "on_merge")
    trigger = Trigger(trigger_type="pr_merge", user="x", should_continue=True)

    rc = evaluate(trigger, info(ReleaseState.SNAPSHOT_ACTIVE, release_type="pre-release-rc"), client=FakeClient())
    public = evaluate(trigger, info(ReleaseState.SNAPSHOT_ACTIVE, release_type="public-release"), client=FakeClient())

    assert (rc.publish_mode, rc.action) == ("on_merge", "publish-on-merge")
    assert (public.publish_mode, public.action) == ("draft", "create-draft")


def test_main_writes_the_plan_document(tmp_path, monkeypatch):
    base = {"release_tag": "r1.2", "state": "snapshot-active", "user": "alice"}
    out = run_main(
        tmp_path, monkeypatch, slash("discard-snapshot", args="redo"),
        {"STATE": "snapshot-active", "RELEASE_TAG": "r1.2", "RELEASE_TYPE": "pre-release-rc",
         "SRC_COMMIT_SHA": "abcdef0123", "SNAPSHOT_BRANCH": "release-snapshot/r1.2-abcdef0",
         "RELEASE_REVIEW_BRANCH": "release-review/r1.2-abcdef0", "RELEASE_PR_NUMBER": "24",
         "RELEASE_ISSUE_NUMBER": "23", "COMMONALITIES_RELEASE": "r4.3",
         "IDENTITY_CONSENT_MANAGEMENT_RELEASE": "r4.3",
         "COMMON_CACHE_STATUS": "in_sync", "BASE_CONTEXT": json.dumps(base), "ACK_COMMENT_ID": "555"},
        FakeClient(permissions={"alice": "write"}),
    )

    assert (out["action"], out["finalize"]) == ("discard-snapshot", "true")
    assert json.loads(out["plan"]) == {
        "allowed": True,
        "trigger_type": "slash_command",
        "command": "discard-snapshot",
        "release_tag": "r1.2",
        "state": "snapshot-active",
        "release_type": "pre-release-rc",
        "confirm_tag": "",
        "base_branch": "main",
        "publish_mode": "draft",
        "response": "interim_processing",
        "action": "discard-snapshot",
        "command_args": "redo",
        "issue_number": "42",
        "user": "alice",
        "snapshot_branch": "release-snapshot/r1.2-abcdef0",
        "release_review_branch": "release-review/r1.2-abcdef0",
        "release_pr_number": "24",
        "release_issue_number": "23",
        "src_commit_sha": "abcdef0123",
        "commonalities_release": "r4.3",
        "identity_consent_management_release": "r4.3",
        "common_cache_status": "in_sync",
        "common_cache_details": "",
        "common_sync_pr_url": "",
        "base_context": base,
    }
