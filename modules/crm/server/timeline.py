"""Chronological history for a single entity."""
from datetime import UTC, date, datetime, time

from . import store, views
from .kinds import EVENT_KINDS, RELATIONSHIP_KINDS
from .model import Entity
from .schemas import TimelineEvent


def _at(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=UTC)


def entity_timeline(entity: Entity) -> list[TimelineEvent]:
    v = views.get()
    snap, ix = v.snap, v.ix
    events: list[TimelineEvent] = []
    edges = snap.by_entity.get(entity.id, [])

    # Organizations also show meetings their people attended.
    team: dict[str, list[str]] = {}
    if entity.kind == "organization":
        # Everyone who has worked there, you included (the org's stats leave you out).
        staff = {e.source_id for e in edges if e.kind == "works_at" and e.target_id == entity.id}
        for pid in staff:
            for mid, present in ix.attendees.items():
                if pid in present:
                    team.setdefault(mid, []).append(pid)

    direct_events: set[str] = set()
    for edge in edges:
        outgoing = edge.source_id == entity.id
        other = snap.entities[edge.target_id if outgoing else edge.source_id]
        rel = RELATIONSHIP_KINDS.get(edge.kind)
        label = (rel.label if outgoing else rel.inverse) if rel else edge.kind
        other_summary = v.summary(other.id)

        if other.kind in EVENT_KINDS and other.occurred_at and entity.kind not in EVENT_KINDS:
            direct_events.add(other.id)
            events.append(TimelineEvent(id=f"edge:{edge.id}", at=other.occurred_at, type=other.kind,  # type: ignore[arg-type]
                                        title=other.name, detail=label, entity=other_summary))
            continue

        # Undated edges (e.g. "works at") live in the relationships panel, not here.
        title = f"{label.capitalize()} {other.name}"
        if edge.started_at:
            events.append(TimelineEvent(id=f"edge:{edge.id}", at=_at(edge.started_at), type="relationship", title=title,
                                        detail=edge.properties.get("title") or edge.properties.get("context"),
                                        entity=other_summary))
        if edge.ended_at:
            events.append(TimelineEvent(id=f"edge-end:{edge.id}", at=_at(edge.ended_at), type="relationship_end",
                                        title=f"No longer {label} {other.name}", entity=other_summary))

    for mid, attendees in team.items():
        m = snap.entities[mid]
        if mid in direct_events or not m.occurred_at:
            continue
        names = sorted({snap.entities[p].name for p in attendees})
        events.append(TimelineEvent(id=f"team:{mid}", at=m.occurred_at, type="meeting", title=m.name,
                                    detail="with " + ", ".join(names), entity=v.summary(mid),
                                    via=v.summary(sorted(attendees)[0])))

    for note in store.notes_of(entity.id):
        first_line = note.body.strip().splitlines()[0] if note.body.strip() else "Note"
        events.append(TimelineEvent(id=f"note:{note.id}", at=note.occurred_at, type="note",  # type: ignore[arg-type]
                                    title=first_line[:140], detail=note.body))

    events.sort(key=lambda e: (e.at, e.id), reverse=True)
    return events
