"""Which system this is, the words for it, and what the shell around the app can do.

The server runs on the computer it talks about (in the Mac app and the desktop app for Windows and Linux), so it
says which system that is, and the web app words things to match: "this Mac" or "this PC", Finder or File Explorer,
the menu bar or the system tray. Words for the system live here and only here.

The shell names itself and what it can do in the environment it starts the server with: <PREFIX>_SHELL ("mac" or
"desktop") and <PREFIX>_SHELL_CAN, a comma-separated list such as "quit,reveal,updates,login". The web app hides what
the shell can't do instead of showing a button that does nothing. A browser (development, a server install) has no
shell, so it can do none of them.

    quit      the window can quit the whole app
    reveal    show a file in Finder or File Explorer
    updates   the app updates itself (Settings → Updates)
    login     open at login
"""
import sys

from . import config

OS = "mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "linux"

_WORDS = {
    "mac": {"here": "this Mac", "files": "Finder", "tray": "the menu bar", "app": "the Mac app", "apps": "Applications",
            "terminal": "Terminal", "os": "macOS"},
    "windows": {"here": "this PC", "files": "File Explorer", "tray": "the system tray", "app": "the desktop app",
                "apps": "the Start menu", "terminal": "PowerShell", "os": "Windows"},
    "linux": {"here": "this computer", "files": "your file manager", "tray": "the system tray", "app": "the desktop app",
              "apps": "your apps menu", "terminal": "a terminal", "os": "Linux"},
}
WORDS: dict[str, str] = _WORDS[OS]


def word(key: str) -> str:
    """WORDS[key], e.g. word("here") is "this Mac" on a Mac."""
    return WORDS[key]


def shell() -> str | None:
    """"mac" or "desktop" when the app's own shell started this server, else None (a browser)."""
    return (config.env("SHELL") or "").strip().lower() or None


def can() -> list[str]:
    """What the shell can do (see the module's docstring). Nothing without a shell."""
    if not shell():
        return []
    return sorted({c.strip().lower() for c in (config.env("SHELL_CAN") or "").split(",") if c.strip()})


def info() -> dict:
    """For the web app (app_info): {os, words, shell, can}."""
    return {"os": OS, "words": WORDS, "shell": shell(), "can": can()}
