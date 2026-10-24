"""Lockdown: nothing leaves this computer. The family's rule 9 (TRAILMIX.md), one switch for every family app on this Mac.

With it on, only AI that runs here answers (ai.configured says why for the rest), the app makes no update checks of its
own, Ollama and its models aren't downloaded, and every module's feature that talks to the outside stops. A module
asks before each such thing:

    if why := lockdown.blocked("Syncing the Google Sheet"):
        raise SomethingError(why)          # or, for a scheduled sync: do nothing, and say so in Settings

What a module does with data already on this Mac (imports, the network, search, backups) is not affected. A new feature
that reaches out must call blocked() and add itself to the test that proves nothing goes out (core/tests/test_lockdown.py
for the host, each module's own for its sync jobs).
"""
from urllib.parse import urlparse

from . import settings

KEY = "core.lockdown"
WHY = "Lockdown mode is on (Settings → Privacy)"


def on() -> bool:
    return bool(settings.get_all().get(KEY))


def blocked(what: str) -> str | None:
    """Why `what` can't happen now, in words for a person, or None when it may."""
    return f"{what} is off while Lockdown is on (Settings → Privacy)." if on() else None


def on_this_computer(url: str) -> bool:
    return (urlparse(url or "").hostname or "") in ("localhost", "127.0.0.1", "::1")
