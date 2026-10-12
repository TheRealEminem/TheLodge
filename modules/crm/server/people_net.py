"""The people-first view of the graph: only people are nodes, and everything else is *why* or *where*.

Lines are connections between two people, each with its reasons:
    direct      you recorded it: knows, introduced by, reports to, related to
    met         both took part in the same meeting or document (attended, wrote)
    mentioned   one took part and the other came up there

Groups are named sets of people, drawn as gravity wells rather than nodes:
    organization  works at, advises or invested in it (now, not formerly)
    topic         took part in something about it, or came up in two or more things about it
    tag           you tagged the person with it

Same employer and same topic are shown by the group, so they don't also draw a line between every pair.
Meetings and documents are the evidence: evidence() lists them for one person.
Everything is derived from the snapshot and cached until something changes.
"""
import itertools
from collections import defaultdict
from dataclasses import dataclass, field

from . import graph as graph_svc, snapshot, store, views
from .kinds import EVENT_KINDS
from .model import iso

PARTICIPATION = {"attended", "authored"}      # being there, or having written it
MENTION = {"discussed_in", "mentioned_in", "about"}   # coming up in it
DIRECT = {"knows": "Know each other", "introduced_by": "was introduced by", "reports_to": "reports to",
          "related_to": "Related"}
MAX_PARTICIPANTS = 12   # a meeting with more people than this says little about who knows whom
MAX_MENTIONED = 15
TOPIC_MIN_SCORE = 2     # taking part counts 2, coming up counts 1
MIN_GROUP = 2
WHY_LIMIT = 6

_PRIORITY = {"direct": 3, "met": 2, "mentioned": 1}


@dataclass
class PLink:
    id: str
    a: str
    b: str
    weight: float = 0
    basis: str = "mentioned"
    why: list[dict] = field(default_factory=list)

    def add(self, basis: str, weight: float, text: str, ref: dict | None = None) -> None:
        self.weight += weight
        if _PRIORITY[basis] > _PRIORITY[self.basis] or not self.why:
            self.basis = basis
        if len(self.why) < WHY_LIMIT:
            self.why.append({"text": text, **({"ref": ref} if ref else {})})


@dataclass
class Group:
    id: str
    kind: str          # organization | topic | tag
    name: str
    ref: str | None    # the organization or topic record, if there is one
    members: dict[str, str] = field(default_factory=dict)   # person id -> why they're in it


@dataclass
class PeopleNet:
    people: dict[str, object]                       # id -> Entity (everyone of kind person)
    me: str | None
    links: dict[str, PLink]
    adj: dict[str, list[tuple[str, str]]]           # person -> [(other person, link id)]
    groups: dict[str, Group]
    member_of: dict[str, list[str]]                 # person -> group ids
    events: dict[str, dict]                         # event id -> {"entity", "people": {pid: role}}
    tiers: dict[str, str]

    def degree(self, pid: str) -> int:
        return len(self.adj.get(pid, ()))

    def as_graph_data(self) -> "graph_svc.GraphData":
        """The same people and lines in the shape graph.py's traversals expect (so paths reuse them)."""
        g = graph_svc.GraphData()
        for pid, e in self.people.items():
            g.nodes[pid] = graph_svc.NodeRow(pid, "person", e.name, e.attributes or {}, e.is_self)
        g.tiers = dict(self.tiers)
        for lid, link in self.links.items():
            g.edges[lid] = graph_svc.EdgeRow(lid, link.a, link.b, link.basis, max(1, min(5, round(link.weight))), None)
            g.adj[link.a].append((link.b, lid))
            g.adj[link.b].append((link.a, lid))
        return g


def _lid(a: str, b: str) -> str:
    return "~".join(sorted((a, b)))


_cache: tuple[int, PeopleNet] | None = None


def get() -> PeopleNet:
    global _cache
    version = store.version()
    if _cache is None or _cache[0] != version:
        _cache = (version, _build())
    return _cache[1]


