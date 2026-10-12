"""People and organizations as seen from you: who you know, how well, and where."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from . import research, store, views
from .connections import TIER_RANK, sort_key
from .schemas import ConnectionOut, ConnectionUpdate, EntityContext, OrgPage, PeoplePage

router = APIRouter()


def _matches(q: str, *fields: object) -> bool:
    return any(q in str(f).lower() for f in fields if f)


@router.get("/people")
def list_people(
    tier: str | None = Query(None, description="Comma-separated: strong,working,light,indirect,none"),
    org: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    needs_research: bool = False,
    sort: Literal["strength", "recent", "name", "added", "meetings"] = "strength",
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    v = views.get()
    flags = research.states(v)
    rows = [v.person_row(pid) for pid in v.conns]
    for r in rows:
        r.needs_research = flags.get(r.person.id) == research.NEEDED
    book_needs = sum(1 for r in rows if r.needs_research)
    if needs_research:
        rows = [r for r in rows if r.needs_research]
    if org:
        s = v.orgs.get(org)
        members = s.people if s else set()
        rows = [r for r in rows if r.person.id in members]
    if tag:
        rows = [r for r in rows if tag.lower() in r.tags]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if _matches(
                needle,
                r.person.name,
                r.title,
                r.org.name if r.org else None,
                r.location,
                " ".join(r.tags),
                " ".join(v.snap.entities[r.person.id].attributes.get("aliases") or []),
            )
        ]
    tiers = {t: 0 for t in TIER_RANK}
    for r in rows:
        tiers[r.connection.tier] += 1
    if tier:
        wanted = set(tier.split(","))
        rows = [r for r in rows if r.connection.tier in wanted]

    conns = v.conns
    if sort == "strength":
        rows.sort(key=lambda r: sort_key(conns[r.person.id], r.person.name))
    elif sort == "recent":
        rows.sort(key=lambda r: (conns[r.person.id].last_signal_at is None, -(conns[r.person.id].last_signal_at.timestamp() if conns[r.person.id].last_signal_at else 0), r.person.name.lower()))
    elif sort == "meetings":
        rows.sort(key=lambda r: (-r.connection.meetings, *sort_key(conns[r.person.id], r.person.name)))
    elif sort == "added":
        rows.sort(key=lambda r: r.created_at, reverse=True)
    else:
        rows.sort(key=lambda r: r.person.name.lower())
    return PeoplePage(items=rows[offset : offset + limit], total=len(rows), tiers=tiers, needs_research=book_needs)


@router.put("/people/{person_id}/connection")
def set_connection(person_id: str, body: ConnectionUpdate):
    """Rate how well you know someone (1-5). The rating overrides the automatic tier."""
    me = store.get_me()
    if me is None:
        raise HTTPException(422, "Set who you are first (This is me)")
    person = store.get_entity(person_id)
    if person is None or person.kind != "person":
        raise HTTPException(404, "Person not found")
    if person.is_self:
        raise HTTPException(422, "That's you")

    edge = store.find_edge(me.id, person_id, "knows")
    if body.strength is None:
        if edge is not None:
            props = {k: v for k, v in edge.properties.items() if k not in ("user_set", "from_rating")}
            if edge.properties.get("from_rating") and not props:
                store.delete_edge(edge.id)
            else:
                store.update_edge(edge.id, properties=props)
    elif edge is None:
        store.create_edge(me.id, person_id, "knows", strength=body.strength,
                          properties={"user_set": True, "from_rating": True})
    else:
        store.update_edge(edge.id, strength=body.strength, properties={**edge.properties, "user_set": True})
    return views.get().connection(person_id)


@router.get("/organizations")
def list_organizations(
    scope: Literal["known", "connected", "mentioned", "all"] = "known",
    q: str | None = None,
    tag: str | None = None,
    sort: Literal["known", "people", "recent", "name"] = "known",
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    v = views.get()
    rows = [v.org_row(oid) for oid in v.orgs]
    if tag:
        rows = [r for r in rows if tag.lower() in r.tags]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if _matches(
                needle,
                r.org.name,
                r.org.subtitle,
                " ".join(r.tags),
                " ".join(v.snap.entities[r.org.id].attributes.get("aliases") or []),
            )
        ]
    in_scope = {
        "known": lambda r: bool(r.known or r.mine),
        "connected": lambda r: r.connected,
        "mentioned": lambda r: not r.connected,
        "all": lambda r: True,
    }
    scopes = {name: sum(1 for r in rows if test(r)) for name, test in in_scope.items()}
    rows = [r for r in rows if in_scope[scope](r)]

    if sort == "known":
        rows.sort(key=lambda r: (r.mine is None, -r.known, -TIER_RANK[r.best_tier], -(r.members + r.past + r.affiliates), -r.mentions, r.org.name.lower()))
    elif sort == "people":
        rows.sort(key=lambda r: (-(r.members + r.past + r.affiliates), r.org.name.lower()))
    elif sort == "recent":
        rows.sort(key=lambda r: (r.last_activity_at is None, -(r.last_activity_at.timestamp() if r.last_activity_at else 0), r.org.name.lower()))
    else:
        rows.sort(key=lambda r: r.org.name.lower())
    return OrgPage(items=rows[offset : offset + limit], total=len(rows), scopes=scopes)


@router.get("/entities/{entity_id}/context")
def entity_context(entity_id: str):
    """Everything a profile page shows beyond the record itself, grouped for tabs."""
    v = views.get()
    if entity_id not in v.snap.entities:
        raise HTTPException(404, "Entity not found")
    return v.context(entity_id)
