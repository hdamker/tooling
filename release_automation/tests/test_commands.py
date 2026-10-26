"""Tests for commands.py: the slash commands, the valid actions per state and their renderer."""

import re

import pytest

from release_automation.scripts import config
from release_automation.scripts.commands import (
    ALLOWED_COMMANDS,
    COMMANDS,
    DISPATCH_ACTIONS,
    STATE_ACTIONS,
    actions_for,
    command,
)

PR = "https://github.com/camaraproject/Example/pull/41"
STATES = (
    config.STATE_PLANNED, config.STATE_SNAPSHOT_ACTIVE, config.STATE_DRAFT_READY,
    config.STATE_PUBLISHED, config.STATE_NOT_PLANNED,
)


def test_commands_in_match_order():
    assert [(c.name, c.takes_args) for c in COMMANDS] == [
        ("create-snapshot", False),
        ("discard-snapshot", True),
        ("delete-draft", True),
        ("sync-issue", False),
        ("publish-release", True),
    ]
    assert DISPATCH_ACTIONS == ("sync-issue", "create-maintenance-branch")


def test_result_templates_and_state_after_success():
    assert {c.name: (c.ok, c.failed, c.state_after) for c in COMMANDS} == {
        "create-snapshot": ("snapshot_created", "snapshot_failed", config.STATE_SNAPSHOT_ACTIVE),
        "discard-snapshot": ("snapshot_discarded", "snapshot_failed", config.STATE_PLANNED),
        "delete-draft": ("draft_revoked", "snapshot_failed", config.STATE_PLANNED),
        "sync-issue": ("issue_synced", "internal_error", ""),
        "publish-release": ("release_published", "publish_failed", config.STATE_PUBLISHED),
    }
    assert [c.name for c in COMMANDS if c.job] == [
        "create-snapshot", "discard-snapshot", "delete-draft", "publish-release"]
    assert command("sync-issue").hidden and command("nope") is None


def test_allowed_commands_are_the_listed_ones_plus_hidden():
    assert ALLOWED_COMMANDS == {
        config.STATE_PLANNED: ["create-snapshot", "sync-issue"],
        config.STATE_SNAPSHOT_ACTIVE: ["discard-snapshot", "sync-issue"],
        config.STATE_DRAFT_READY: ["publish-release", "delete-draft", "sync-issue"],
        config.STATE_PUBLISHED: ["sync-issue"],
        config.STATE_NOT_PLANNED: ["sync-issue"],
    }
    assert set(STATE_ACTIONS) == set(STATES)


@pytest.mark.parametrize("state", STATES)
def test_valid_actions_offer_only_allowed_commands(state):
    # The published / not-planned drift: a rejection offering /create-snapshot
    offered = re.findall(r"`/([a-z-]+)", actions_for(state, "r1.4", PR))

    assert set(offered) <= set(ALLOWED_COMMANDS[state])
    assert "sync-issue" not in offered


def test_actions_for_each_state():
    assert actions_for(config.STATE_PLANNED, "r1.4") == (
        "**Valid actions:**<br>→ **`/create-snapshot` — begin the release process**"
    )
    assert actions_for(config.STATE_SNAPSHOT_ACTIVE, "r1.4", PR) == (
        f"**Valid actions:**<br>→ **Update, review, and merge [Release PR]({PR}) to create draft release**"
        "<br>→ `/discard-snapshot <reason>` — discard and return to `planned`"
    )
    assert actions_for(config.STATE_DRAFT_READY, "r1.4") == (
        "**Valid actions:**<br>→ **`/publish-release --confirm r1.4` — publish the release**"
        "<br>→ `/delete-draft <reason>` — delete draft and return to `planned`"
    )
    assert actions_for(config.STATE_NOT_PLANNED, "r1.4") == (
        "**Valid actions:**<br>→ **Update `release-plan.yaml` with a planned release type to resume**"
        "<br>→ Close this issue — a new one will be created when a release is planned"
    )
    assert actions_for(config.STATE_PUBLISHED, "r1.4") == ""
    assert actions_for("", "") == ""


def test_actions_for_without_release_pr_url():
    assert "→ **Update, review, and merge Release PR to create draft release**" in actions_for(
        config.STATE_SNAPSHOT_ACTIVE, "r1.4")