def _build() -> PeopleNet:
    snap = snapshot.load()
    ents = snap.entities
    me = snap.me.id if snap.me else None
    people = {e.id: e for e in ents.values() if e.kind == "person"}
    v = views.get()
    tiers = {pid: v.tier(pid) for pid in people if pid != me}

    links: dict[str, PLink] = {}

    def link(a: str, b: str) -> PLink:
        lid = _lid(a, b)
        if lid not in links:
            links[lid] = PLink(lid, *sorted((a, b)))
        return links[lid]

    # events: who took part, who came up, which topics and organizations are about it
    events: dict[str, dict] = {}
    topics_of: dict[str, set[str]] = defaultdict(set)
    for r in snap.edges:
        a, b = ents[r.source_id], ents[r.target_id]
        if a.kind in EVENT_KINDS and b.kind not in EVENT_KINDS:
            a, b = b, a
        if b.kind not in EVENT_KINDS or a.kind in EVENT_KINDS:
            continue
        ev = events.setdefault(b.id, {"entity": b, "people": {}})
        if a.kind == "person":
            role = "took part" if r.kind in PARTICIPATION else "came up"
            if ev["people"].get(a.id) != "took part":
                ev["people"][a.id] = role
        elif a.kind == "topic":
            topics_of[b.id].add(a.id)

    # direct lines between people
    for r in snap.edges:
        if r.kind not in DIRECT or r.source_id not in people or r.target_id not in people:
            continue
        a, b = people[r.source_id], people[r.target_id]
        if r.kind == "knows":
            weight = max(1, r.strength or 1)
            text = "You know them" if me in (a.id, b.id) else "Know each other"
        elif r.kind == "related_to":
            weight, text = 1, "Related"
        else:
            weight = 3
            text = f"{a.name} {DIRECT[r.kind]} {b.name}"
        link(a.id, b.id).add("direct", weight, text)

    # lines from shared meetings and documents
    for ev_id, ev in events.items():
        e = ev["entity"]
        ref = {"id": e.id, "kind": e.kind, "name": e.name}
        took = [p for p, role in ev["people"].items() if role == "took part"]
        came = [p for p, role in ev["people"].items() if role == "came up"]
        verb = "Both took part in" if e.kind == "meeting" else "Both on"
        if 2 <= len(took) <= MAX_PARTICIPANTS:
            for x, y in itertools.combinations(took, 2):
                link(x, y).add("met", 2, f"{verb} {e.name}", ref)
        if took and came and len(took) <= MAX_PARTICIPANTS and len(came) <= MAX_MENTIONED:
            for x in took:
                for y in came:
                    if x != y:
                        link(x, y).add("mentioned", 1, f"{people[y].name} came up in {e.name}", ref)
    for lnk in links.values():
        lnk.weight = min(5.0, lnk.weight)

    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for lid, lnk in links.items():
        adj[lnk.a].append((lnk.b, lid))
        adj[lnk.b].append((lnk.a, lid))

    groups: dict[str, Group] = {}

    # organizations
    for r in snap.edges:
        if r.kind not in ("works_at", "advises", "invested_in") or r.ended_at is not None:
            continue
        a, b = ents[r.source_id], ents[r.target_id]
        if a.kind != "person" or b.kind != "organization" or a.id == me:
            continue
        g = groups.setdefault(f"org:{b.id}", Group(f"org:{b.id}", "organization", b.name, b.id))
        g.members.setdefault(a.id, {"works_at": "Works there", "advises": "Advises them", "invested_in": "Invested in them"}[r.kind])

    # topics: score each person by the things about the topic they took part in or came up in
    score: dict[tuple[str, str], int] = defaultdict(int)
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for ev_id, ts in topics_of.items():
        e = events[ev_id]["entity"]
        for pid, role in events[ev_id]["people"].items():
            if pid == me:
                continue
            points = 2 if role == "took part" else 1
            for t in ts:
                score[(t, pid)] += points
                if (t, pid) not in best or points > best[(t, pid)][0]:
                    best[(t, pid)] = (points, f"{'Took part in' if points == 2 else 'Came up in'} {e.name}")
    for (t, pid), s in score.items():
        if s >= TOPIC_MIN_SCORE:
            g = groups.setdefault(f"topic:{t}", Group(f"topic:{t}", "topic", ents[t].name, t))
            g.members[pid] = best[(t, pid)][1]
    for r in snap.edges:  # a topic you linked to a person yourself
        if r.kind == "related_to":
            a, b = ents[r.source_id], ents[r.target_id]
            if a.kind == "topic" and b.kind == "person":
                a, b = b, a
            if a.kind == "person" and b.kind == "topic" and a.id != me:
                g = groups.setdefault(f"topic:{b.id}", Group(f"topic:{b.id}", "topic", b.name, b.id))
                g.members[a.id] = "Linked to it"

    # tags
    for pid, p in people.items():
        if pid == me:
            continue
        for tag in p.tags or []:
            g = groups.setdefault(f"tag:{tag}", Group(f"tag:{tag}", "tag", tag.replace("-", " "), None))
            g.members[pid] = "Tagged"

    groups = {gid: g for gid, g in groups.items() if len(g.members) >= MIN_GROUP}
    member_of: dict[str, list[str]] = defaultdict(list)
    for gid, g in sorted(groups.items(), key=lambda kv: (-len(kv[1].members), kv[1].name.lower())):
        for pid in g.members:
            member_of[pid].append(gid)
    return PeopleNet(people, me, links, dict(adj), groups, dict(member_of), events, tiers)


# ── What the API returns ──────────────────────────────────────────────

def _node(net: PeopleNet, pid: str, depth: int | None = None) -> dict:
    e = net.people[pid]
    from .summaries import subtitle_for
    employer = None
    for gid in net.member_of.get(pid, ()):
        if gid.startswith("org:") and net.groups[gid].members[pid] == "Works there":
            employer = net.groups[gid].name
            break
    return {"id": pid, "name": e.name, "subtitle": subtitle_for(e, employer), "degree": net.degree(pid),
            "is_self": e.is_self, "tier": net.tiers.get(pid), "depth": depth, "groups": net.member_of.get(pid, []),
            "tags": list(e.tags or [])}


