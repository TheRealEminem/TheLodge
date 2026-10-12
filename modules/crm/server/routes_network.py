"""The people-first network API, mounted under /api/crm/network."""
import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.server import db

from . import people_net, store

router = APIRouter(prefix="/network")


def _missing(e: store.NotFound) -> HTTPException:
    return HTTPException(404, str(e))


@router.get("")
def get_network(focus: str | None = None, depth: int = Query(2, ge=1, le=3), max_nodes: int = Query(400, ge=10, le=2000)):
    """People and the lines between them, with every group (organizations, topics, tags). `focus` limits it to
    one person's neighborhood."""
    try:
        return people_net.network(focus, depth, max_nodes)
    except store.NotFound as e:
        raise _missing(e) from e


@router.get("/groups/{group_id:path}")
def get_group(group_id: str):
    try:
        return people_net.group_detail(group_id)
    except store.NotFound as e:
        raise _missing(e) from e


@router.get("/evidence/{person_id}")
def get_evidence(person_id: str):
    """The meetings and documents behind a person's lines."""
    try:
        return people_net.evidence(person_id)
    except store.NotFound as e:
        raise _missing(e) from e


@router.get("/paths")
def get_paths(target: str, limit: int = Query(5, ge=1, le=20), max_hops: int = Query(4, ge=1, le=6)):
    """How you reach `target` through people, strongest first, with the reason for each hop."""
    try:
        return people_net.paths(target, limit, max_hops)
    except store.NotFound as e:
        raise _missing(e) from e


# ── Tags ──────────────────────────────────────────────────────────────

class TagChange(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    add: list[str] = []
    remove: list[str] = []


@router.get("/tags")
def get_tags():
    return people_net.tag_names()


@router.post("/tags")
def change_tags(body: TagChange):
    """Add and remove tags on several people at once."""
    return {"changed": people_net.retag(body.ids, body.add, body.remove)}


# ── Saved views ───────────────────────────────────────────────────────

class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    wells: list[str] = Field(max_length=30)


def _view(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "wells": json.loads(row["wells"])}


@router.get("/views")
def list_views():
    return [_view(r) for r in db.query("SELECT * FROM crm_views ORDER BY name COLLATE NOCASE")]


@router.post("/views", status_code=201)
def save_view(body: ViewIn):
    name = body.name.strip()
    existing = db.one("SELECT id FROM crm_views WHERE lower(name) = lower(?)", (name,))
    view_id = existing["id"] if existing else db.new_id()
    db.execute("INSERT INTO crm_views (id, name, wells, created_at) VALUES (?, ?, ?, datetime('now')) "
               "ON CONFLICT(id) DO UPDATE SET name = excluded.name, wells = excluded.wells",
               (view_id, name, json.dumps(body.wells)))
    return _view(db.one("SELECT * FROM crm_views WHERE id = ?", (view_id,)))


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: str):
    if not db.execute("DELETE FROM crm_views WHERE id = ?", (view_id,)):
        raise HTTPException(404, "View not found")
