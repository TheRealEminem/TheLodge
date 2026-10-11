"""API views over a connection snapshot: people rows, organization rows and
the context bundle behind each profile page. Built in memory from one load of
the graph, so a page costs two queries however many people it shows."""

import re
from datetime import datetime

from .kinds import RELATIONSHIP_KINDS
from .model import Entity, Relationship
from .schemas import (
    Affiliation,
    ConnectionOut,
    ContactRef,
    EntityContext,
    EntitySummary,
    EventRef,
    OrgLink,
    OrgRow,
    PersonLink,
    PersonRow,
    RoleOut,
)
from .connections import (
    KNOWN_TIERS,
    TIER_RANK,
    Connection,
    Index,
    OrgStats,
    build_index,
    compute,
    current_org,
    org_stats,
    sort_key,
)
from . import snapshot, store
from .snapshot import Snapshot
from .summaries import subtitle_for, to_summary

SNIPPET = 220


def _label(edge: Relationship, outgoing: bool) -> str:
    rel = RELATIONSHIP_KINDS.get(edge.kind)
    if rel is None:
        return edge.kind.replace("_", " ")
    return rel.label if outgoing else rel.inverse


def _timestamp(when: datetime | None) -> float:
    return when.timestamp() if when else 0.0


def _title(edge: Relationship) -> str | None:
    props = edge.properties or {}
    return props.get("title") or props.get("context")


def _role_at(edge: Relationship, org_name: str) -> str | None:
    """The part of a multi-job title that belongs to this organization.

    Extraction often copies someone's whole headline ("Principal, Nora Linden
    Consulting; Part-time COO, UvaVac") onto every job; show only "Principal"
    at Nora Linden Consulting."""
    props = edge.properties or {}
    title = props.get("title")
    if not title:
        return props.get("context")
    parts = [p.strip() for p in re.split(r"[;|]", title) if p.strip()]
    if len(parts) == 1 and "," not in title:
        return title
    org = org_name.lower()
    for part in parts:
        at = part.lower().find(org)
        if at < 0:
            continue
        # "Role, Org" / "Role, Org A and Org B": the role is what precedes the first comma.
        comma = part.find(",")
        if 0 < comma < at:
            return part[:comma].strip() or None
        role = re.sub(re.escape(org_name), "", part, flags=re.IGNORECASE).strip(" ,-@–·")
        return re.sub(r"[\s,]+(at|of|for|and|&)$", "", role, flags=re.IGNORECASE) or None
    return props.get("context") if len(parts) > 1 else title


