"""Presets: focused questions the network answers, each one a list of people with the reasons beside every name.

Built in, each about something you pick:
    at          who you know at an organization, or in a topic or tag (a sector): staff, people who used to work
                there, advisors, investors, and anyone you linked to it
    intro       who could introduce you to a person or an organization: people you know who know them, met them,
                work alongside them or work there, strongest ties first
    investors   investors and advisors: by tag, by the ties you recorded (invested in, advises) and by title
    event       everyone from a meeting, or a series of meetings with the same name, and anyone tagged with it
    bridges     people in two groups at once
    followups   prospects, leads, thank-you notes and people met at an event, the ones you haven't met or rated first
    rule        a rule over tags, topics, organizations, events and words in titles or summaries, plus people picked
                by hand with a reason each. The AI writes these, from what you ask for or on its own

A preset is worked out fresh from the book every time it runs, so a saved one keeps up as people are added. Nothing
here writes to the graph.

    crm_presets       the ones you saved: a name, a line on what it's for, and its spec
    crm_preset_asks   what you asked the AI for (empty = "suggest some") and the presets it wrote
(the tables are created in store.py, with the module's other tables)

Which AI writes them is the "profiles" job in Settings → AI, the same one that answers questions about a person.
"""
import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.server import ai, db, events, jobs
from core.server.tags import normalize_tags

from . import people_net, profiles, roles, views
from .connections import KNOWN_TIERS, TIER_RANK
from .kinds import EVENT_KINDS
from .model import iso

KINDS = ("at", "intro", "investors", "event", "bridges", "followups", "rule")
RULE_FIELDS = ("tags", "topics", "organizations", "events", "words")
MAX_LIST, MAX_PICKS, MAX_WHY, MAX_REQUEST, KEEP_ASKS = 20, 40, 160, 500, 6

INVESTOR_TAG = re.compile(r"invest|advis|angel|venture|(^|-)vc($|-)")
INVESTOR_TITLE = re.compile(
    r"\b(investors?|angel|venture|vc|advis[eo]rs?|advisory|board member|managing partner|general partner|fund)\b", re.I)
FOLLOW_TAGS = ("prospect", "warm-lead", "partner-lead", "lead", "follow-up", "thank-you-note", "soft-contact")

# A person's tie to an organization: (said on its own page, said elsewhere, points)
ORG_TIES = {
    "works_at": ("Works there", "Works at {org}", 3),
    "former": ("Used to work there", "Used to work at {org}", 2),
    "advises": ("Advises them", "Advises {org}", 3),
    "invested_in": ("Invested in them", "Invested in {org}", 3),
    "related_to": ("Linked to it", "Linked to {org}", 1),
}


class PresetError(ValueError):
    pass


def _now() -> str:
    return iso(datetime.now(UTC))  # type: ignore[return-value]


def _changed() -> None:
    """Tells open screens to refresh. Nothing in the graph changed, so the store's version stays."""
    events.publish("crm.presets.changed", {})


# ── Working out who's in a preset ─────────────────────────────────────

class _Found:
    """People with their reasons. Points add up, so someone who fits several ways comes first."""

    def __init__(self, net: people_net.PeopleNet):
        self.net = net
        self.rows: dict[str, dict] = {}

    def add(self, pid: str, why: str, points: float = 1) -> None:
        if pid not in self.net.people or pid == self.net.me:
            return
        row = self.rows.setdefault(pid, {"why": [], "points": 0.0})
        if why not in row["why"]:
            row["why"].append(why)
            row["points"] += points

    def people(self, by_tier: float = 1) -> list[dict]:
        def rank(pid: str) -> int:
            return TIER_RANK.get(self.net.tiers.get(pid) or "none", 0)
        ordered = sorted(self.rows, key=lambda p: (-(self.rows[p]["points"] + by_tier * rank(p)), -rank(p), self.net.people[p].name.lower()))
        out = []
        for pid in ordered:
            node = people_net._node(self.net, pid)
            out.append({"id": pid, "name": node["name"], "subtitle": node["subtitle"], "tier": node["tier"], "why": self.rows[pid]["why"]})
        return out


