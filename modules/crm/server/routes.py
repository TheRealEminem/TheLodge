"""The People API, mounted at /api/crm: entities, relationships, notes and "me".
(Tiers, profiles and the dashboard arrive with the views, in the next chunk.)"""
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from . import dashboard as dash
from . import graph as graph_svc
from . import listing, routes_people, store, timeline as timeline_svc, views
from .kinds import ENTITY_KINDS, RELATIONSHIP_KINDS, validate_relationship
from .model import Entity, Note, Relationship, iso

router = APIRouter()
router.include_router(routes_people.router)


# ── Shapes ────────────────────────────────────────────────────────────

def entity_out(e: Entity) -> dict:
    return {"id": e.id, "kind": e.kind, "name": e.name, "summary": e.summary, "attributes": e.attributes,
            "tags": e.tags, "occurred_at": iso(e.occurred_at), "is_self": e.is_self, "source": e.source,
            "created_at": iso(e.created_at), "updated_at": iso(e.updated_at)}


def edge_out(r: Relationship) -> dict:
    return {"id": r.id, "source_id": r.source_id, "target_id": r.target_id, "kind": r.kind,
            "properties": r.properties, "strength": r.strength,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "source": r.source, "evidence_id": r.evidence_id, "created_at": iso(r.created_at)}


def note_out(n: Note) -> dict:
    return {"id": n.id, "entity_id": n.entity_id, "body": n.body, "occurred_at": iso(n.occurred_at),
            "source": n.source, "evidence_id": n.evidence_id, "created_at": iso(n.created_at)}


class EntityIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=300)
    summary: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in ENTITY_KINDS:
            raise ValueError(f"kind must be one of {sorted(ENTITY_KINDS)}")
        return v


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = None
    attributes: dict[str, Any] | None = None
    tags: list[str] | None = None
    occurred_at: datetime | None = None


class EdgeIn(BaseModel):
    source_id: str
    target_id: str
    kind: str
    properties: dict[str, Any] = Field(default_factory=dict)
    strength: int = Field(default=3, ge=1, le=5)
    started_at: date | None = None
    ended_at: date | None = None
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in RELATIONSHIP_KINDS:
            raise ValueError(f"kind must be one of {sorted(RELATIONSHIP_KINDS)}")
        return v


class EdgePatch(BaseModel):
    properties: dict[str, Any] | None = None
    strength: int | None = Field(default=None, ge=1, le=5)
    started_at: date | None = None
    ended_at: date | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1)
    occurred_at: datetime | None = None


class MergeIn(BaseModel):
    into_id: str


class MeIn(BaseModel):
    entity_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)


def _missing(e: store.NotFound) -> HTTPException:
    return HTTPException(404, str(e))


# ── Meta ──────────────────────────────────────────────────────────────

@router.get("/meta")
def meta():
    from .kinds import meta as kinds_meta
    return kinds_meta()


# ── Entities ──────────────────────────────────────────────────────────

@router.get("/entities")
def list_entities(kind: str | None = None, q: str | None = None, tag: str | None = None,
                  sort: Literal["name", "recent", "updated", "last_interaction", "connections", "occurred"] = "name",
                  limit: int = 50, offset: int = 0):
    items, total = listing.list_entities(kind, q, tag, sort, max(1, min(limit, 500)), max(0, offset))
    return {"items": items, "total": total}


@router.post("/entities", status_code=201)
def create_entity(body: EntityIn):
    e = store.create_entity(body.kind, body.name, summary=body.summary, attributes=body.attributes,
                            tags=body.tags, occurred_at=body.occurred_at)
    return entity_out(e)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    detail = listing.entity_detail(entity_id)
    if detail is None:
        raise HTTPException(404, "Entity not found")
    return detail


@router.get("/entities/{entity_id}/timeline")
def timeline(entity_id: str):
    e = store.get_entity(entity_id)
    if e is None:
        raise HTTPException(404, "Entity not found")
    return timeline_svc.entity_timeline(e)


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: EntityPatch):
    try:
        return entity_out(store.update_entity(entity_id, **body.model_dump(exclude_unset=True)))
    except store.NotFound as e:
        raise _missing(e) from e


@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(entity_id: str):
    try:
        store.delete_entity(entity_id)
    except store.NotFound as e:
        raise _missing(e) from e
    return Response(status_code=204)


@router.post("/entities/{entity_id}/merge")
def merge_entity(entity_id: str, body: MergeIn):
    """Merge this entity into `into_id` (this one is deleted)."""
    try:
        return entity_out(store.merge_entities(entity_id, body.into_id))
    except store.NotFound as e:
        raise _missing(e) from e
    except store.MergeError as e:
        raise HTTPException(422, str(e)) from e


# ── Relationships ─────────────────────────────────────────────────────

