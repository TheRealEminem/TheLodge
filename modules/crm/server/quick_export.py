"""Quick export: what's on file about one person or organization, as Markdown to copy (say, into an AI chat) or to
save as a Markdown or PDF file.

It's the record as it stands, not a packet: who they are, how you know them, the overview, organizations, recent
meetings, notes (each cut to a length), research reports and the people around them. Email addresses and phone numbers
are left out, the same rule the app keeps for anything it sends to an AI. Nothing is sent anywhere from here; saved
files go in the data folder's crm/exports/. Roundups (roundups.py) is the larger cousin: a packet about a set of people.
"""
from datetime import date, datetime

from core.server import config, db

from . import profiles, research, roundup_files, store, views
from .model import Entity
from .roundups import _safe

FORMATS = {"md": "Markdown", "pdf": "PDF"}
MEETINGS, NOTES, PEOPLE, DOCUMENTS = 10, 12, 25, 12
NOTE_CHARS = 1_500          # the most of any one note; a long report says where the rest is
TOTAL_CHARS = 60_000        # the whole export stays a size an AI chat takes in one paste


class ExportError(ValueError):
    pass


def folder():
    return config.DATA_DIR / "crm" / "exports"


def _day(d: date | datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "undated"


def _url(u: str) -> str:
    return u if u.startswith(("http://", "https://")) else f"https://{u}"


def _entity(entity_id: str) -> tuple[views.Views, Entity]:
    v = views.get()
    e = v.snap.entities.get(entity_id)
    if e is None and (now := store.merged_into(entity_id)):
        e = v.snap.entities.get(now)
    if e is None:
        raise LookupError("That isn't in your book any more")
    if e.kind not in ("person", "organization"):
        raise ExportError("Quick export is for people and organizations")
    return v, e


def _head(e: Entity, sub: str) -> list[str]:
    a = e.attributes or {}
    out = [f"# {e.name}"]
    if sub:
        out.append(sub)
    links = [f"[{label}]({_url(a[key])})" for key, label in (("linkedin_url", "LinkedIn"), ("website", "Website")) if a.get(key)]
    if links:
        out.append(" · ".join(links))
    out.append(f"_From The Lodge, {date.today().isoformat()}. Email addresses and phone numbers are left out._")
    return out


def _section(title: str, lines: list[str]) -> str:
    return f"## {title}\n" + "\n".join(lines) if lines else ""


def _notes(entity_id: str) -> list[str]:
    out = []
    for n in store.notes_of(entity_id)[:NOTES]:
        body = n.body.strip()
        if len(body) > NOTE_CHARS:
            body = body[:NOTE_CHARS].rsplit(" ", 1)[0] + " … (cut for length; the whole note is in The Lodge)"
        out.append(f"- {_day(n.occurred_at)} ({n.source}): " + " ".join(body.split()))
    return out


def _meetings(v: views.Views, ctx) -> list[str]:
    out = []
    for m in ctx.meetings[:MEETINGS]:
        ev = v.snap.entities.get(m.event.id)
        line = f"- {_day(m.event.occurred_at)} · {m.event.name}" + (" (you were there)" if m.with_me else "")
        if ev and (ev.summary or "").strip():
            line += f": {' '.join(ev.summary.split())[:600]}"
        out.append(line)
    return out


def _person(v: views.Views, p: Entity) -> list[str]:
    a = p.attributes or {}
    ctx = v.context(p.id)
    org = v.employer(p.id)
    role = " at ".join(x for x in (a.get("title"), org.name if org else None) if x)
    parts = ["\n\n".join(_head(p, " · ".join(x for x in (role, a.get("location")) if x)))]

    conn = v.conns.get(p.id)
    you = []
    if conn and not p.is_self:
        you.append(f"- {profiles.TIER_WORDS.get(conn.tier, conn.tier).capitalize()}")
        if conn.strength:
            you.append(f"- Your rating: {conn.strength} of 5")
        if conn.context:
            you.append(f"- How you know them: {conn.context}")
        if conn.roles:
            you.append(f"- To you they are: {'; '.join(conn.roles)}")
        if conn.meetings:
            you.append(f"- Meetings together: {conn.meetings}, first {_day(conn.first_met_at)}, latest {_day(conn.last_met_at)}")
        if conn.mutual:
            you.append("- People you both know: " + ", ".join(v.snap.entities[m].name for m in conn.mutual[:12] if m in v.snap.entities))
    parts.append(_section("How you know them", you))

    if not p.is_self and (row := profiles._overview_row(p.id)):
        parts.append(_section("Overview", [row["body"].strip(), f"_Written by {row['written_by']}._"]))
    if (p.summary or "").strip():
        parts.append(_section("About", [p.summary.strip()]))
    if p.tags:
        parts.append(_section("Tags", [", ".join(p.tags)]))
    orgs = []
    for af in ctx.affiliations:
        for r in af.roles:
            span = f", {_day(r.started_at) if r.started_at else '?'} to {_day(r.ended_at) if r.ended_at else 'now'}" if r.started_at or r.ended_at else ""
            orgs.append(f"- {af.org.name}: {r.title or r.label}{span}" + ("" if af.current else " (earlier)"))
    parts.append(_section("Organizations", orgs))
    parts.append(_section("Meetings, newest first", _meetings(v, ctx)))
    parts.append(_section("Notes, newest first", _notes(p.id)))
    if not p.is_self:
        reps = research.reports(p.id, v)
        parts.append(_section("Research reports", [
            f"- {(r['date'] or '')[:10] or 'undated'} · {r['title']}"
            + ("" if r["about_them"] else f" (about {r['about']}, and names them)" if r["about"] else "") for r in reps]))
    parts.append(_section("Documents", [f"- {_day(d.event.occurred_at)} · {d.event.name} ({d.role})" for d in ctx.documents[:DOCUMENTS]]))
    parts.append(_section("People they're connected to", [
        f"- {l.person.name}: {l.relation}" + (f" ({l.detail})" if l.detail else "") for l in ctx.people[:PEOPLE]]))
    return parts


def _organization(v: views.Views, o: Entity) -> list[str]:
    a = o.attributes or {}
    ctx = v.context(o.id)
    parts = ["\n\n".join(_head(o, " · ".join(x for x in (a.get("industry"), a.get("location")) if x)))]
    if (o.summary or "").strip():
        parts.append(_section("About", [o.summary.strip()]))
    if o.tags:
        parts.append(_section("Tags", [", ".join(o.tags)]))
    parts.append(_section("People there", [
        f"- {l.person.name}: {l.relation}" + (f" ({l.detail})" if l.detail else "") + ("" if l.current else ", earlier")
        for l in ctx.people[:40]]))
    parts.append(_section("Meetings, newest first", _meetings(v, ctx)))
    parts.append(_section("Notes, newest first", _notes(o.id)))
    parts.append(_section("Documents", [f"- {_day(d.event.occurred_at)} · {d.event.name} ({d.role})" for d in ctx.documents[:DOCUMENTS]]))
    return parts


def build(entity_id: str) -> dict:
    """{title, markdown, characters} for a person or organization."""
    v, e = _entity(entity_id)
    parts = [x for x in (_person(v, e) if e.kind == "person" else _organization(v, e)) if x.strip()]
    md, used = [], 0
    for part in parts:
        if used + len(part) > TOTAL_CHARS:
            md.append("_(More is on file in The Lodge; this export stops here for length.)_")
            break
        md.append(part)
        used += len(part) + 2
    text = "\n\n".join(md) + "\n"
    return {"id": e.id, "title": e.name, "markdown": text, "characters": len(text)}


def save(entity_id: str, fmt: str) -> dict:
    """Writes the export as a file in crm/exports/, replacing an earlier one from the same day."""
    if fmt not in FORMATS:
        raise ExportError("Choose Markdown or PDF")
    out = build(entity_id)
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_safe(out['title'])} {date.today().isoformat()}.{fmt}"
    owner = (db.one("SELECT name FROM crm_entities WHERE is_self = 1") or {}).get("name") or ""
    data = out["markdown"].encode() if fmt == "md" else roundup_files.markdown_pdf(out["title"], out["markdown"], owner)
    path.write_bytes(data)
    return {"name": path.name, "path": str(path), "folder": str(d), "format": fmt, "bytes": len(data)}


def file_path(name: str):
    path = folder() / name
    if path.parent != folder() or not path.is_file() or path.suffix.lstrip(".") not in FORMATS:
        raise LookupError("That file is gone")
    return path
