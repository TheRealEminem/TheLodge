"""The family link: Trailmix family apps on one Mac share API keys and basic preferences, know about each other,
and ask each other for data.

It has two parts, because keys and data behave differently:

- **Shared settings** live in one small SQLite file that every family app opens directly (`family.db` in the
  family folder), so they're there even while the other apps are closed. Only the keys in `is_shared()` are shared:
  the AI settings, your name, the appearance and Lockdown. Each app also keeps its own copy, and "Share keys and
  preferences" (`core.share_with_family`, never shared) turns sharing off for one app.
- **Data stays in the app that owns it.** Each running app registers itself (`family_apps`: its port and the
  offers its modules answer, such as "people.search"), and a module asks another app with
  `call("people.search", q="ana")`, over localhost, with the family token. A merged app answers from its own
  modules first, so the same code works either way. Nothing ever leaves the Mac.

The family folder is `TRAILMIX_FAMILY_DIR` when that's set ("off" turns the link off). Otherwise an app running
as the Mac app (its data in ~/Library/Application Support) uses ~/Library/Application Support/Trailmix Family.
Development copies (data in ./data) and server installs join only when `TRAILMIX_FAMILY_DIR` says where.
"""
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from . import config

log = logging.getLogger("core.family")

DEFAULT_DIR = Path.home() / "Library" / "Application Support" / "Trailmix Family"
SHARED_NAMESPACES = ("ai.",)                                  # every AI setting: provider, fallback, models, keys
SHARED_KEYS = {"core.your_name", "core.appearance", "core.lockdown"}
SHARING_KEY = "core.share_with_family"                        # this app's own choice, never shared
HEARTBEAT_SECONDS = 60
STALE_SECONDS = 3 * HEARTBEAT_SECONDS
TOKEN_HEADER = "X-Family-Token"
_ready: set[Path] = set()                                    # family files whose tables this process has made sure of

_SCHEMA = """
CREATE TABLE IF NOT EXISTS family_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL,
                                            updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS family_apps (id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                                        port INTEGER NOT NULL, pid INTEGER, offers TEXT NOT NULL DEFAULT '[]',
                                        data_dir TEXT NOT NULL, started_at TEXT NOT NULL, seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS family_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Unavailable(Exception):
    """No running family app can answer. The message says what to do, in words a person can act on."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── Where, and whether ────────────────────────────────────────────────

def folder() -> Path | None:
    """The family folder, or None when this copy of the app doesn't join the family."""
    raw = os.getenv("TRAILMIX_FAMILY_DIR")
    if raw:
        return None if raw.strip().lower() == "off" else Path(raw).expanduser()
    mac_data = Path.home() / "Library" / "Application Support"
    try:
        config.DATA_DIR.resolve().relative_to(mac_data)        # running as the Mac app
    except ValueError:
        return None
    return DEFAULT_DIR


def enabled() -> bool:
    return folder() is not None


def is_shared(key: str) -> bool:
    return key in SHARED_KEYS or key.startswith(SHARED_NAMESPACES)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    where = folder()
    if where is None:
        raise Unavailable("The family link is off for this copy of the app.")
    where.mkdir(parents=True, exist_ok=True)
    try:
        where.chmod(0o700)
    except OSError:
        pass
    path = where / "family.db"
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        if path not in _ready:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            _ready.add(path)
        yield conn
    finally:
        conn.close()


