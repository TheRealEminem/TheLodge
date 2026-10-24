"""Recurring work: a module says "run this kind of job every so often" and the host does the asking.

    Module(..., recurring={"sync": lambda: 900})        # seconds; 0 pauses it (nothing is set up, so nothing to do)

Each time it is due the host queues an ordinary job (module, kind, target "scheduled"), so it runs on the job
runner like everything else, with the same lanes, and shows up the same way. Like any job it may run twice (a
restart, a press of "sync now"), so handlers check what's done before doing it. The clock lives in memory: after a
restart everything is due again a short while later, which is the point.

Rows for finished runs are cleared as the next one is queued, so a job that runs every 15 minutes leaves one row,
not thousands. The module keeps whatever history it cares about.
"""
import logging
import threading
import time
from typing import Callable

from . import db, jobs

log = logging.getLogger("core.schedule")

TICK_SECONDS = 20
FIRST_RUN_DELAY = 15      # after start, so the app is up and the window has opened before the first sync
TARGET = "scheduled"

_entries: dict[tuple[str, str], Callable[[], int] | int] = {}
_last: dict[tuple[str, str], float] = {}
_started_at: float | None = None
_thread: threading.Thread | None = None


def register(module: str, kind: str, every: "Callable[[], int] | int") -> None:
    _entries[(module, kind)] = every


def _interval(every: "Callable[[], int] | int") -> int:
    try:
        return int(every() if callable(every) else every)
    except Exception:  # noqa: BLE001 - a broken settings read must not stop the clock
        log.exception("could not work out a schedule")
        return 0


def tick(now: float | None = None) -> list[str]:
    """Queue whatever is due. Returns the kinds queued. (The thread calls this; tests call it with a fake clock.)"""
    now = time.monotonic() if now is None else now
    try:
        jobs.resume_when_room()          # work parked for lack of memory goes again once there's room
    except Exception:  # noqa: BLE001 - never let this stop the clock
        log.exception("could not look for jobs waiting for memory")
    started = _started_at if _started_at is not None else now - FIRST_RUN_DELAY
    queued = []
    for (module, kind), every in list(_entries.items()):
        seconds = _interval(every)
        if seconds <= 0:
            continue
        last = _last.get((module, kind), started + FIRST_RUN_DELAY - seconds)
        if now - last < seconds:
            continue
        _last[(module, kind)] = now
        db.execute("DELETE FROM core_jobs WHERE module = ? AND kind = ? AND target = ? AND status IN ('done', 'error')",
                   (module, kind, TARGET))
        jobs.enqueue(module, kind, TARGET)
        queued.append(f"{module}/{kind}")
    return queued


def start() -> None:
    global _started_at, _thread
    if _thread is not None:
        return
    _started_at = time.monotonic()

    def loop():
        while True:
            time.sleep(TICK_SECONDS)
            try:
                tick()
            except Exception:  # noqa: BLE001
                log.exception("the scheduler could not queue work")

    _thread = threading.Thread(target=loop, daemon=True, name="schedule")
    _thread.start()


def reset() -> None:
    """Tests only."""
    _entries.clear()
    _last.clear()
