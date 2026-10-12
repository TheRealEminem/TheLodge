"""The whole graph in memory, loaded once and reused until something changes.

Tiers, paths and page views are computed over a snapshot (a personal CRM is hundreds to tens of thousands of
records), not by SQL. The snapshot is cached against store.version() and must be treated as read-only."""
import gc
import threading
from contextlib import contextmanager
from collections import defaultdict
from dataclasses import dataclass, field, replace

from . import store
from .model import Entity, Relationship


@dataclass(frozen=True)
class Snapshot:
    entities: dict[str, Entity]
    edges: list[Relationship]
    me: Entity | None
    by_entity: dict[str, list[Relationship]] = field(default_factory=dict)

    def of_kind(self, *kinds: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.kind in kinds]

    def seen_from(self, me_id: str | None) -> "Snapshot":
        """The same graph from another person's point of view (None = the CRM owner)."""
        if me_id is None:
            return self
        return replace(self, me=self.entities.get(me_id))


@contextmanager
def building():
    """Building the graph makes hundreds of thousands of small objects in a burst, and Python's cycle collector keeps
    stopping to look through them (most of the time at tens of thousands of records). None of them are garbage yet,
    so it's paused for the build."""
    was = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was:
            gc.enable()


_lock = threading.Lock()
_cache: tuple[int, Snapshot] | None = None


def load() -> Snapshot:
    global _cache
    with _lock:
        version = store.version()
        if _cache is None or _cache[0] != version:
            with building():
                entities = {e.id: e for e in store.all_entities()}
                edges = store.all_edges()
                me = next((e for e in entities.values() if e.is_self), None)
                by_entity: dict[str, list[Relationship]] = defaultdict(list)
                for edge in edges:
                    by_entity[edge.source_id].append(edge)
                    by_entity[edge.target_id].append(edge)
                _cache = (version, Snapshot(entities, edges, me, dict(by_entity)))
        return _cache[1]