def _bump(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO family_meta (key, value) VALUES ('changes', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)")


# ── Shared settings ───────────────────────────────────────────────────

def sharing(local: dict) -> bool:
    """Whether this app shares: the family link is on and its own "Share keys and preferences" is on.
    `local` is this app's stored settings (the switch is never shared, so it's read from there)."""
    return enabled() and local.get(SHARING_KEY, True) is not False


def values() -> dict[str, Any]:
    """Every shared setting the family holds: {"ai.anthropic_api_key": "…", "core.your_name": "Sam", …}."""
    if not enabled():
        return {}
    with _connect() as conn:
        return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM family_settings")}


def put(changes: dict[str, Any]) -> None:
    """Saves shared settings for every family app. Keys that aren't shared are ignored."""
    shared = {k: v for k, v in changes.items() if is_shared(k)}
    if not shared or not enabled():
        return
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in shared.items():
            conn.execute("INSERT INTO family_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, "
                         "updated_by = excluded.updated_by", (key, json.dumps(value), _now(), config.APP_ID))
        _bump(conn)
        conn.execute("COMMIT")


def seed(local: dict[str, Any]) -> list[str]:
    """When an app joins: its own shared settings fill in what the family doesn't have yet (the first app to have a
    key gives it to the rest). It never replaces a value the family already holds. Returns the keys it added."""
    if not sharing(local):
        return []
    have = values()
    new = {k: v for k, v in local.items() if is_shared(k) and k not in have and v not in ("", None)}
    put(new)
    return sorted(new)


def seq() -> int:
    """A counter that moves whenever a shared setting changes, from any app (open screens refresh on it)."""
    if not enabled():
        return 0
    with _connect() as conn:
        row = conn.execute("SELECT value FROM family_meta WHERE key = 'changes'").fetchone()
    return int(row["value"]) if row else 0


def token() -> str:
    """The family's shared secret for app-to-app calls, made on first use. Only family apps can read the file."""
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO family_meta (key, value) VALUES ('token', ?)", (secrets.token_urlsafe(32),))
        return conn.execute("SELECT value FROM family_meta WHERE key = 'token'").fetchone()["value"]


def check_token(candidate: str) -> bool:
    return enabled() and bool(candidate) and secrets.compare_digest(candidate, token())


# ── Who's installed ───────────────────────────────────────────────────

def _offers() -> list[str]:
    from . import module                                        # (module imports settings, which imports this)
    return sorted({name for m in module.all_modules() for name in (m.offers or {})})


def register(port: int | None = None) -> None:
    """This app is here: its port, its process and what its modules offer. Run at startup, then every minute."""
    if not enabled():
        return
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO family_apps (id, name, version, port, pid, offers, data_dir, started_at, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "version = excluded.version, port = excluded.port, pid = excluded.pid, offers = excluded.offers, "
            "data_dir = excluded.data_dir, started_at = excluded.started_at, seen_at = excluded.seen_at",
            (config.APP_ID, config.NAME, config.VERSION, port or config.PORT, os.getpid(), json.dumps(_offers()),
             str(config.DATA_DIR), now, now))


def touch() -> None:
    if not enabled():
        return
    with _connect() as conn:
        conn.execute("UPDATE family_apps SET seen_at = ? WHERE id = ? AND pid = ?", (_now(), config.APP_ID, os.getpid()))


def leave() -> None:
    """A clean exit: this app is installed but no longer running."""
    if not enabled():
        return
    with _connect() as conn:
        conn.execute("UPDATE family_apps SET pid = NULL WHERE id = ? AND pid = ?", (config.APP_ID, os.getpid()))


def start_heartbeat() -> None:
    def beat():
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            try:
                touch()
            except Exception:  # noqa: BLE001 - a missed beat only makes this app look closed for a while
                log.exception("family heartbeat failed")
    if enabled():
        threading.Thread(target=beat, daemon=True, name="family-heartbeat").start()


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def apps() -> list[dict]:
    """The family apps installed on this Mac (each one that has run), with whether each is open now."""
    if not enabled():
        return []
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM family_apps ORDER BY name")]
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        seen = datetime.fromisoformat(r["seen_at"].replace("Z", "+00:00"))
        running = _alive(r["pid"]) and (now - seen).total_seconds() < STALE_SECONDS
        out.append({"id": r["id"], "name": r["name"], "version": r["version"], "port": r["port"], "running": running,
                    "offers": json.loads(r["offers"]), "seen_at": r["seen_at"], "self": r["id"] == config.APP_ID})
    return out


# ── Asking another app ────────────────────────────────────────────────

def local_handler(offer: str) -> Callable[[dict], Any] | None:
    from . import module
    for m in module.all_modules():
        if m.offers and offer in m.offers:
            return m.offers[offer]
    return None


def _post(url: str, body: dict, headers: dict, timeout: float) -> httpx.Response:
    """The one place a request leaves this app (tests replace it)."""
    return httpx.post(url, json=body, headers=headers, timeout=timeout)


def call(offer: str, timeout: float = 5.0, **args: Any) -> Any:
    """Asks for `offer` ("people.search", q="ana"): this app's own modules first, then a running family app that
    offers it. Raises Unavailable with a sentence for the screen when none can answer right now."""
    handler = local_handler(offer)
    if handler:
        return handler(args)
    candidates = [a for a in apps() if offer in a["offers"] and not a["self"]]
    running = [a for a in candidates if a["running"]]
    if not running:
        if candidates:
            raise Unavailable(f"Open {candidates[0]['name']} to see this here.")
        raise Unavailable("None of your family apps on this Mac can answer that yet.")
    errors = []
    for app in running:
        try:
            r = _post(f"http://127.0.0.1:{app['port']}/api/family/call/{offer}", args, {TOKEN_HEADER: token()}, timeout)
        except httpx.HTTPError as e:
            errors.append(f"{app['name']}: {e}")
            continue
        if r.status_code == 200:
            return r.json()["result"]
        errors.append(f"{app['name']}: {r.status_code} {r.text[:200]}")
    log.warning("family call %s failed: %s", offer, "; ".join(errors))
    raise Unavailable(f"{running[0]['name']} didn't answer. Try again in a moment.")