def _known(net: people_net.PeopleNet, pid: str) -> bool:
    return net.tiers.get(pid) in KNOWN_TIERS


def _entity(v: views.Views, eid: str, kinds: tuple[str, ...], what: str):
    e = v.snap.entities.get(eid or "")
    if e is None or e.kind not in kinds:
        raise PresetError(f"Pick {what} first")
    return e


def _org_ties(v: views.Views, org_id: str) -> list[tuple[str, str]]:
    """(person id, which tie) for everyone linked to an organization, former staff included."""
    out = []
    for r in v.snap.edges:
        if r.target_id != org_id or v.snap.entities[r.source_id].kind != "person":
            continue
        if r.kind == "works_at":
            out.append((r.source_id, "works_at" if r.ended_at is None else "former"))
        elif r.kind in ("advises", "invested_in", "related_to") and r.ended_at is None:
            out.append((r.source_id, r.kind))
    return out


def _tie_words(text: str, introducer: str, other: str) -> str:
    """A line's reason, said from the introducer's side: "Knows Lena Lowell", "Came up in X, with Lena Lowell",
    "Was introduced by Nora Linden"."""
    if text in ("Know each other", "You know them"):
        return f"Knows {other}"
    if text == "Related":
        return f"Linked to {other}"
    if text.startswith(f"{introducer} "):
        text = text[len(introducer) + 1:]
        text = text[0].upper() + text[1:]
    return text if other in text else f"{text}, with {other}"


def _group_name(net: people_net.PeopleNet, gid: str) -> str:
    g = net.every_group.get(gid)
    if g:
        return g.name
    kind, _, ref = gid.partition(":")
    return ref.replace("-", " ") if kind == "tag" else ref


def _at(net, v, spec: dict) -> dict:
    gid = spec.get("group") or ""
    kind, _, ref = gid.partition(":")
    found = _Found(net)
    if kind == "org":
        org = _entity(v, ref, ("organization",), "an organization")
        for pid, tie in _org_ties(v, org.id):
            found.add(pid, ORG_TIES[tie][0], ORG_TIES[tie][2])
        name = org.name
    elif kind in ("topic", "tag"):
        g = net.every_group.get(gid)
        if kind == "topic":
            _entity(v, ref, ("topic",), "a topic")
        name = _group_name(net, gid)
        for pid, why in (g.members.items() if g else ()):
            found.add(pid, f"Tagged {name}" if why == "Tagged" else why, 2)
    else:
        raise PresetError("Pick an organization, topic or tag first")
    return {"title": f"Who you know at {name}" if kind == "org" else f"Who you know in {name}",
            "about": "Everyone linked to it, the people you know best first.", "people": found.people(by_tier=2)}


def _intro(net, v, spec: dict) -> dict:
    target = _entity(v, spec.get("target") or "", ("person", "organization"), "a person or an organization")
    found = _Found(net)
    about = "People you know, strongest ties first."
    if target.kind == "person":
        if target.id == net.me:
            raise PresetError("That's you")
        for w, lid in net.adj.get(target.id, ()):
            if w != target.id and _known(net, w):
                link = net.links[lid]
                found.add(w, _tie_words(link.why[0]["text"] if link.why else "Know each other", net.people[w].name, target.name),
                          link.weight * TIER_RANK[net.tiers[w]])
        for gid in net.member_of.get(target.id, ()):
            g = net.groups[gid]
            if g.kind == "organization":
                for m in g.members:
                    if m != target.id and _known(net, m):
                        found.add(m, f"Also at {g.name}", 1.5 * TIER_RANK[net.tiers[m]])
        if _known(net, target.id):
            about = f"You know {target.name} yourself ({net.tiers[target.id]}). These people could also put in a word."
    else:
        inside = {}
        for pid, tie in _org_ties(v, target.id):
            if tie != "related_to":
                inside.setdefault(pid, tie)
        for pid, tie in inside.items():
            if _known(net, pid):
                found.add(pid, ORG_TIES[tie][1].format(org=target.name), 3 * TIER_RANK[net.tiers[pid]])
        for pid in inside:
            for w, lid in net.adj.get(pid, ()):
                if w not in inside and _known(net, w):
                    link = net.links[lid]
                    found.add(w, _tie_words(link.why[0]["text"] if link.why else "Know each other", net.people[w].name,
                                            net.people[pid].name),
                              link.weight * TIER_RANK[net.tiers[w]])
        about = "People you know there, then people you know who know someone there."
    return {"title": f"Who could introduce you to {target.name}", "about": about, "people": found.people(by_tier=0)}


