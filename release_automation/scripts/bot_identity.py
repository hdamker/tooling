"""
Commit identity of release automation.

Shared by the snapshot job (snapshot commits) and finalize (sync PR commits).
The identity is the App bot when an App token is in use, otherwise
github-actions[bot]; the noreply address needs the bot's user ID, which is
not the App ID.
"""

from typing import Tuple


def resolve_bot_identity(gh, app_slug: str, app_token_used: bool) -> Tuple[str, str]:
    """Return (name, email) for commits made with the token in use."""
    login = f"{app_slug}[bot]" if app_slug and app_token_used else "github-actions[bot]"
    user = gh.get_user(login)
    name = user["login"]
    return name, f"{user['id']}+{name}@users.noreply.github.com"
