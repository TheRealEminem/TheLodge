"""Lockdown: nothing leaves this computer. The family's rule 9 (TRAILMIX.md), one switch for every family app on this Mac.

`core.lockdown` is one of the settings shared with the other family apps (family.py), so turning it on in one app turns
it on in every family app on this Mac that shares keys and preferences. While it's on:

- **AI:** only models on this Mac answer (Ollama, or an OpenAI-compatible server, at a local address). ai.configured()
  says why the others aren't ready, and ai.attempt() stops them before anything is sent; the usage log shows each stop,
  at no cost.
- **Updates:** the app makes no update checks of its own. The Mac app asks GET /api/lockdown before it checks for or
  downloads an update, and doesn't while it's on (or while the server can't say).
- **Ollama and its models** aren't downloaded, and every module's feature that talks to the outside stops. A module
  asks before each such thing:

      if why := lockdown.blocked("Syncing the Google Sheet"):
          raise SomethingError(why)          # a request that can't wait
      lockdown.check(url)                    # right before a request leaves; raises Blocked
      lockdown.may_reach(url)                # to know in advance

An address on this Mac (localhost) is never the cloud, so a local Ollama or Trailmix keeps working. What a module does
with data already on this Mac (imports, search, backups) is not affected. A new feature that reaches out must ask, and
add itself to the test that proves nothing goes out (core/tests/test_lockdown.py for the host, each module's own for
its sync jobs).

Work stopped by Lockdown isn't an error. check() raises Blocked, a jobs.Wait, so a job that meets it parks with the
reason "Lockdown mode is on" (wait_reason starts with REASON) and goes again by itself once Lockdown is off: resume(), run
when the setting is saved here and every few seconds by watch(), which also notices another app turning it off.
"""
import ipaddress
import logging
import threading
import time
from urllib.parse import urlparse

from . import db, jobs, settings

log = logging.getLogger("core.lockdown")

KEY = "core.lockdown"
REASON = "Lockdown mode is on"
WHY = f"{REASON} (Settings → Privacy)"
SENTENCE = f"{REASON}, so nothing leaves this computer. Turn it off in Settings → Privacy to go ahead."
WATCH_SECONDS = 5


class Blocked(jobs.Wait):
    """Lockdown stopped a request before it was sent. A job that meets it parks until Lockdown is off; a request to
    the app's API gets 409 with SENTENCE (app.py)."""

    def __init__(self, message: str = REASON):
        super().__init__(message)


def on() -> bool:
    return bool(settings.get_all().get(KEY))


def blocked(what: str) -> str | None:
    """Why `what` can't happen now, in words for a person, or None when it may."""
    return f"{what} is off while Lockdown is on (Settings → Privacy)." if on() else None


def local(url: str | None) -> bool:
    """The address is this computer: localhost, or a loopback IP (127.x.x.x, ::1)."""
    host = (urlparse(url or "").hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


on_this_computer = local


def may_reach(url: str | None = None) -> bool:
    """"May I reach the cloud?": whether this app may send a request to `url` now (with no url, anywhere beyond this
    computer). Yes when Lockdown is off, or the address is this computer."""
    return local(url) or not on()


def check(url: str | None = None) -> None:
    """Raises Blocked unless may_reach(url). Call it right before a request leaves the app."""
    if not may_reach(url):
        raise Blocked()


# ── Parked work ───────────────────────────────────────────────────────

def parked() -> list[dict]:
    """The jobs waiting for Lockdown to be off, oldest first."""
    return db.query("SELECT id, module, kind, target FROM core_jobs WHERE status = 'waiting' AND wait_reason LIKE ? "
                    "ORDER BY created_at", (REASON + "%",))


def resume() -> int:
    """Lockdown is off: everything it parked goes again. Returns how many jobs went."""
    waiting = parked()
    if not waiting or on():
        return 0
    for job in waiting:
        jobs.release(job["id"])
    log.info("Lockdown is off: %s parked jobs go again", len(waiting))
    return len(waiting)


_watching = False


def watch() -> None:
    """Notices Lockdown turned off, here or in another family app, and lets the work it parked go."""
    global _watching
    if _watching:
        return
    _watching = True

    def loop():
        while True:
            time.sleep(WATCH_SECONDS)
            try:
                resume()
            except Exception:  # noqa: BLE001 - one missed look only delays the work a few seconds
                log.exception("couldn't resume the work Lockdown parked")

    threading.Thread(target=loop, daemon=True, name="lockdown-watch").start()


def status() -> dict:
    """For the app's chrome, Settings and the Mac app's updater (GET /api/lockdown)."""
    return {"on": on(), "parked": len(parked())}