def _investors(net, v, spec: dict) -> dict:
    found = _Found(net)
    for pid, p in net.people.items():
        for t in p.tags or []:
            if INVESTOR_TAG.search(t):
                found.add(pid, f"Tagged {t.replace('-', ' ')}", 2)
        title = (p.attributes or {}).get("title") or ""
        if INVESTOR_TITLE.search(title):
            found.add(pid, title, 2)
    ents = v.snap.entities
    for r in v.snap.edges:
        if r.kind in ("invested_in", "advises") and r.ended_at is None and ents[r.source_id].kind == "person":
            other = ents[r.target_id]
            if r.kind == "invested_in":
                found.add(r.source_id, f"Invested in {other.name}", 3)
            else:
                found.add(r.source_id, "Advises you" if other.is_self else f"Advises {other.name}", 3)
    return {"title": "Investors and advisors", "about": "From your tags, the ties you recorded and their titles.",
            "people": found.people()}


def _same_name(a: str, b: str) -> bool:
    return bool(re.search(rf"\b{re.escape(a)}\b", b, re.I) or re.search(rf"\b{re.escape(b)}\b", a, re.I))


def _event(net, v, spec: dict) -> dict:
    ev = _entity(v, spec.get("event") or "", tuple(EVENT_KINDS), "a meeting or document")
    series = [ev] + [x["entity"] for eid, x in net.events.items() if eid != ev.id and _same_name(ev.name, x["entity"].name)]
    found = _Found(net)
    for e in series:
        for pid, role in net.events.get(e.id, {"people": {}})["people"].items():
            found.add(pid, f"{'Took part in' if role == 'took part' else 'Came up in'} {e.name}", 2 if role == "took part" else 1)
    tag = normalize_tags([ev.name])[0]
    for pid, p in net.people.items():
        if tag in (p.tags or []):
            found.add(pid, f"Tagged {tag.replace('-', ' ')}", 2)
    about = "Everyone who took part, came up there, or carries its tag."
    if len(series) > 1:
        about += f" Includes {len(series) - 1} more with the same name."
    return {"title": f"Everyone from {ev.name}", "about": about, "people": found.people()}


def _bridges(net, v, spec: dict) -> dict:
    a, b = spec.get("a") or "", spec.get("b") or ""
    ga, gb = net.every_group.get(a), net.every_group.get(b)
    if not ga or not gb:
        raise PresetError("Pick two groups first")
    if a == b:
        raise PresetError("Pick two different groups")
    found = _Found(net)
    for pid in ga.members.keys() & gb.members.keys():
        found.add(pid, f"{ga.name}: {ga.members[pid].lower()}")
        found.add(pid, f"{gb.name}: {gb.members[pid].lower()}")
    return {"title": f"In both {ga.name} and {gb.name}", "about": "The people who connect the two.", "people": found.people()}