def _link(net: PeopleNet, lid: str) -> dict:
    link = net.links[lid]
    return {"id": lid, "source": link.a, "target": link.b, "basis": link.basis, "weight": round(link.weight, 1), "why": link.why}


def group_list(net: PeopleNet) -> list[dict]:
    return [{"id": g.id, "kind": g.kind, "name": g.name, "size": len(g.members), "ref": g.ref}
            for g in sorted(net.groups.values(), key=lambda g: (-len(g.members), g.name.lower()))]


def network(focus: str | None = None, depth: int = 2, max_nodes: int = 400) -> dict:
    net = get()
    keep: dict[str, int | None]
    truncated = False
    if focus:
        if focus not in net.people:
            raise store.NotFound("Person not found")
        keep = {focus: 0}
        frontier = [focus]
        for d in range(1, depth + 1):
            reach = {}
            for u in frontier:
                for w, lid in net.adj.get(u, ()):
                    if w not in keep:
                        reach[w] = max(reach.get(w, 0), net.links[lid].weight)
            ordered = sorted(reach, key=lambda w: (-reach[w], -net.degree(w), net.people[w].name))
            room = max_nodes - len(keep)
            if len(ordered) > room:
                truncated, ordered = True, ordered[:room]
            keep.update({w: d for w in ordered})
            frontier = ordered
            if not frontier:
                break
    else:
        ids = list(net.people)
        if len(ids) > max_nodes:
            truncated = True
            ids.sort(key=lambda p: (not net.people[p].is_self, -net.degree(p)))
            ids = ids[:max_nodes]
        keep = dict.fromkeys(ids)
    nodes = [_node(net, pid, d) for pid, d in sorted(keep.items(), key=lambda kv: net.people[kv[0]].name.lower())]
    lids = [lid for lid, l in net.links.items() if l.a in keep and l.b in keep]
    return {"nodes": nodes, "links": [_link(net, lid) for lid in lids], "groups": group_list(net), "truncated": truncated}


def group_detail(gid: str) -> dict:
    net = get()
    g = net.groups.get(gid)
    if not g:
        raise store.NotFound("Group not found")
    members = sorted(g.members.items(), key=lambda kv: (net.tiers.get(kv[0]) != "strong", net.people[kv[0]].name.lower()))
    return {"id": g.id, "kind": g.kind, "name": g.name, "ref": g.ref, "size": len(g.members),
            "members": [{"id": pid, "name": net.people[pid].name, "tier": net.tiers.get(pid), "why": why} for pid, why in members]}


def evidence(pid: str) -> list[dict]:
    """The meetings and documents behind one person's lines: each with who else was there (or came up)."""
    net = get()
    if pid not in net.people:
        raise store.NotFound("Person not found")
    out = []
    for ev_id, ev in net.events.items():
        if pid not in ev["people"]:
            continue
        e = ev["entity"]
        others = [p for p in ev["people"] if p != pid and p in net.people]
        out.append({"id": e.id, "kind": e.kind, "name": e.name, "at": iso(e.occurred_at), "role": ev["people"][pid],
                    "people": others[:40]})
    out.sort(key=lambda x: (x["at"] or "", x["name"]), reverse=True)
    return out


def paths(target: str, limit: int = 5, max_hops: int = 4) -> dict:
    """How the owner reaches `target` through people, strongest first, each hop with its reasons."""
    net = get()
    if target not in net.people or not net.me:
        raise store.NotFound("Person not found")
    g = net.as_graph_data()
    found = graph_svc.shortest_paths(g, net.me, target, max_hops, limit)
    out = []
    for p in found:
        links = []
        for gl in p.links:
            d = gl.model_dump()
            d["why"] = net.links[gl.id].why
            d["label"] = net.links[gl.id].why[0]["text"] if net.links[gl.id].why else gl.kind
            links.append(d)
        out.append({"nodes": [n.model_dump() for n in p.nodes], "links": links, "hops": p.hops, "score": p.score})
    return {"source": g.to_node(net.me).model_dump(), "target": g.to_node(target).model_dump(), "paths": out}


# ── Tags ──────────────────────────────────────────────────────────────

def retag(ids: list[str], add: list[str], remove: list[str]) -> int:
    """Add and remove tags on several people at once. Returns how many changed."""
    add, remove = store.normalize_tags(add), set(store.normalize_tags(remove))
    changed = 0
    for pid in dict.fromkeys(ids):
        e = store.get_entity(pid)
        if e is None or e.kind != "person":
            continue
        tags = [t for t in e.tags if t not in remove]
        tags += [t for t in add if t not in tags]
        if tags != e.tags:
            store.update_entity(pid, tags=tags)
            changed += 1
    return changed


def tag_names() -> list[dict]:
    """Every tag in use on people, with how many carry it (for suggestions while typing)."""
    count: dict[str, int] = defaultdict(int)
    for p in get().people.values():
        for t in p.tags or []:
            count[t] += 1
    return [{"tag": t, "count": n} for t, n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))]
