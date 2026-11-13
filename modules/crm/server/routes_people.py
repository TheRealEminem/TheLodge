"""People and organizations as seen from you: who you know, how well, and where."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from . import hats, people_net, research, store, views
from .kinds import EVENT_KINDS
from .connections import TIER_RANK, sort_key
from .schemas import ConnectionUpdate, OrgPage, PeoplePage

router = APIRouter()


def _matches(q: str, *fields: object) -> bool:
    return any(q in str(f).lower() for f in fields if f)


def _match_rank(q: str, name: str, aliases: list[str]) -> int:
    """How well a person matches what was typed: their name starts with it (or a word in it does), their name
    has it somewhere, an alias has it, or only their role, organization, place or tags do."""
    name = name.lower()
    if name.startswith(q) or any(w.startswith(q) for w in name.split()):
        return 0
    if q in name:
        return 1
    return 2 if any(q in a.lower() for a in aliases) else 3


def _meeting_tags(v) -> dict[str, set[str]]:
    """Tag -> who was on a meeting or document with that tag. Kept apart from a person's own tags."""
    out: dict[str, set[str]] = {}
    for e in v.snap.of_kind(*EVENT_KINDS):
        if not e.tags:
            continue
        people = {(r.target_id if r.source_id == e.id else r.source_id) for r in v.snap.by_entity.get(e.id, ())}
        people &= set(v.conns)
        for t in e.tags:
            if people:
                out.setdefault(t, set()).update(people)
    return out


def _topic_members(topic: str) -> set[str]:
    g = people_net.get().every_group.get(f"topic:{topic}")
    return set(g.members) if g else set()


def _filtered(v, *, hat=None, org=None, tag=None, topic=None, mtag=None) -> list[str]:
    ents = v.snap.entities
    ids = list(v.conns)
    only = hats.lens_people(hat)
    if only is not None:
        ids = [pid for pid in ids if pid in only]
    if org:
        s = v.orgs.get(org)
        members = s.people if s else set()
        ids = [pid for pid in ids if pid in members]
    if tag:
        ids = [pid for pid in ids if tag.lower() in (ents[pid].tags or [])]
    if topic:
        members = _topic_members(topic)
        ids = [pid for pid in ids if pid in members]
    if mtag:
        members = _meeting_tags(v).get(mtag.lower(), set())
        ids = [pid for pid in ids if pid in members]
    return ids


@router.get("/people/facets")
def people_facets(hat: str | None = None, org: str | None = None, tag: str | None = None, topic: str | None = None, mtag: str | None = None):
    """What the people in view can be filtered by, kept apart: their tags, organizations, topics and the tags on their
    meetings, each counted with the other filters applied."""
    v = views.get()
    ents = v.snap.entities

    def counted(items) -> list[dict]:
        return sorted(items, key=lambda x: (-x["count"], x["name"].lower()))

    tags: dict[str, int] = {}
    for pid in _filtered(v, hat=hat, org=org, topic=topic, mtag=mtag):
        for t in ents[pid].tags or []:
            tags[t] = tags.get(t, 0) + 1
    in_org = set(_filtered(v, hat=hat, tag=tag, topic=topic, mtag=mtag))
    orgs = [{"id": oid, "name": ents[oid].name, "count": n} for oid, s in v.orgs.items() if (n := len(s.people & in_org))]
    in_topic = set(_filtered(v, hat=hat, org=org, tag=tag, mtag=mtag))
    topics = [{"id": g.ref, "name": g.name, "count": n} for g in people_net.get().every_group.values()
              if g.kind == "topic" and g.ref and (n := len(in_topic & set(g.members)))]
    in_mtag = set(_filtered(v, hat=hat, org=org, tag=tag, topic=topic))
    mtags = [{"id": t, "name": t, "count": n} for t, people in _meeting_tags(v).items() if (n := len(people & in_mtag))]
    return {"tags": counted({"id": t, "name": t, "count": n} for t, n in tags.items()), "orgs": counted(orgs),
            "topics": counted(topics), "meeting_tags": counted(mtags)}