def _followups(net, v, spec: dict) -> dict:
    found = _Found(net)
    for pid, p in net.people.items():
        if net.tiers.get(pid) == "strong":
            continue
        signals = [f"Tagged {t.replace('-', ' ')}" for t in p.tags or [] if t in FOLLOW_TAGS]
        if stage := (p.attributes or {}).get("connection_stage"):
            signals.append(str(stage))
        if not signals:
            continue
        for s in signals:
            found.add(pid, s, 1)
        conn = v.conns.get(pid)
        if conn and conn.meetings:
            found.add(pid, f"Last met {conn.last_met_at.strftime('%-d %b %Y')}" if conn.last_met_at else "You've met", 0)
        else:
            found.add(pid, "No meeting together yet", 2)
        if not (conn and conn.user_set):
            found.add(pid, "You haven't rated them", 1)
    return {"title": "Follow-ups waiting", "about": "Prospects, leads and thank-yous, the ones you haven't met or rated first.",
            "people": found.people(by_tier=-0.5)}


def _rule(net, v, spec: dict) -> dict:
    found = _Found(net)
    ents = v.snap.entities
    tags = set(spec.get("tags") or [])
    for pid, p in net.people.items():
        for t in p.tags or []:
            if t in tags:
                found.add(pid, f"Tagged {t.replace('-', ' ')}", 2)
    for tid in spec.get("topics") or []:
        g = net.every_group.get(f"topic:{tid}")
        for pid, why in (g.members.items() if g else ()):
            found.add(pid, f"{g.name}: {why[0].lower()}{why[1:]}", 2)
    for oid in spec.get("organizations") or []:
        if (org := ents.get(oid)) and org.kind == "organization":
            for pid, tie in _org_ties(v, oid):
                found.add(pid, ORG_TIES[tie][1].format(org=org.name), ORG_TIES[tie][2])
    for eid in spec.get("events") or []:
        for pid, role in net.events.get(eid, {"people": {}})["people"].items():
            found.add(pid, f"{'Took part in' if role == 'took part' else 'Came up in'} {ents[eid].name}", 2 if role == "took part" else 1)
    for word in spec.get("words") or []:
        pattern = re.compile(rf"\b{re.escape(word)}", re.I)
        for pid, p in net.people.items():
            title = (p.attributes or {}).get("title") or ""
            if pattern.search(title):
                found.add(pid, title, 2)
            elif pattern.search(p.summary or ""):
                found.add(pid, f"Their summary mentions “{word}”", 1)
    for pick in spec.get("picks") or []:
        found.add(pick["id"], pick.get("why") or "Picked from their records", 3)
    return {"title": spec.get("name") or "Your list", "about": spec.get("about") or "", "people": found.people()}


RUNNERS = {"at": _at, "intro": _intro, "investors": _investors, "event": _event, "bridges": _bridges,
           "followups": _followups, "rule": _rule}