class Views:
    def __init__(self, snap: Snapshot, me_id: str | None = None):
        snap = snap.seen_from(me_id)
        self.snap = snap
        self.ix: Index = build_index(snap)
        self.conns: dict[str, Connection] = compute(snap, self.ix)
        self._orgs: dict[str, OrgStats] | None = None
        self._employer: dict[str, Entity | None] = {}

    @property
    def me(self) -> Entity | None:
        return self.snap.me

    @property
    def orgs(self) -> dict[str, OrgStats]:
        if self._orgs is None:
            self._orgs = org_stats(self.snap, self.ix)
        return self._orgs

    # ---------- small pieces ----------

    def employer(self, pid: str) -> Entity | None:
        if pid not in self._employer:
            self._employer[pid] = current_org(self.snap, self.ix, pid)
        return self._employer[pid]

    def summary(self, eid: str) -> EntitySummary:
        e = self.snap.entities[eid]
        employer = self.employer(eid) if e.kind == "person" else None
        return to_summary(e, subtitle_for(e, employer.name if employer else None))

    def tier(self, pid: str) -> str:
        if self.me and pid == self.me.id:
            return "strong"
        c = self.conns.get(pid)
        return c.tier if c else "none"

    def connection(self, pid: str) -> ConnectionOut:
        c = self.conns[pid]
        return ConnectionOut(
            tier=c.tier,
            score=c.score,
            strength=c.strength,
            user_set=c.user_set,
            context=c.context,
            roles=c.roles,
            meetings=c.meetings,
            first_met_at=c.first_met_at,
            last_met_at=c.last_met_at,
            coauthored=c.coauthored,
            mentions=c.mentions,
            last_mentioned_at=c.last_mentioned_at,
            mutual=[self.summary(m) for m in sorted(c.mutual, key=lambda m: sort_key(self.conns[m], self.snap.entities[m].name))],
            via=[self.summary(v) for v in c.via],
        )

    def person_row(self, pid: str) -> PersonRow:
        p = self.snap.entities[pid]
        a = p.attributes or {}
        org = self.employer(pid)
        return PersonRow(
            person=self.summary(pid),
            title=a.get("title"),
            org=self.summary(org.id) if org else None,
            location=a.get("location"),
            tags=p.tags or [],
            connection=self.connection(pid),
            created_at=p.created_at,
        )

    def org_row(self, oid: str) -> OrgRow:
        o = self.snap.entities[oid]
        s = self.orgs[oid]
        known = [p for p in s.people if self.tier(p) in KNOWN_TIERS]
        known.sort(key=lambda p: sort_key(self.conns[p], self.snap.entities[p].name))
        best = max((self.tier(p) for p in s.people), key=lambda t: TIER_RANK[t], default="none")
        return OrgRow(
            org=self.summary(oid),
            tags=o.tags or [],
            members=len(s.members),
            past=len(s.past),
            affiliates=len(s.affiliates),
            known=len(known),
            best_tier=best,  # type: ignore[arg-type]
            contacts=[ContactRef(person=self.summary(p), tier=self.tier(p)) for p in known[:3]],  # type: ignore[arg-type]
            mine=s.mine,
            mentions=s.mentions,
            last_activity_at=s.last_activity_at,
            connected=s.connected,
        )

    def _event_ref(self, ev_id: str, role: str, exclude: set[str]) -> EventRef:
        ev = self.snap.entities[ev_id]
        present = self.ix.attendees.get(ev_id, set()) | self.ix.authors.get(ev_id, set())
        people = [p for p in present if p not in exclude and self.snap.entities[p].kind == "person"]
        people.sort(key=lambda p: (not self.snap.entities[p].is_self, self.snap.entities[p].name.lower()))
        snippet = (ev.summary or "").strip()
        return EventRef(
            event=self.summary(ev_id),
            role=role,
            with_me=bool(self.me and self.me.id in self.ix.attendees.get(ev_id, set()) | self.ix.authors.get(ev_id, set())),
            people=[self.summary(p) for p in people],
            snippet=(snippet[:SNIPPET] + "…") if len(snippet) > SNIPPET else snippet or None,
        )

    def _events(self, kind: str, roles: dict[str, str], exclude: set[str]) -> list[EventRef]:
        ids = [i for i in roles if self.snap.entities[i].kind == kind]
        ids.sort(key=lambda i: _timestamp(self.snap.entities[i].occurred_at), reverse=True)
        return [self._event_ref(i, roles[i], exclude) for i in ids]

    def _topics(self, eid: str) -> list[EntitySummary]:
        ids = set()
        for edge in self.snap.edges:
            if eid in (edge.source_id, edge.target_id):
                other = edge.target_id if edge.source_id == eid else edge.source_id
                if self.snap.entities[other].kind == "topic":
                    ids.add(other)
        return sorted((self.summary(i) for i in ids), key=lambda s: s.name.lower())

    # ---------- profile context ----------

    def context(self, eid: str) -> EntityContext:
        e = self.snap.entities[eid]
        if e.kind == "person":
            return self._person_context(e)
        if e.kind == "organization":
            return self._org_context(e)
        if e.kind == "topic":
            return self._topic_context(e)
        return self._event_context(e)

    def _topic_context(self, t: Entity) -> EntityContext:
        ix, ents = self.ix, self.snap.entities
        meetings = {mid: "discussed" for mid, named in ix.discussed.items() if t.id in named}
        docs = {did: "mentioned" for did, named in ix.mentioned.items() if t.id in named}
        people = []
        for edge in self.snap.edges:
            if t.id not in (edge.source_id, edge.target_id):
                continue
            other = edge.target_id if edge.source_id == t.id else edge.source_id
            if ents[other].kind == "person" and not ents[other].is_self:
                people.append(
                    PersonLink(person=self.summary(other), relation=_label(edge, edge.source_id == other), tier=self.tier(other))  # type: ignore[arg-type]
                )
        people.sort(key=lambda l: (-TIER_RANK[l.tier], l.person.name.lower()))
        return EntityContext(
            people=people,
            meetings=self._events("meeting", meetings, set()),
            documents=self._events("document", docs, set()),
        )

    def _person_context(self, p: Entity) -> EntityContext:
        ix, ents, me = self.ix, self.snap.entities, self.me
        by_org: dict[str, list[Relationship]] = {}
        for org_id, edge in ix.affiliations.get(p.id, []):
            by_org.setdefault(org_id, []).append(edge)
        affiliations = []
        for org_id, edges in by_org.items():
            org_name = ents[org_id].name
            roles = [
                RoleOut(kind=e.kind, label=_label(e, True), title=_role_at(e, org_name), started_at=e.started_at, ended_at=e.ended_at)
                for e in sorted(edges, key=lambda e: (e.kind != "works_at", e.ended_at is not None))
            ]
            s = self.orgs.get(org_id)
            known = sum(1 for q in (s.people if s else ()) if q != p.id and self.tier(q) in KNOWN_TIERS)
            affiliations.append(
                Affiliation(org=self.summary(org_id), roles=roles, current=any(e.ended_at is None for e in edges), known=known)
            )
        affiliations.sort(
            key=lambda a: (
                not a.current,
                a.roles[0].kind != "works_at",
                -(a.roles[0].started_at.toordinal() if a.roles[0].started_at else 0),
            )
        )

        links: dict[str, PersonLink] = {}

        def add(pid: str, relation: str, detail: str | None = None, current: bool = True) -> None:
            if pid == p.id or (me and pid == me.id) or ents[pid].kind != "person":
                return
            if pid in links:
                link = links[pid]
                if relation not in link.relation.split(" · "):
                    link.relation += f" · {relation}"
                link.detail = link.detail or detail
                link.current = link.current or current
            else:
                links[pid] = PersonLink(
                    person=self.summary(pid), relation=relation, detail=detail, current=current, tier=self.tier(pid)  # type: ignore[arg-type]
                )

        for other, edge in ix.ties.get(p.id, []):
            add(other, _label(edge, edge.source_id == p.id), (edge.properties or {}).get("context"))
        met: dict[str, int] = {}
        for meeting_id, present in ix.attendees.items():
            if p.id in present:
                for other in present - {p.id}:
                    met[other] = met.get(other, 0) + 1
        for other, n in met.items():
            add(other, f"{n} meeting{'s' if n > 1 else ''} together")
        for org_id, edge in ix.affiliations.get(p.id, []):
            if edge.kind != "works_at" or edge.ended_at is not None:
                continue
            s = self.orgs.get(org_id)
            for colleague in s.members if s else ():
                add(colleague, f"colleague at {ents[org_id].name}")
        people = sorted(links.values(), key=lambda l: (-TIER_RANK[l.tier], l.person.name.lower()))

        meetings: dict[str, str] = {}
        for mid, present in ix.attendees.items():
            if p.id in present:
                meetings[mid] = "attended"
        for mid, named in ix.discussed.items():
            if p.id in named and mid not in meetings:
                meetings[mid] = "discussed"
        docs: dict[str, str] = {}
        for did, authors in ix.authors.items():
            if p.id in authors:
                docs[did] = "authored"
        for did, subjects in ix.subjects.items():
            if p.id in subjects and did not in docs:
                docs[did] = "about them"
        for did, named in ix.mentioned.items():
            if p.id in named and did not in docs:
                docs[did] = "mentioned"

        return EntityContext(
            connection=self.connection(p.id) if p.id in self.conns else None,
            affiliations=affiliations,
            people=people,
            meetings=self._events("meeting", meetings, {p.id}),
            documents=self._events("document", docs, {p.id}),
            topics=self._topics(p.id),
        )

    def _org_context(self, o: Entity) -> EntityContext:
        ix, ents = self.ix, self.snap.entities
        s = self.orgs[o.id]
        links: list[PersonLink] = []
        for pid, affs in ix.affiliations.items():
            if self.me and pid == self.me.id:
                continue
            for org_id, edge in affs:
                if org_id != o.id:
                    continue
                current = edge.ended_at is None
                relation = ("works at" if current else "worked at") if edge.kind == "works_at" else _label(edge, True)
                links.append(
                    PersonLink(
                        person=self.summary(pid), relation=relation, detail=_role_at(edge, o.name), current=current, tier=self.tier(pid)  # type: ignore[arg-type]
                    )
                )
        links.sort(key=lambda l: (not l.current, -TIER_RANK[l.tier], l.person.name.lower()))

        relations: dict[str, list[str]] = {}
        for other, edge in ix.org_links.get(o.id, []):
            label = _label(edge, edge.source_id == o.id)
            if label not in relations.setdefault(other, []):
                relations[other].append(label)
        orgs = [OrgLink(org=self.summary(other), relation=" · ".join(labels)) for other, labels in relations.items()]
        orgs.sort(key=lambda l: (l.relation, l.org.name.lower()))

        staff = s.members | s.past
        meetings: dict[str, str] = {}
        for mid, named in ix.discussed.items():
            if o.id in named:
                meetings[mid] = "discussed"
        for mid, present in ix.attendees.items():
            if mid not in meetings and (present & staff):
                names = sorted(ents[q].name for q in present & staff)
                meetings[mid] = "with " + ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
        docs: dict[str, str] = {}
        for did in {d for d, a in ix.authors.items() if o.id in a}:
            docs[did] = "authored"
        for did, subjects in ix.subjects.items():
            if o.id in subjects and did not in docs:
                docs[did] = "about them"
        for did, named in ix.mentioned.items():
            if o.id in named and did not in docs:
                docs[did] = "mentioned"
        for did, authors in ix.authors.items():
            if did not in docs and authors & staff:
                docs[did] = "by their people"

        return EntityContext(
            org=self.org_row(o.id),
            people=links,
            orgs=orgs,
            meetings=self._events("meeting", meetings, set()),
            documents=self._events("document", docs, set()),
            topics=self._topics(o.id),
        )

    def _event_context(self, ev: Entity) -> EntityContext:
        ix, ents = self.ix, self.snap.entities
        people: list[PersonLink] = []
        orgs: list[OrgLink] = []
        roles = [
            (ix.attendees.get(ev.id, set()), "attended"),
            (ix.authors.get(ev.id, set()), "authored"),
            (ix.subjects.get(ev.id, set()), "subject"),
            (ix.discussed.get(ev.id, set()) | ix.mentioned.get(ev.id, set()), "discussed" if ev.kind == "meeting" else "mentioned"),
        ]
        seen: set[str] = set()
        for ids, relation in roles:
            for i in ids - seen:
                seen.add(i)
                kind = ents[i].kind
                if kind == "person":
                    people.append(PersonLink(person=self.summary(i), relation=relation, tier=self.tier(i)))  # type: ignore[arg-type]
                elif kind == "organization":
                    orgs.append(OrgLink(org=self.summary(i), relation=relation))
        people.sort(key=lambda l: (l.relation not in ("attended", "authored"), not l.person.is_self, -TIER_RANK[l.tier], l.person.name.lower()))
        orgs.sort(key=lambda l: l.org.name.lower())
        return EntityContext(people=people, orgs=orgs, topics=self._topics(ev.id))


_cache: dict[str | None, tuple[int, Views]] = {}


def get(me_id: str | None = None) -> Views:
    """The page views, from `me_id`'s point of view (None = the CRM owner). Cached until something changes."""
    version = store.version()
    hit = _cache.get(me_id)
    if hit is None or hit[0] != version:
        hit = (version, Views(snapshot.load(), me_id))
        _cache.clear()
        _cache[me_id] = hit
    return hit[1]
