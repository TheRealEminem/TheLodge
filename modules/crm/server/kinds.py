"""Vocabulary for the knowledge graph: node kinds and edge kinds.

Kinds are stored as plain strings so new ones can be added here without a
migration. The frontend reads this registry from GET /api/meta.
"""

from dataclasses import asdict, dataclass

ENTITY_KINDS: dict[str, dict] = {
    "person": {"label": "Person", "plural": "People", "is_event": False},
    "organization": {"label": "Organization", "plural": "Organizations", "is_event": False},
    "meeting": {"label": "Meeting", "plural": "Meetings", "is_event": True},
    "document": {"label": "Document", "plural": "Documents", "is_event": True},
    "topic": {"label": "Topic", "plural": "Topics", "is_event": False},
}

EVENT_KINDS = {k for k, v in ENTITY_KINDS.items() if v["is_event"]}

PEOPLE = ("person",)
ORGS = ("organization",)
ACTORS = ("person", "organization")


@dataclass(frozen=True)
class RelKind:
    label: str  # read source -> target: "Ana works at Acme"
    inverse: str  # read target -> source: "Acme employs Ana"
    sources: tuple[str, ...] | None = None  # None = any kind
    targets: tuple[str, ...] | None = None
    symmetric: bool = False


RELATIONSHIP_KINDS: dict[str, RelKind] = {
    "works_at": RelKind("works at", "employs", PEOPLE, ORGS),
    "advises": RelKind("advises", "advised by", PEOPLE, ACTORS),
    "invested_in": RelKind("invested in", "backed by", ACTORS, ORGS),
    "introduced_by": RelKind("introduced by", "introduced", PEOPLE, PEOPLE),
    "knows": RelKind("knows", "knows", PEOPLE, PEOPLE, symmetric=True),
    "reports_to": RelKind("reports to", "manages", PEOPLE, PEOPLE),
    "attended": RelKind("attended", "attended by", PEOPLE, ("meeting",)),
    "discussed_in": RelKind("discussed in", "discussed", None, ("meeting",)),
    "authored": RelKind("authored", "authored by", ACTORS, ("document",)),
    "mentioned_in": RelKind("mentioned in", "mentions", None, ("document",)),
    "about": RelKind("subject of", "about", None, ("document",)),
    "partner_of": RelKind("partner of", "partner of", ORGS, ORGS, symmetric=True),
    "part_of": RelKind("part of", "includes", ("organization", "topic"), ("organization", "topic")),
    "related_to": RelKind("related to", "related to", None, None, symmetric=True),
}


def validate_relationship(kind: str, source_kind: str, target_kind: str) -> str | None:
    """Return an error message, or None if the edge is allowed."""
    rel = RELATIONSHIP_KINDS.get(kind)
    if rel is None:
        return f"Unknown relationship kind '{kind}'"
    if rel.sources is not None and source_kind not in rel.sources:
        return f"'{kind}' cannot start from a {source_kind}"
    if rel.targets is not None and target_kind not in rel.targets:
        return f"'{kind}' cannot point to a {target_kind}"
    return None


def meta() -> dict:
    return {
        "entity_kinds": ENTITY_KINDS,
        "relationship_kinds": {k: asdict(v) for k, v in RELATIONSHIP_KINDS.items()},
    }