def _strings(value, limit: int = MAX_LIST, size: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for x in value:
        if isinstance(x, str) and x.strip() and x.strip()[:size] not in out:
            out.append(x.strip()[:size])
    return out[:limit]


def clean(spec: dict) -> dict:
    """The spec with only what each kind takes, trimmed. Raises PresetError for an unknown kind."""
    if not isinstance(spec, dict) or spec.get("kind") not in KINDS:
        raise PresetError("That isn't a preset The Lodge knows")
    kind = spec["kind"]
    keep = {"at": ("group",), "intro": ("target",), "event": ("event",), "bridges": ("a", "b")}.get(kind, ())
    out: dict = {"kind": kind, **{k: str(spec[k]) for k in keep if spec.get(k)}}
    if kind == "rule":
        out["name"] = str(spec.get("name") or "")[:80]
        out["about"] = str(spec.get("about") or "")[:240]
        out["tags"] = normalize_tags(_strings(spec.get("tags")))
        for k in ("topics", "organizations", "events"):
            out[k] = _strings(spec.get(k), size=64)
        out["words"] = [w for w in _strings(spec.get("words"), 8, 40) if len(w) >= 3]
        picks, seen = [], set()
        for p in spec.get("picks") or []:
            if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"] not in seen:
                seen.add(p["id"])
                picks.append({"id": p["id"], "why": str(p.get("why") or "").strip()[:MAX_WHY]})
        out["picks"] = picks[:MAX_PICKS]
    return out


def run(spec: dict) -> dict:
    """Who a preset finds right now: {title, about, spec, people: [{id, name, subtitle, tier, why}]}."""
    spec = clean(spec)
    net = people_net.get()
    result = RUNNERS[spec["kind"]](net, views.get(), spec)
    return {**result, "spec": spec}


def choices() -> dict:
    """What the presets can be about, for the pickers: every group (small ones too) and every meeting or document
    with people on it."""
    net = people_net.get()
    groups = [{"id": g.id, "kind": g.kind, "name": g.name, "size": len(g.members)}
              for g in sorted(net.every_group.values(), key=lambda g: (-len(g.members), g.name.lower()))]
    evs = sorted(net.events.values(), key=lambda x: (iso(x["entity"].occurred_at) or "", x["entity"].name), reverse=True)
    return {"groups": groups,
            "events": [{"id": x["entity"].id, "kind": x["entity"].kind, "name": x["entity"].name,
                        "at": iso(x["entity"].occurred_at), "size": len(x["people"])} for x in evs if x["people"]]}


# ── Saved presets ─────────────────────────────────────────────────────

def _saved(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "about": row["about"], "spec": json.loads(row["spec"]),
            "source": row["source"], "created_at": row["created_at"]}


def saved() -> list[dict]:
    return [_saved(r) for r in db.query("SELECT * FROM crm_presets ORDER BY name COLLATE NOCASE")]


def save(name: str, about: str, spec: dict, source: str = "you") -> dict:
    """Keeps a preset under a name (the same name replaces it)."""
    name = (name or "").strip()[:80]
    if not name:
        raise PresetError("Give it a name")
    spec = run(spec)["spec"]   # checks it runs
    if spec["kind"] == "rule":
        spec["name"], spec["about"] = name, (about or spec.get("about") or "").strip()[:240]
    existing = db.one("SELECT id FROM crm_presets WHERE lower(name) = lower(?)", (name,))
    pid = existing["id"] if existing else db.new_id()
    db.execute("INSERT INTO crm_presets (id, name, about, spec, source, created_at) VALUES (?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(id) DO UPDATE SET name = excluded.name, about = excluded.about, spec = excluded.spec, "
               "source = excluded.source", (pid, name, (about or "").strip()[:240], json.dumps(spec), source, _now()))
    _changed()
    return _saved(db.one("SELECT * FROM crm_presets WHERE id = ?", (pid,)))


def delete(preset_id: str) -> bool:
    gone = bool(db.execute("DELETE FROM crm_presets WHERE id = ?", (preset_id,)))
    if gone:
        _changed()
    return gone


# ── The AI writes presets ─────────────────────────────────────────────

class Pick(BaseModel):
    id: str = Field(description="The person's id, exactly as in the People list")
    why: str = Field(description="One short phrase from their records saying why they belong, e.g. 'Ran cold-chain pilots in Kenya'")


class Idea(BaseModel):
    name: str = Field(description="A short name in sentence case for the list, e.g. 'Cold-chain funders you know'")
    about: str = Field(description="One plain sentence on what the list is for")
    tags: list[str] = Field(description="Tags from the Tags list; anyone with one of them is in")
    topics: list[str] = Field(description="Topic ids from the Topics list; anyone in one of them is in")
    organizations: list[str] = Field(description="Organization ids from the Organizations list; anyone linked to one is in")
    events: list[str] = Field(description="Meeting or document ids from the Meetings list; anyone on one is in")
    words: list[str] = Field(description="A few specific words or short phrases matched in titles and summaries, e.g. 'grant', 'cold chain'. Leave empty unless they are specific")
    picks: list[Pick] = Field(description="People whose records show they fit but whom the rule above would miss, each with a reason")


class Ideas(BaseModel):
    presets: list[Idea]


SYSTEM = (
    "You write saved lists (\"presets\") for the owner of a personal CRM, from the owner's own records below. "
    "A preset has a rule (tags, topics, organizations, events, words) that the app matches against the records, "
    "and picks: people whose records clearly show they fit but whom the rule would miss, each with a short reason "
    "taken from their records. Use only the ids and tags given, exactly as written. Never invent people, ids, tags "
    "or facts, and add nothing from general knowledge. Names are short and in sentence case, and say what the list "
    "is, in plain warm English."
)
BUILT_IN = ("who you know at an organization or in a field, who could introduce you to someone, investors and "
            "advisors, everyone from an event, people in two groups at once, and follow-ups waiting")
BOOK = {"local": 18_000, "cloud": 90_000}   # characters of book given to the model
SUMMARY = {"local": 120, "cloud": 320}


def book(net: people_net.PeopleNet, v: views.Views, local: bool) -> str:
    """The whole book, compactly: the vocabulary a rule can use, then each person with an id."""
    scale = "local" if local else "cloud"
    tags = sorted(((g.name, len(g.members), g.id[4:]) for g in net.every_group.values() if g.kind == "tag"), key=lambda t: -t[1])
    groups = sorted(net.every_group.values(), key=lambda g: (-len(g.members), g.name.lower()))
    evs = sorted(net.events.values(), key=lambda x: iso(x["entity"].occurred_at) or "", reverse=True)
    parts = [
        "Tags (tag: people): " + "; ".join(f"{t}: {n}" for _, n, t in tags),
        "Topics (id: name, people):\n" + "\n".join(f"{g.ref}: {g.name}, {len(g.members)}" for g in groups if g.kind == "topic"),
        "Organizations (id: name, people):\n" + "\n".join(f"{g.ref}: {g.name}, {len(g.members)}" for g in groups if g.kind == "organization"),
        "Meetings and documents (id: name, date, people):\n" + "\n".join(
            f"{x['entity'].id}: {x['entity'].name}, {(iso(x['entity'].occurred_at) or 'undated')[:10]}, {len(x['people'])}"
            for x in evs[:80] if x["people"]),
    ]
    lines = ["People (id | name | how well you know them | role | tags | groups | summary):"]
    room = BOOK[scale] - sum(len(p) for p in parts)
    order = sorted((p for p in net.people if p != net.me),
                   key=lambda p: (-TIER_RANK.get(net.tiers.get(p) or "none", 0), net.people[p].name.lower()))
    for pid in order:
        p = net.people[pid]
        org = v.employer(pid)
        role = " at ".join(x for x in ((p.attributes or {}).get("title"), org.name if org else None) if x)
        groups_of = ", ".join(net.groups[g].name for g in net.member_of.get(pid, [])[:5] if not g.startswith("tag:"))
        summary = " ".join((p.summary or "").split())[:SUMMARY[scale]]
        line = " | ".join((pid, p.name, net.tiers.get(pid) or "none", role, ", ".join(p.tags or []), groups_of, summary))
        if room - len(line) < 0:
            lines.append(f"({len(order) - len(lines) + 1} more people left out for length)")
            break
        room -= len(line) + 1
        lines.append(line)
    return "\n\n".join([*parts, "\n".join(lines)])


def _ask_row(row: dict) -> dict:
    return {"id": row["id"], "request": row["request"], "status": row["status"], "ideas": json.loads(row["ideas"]),
            "error": row["error"], "written_by": row["written_by"], "created_at": row["created_at"]}


def asks() -> list[dict]:
    return [_ask_row(r) for r in db.query("SELECT * FROM crm_preset_asks ORDER BY created_at DESC, id LIMIT ?", (KEEP_ASKS,))]


def ask(request: str) -> dict:
    """Asks the AI for a list ("everyone who could help with cold-chain funding"), or, with no request, for a few
    presets worth having. The AI works in the background; the answer shows up in asks()."""
    request = (request or "").strip()
    if len(request) > MAX_REQUEST:
        raise PresetError(f"Keep it under {MAX_REQUEST} characters")
    prov = profiles.provider()
    if not prov["ready"]:
        raise PresetError(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    aid = db.new_id()
    db.execute("INSERT INTO crm_preset_asks (id, request, status, created_at) VALUES (?, ?, 'queued', ?)", (aid, request, _now()))
    for old in db.query("SELECT id FROM crm_preset_asks ORDER BY created_at DESC, id LIMIT -1 OFFSET ?", (KEEP_ASKS,)):
        dismiss(old["id"], quiet=True)
    jobs.enqueue("crm", "write_presets", aid)
    _changed()
    return _ask_row(db.one("SELECT * FROM crm_preset_asks WHERE id = ?", (aid,)))


def dismiss(ask_id: str, quiet: bool = False) -> None:
    jobs.cancel_for("crm", ask_id)
    db.execute("DELETE FROM crm_preset_asks WHERE id = ?", (ask_id,))
    if not quiet:
        _changed()


def prompt(net: people_net.PeopleNet, v: views.Views, request: str, local: bool) -> str:
    head = f"{profiles._about_me(v)} Today is {datetime.now(UTC).strftime('%d %B %Y')}.\n\nThe owner's records:\n\n{book(net, v, local)}\n\n"
    if request:
        return head + (
            f"The owner asks for: “{request}”\n\nWrite one preset that answers it (two only if the request clearly asks "
            "for two different lists). Use the rule for whatever tags, topics, organizations or meetings capture it. "
            "Use words only for specific terms likely to appear in titles or summaries. Add picks for people the rule "
            "would miss whose records clearly fit. If nothing in the records fits, return no presets.")
    return head + (
        "Suggest 4 to 6 presets the owner would find useful, built from what is actually in these records: focused "
        "questions such as who could help with something the owner is working on, people in one field, or people to "
        f"get back in touch with for a reason. The app already has these, so don't repeat them: {BUILT_IN}. Each "
        "preset should find at least 3 people.")


def write(job: jobs.Job) -> None:
    """Writes the presets for one ask, keeping only the ones that find somebody."""
    row = db.one("SELECT * FROM crm_preset_asks WHERE id = ?", (job.target,))
    if not row or row["status"] == "done":
        return

    def fail(text: str) -> None:
        db.execute("UPDATE crm_preset_asks SET status = 'error', error = ? WHERE id = ?", (text, row["id"]))
        _changed()

    prov = profiles.provider()
    if not prov["ready"]:
        return fail(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    net, v = people_net.get(), views.get()
    job.stage("Writing the list" if row["request"] else "Looking for lists worth having")
    try:
        answer, pid = roles.structured("profiles", prompt(net, v, row["request"], prov["local"]), SYSTEM, Ideas)
    except ai.AIError as e:
        return fail(str(e))
    ideas = []
    for idea in answer.presets[:8]:  # type: ignore[attr-defined]
        spec = clean({"kind": "rule", **idea.model_dump()})
        ents = v.snap.entities
        spec["topics"] = [t for t in spec["topics"] if t in ents and ents[t].kind == "topic"]
        spec["organizations"] = [o for o in spec["organizations"] if o in ents and ents[o].kind == "organization"]
        spec["events"] = [e for e in spec["events"] if e in ents and ents[e].kind in EVENT_KINDS]
        spec["picks"] = [p for p in spec["picks"] if p["id"] in net.people and p["id"] != net.me]
        result = run(spec)
        if not spec["name"] or not result["people"]:
            continue
        ideas.append({"name": spec["name"], "about": spec["about"], "spec": result["spec"], "count": len(result["people"]),
                      "sample": [p["name"] for p in result["people"][:4]]})
    db.execute("UPDATE crm_preset_asks SET status = 'done', ideas = ?, error = NULL, written_by = ?, answered_at = ? WHERE id = ?",
               (json.dumps(ideas), profiles._written_by(pid), _now(), row["id"]))
    _changed()
