"""Entity lists and detail pages, enriched with subtitle, connection count and last interaction."""
from datetime import UTC, datetime

from . import resolve, views
from .kinds import EVENT_KINDS, RELATIONSHIP_KINDS
from .model import Entity, iso
from .schemas import EntityDetail, EntityOut, RelationshipView


def _last_interaction(v: views.Views, e: Entity, now: datetime) -> datetime | None:
    best = None
    for edge in v.snap.by_entity.get(e.id, []):
        other = v.snap.entities[edge.target_id if edge.source_id == e.id else edge.source_id]
        if other.kind in EVENT_KINDS and other.occurred_at and other.occurred_at <= now:
            best = max(best, other.occurred_at) if best else other.occurred_at
    return best


def entity_out(v: views.Views, e: Entity, now: datetime | None = None) -> EntityOut:
    now = now or datetime.now(UTC)
    employer = v.employer(e.id) if e.kind == "person" else None
    from .summaries import subtitle_for
    return EntityOut(
        id=e.id, kind=e.kind, name=e.name, summary=e.summary, attributes=e.attributes, tags=e.tags,
        occurred_at=e.occurred_at, is_self=e.is_self, source=e.source, created_at=e.created_at,
        updated_at=e.updated_at, subtitle=subtitle_for(e, employer.name if employer else None),
        degree=len(v.snap.by_entity.get(e.id, [])), last_interaction_at=_last_interaction(v, e, now),
    )


def list_entities(kind: str | None, q: str | None, tag: str | None, sort: str, limit: int, offset: int):
    v = views.get()
    now = datetime.now(UTC)
    items = list(v.snap.entities.values())
    if kind:
        kinds = set(kind.split(","))
        items = [e for e in items if e.kind in kinds]
    if tag:
        items = [e for e in items if tag.lower() in e.tags]
    needle = (q or "").strip().lower()
    if needle:
        import json
        items = [e for e in items if needle in e.name.lower() or needle in (e.summary or "").lower()
                 or needle in json.dumps(e.attributes).lower()]
    total = len(items)
    far = datetime.min.replace(tzinfo=UTC)
    if sort == "recent":
        items.sort(key=lambda e: e.created_at or far, reverse=True)
    elif sort == "updated":
        items.sort(key=lambda e: e.updated_at or far, reverse=True)
    elif sort == "occurred":
        items.sort(key=lambda e: (e.occurred_at is None, -(e.occurred_at.timestamp() if e.occurred_at else 0)))
    elif sort == "connections":
        items.sort(key=lambda e: (-len(v.snap.by_entity.get(e.id, [])), e.name.lower()))
    elif sort == "last_interaction":
        last = {e.id: _last_interaction(v, e, now) for e in items}
        items.sort(key=lambda e: (last[e.id] is None, -(last[e.id].timestamp() if last[e.id] else 0), e.name.lower()))
    else:
        items.sort(key=lambda e: e.name.lower())
        if needle:
            items.sort(key=lambda e: -resolve.similarity(e.name, needle))
    page = items[offset: offset + limit]
    return [entity_out(v, e, now) for e in page], total


def entity_detail(entity_id: str) -> EntityDetail | None:
    v = views.get()
    e = v.snap.entities.get(entity_id)
    if e is None:
        return None
    rels = []
    for edge in sorted(v.snap.by_entity.get(entity_id, []), key=lambda r: (r.created_at or datetime.min.replace(tzinfo=UTC), r.id)):
        outgoing = edge.source_id == entity_id
        rel = RELATIONSHIP_KINDS.get(edge.kind)
        rels.append(RelationshipView(
            id=edge.id, kind=edge.kind, direction="out" if outgoing else "in",
            label=(rel.label if outgoing else rel.inverse) if rel else edge.kind,
            other=v.summary(edge.target_id if outgoing else edge.source_id), properties=edge.properties,
            strength=edge.strength, started_at=edge.started_at, ended_at=edge.ended_at, source=edge.source,
            evidence=v.summary(edge.evidence_id) if edge.evidence_id in v.snap.entities else None,
        ))
    return EntityDetail(entity=entity_out(v, e), relationships=rels)
