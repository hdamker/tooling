"""Tests for bot_identity.py: the commit identity shared by the snapshot and finalize jobs."""

from release_automation.scripts.bot_identity import resolve_bot_identity


class Users:
    """Stands in for GitHubClient.get_user; records the login it was asked for."""

    def __init__(self):
        self.logins = []

    def get_user(self, login):
        self.logins.append(login)
        return {"id": 7, "login": login}


def test_app_bot_when_an_app_token_is_in_use():
    gh = Users()

    assert resolve_bot_identity(gh, "camara-release", app_token_used=True) == (
        "camara-release[bot]",
        "7+camara-release[bot]@users.noreply.github.com",
    )
    assert gh.logins == ["camara-release[bot]"]


def test_github_actions_bot_without_an_app_token():
    gh = Users()

    assert resolve_bot_identity(gh, "camara-release", app_token_used=False) == (
        "github-actions[bot]",
        "7+github-actions[bot]@users.noreply.github.com",
    )


def test_github_actions_bot_without_an_app_slug():
    gh = Users()

    name, _ = resolve_bot_identity(gh, "", app_token_used=True)

    assert name == "github-actions[bot]"
