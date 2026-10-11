"""Plain records for the CRM's tables. The attribute names match the old ORM models, so code that works on
an in-memory snapshot (tiers, paths, page views) reads them the same way. Ids are random text."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    # Microseconds: rows created in the same millisecond (an import) keep their order.
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    summary: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    occurred_at: datetime | None = None
    is_self: bool = False
    source: str = "manual"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Relationship:
    id: str
    source_id: str
    target_id: str
    kind: str
    properties: dict[str, Any] = field(default_factory=dict)
    strength: int = 3
    started_at: date | None = None
    ended_at: date | None = None
    source: str = "manual"
    evidence_id: str | None = None
    created_at: datetime | None = None


@dataclass
class Note:
    id: str
    entity_id: str
    body: str
    occurred_at: datetime | None = None
    source: str = "manual"
    evidence_id: str | None = None
    created_at: datetime | None = None
