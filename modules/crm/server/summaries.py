"""Short, human-readable labels for entities ("CTO · Acme", "Climate tech")."""
from .model import Entity
from .schemas import EntitySummary


def subtitle_for(entity, employer: str | None = None) -> str | None:
    a = entity.attributes or {}
    if entity.kind == "person":
        parts = [p for p in (a.get("title"), employer) if p]
        return " · ".join(parts) or a.get("email") or a.get("location")
    if entity.kind == "organization":
        return a.get("industry") or a.get("domain") or a.get("website")
    if entity.kind == "meeting":
        return a.get("location")
    if entity.kind == "document":
        return a.get("doc_type") or a.get("url")
    return a.get("description")


def to_summary(entity: Entity, subtitle: str | None = None) -> EntitySummary:
    return EntitySummary(id=entity.id, kind=entity.kind, name=entity.name, subtitle=subtitle,
                         occurred_at=entity.occurred_at, is_self=entity.is_self)