@router.post("/relationships", status_code=201)
def create_relationship(body: EdgeIn):
    if body.source_id == body.target_id:
        raise HTTPException(422, "A relationship needs two different entities")
    source, target = store.get_entity(body.source_id), store.get_entity(body.target_id)
    if source is None or target is None:
        raise HTTPException(404, "Source or target not found")
    if err := validate_relationship(body.kind, source.kind, target.kind):
        raise HTTPException(422, err)
    try:
        edge = store.create_edge(body.source_id, body.target_id, body.kind, properties=body.properties,
                                 strength=body.strength, started_at=body.started_at, ended_at=body.ended_at,
                                 evidence_id=body.evidence_id)
    except store.EdgeExists as e:
        raise HTTPException(409, str(e)) from e
    return edge_out(edge)


@router.patch("/relationships/{rel_id}")
def update_relationship(rel_id: str, body: EdgePatch):
    edge = store.get_edge(rel_id)
    if edge is None:
        raise HTTPException(404, "Relationship not found")
    changes = body.model_dump(exclude_unset=True)
    me = store.get_me()
    if "strength" in changes and edge.kind == "knows" and me and me.id in (edge.source_id, edge.target_id):
        # Rating your own tie is a statement of how well you know them: it overrides the automatic tier.
        changes["properties"] = {**(changes.get("properties") or edge.properties), "user_set": True}
    return edge_out(store.update_edge(rel_id, **changes))


@router.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: str):
    try:
        store.delete_edge(rel_id)
    except store.NotFound as e:
        raise _missing(e) from e
    return Response(status_code=204)


# ── Notes ─────────────────────────────────────────────────────────────

@router.get("/entities/{entity_id}/notes")
def list_notes(entity_id: str):
    if store.get_entity(entity_id) is None:
        raise HTTPException(404, "Entity not found")
    return [note_out(n) for n in store.notes_of(entity_id)]


@router.post("/entities/{entity_id}/notes", status_code=201)
def add_note(entity_id: str, body: NoteIn):
    if store.get_entity(entity_id) is None:
        raise HTTPException(404, "Entity not found")
    return note_out(store.add_note(entity_id, body.body, occurred_at=body.occurred_at))


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str):
    try:
        store.delete_note(note_id)
    except store.NotFound as e:
        raise _missing(e) from e
    return Response(status_code=204)


# ── Me ────────────────────────────────────────────────────────────────

@router.get("/me")
def get_me():
    me = store.get_me()
    return entity_out(me) if me else None


@router.put("/me")
def set_me(body: MeIn):
    """Mark an existing person as "me", or create one from a name."""
    if not body.entity_id and not body.name:
        raise HTTPException(422, "Provide entity_id or name")
    try:
        return entity_out(store.set_me(body.entity_id, body.name))
    except store.NotFound as e:
        raise _missing(e) from e


# ── Graph and dashboard ───────────────────────────────────────────────

def _kinds(kinds: str | None) -> set[str] | None:
    return {k for k in kinds.split(",") if k} if kinds else None


@router.get("/graph")
def get_graph(center: str | None = None, depth: int = Query(2, ge=1, le=4), kinds: str | None = None,
              max_nodes: int = Query(400, ge=10, le=3000)):
    """Whole network, or the neighborhood around `center`."""
    g = graph_svc.load_graph(_kinds(kinds))
    if center is None:
        return graph_svc.overview(g, max_nodes)
    if center not in g.nodes:
        raise HTTPException(404, "Center entity not found (or filtered out by kinds)")
    return graph_svc.ego(g, center, depth, max_nodes)


@router.get("/graph/paths")
def find_paths(target: str, source: str | None = None, max_hops: int = Query(4, ge=1, le=6),
               limit: int = Query(5, ge=1, le=20), through: str | None = None):
    """How is `source` (default: you) connected to `target`? Shortest paths, strongest ties first."""
    if source is None:
        me = store.get_me()
        if me is None:
            raise HTTPException(422, "No source given and no 'me' record set")
        source = me.id
    g = graph_svc.load_graph()
    if source not in g.nodes or target not in g.nodes:
        raise HTTPException(404, "Source or target not found")
    return {"source": g.to_node(source), "target": g.to_node(target),
            "paths": graph_svc.shortest_paths(g, source, target, max_hops, limit, _kinds(through))}


@router.get("/dashboard")
def dashboard():
    return dash.build_dashboard()


@router.post("/admin/demo")
def load_demo(force: bool = False):
    from . import seed
    if seed.has_demo():
        raise HTTPException(409, "The demo network is already loaded.")
    if seed.has_data() and not force:
        raise HTTPException(409, "There is already data. Pass ?force=true to add the demo network anyway.")
    return seed.seed_demo()


@router.delete("/admin/demo")
def remove_demo():
    from . import seed
    return {"deleted": seed.remove_demo()}
