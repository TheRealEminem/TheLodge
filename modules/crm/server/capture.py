"""What the automatic syncs (Granola, calendars) share: where each got to, and taking back what one brought in.

Everything a sync creates is stamped with its origin in the `source` column of the entities, lines and notes it
makes ("granola", "calendar"). That is the handle for removing it: `preview(origin)` says what would go,
`remove(origin)` does it. Tags are not used for this, because a tag would turn into a group on the network.
"""
import json
import logging

from core.server import db, events

from . import inbox, store

log = logging.getLogger("crm.capture")

ORIGINS = {"granola": "Granola", "calendar": "Calendar"}


# ── Where each sync got to ────────────────────────────────────────────

def get_state(name: str) -> dict:
    row = db.one("SELECT state FROM crm_sync WHERE name = ?", (name,))
    return json.loads(row["state"]) if row else {}


def set_state(name: str, **fields) -> dict:
    """Merges into what's kept (a None removes a field)."""
    state = {**get_state(name), **fields}
    state = {k: v for k, v in state.items() if v is not None}
    db.execute("INSERT INTO crm_sync (name, state, updated_at) VALUES (?, ?, ?) "
               "ON CONFLICT(name) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
               (name, json.dumps(state), db.now()))
    events.publish("crm.capture.changed", {"name": name})
    return state


# ── Taking it back ────────────────────────────────────────────────────

def _enriched(attrs: dict, has_notes: bool) -> bool:
    """A calendar event that something else has since written into (meeting notes, a summary): it's no longer just
    the calendar's, so removing the calendar's events leaves it alone."""
    others = set((attrs.get("external_ids") or {})) - {"calendar"}
    return bool(others or attrs.get("key_points") or attrs.get("action_items") or has_notes)


def _plan(origin: str) -> dict:
    """What `remove` would delete, worked out without deleting anything."""
    if origin not in ORIGINS:
        raise ValueError("Unknown source")
    with_notes = {r["entity_id"] for r in db.query("SELECT DISTINCT entity_id FROM crm_notes WHERE source != ?", (origin,))}
    meetings, kept_ids = [], []
    for r in db.query("SELECT id, attributes, summary FROM crm_entities WHERE kind = 'meeting' AND source = ?", (origin,)):
        if origin == "calendar" and (r["summary"] or _enriched(json.loads(r["attributes"] or "{}"), r["id"] in with_notes)):
            kept_ids.append(r["id"])
        else:
            meetings.append(r["id"])
    gone = set(meetings)
    # Others this source created that nothing else holds on to once the meetings are gone: no lines to anything that
    # stays, no notes of your own, no summary.
    people = []
    for r in db.query("SELECT id, summary FROM crm_entities WHERE kind != 'meeting' AND source = ? AND is_self = 0", (origin,)):
        if r["summary"] or r["id"] in with_notes:
            continue
        edges = db.query("SELECT source_id, target_id FROM crm_relationships WHERE source_id = ? OR target_id = ?", (r["id"], r["id"]))
        if all((e["target_id"] if e["source_id"] == r["id"] else e["source_id"]) in gone for e in edges):
            people.append(r["id"])
    return {"meetings": meetings, "people": people, "kept": len(kept_ids), "kept_ids": kept_ids}


def _loose_lines(origin: str, plan: dict) -> list[str]:
    """Lines the source drew that are not part of a meeting being deleted or of one that stays."""
    leaving = set(plan["meetings"]) | set(plan["kept_ids"])
    return [r["id"] for r in db.query("SELECT id, source_id, target_id FROM crm_relationships WHERE source = ?", (origin,))
            if r["source_id"] not in leaving and r["target_id"] not in leaving]


def preview(origin: str) -> dict:
    plan = _plan(origin)
    return {"origin": origin, "label": ORIGINS[origin], "meetings": len(plan["meetings"]), "people": len(plan["people"]),
            "kept": plan["kept"], "lines": len(_loose_lines(origin, plan))}


def remove(origin: str) -> dict:
    """Deletes what a sync brought in: its meetings (and their lines and notes), the people and organizations it made
    that nothing else holds on to, and any other line it drew. Items it brought through the inbox are marked as
    discarded there, so the same meeting is not imported again by the next sync."""
    from .ingest import _apply_lock   # the same lock the inbox uses when it writes
    with _apply_lock:
        plan = _plan(origin)
        counts = {"meetings": 0, "people": 0, "lines": 0}
        for entity_id in plan["meetings"]:
            store.delete_entity(entity_id)
            counts["meetings"] += 1
        for entity_id in plan["people"]:
            if store.get_entity(entity_id) is not None:
                store.delete_entity(entity_id)
                counts["people"] += 1
        for edge_id in _loose_lines(origin, plan):
            if store.get_edge(edge_id) is not None:
                store.delete_edge(edge_id)
                counts["lines"] += 1
        db.execute("DELETE FROM crm_notes WHERE source = ?", (origin,))
        for r in db.query("SELECT id FROM crm_inbox WHERE json_extract(payload, '$.origin') = ? AND status IN ('applied', 'review', 'pending')",
                          (origin,)):
            inbox.update(r["id"], status="discarded", error=f"Removed with everything from {ORIGINS[origin]}.")
    store._touch()
    return {**counts, "kept": plan["kept"]}
