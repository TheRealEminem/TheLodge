"""How modules tell each other things without importing each other.

A module publishes "<module>.<thing>.<happened>" (or a shared contract from contracts.py) and any module may
subscribe. Handlers run right away, in the publisher's thread, and must be quick: anything slow belongs in a
job (jobs.enqueue). A failing handler is logged and never breaks the publisher.

Every publish also bumps a change counter that the web app polls (GET /api/changes), so any screen that
shows data can refresh when something changed, whichever module changed it.
"""
import logging
import threading
from collections import defaultdict
from typing import Callable

log = logging.getLogger("core.events")
Handler = Callable[[dict], None]

_subscribers: dict[str, list[Handler]] = defaultdict(list)
_lock = threading.Lock()
_seq = 0
_recent: list[tuple[int, str]] = []  # (seq, name), the last 200, so the web app can tell what changed


def subscribe(name: str, handler: Handler) -> None:
    """name: an exact event name, or a prefix ending in "*" ("notes.*")."""
    _subscribers[name].append(handler)


def publish(name: str, payload: dict | None = None) -> None:
    global _seq
    with _lock:
        _seq += 1
        _recent.append((_seq, name))
        del _recent[:-200]
    for pattern, handlers in list(_subscribers.items()):
        if pattern == name or (pattern.endswith("*") and name.startswith(pattern[:-1])):
            for handler in handlers:
                try:
                    handler(payload or {})
                except Exception:  # noqa: BLE001 - one bad subscriber mustn't break the publisher
                    log.exception("Handler for %s failed", name)


def changes(since: int) -> dict:
    with _lock:
        return {"seq": _seq, "names": sorted({n for s, n in _recent if s > since})}


def reset() -> None:
    """Tests only."""
    global _seq
    _subscribers.clear()
    _recent.clear()
    _seq = 0
