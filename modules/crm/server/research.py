"""Research flags: people with nothing on file about them, and the brief to take to a deep-research tool.

A person is flagged when there is no summary and no long-form research on them. "Long-form" is a note over
FLAG_NOTE_CHARS (a pasted report, the text of a profile document), or a document filed as being about them.
The app never runs the research itself and never looks anyone up: it says who needs it, writes the brief you
paste into the tool you use, and takes the report back through the inbox like any other profile.

What you did about a flag lives on the person, in attributes.research:
    {"status": "snoozed", "until": "<iso>"}   hidden until then
    {"status": "dismissed"}                    not worth researching
    {"status": "done", "at": "<iso>"}          a profile was applied to them (even a short one)
"""
import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from core.server import db

from . import store, views
from .connections import sort_key
from .model import Entity, iso, parse_dt

FLAG_NOTE_CHARS = 1500
SNOOZE_DAYS = 30
MEETINGS_IN_BRIEF = 6

# needed: flagged. name_needed: no surname yet, so a search would find the wrong person.
NEEDED, SNOOZED, DISMISSED, NAME_NEEDED = "needed", "snoozed", "dismissed", "name_needed"
HAS_CONTEXT = "has_context"

_cache: dict = {}


class ResearchError(ValueError):
    pass


def _long_note_owners() -> set[str]:
    rows = db.query("SELECT DISTINCT entity_id FROM crm_notes WHERE length(body) >= ?", (FLAG_NOTE_CHARS,))
    return {r["entity_id"] for r in rows}


def _documented(v: views.Views) -> set[str]:
    """People a document is filed about."""
    ents = v.snap.entities
    return {e.source_id for e in v.snap.edges
            if e.kind == "about" and ents[e.source_id].kind == "person" and ents[e.target_id].kind == "document"}


def _state(p: Entity, long_notes: set[str], documented: set[str], now: datetime) -> str:
    research = (p.attributes or {}).get("research") or {}
    status = research.get("status")
    if (p.summary or "").strip() or p.id in long_notes or p.id in documented or status == "done":
        return HAS_CONTEXT
    if status == "dismissed":
        return DISMISSED
    if status == "snoozed" and (until := parse_dt(research.get("until"))) and until > now:
        return SNOOZED
    if len(p.name.split()) < 2:
        return NAME_NEEDED
    return NEEDED


def states(v: views.Views | None = None) -> dict[str, str]:
    """person id -> state, for everyone but you. Cached until something is written."""
    version = store.version()
    if _cache.get("v") != version or _cache.get("day") != datetime.now(UTC).date():
        v = v or views.get()
        long_notes, documented, now = _long_note_owners(), _documented(v), datetime.now(UTC)
        _cache.update(v=version, day=now.date(), states={
            p.id: _state(p, long_notes, documented, now)
            for p in v.snap.of_kind("person") if not p.is_self})
    return _cache["states"]


def listing(state: str = NEEDED, limit: int = 100, offset: int = 0) -> dict:
    """People in a state, the ones who matter most to you first."""
    v = views.get()
    st = states(v)
    ids = [pid for pid, s in st.items() if s == state and pid in v.conns]
    ids.sort(key=lambda pid: sort_key(v.conns[pid], v.snap.entities[pid].name))
    counts = {k: sum(1 for s in st.values() if s == k) for k in (NEEDED, SNOOZED, DISMISSED, NAME_NEEDED)}
    close = sum(1 for pid in ids if v.conns[pid].tier in ("strong", "working")) if state == NEEDED else 0
    items = [v.person_row(pid) for pid in ids[offset: offset + limit]]
    for row in items:
        row.needs_research = state == NEEDED
    return {"total": len(ids), "close": close, "counts": counts, "items": items}


def state_of(person_id: str) -> dict:
    v = views.get()
    p = v.snap.entities.get(person_id)
    if p is None or p.kind != "person" or p.is_self:
        raise ResearchError("Research flags are for people other than you")
    research = (p.attributes or {}).get("research") or {}
    return {"state": states(v).get(person_id, HAS_CONTEXT), "until": research.get("until"), "at": research.get("at")}


# ── What you do about a flag ──────────────────────────────────────────

def set_status(person_id: str, action: str, days: int = SNOOZE_DAYS) -> dict:
    p = store.get_entity(person_id)
    if p is None or p.kind != "person" or p.is_self:
        raise ResearchError("Research flags are for people other than you")
    attrs = dict(p.attributes or {})
    now = datetime.now(UTC)
    if action == "snooze":
        attrs["research"] = {"status": "snoozed", "until": iso(now + timedelta(days=days)), "at": iso(now)}
    elif action == "dismiss":
        attrs["research"] = {"status": "dismissed", "at": iso(now)}
    elif action == "restore":
        attrs.pop("research", None)
    else:
        raise ResearchError("Unknown action")
    store.update_entity(person_id, attributes=attrs)
    return state_of(person_id)