@router.get("/organizations/facets")
def org_facets(hat: str | None = None):
    v = views.get()
    only = hats.lens_orgs(hat)
    tags: dict[str, int] = {}
    for oid in v.orgs:
        if only is None or oid in only:
            for t in v.snap.entities[oid].tags or []:
                tags[t] = tags.get(t, 0) + 1
    return {"tags": sorted(({"id": t, "name": t, "count": n} for t, n in tags.items()), key=lambda x: (-x["count"], x["name"]))}


@router.get("/people")
def list_people(
    tier: str | None = Query(None, description="Comma-separated: strong,working,light,indirect,none"),
    org: str | None = None,
    tag: str | None = None,
    topic: str | None = None,
    mtag: str | None = None,
    hat: str | None = None,
    q: str | None = None,
    needs_research: bool = False,
    sort: Literal["strength", "recent", "name", "added", "meetings", "match"] = "strength",
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    v = views.get()
    ents, conns = v.snap.entities, v.conns
    flags = research.states(v)
    # Work with ids and the connection numbers, and build full rows only for the page asked for: at tens of thousands
    # of people, building a row for each is most of the time.
    ids = _filtered(v, hat=hat)
    book_needs = sum(1 for pid in ids if flags.get(pid) == research.NEEDED)
    if needs_research:
        ids = [pid for pid in ids if flags.get(pid) == research.NEEDED]
    if org or tag or topic or mtag:
        narrowed = set(_filtered(v, org=org, tag=tag, topic=topic, mtag=mtag))
        ids = [pid for pid in ids if pid in narrowed]
    if q and q.strip():
        needle = q.strip().lower()

        def hit(pid: str) -> bool:
            p, a = ents[pid], ents[pid].attributes or {}
            employer = v.employer(pid)
            return _matches(needle, p.name, a.get("title"), employer.name if employer else None, a.get("location"),
                            " ".join(p.tags or []), " ".join(a.get("aliases") or []))
        ids = [pid for pid in ids if hit(pid)]
    tiers = {t: 0 for t in TIER_RANK}
    for pid in ids:
        tiers[conns[pid].tier] += 1
    if tier:
        wanted = set(tier.split(","))
        ids = [pid for pid in ids if conns[pid].tier in wanted]

    name = lambda pid: ents[pid].name.lower()  # noqa: E731
    if sort == "match" and q and q.strip():   # the best matches for what was typed, then the closest people
        needle = q.strip().lower()
        ids.sort(key=lambda pid: (_match_rank(needle, ents[pid].name, (ents[pid].attributes or {}).get("aliases") or []),
                                  *sort_key(conns[pid], ents[pid].name)))
    elif sort == "strength" or sort == "match":
        ids.sort(key=lambda pid: sort_key(conns[pid], ents[pid].name))
    elif sort == "recent":
        ids.sort(key=lambda pid: (conns[pid].last_signal_at is None, -(conns[pid].last_signal_at.timestamp() if conns[pid].last_signal_at else 0), name(pid)))
    elif sort == "meetings":
        ids.sort(key=lambda pid: (-conns[pid].meetings, *sort_key(conns[pid], ents[pid].name)))
    elif sort == "added":
        ids.sort(key=lambda pid: ents[pid].created_at, reverse=True)
    else:
        ids.sort(key=name)
    rows = [v.person_row(pid) for pid in ids[offset : offset + limit]]
    for r in rows:
        r.needs_research = flags.get(r.person.id) == research.NEEDED
    return PeoplePage(items=rows, total=len(ids), tiers=tiers, needs_research=book_needs)


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
    hat: str | None = None,
    sort: Literal["known", "people", "recent", "name"] = "known",
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    v = views.get()
    only = hats.lens_orgs(hat)
    rows = [v.org_row(oid) for oid in v.orgs if only is None or oid in only]
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
