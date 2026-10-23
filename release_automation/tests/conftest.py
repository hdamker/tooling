import pytest


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path_factory, monkeypatch):
    """Keep the developer's git config (signing, hooks, identity) out of git-level tests."""
    empty = tmp_path_factory.getbasetemp() / "gitconfig-empty"
    empty.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
