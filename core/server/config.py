"""Who this app is and where it keeps things.

Identity comes from app.json at the repository root (copied next to the code inside the .app). Anything can
be overridden from the environment as <envPrefix>_<KEY>, e.g. STARTER_DATA_DIR (the Mac app sets those), or
as APP_<KEY> where the prefix isn't known ahead of time (the Dockerfile).
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY: dict = json.loads((ROOT / "app.json").read_text())
APP_ID: str = IDENTITY["id"]
NAME: str = IDENTITY["name"]
PREFIX: str = IDENTITY["envPrefix"]
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "dev"


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(f"{PREFIX}_{key}") or os.getenv(f"APP_{key}") or default


DATA_DIR = Path(env("DATA_DIR") or ROOT / "data")
PORT = int(env("PORT") or IDENTITY["port"])     # where this copy listens; <PREFIX>_PORT for one beside the installed app
UI_DIR = Path(env("UI_DIR") or ROOT / "dist")


def enabled_modules() -> list[str]:
    """The modules this app is made of. <PREFIX>_MODULES="notes,tasks" overrides app.json (tests, trying one out)."""
    raw = env("MODULES")
    return [m.strip() for m in raw.split(",") if m.strip()] if raw else list(IDENTITY["modules"])