def mark_done(person_id: str, conn: sqlite3.Connection) -> None:
    """A profile was applied to them: that is the research, however short."""
    p = store.get_entity(person_id, conn)
    if p is None or p.kind != "person" or p.is_self:
        return
    attrs = {**(p.attributes or {}), "research": {"status": "done", "at": iso(datetime.now(UTC))}}
    store.update_entity(person_id, attributes=attrs, conn=conn)


# ── The brief ─────────────────────────────────────────────────────────

def _domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


def _linkedin(url: str | None) -> str | None:
    if not url:
        return None
    return url if urlparse(url).scheme else f"https://{url}"


def _when(when: datetime | None) -> str:
    return when.strftime("%b %Y") if when else "undated"


def brief(person_id: str) -> str:
    """A prompt for any deep-research tool: who this is as far as you know, why you care, and the shape of answer
    the importer reads best. It holds no email address, only the domain, and nothing is sent anywhere."""
    v = views.get()
    p = v.snap.entities.get(person_id)
    if p is None or p.kind != "person" or p.is_self:
        raise ResearchError("A research brief is for people other than you")
    if len(p.name.split()) < 2:
        raise ResearchError("Add a surname first: a first name alone would find the wrong person")

    a = p.attributes or {}
    org = v.employer(person_id)
    ctx = v.context(person_id)
    conn = v.conns.get(person_id)
    me = v.me
    my_org = v.employer(me.id) if me else None

    known = [f"- Name: {p.name}"]
    if a.get("aliases"):
        known.append(f"- Also written as: {', '.join(a['aliases'])}")
    if a.get("title") or org:
        known.append("- Role: " + " at ".join(x for x in (a.get("title"), org.name if org else None) if x))
    if a.get("location"):
        known.append(f"- Location: {a['location']}")
    if domain := _domain(a.get("email")):
        known.append(f"- Email domain: {domain}")
    if link := _linkedin(a.get("linkedin_url")):
        known.append(f"- LinkedIn: {link}")
    past = [x.org.name for x in ctx.affiliations if not x.current]
    if past:
        known.append(f"- Earlier organizations: {', '.join(past[:6])}")
    if p.tags:
        known.append(f"- Tags I use for them: {', '.join(p.tags[:8])}")

    mine = []
    if conn and conn.meetings:
        mine.append(f"I've met them {conn.meetings} time{'s' if conn.meetings != 1 else ''}"
                    + (f", most recently {_when(conn.last_met_at)}" if conn.last_met_at else "") + ".")
    for m in ctx.meetings[:MEETINGS_IN_BRIEF]:
        mine.append(f"- {_when(m.event.occurred_at)}: {m.event.name}" + (f" ({m.snippet})" if m.snippet else ""))
    if ctx.documents:
        mine.append("Documents that mention them: " + "; ".join(d.event.name for d in ctx.documents[:5]) + ".")
    if conn and conn.mutual:
        mine.append("People we both know: " + ", ".join(m.name for m in conn.mutual[:6]) + ".")
    if conn and conn.context:
        mine.append(f"How we're connected: {conn.context}")

    about_me = ""
    if me:
        about_me = f"I'm {me.name}" + (f", {(me.attributes or {}).get('title')}" if (me.attributes or {}).get("title") else "")
        about_me += f" at {my_org.name}." if my_org else "."

    lines = [
        f"Deep research request: {p.name}",
        "",
        f"Please research this person and write a report I can file in my personal CRM. {about_me}".strip(),
        "",
        "What I already know about them:",
        *known,
        "",
        *(["How I know them:", *mine, ""] if mine else []),
        "Use the details above to make sure you have the right person. If more than one person fits the name, "
        "say how you told them apart, and if you can't be sure, say so rather than guessing.",
        "",
        "What I want to learn:",
        "1. Who they are: current role and organization, and how they got there.",
        "2. Background: education, earlier roles, and what they are known for.",
        "3. Organizations they are tied to: employers, boards, advisory roles, investments, with dates where known.",
        "4. Expertise and interests, and anything they've published, said or built in public.",
        "5. Who they are connected to that I may know or want to meet.",
        "6. Why they could matter to me, and a good reason to get back in touch.",
        "",
        "Rules: use public, verifiable sources only. Don't make up details. Put a link beside every claim that "
        "matters, and mark anything uncertain as uncertain.",
        "",
        f"Format: Markdown. Begin with a 2-3 sentence summary that starts with \"{p.name}\". Then these headings: "
        "Background, Current role, Organizations and affiliations, Expertise and interests, Notable work and "
        "mentions, People they're connected to, Why they could matter, Sources.",
    ]
    return "\n".join(lines)
