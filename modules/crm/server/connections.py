"""How strongly the owner ("me") is connected to everyone else.

Nothing here is stored. Tiers are recomputed from the graph on each request,
so a new meeting or a changed rating shows up immediately:

- strong / working / light: you have direct contact (a tie, a meeting, a shared
  organization, a document you wrote together). The tier comes from a score.
- indirect: you've never dealt with them, but they came up in your meetings or
  documents, or people you know are connected to them.

A rating you set by hand (the "Your connection" dots) overrides the score.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .model import Entity, Relationship
from .snapshot import Snapshot

Tier = Literal["strong", "working", "light", "indirect", "none"]
TIER_RANK: dict[str, int] = {"strong": 4, "working": 3, "light": 2, "indirect": 1, "none": 0}
KNOWN_TIERS = ("strong", "working", "light")

# Person-to-person ties that count as "knowing" someone.
TIE_KINDS = {"knows", "advises", "reports_to", "introduced_by", "related_to"}
# Person-to-organization ties, in the order a profile lists them.
AFFILIATION_KINDS = ("works_at", "advises", "invested_in", "related_to")

STRENGTH_POINTS = {1: 8, 2: 18, 3: 32, 4: 60, 5: 80}
USER_TIER: dict[int, Tier] = {5: "strong", 4: "strong", 3: "working", 2: "light", 1: "light"}
TAG_POINTS = {"inner-circle": 45, "family": 45, "core-team": 35}
MEETING_POINTS, MEETING_CAP, HALF_LIFE_DAYS = 14, 45, 365
# A 1:1 or small group counts fully; at a 30-person event you barely met anyone.
SMALL_GROUP = 4
COLLEAGUE_POINTS, FORMER_COLLEAGUE_POINTS, ORG_ROLE_POINTS, ORG_CAP = 30, 15, 25, 40
COAUTHOR_POINTS, COAUTHOR_CAP = 10, 20
MENTION_POINTS, MENTION_CAP, MUTUAL_POINTS, MUTUAL_CAP = 6, 12, 4, 12
STRONG_AT, WORKING_AT = 60, 35

# Tags that describe how you know someone, tolerant of the "inner-cricle" typo.
TAG_ALIASES = {"inner-cricle": "inner-circle"}
TAG_ROLES = {"inner-circle": "inner circle", "family": "family", "core-team": "core team"}

TIE_ROLES = {
    ("advises", "in"): "advises you",
    ("advises", "out"): "you advise them",
    ("reports_to", "in"): "reports to you",
    ("reports_to", "out"): "your manager",
    ("introduced_by", "out"): "introduced you",
    ("introduced_by", "in"): "you introduced them",
}


@dataclass
class Connection:
    tier: Tier = "none"
    score: int = 0
    strength: int | None = None  # your rating on the direct tie, 1-5
    user_set: bool = False
    edge_id: str | None = None  # the "knows" edge the rating lives on
    context: str | None = None  # "met in person", "SOU roommates"
    roles: list[str] = field(default_factory=list)  # "advises you", "colleague at Cinder Labs"
    meetings: int = 0  # meetings you both attended
    first_met_at: datetime | None = None
    last_met_at: datetime | None = None
    coauthored: int = 0
    mentions: int = 0  # times they came up in your meetings/documents
    last_mentioned_at: datetime | None = None
    mutual: list[str] = field(default_factory=list)  # your contacts who know them
    via: list[str] = field(default_factory=list)  # who brought them up

    @property
    def last_signal_at(self) -> datetime | None:
        dates = [d for d in (self.last_met_at, self.last_mentioned_at) if d]
        return max(dates) if dates else None


def _decay(when: datetime | None, now: datetime) -> float:
    if when is None:
        return 0.5
    age = max((now - when).days, 0)
    return 0.5 ** (age / HALF_LIFE_DAYS)


def _tags(e: Entity) -> set[str]:
    return {TAG_ALIASES.get(t, t) for t in (e.tags or [])}


@dataclass
class Index:
    """Adjacency lists over the snapshot, built once per request."""

    attendees: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    discussed: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    authors: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    mentioned: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    subjects: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # person -> [(org, edge)] for person->organization edges
    affiliations: dict[str, list[tuple[str, Relationship]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    ties: dict[str, list[tuple[str, Relationship]]] = field(default_factory=lambda: defaultdict(list))
    org_links: dict[str, list[tuple[str, Relationship]]] = field(
        default_factory=lambda: defaultdict(list)
    )


def build_index(snap: Snapshot) -> Index:
    ix = Index()
    kind = {i: e.kind for i, e in snap.entities.items()}
    for edge in snap.edges:
        s, t = edge.source_id, edge.target_id
        sk, tk = kind.get(s), kind.get(t)
        if edge.kind == "attended":
            ix.attendees[t].add(s)
        elif edge.kind == "discussed_in":
            ix.discussed[t].add(s)
        elif edge.kind == "authored":
            ix.authors[t].add(s)
        elif edge.kind in ("mentioned_in", "about"):
            ix.mentioned[t].add(s)
            if edge.kind == "about":
                ix.subjects[t].add(s)
        elif sk == "person" and tk == "organization" and edge.kind in AFFILIATION_KINDS:
            ix.affiliations[s].append((t, edge))
        elif sk == "person" and tk == "person" and edge.kind in TIE_KINDS:
            ix.ties[s].append((t, edge))
            ix.ties[t].append((s, edge))
        elif sk == "organization" and tk == "organization":
            ix.org_links[s].append((t, edge))
            ix.org_links[t].append((s, edge))
    return ix


def _is_current(edge: Relationship) -> bool:
    return edge.ended_at is None


def compute(snap: Snapshot, ix: Index | None = None, now: datetime | None = None) -> dict[str, Connection]:
    """Connection from `snap.me` to every other person."""
    ix = ix or build_index(snap)
    now = now or datetime.now(UTC)
    people = {e.id: e for e in snap.of_kind("person") if not e.is_self}
    conns = {pid: Connection() for pid in people}
    me = snap.me
    if me is None:
        return conns

    meet_pts: dict[str, float] = defaultdict(float)
    close_meetings: dict[str, float] = defaultdict(float)
    org_pts: dict[str, float] = defaultdict(float)
    working: set[str] = set()
    via: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Direct ties with me.
    for other, edge in ix.ties.get(me.id, []):
        c = conns.get(other)
        if c is None:
            continue
        direction = "out" if edge.source_id == me.id else "in"
        if role := TIE_ROLES.get((edge.kind, direction)):
            c.roles.append(role)
            working.add(other)
        props = edge.properties or {}
        if edge.kind == "knows":
            c.edge_id = edge.id
            if props.get("user_set"):
                c.user_set, c.strength = True, edge.strength
        if not c.user_set:
            c.strength = max(c.strength or 0, edge.strength)
        c.context = c.context or props.get("context")

    # Meetings: attending together is contact; being discussed is an indirect signal.
    for meeting_id, present in ix.attendees.items():
        if me.id not in present:
            continue
        m = snap.entities[meeting_id]
        when = m.occurred_at
        if when and when > now:   # on the calendar, not yet met
            continue
        size = min(1.0, (SMALL_GROUP - 1) / max(len(present) - 1, 1))
        for pid in present - {me.id}:
            c = conns.get(pid)
            if c is None:
                continue
            c.meetings += 1
            close_meetings[pid] += size
            meet_pts[pid] += MEETING_POINTS * size * _decay(when, now)
            if when:
                c.first_met_at = min(filter(None, (c.first_met_at, when)))
                c.last_met_at = max(filter(None, (c.last_met_at, when)))
        for pid in ix.discussed.get(meeting_id, set()) - present:
            c = conns.get(pid)
            if c is None:
                continue
            c.mentions += 1
            if when:
                c.last_mentioned_at = max(filter(None, (c.last_mentioned_at, when)))
            for speaker in present - {me.id, pid}:
                via[pid][speaker] += 1

    # Documents in your library: co-authors are contact; mentions are indirect.
    for doc in snap.of_kind("document"):
        authors = ix.authors.get(doc.id, set())
        mine = me.id in authors
        for pid in authors - {me.id}:
            if mine and (c := conns.get(pid)):
                c.coauthored += 1
                working.add(pid)
        for pid in ix.mentioned.get(doc.id, set()) - authors:
            c = conns.get(pid)
            if c is None:
                continue
            c.mentions += 1
            if doc.occurred_at:
                c.last_mentioned_at = max(filter(None, (c.last_mentioned_at, doc.occurred_at)))
            for author in authors - {me.id, pid}:
                if author in people:
                    via[pid][author] += 1

    # Shared organizations.
    my_orgs = {org: _is_current(e) for org, e in ix.affiliations.get(me.id, []) if e.kind == "works_at"}
    for pid in people:
        c = conns[pid]
        for org_id, edge in ix.affiliations.get(pid, []):
            if org_id not in my_orgs:
                continue
            name = snap.entities[org_id].name
            both_current = my_orgs[org_id] and _is_current(edge)
            if edge.kind == "works_at":
                if both_current:
                    c.roles.append(f"colleague at {name}")
                    org_pts[pid] += COLLEAGUE_POINTS
                    working.add(pid)
                else:
                    c.roles.append(f"former colleague at {name}")
                    org_pts[pid] += FORMER_COLLEAGUE_POINTS
            elif edge.kind in ("advises", "invested_in") and my_orgs[org_id]:
                c.roles.append(f"{'advises' if edge.kind == 'advises' else 'invested in'} {name}")
                org_pts[pid] += ORG_ROLE_POINTS
                working.add(pid)

    # Tags you gave them.
    tag_pts: dict[str, int] = {}
    for pid, p in people.items():
        tags = _tags(p)
        pts = max((TAG_POINTS[t] for t in tags if t in TAG_POINTS), default=0)
        if pts:
            tag_pts[pid] = pts
            conns[pid].roles.extend(TAG_ROLES[t] for t in sorted(tags) if t in TAG_ROLES)
            if "core-team" in tags:
                working.add(pid)

    # Mutual contacts: people you're directly tied to who are tied to them.
    direct = {o for o, _ in ix.ties.get(me.id, []) if o in people}
    for pid in people:
        conns[pid].mutual = [o for o, _ in ix.ties.get(pid, []) if o in direct and o != pid]

    for pid, c in conns.items():
        contact = bool(c.strength or c.meetings or c.coauthored or org_pts[pid] or tag_pts.get(pid))
        activity = (
            min(meet_pts[pid], MEETING_CAP)
            + min(org_pts[pid], ORG_CAP)
            + min(c.coauthored * COAUTHOR_POINTS, COAUTHOR_CAP)
        )
        indirect = min(c.mentions * MENTION_POINTS, MENTION_CAP) + min(len(c.mutual) * MUTUAL_POINTS, MUTUAL_CAP)
        base = max(STRENGTH_POINTS.get(c.strength or 0, 0), tag_pts.get(pid, 0))
        score = base + activity + (indirect / 2 if contact else indirect)
        c.score = round(min(score, 100))
        ranked = sorted(via[pid].items(), key=lambda kv: (-kv[1], snap.entities[kv[0]].name.lower()))
        c.via = [v for v, _ in ranked][:5]
        if c.user_set and c.strength:
            c.tier = USER_TIER[c.strength]
        elif contact:
            if c.score >= STRONG_AT:
                c.tier = "strong"
            elif c.score >= WORKING_AT or pid in working or close_meetings[pid] >= 3:
                c.tier = "working"
            else:
                c.tier = "light"
        elif indirect:
            c.tier = "indirect"
    return conns


def sort_key(c: Connection, name: str) -> tuple:
    return (-TIER_RANK[c.tier], -c.score, name.lower())


@dataclass
class OrgStats:
    members: set[str] = field(default_factory=set)  # current staff
    past: set[str] = field(default_factory=set)
    affiliates: set[str] = field(default_factory=set)  # advisors, investors, other ties
    mine: Literal["current", "past"] | None = None
    linked_to_mine: bool = False
    mentions: int = 0
    last_activity_at: datetime | None = None

    @property
    def people(self) -> set[str]:
        return self.members | self.past | self.affiliates

    @property
    def connected(self) -> bool:
        return bool(self.people or self.mine or self.linked_to_mine)


def org_stats(snap: Snapshot, ix: Index) -> dict[str, OrgStats]:
    orgs = {o.id: OrgStats() for o in snap.of_kind("organization")}
    me_id = snap.me.id if snap.me else None
    for pid, affs in ix.affiliations.items():
        for org_id, edge in affs:
            s = orgs.get(org_id)
            if s is None:
                continue
            if pid == me_id:
                if edge.kind == "works_at":
                    s.mine = "current" if _is_current(edge) else (s.mine or "past")
                continue
            if edge.kind == "works_at":
                (s.members if _is_current(edge) else s.past).add(pid)
            else:
                s.affiliates.add(pid)
    s_mine = {o for o, s in orgs.items() if s.mine}
    for org_id, links in ix.org_links.items():
        if org_id in orgs and any(other in s_mine for other, _ in links):
            orgs[org_id].linked_to_mine = True

    # Activity: meetings/documents that name the org, or that its people attended.
    now = datetime.now(UTC)
    employers: dict[str, set[str]] = defaultdict(set)
    for org_id, s in orgs.items():
        for pid in s.members:
            employers[pid].add(org_id)
    for ev in snap.of_kind("meeting", "document"):
        named = ix.discussed.get(ev.id, set()) | ix.mentioned.get(ev.id, set()) | ix.authors.get(ev.id, set())
        touched = {o for o in named if o in orgs}
        for o in touched:
            orgs[o].mentions += 1
        for pid in ix.attendees.get(ev.id, set()) | ix.authors.get(ev.id, set()):
            touched |= employers.get(pid, set())
        if ev.occurred_at and ev.occurred_at <= now:
            for o in touched:
                orgs[o].last_activity_at = max(filter(None, (orgs[o].last_activity_at, ev.occurred_at)))
    return orgs


def current_org(snap: Snapshot, ix: Index, person_id: str) -> Entity | None:
    """The organization someone works at now (latest start date wins)."""
    jobs = [(o, e) for o, e in ix.affiliations.get(person_id, []) if e.kind == "works_at" and _is_current(e)]
    if not jobs:
        return None
    # Newest start date wins; among undated jobs the one added last.
    jobs.sort(key=lambda oe: (oe[1].started_at is not None, oe[1].started_at or datetime.min.date(),
                              oe[1].created_at or datetime.min.replace(tzinfo=UTC), oe[1].id), reverse=True)
    return snap.entities.get(jobs[0][0])
