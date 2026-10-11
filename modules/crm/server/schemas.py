from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)




# ---------- Entities ----------





class EntitySummary(ORM):
    id: str
    kind: str
    name: str
    subtitle: str | None = None
    occurred_at: datetime | None = None
    is_self: bool = False


class EntityOut(ORM):
    id: str
    kind: str
    name: str
    summary: str | None
    attributes: dict[str, Any]
    tags: list[str]
    occurred_at: datetime | None
    is_self: bool
    source: str
    created_at: datetime
    updated_at: datetime
    subtitle: str | None = None
    degree: int = 0
    last_interaction_at: datetime | None = None



# ---------- Relationships ----------






class RelationshipView(BaseModel):
    """An edge seen from one entity's point of view."""

    id: str
    kind: str
    direction: Literal["out", "in"]
    label: str
    other: EntitySummary
    properties: dict[str, Any]
    strength: int
    started_at: date | None
    ended_at: date | None
    source: str
    evidence: EntitySummary | None = None


class EntityDetail(BaseModel):
    entity: EntityOut
    relationships: list[RelationshipView]


# ---------- Notes ----------




# ---------- Timeline ----------


class TimelineEvent(BaseModel):
    id: str
    at: datetime
    type: Literal["meeting", "document", "relationship", "relationship_end", "note"]
    title: str
    detail: str | None = None
    entity: EntitySummary | None = None
    via: EntitySummary | None = None


# ---------- Graph ----------


class GraphNode(BaseModel):
    id: str
    kind: str
    name: str
    subtitle: str | None = None
    degree: int = 0
    is_self: bool = False
    depth: int | None = None
    tier: str | None = None  # people only: how well you know them


class GraphLink(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    strength: int


class Graph(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    truncated: bool = False


class GraphPath(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    hops: int
    score: float


class PathResult(BaseModel):
    source: GraphNode
    target: GraphNode
    paths: list[GraphPath]




# ---------- Connections (everything seen from "me") ----------

Tier = Literal["strong", "working", "light", "indirect", "none"]


class ConnectionOut(BaseModel):
    tier: Tier
    score: int
    strength: int | None = None
    user_set: bool = False
    context: str | None = None
    roles: list[str] = []
    meetings: int = 0
    first_met_at: datetime | None = None
    last_met_at: datetime | None = None
    coauthored: int = 0
    mentions: int = 0
    last_mentioned_at: datetime | None = None
    mutual: list[EntitySummary] = []
    via: list[EntitySummary] = []


class ConnectionUpdate(BaseModel):
    # None clears your rating and goes back to the automatic tier.
    strength: int | None = Field(default=None, ge=1, le=5)


class PersonRow(BaseModel):
    person: EntitySummary
    title: str | None = None
    org: EntitySummary | None = None
    location: str | None = None
    tags: list[str] = []
    connection: ConnectionOut
    created_at: datetime


class PeoplePage(BaseModel):
    items: list[PersonRow]
    total: int
    tiers: dict[str, int]


class ContactRef(BaseModel):
    person: EntitySummary
    tier: Tier


class OrgRow(BaseModel):
    org: EntitySummary
    tags: list[str] = []
    members: int = 0
    past: int = 0
    affiliates: int = 0
    known: int = 0
    best_tier: Tier = "none"
    contacts: list[ContactRef] = []
    mine: Literal["current", "past"] | None = None
    mentions: int = 0
    last_activity_at: datetime | None = None
    connected: bool = False


class OrgPage(BaseModel):
    items: list[OrgRow]
    total: int
    scopes: dict[str, int]


class RoleOut(BaseModel):
    kind: str
    label: str
    title: str | None = None
    started_at: date | None = None
    ended_at: date | None = None


class Affiliation(BaseModel):
    org: EntitySummary
    roles: list[RoleOut]
    current: bool
    known: int = 0


class PersonLink(BaseModel):
    person: EntitySummary
    relation: str
    detail: str | None = None
    current: bool = True
    tier: Tier = "none"


class OrgLink(BaseModel):
    org: EntitySummary
    relation: str


class EventRef(BaseModel):
    event: EntitySummary
    role: str
    with_me: bool = False
    people: list[EntitySummary] = []
    snippet: str | None = None


class EntityContext(BaseModel):
    connection: ConnectionOut | None = None
    org: OrgRow | None = None
    affiliations: list[Affiliation] = []
    people: list[PersonLink] = []
    orgs: list[OrgLink] = []
    meetings: list[EventRef] = []
    documents: list[EventRef] = []
    topics: list[EntitySummary] = []
