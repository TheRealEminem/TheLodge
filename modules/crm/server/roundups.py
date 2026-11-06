"""Roundups: a packet about a set of people, for someone else to take to an event.

You pick the people, from a group (an organization, a topic or a tag) or one by one, say what the event is
and who the packet is for, and The Lodge prepares it: a few paragraphs at the top about the event and the people in it,
then, for each person, their picture and LinkedIn, a couple of sentences on what matters about them for this event, the
overview already written about them, their organizations, and the people they're closest to.

It is a summary, on purpose. It draws on the overviews and what's on each record, never on meeting notes, transcripts
or a research report in full, and the AI is told to add nothing that isn't there.

A prepared packet is kept as it was handed over (crm_roundups.packet), so a later export says the same thing. Exports
are Word, PDF or Markdown files in the data folder's crm/roundups/<roundup id>/, which is where to find them again.

    crm_roundups   title, the event, who it's for, the people in order, the packet once prepared
(the table is created in store.py, with the module's other tables)
"""
import base64
import hashlib
import json
import re
from datetime import UTC, datetime

from core.server import ai, config, db, events, jobs

from . import people_net, pictures, profiles, store, views
from .connections import TIER_RANK
from .model import Entity, iso

MAX_PEOPLE = 200
MAX_TEXT = 4_000
CONNECTIONS = 8          # the people closest to each person, in their section
EARLIER_ORGS = 3         # past organizations shown after the current ones
SUMMARY_CAP = 1_200      # characters of a profile summary used when there's no overview
FORMATS = {"docx": "Word", "pdf": "PDF", "md": "Markdown"}
KIND = "roundup"

SYSTEM = (
    "You write briefing packets about people for a colleague of the owner of a personal CRM, who is about to meet "
    "them at an event. Use only the records given. Never invent or guess, and add nothing from general knowledge, even "
    "about well-known people or organizations. Write plain, direct English. If the records say little, say so briefly."
)

WITH_OWNER = {
    "strong": "knows them well",
    "working": "works with them",
    "light": "has met them",
    "indirect": "knows of them through others",
}


class RoundupError(ValueError):
    """The message is shown to the person."""


def _now() -> str:
    return iso(datetime.now(UTC))  # type: ignore[return-value]


def _changed(rid: str) -> None:
    events.publish("crm.roundup.changed", {"id": rid})


def folder(rid: str):
    return config.DATA_DIR / "crm" / "roundups" / rid


def lane(target: str) -> str:
    return "default" if profiles.provider()["local"] else "interactive"


# ── Rows ──────────────────────────────────────────────────────────────

def _row(rid: str) -> dict:
    row = db.one("SELECT * FROM crm_roundups WHERE id = ?", (rid,))
    if not row:
        raise LookupError("That roundup is gone")
    return row


def _ids(row: dict, v: views.Views) -> list[str]:
    """The people on it as they stand now: merges followed, deleted records and you left out, no one twice."""
    out: list[str] = []
    for pid in json.loads(row["people"]):
        if pid not in v.snap.entities:
            pid = store.merged_into(pid) or pid
        p = v.snap.entities.get(pid)
        if p is not None and p.kind == "person" and not p.is_self and pid not in out:
            out.append(pid)
    return out


def _fingerprint(row: dict, ids: list[str]) -> str:
    seed = json.dumps([row["title"], row["event"], row["audience"], ids])
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _job(rid: str) -> dict | None:
    return db.one("SELECT id, kind, status, stage, wait_reason, error, updated_at FROM core_jobs "
                  "WHERE module = 'crm' AND kind = ? AND target = ? ORDER BY created_at DESC LIMIT 1", (KIND, rid))


def _origin_name(origin: str) -> str | None:
    g = people_net.get().every_group.get(origin) if origin else None
    return g.name if g else None


def _clean(text: str | None, limit: int = MAX_TEXT) -> str:
    return (text or "").strip()[:limit]


def _files(rid: str) -> list[dict]:
    d = folder(rid)
    if not d.is_dir():
        return []
    found = [f for f in d.iterdir() if f.is_file() and f.suffix.lstrip(".") in FORMATS]
    found.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "format": f.suffix.lstrip("."), "bytes": f.stat().st_size,
             "saved_at": iso(datetime.fromtimestamp(f.stat().st_mtime, UTC))} for f in found]


def listing() -> list[dict]:
    v = views.get()
    out = []
    for row in db.query("SELECT * FROM crm_roundups ORDER BY updated_at DESC, id"):
        packet = json.loads(row["packet"]) if row["packet"] else None
        out.append({"id": row["id"], "title": row["title"], "audience": row["audience"], "event": row["event"],
                    "people": len(_ids(row, v)), "origin": _origin_name(row["origin"]),
                    "prepared_at": packet["prepared_at"] if packet else None, "job": _job(row["id"]),
                    "files": len(_files(row["id"])), "updated_at": row["updated_at"]})
    return out


def detail(rid: str) -> dict:
    row = _row(rid)
    v = views.get()
    ids = _ids(row, v)
    packet = json.loads(row["packet"]) if row["packet"] else None
    if packet:
        for person in packet["people"]:
            person.pop("picture", None)     # the page shows the live picture; the packet's copy is for the files
    prov = profiles.provider()
    overviews = {r["entity_id"] for r in db.query("SELECT entity_id FROM crm_overviews")}
    return {
        "id": row["id"], "title": row["title"], "event": row["event"], "audience": row["audience"],
        "origin": row["origin"] or None, "origin_name": _origin_name(row["origin"]),
        "people": [{**v.summary(pid).model_dump(mode="json"), "overview": pid in overviews} for pid in ids],
        "packet": packet,
        "stale": bool(packet and packet["fingerprint"] != _fingerprint(row, ids)),
        "job": _job(rid), "files": _files(rid), "folder": str(folder(rid)),
        "ready": prov["ready"], "reason": prov["reason"], "provider": prov["label"], "local": prov["local"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _members(group_id: str) -> list[str]:
    net = people_net.get()
    g = net.every_group.get(group_id)
    if g is None:
        raise LookupError("That group is gone")
    ranked = sorted(g.members, key=lambda pid: (-TIER_RANK.get(net.tiers.get(pid) or "none", 0), net.people[pid].name.lower()))
    return [pid for pid in ranked if pid != net.me]


def groups() -> list[dict]:
    """Every group a roundup can start from: organizations first, then topics, then tags, biggest first."""
    order = {"organization": 0, "topic": 1, "tag": 2}
    net = people_net.get()
    rows = [{"id": g.id, "kind": g.kind, "name": g.name, "size": len([p for p in g.members if p != net.me])}
            for g in net.every_group.values()]
    return sorted((r for r in rows if r["size"]), key=lambda r: (order.get(r["kind"], 3), -r["size"], r["name"].lower()))


def _add(current: list[str], new: list[str]) -> list[str]:
    out = list(current)
    for pid in new:
        if pid not in out:
            out.append(pid)
    if len(out) > MAX_PEOPLE:
        raise RoundupError(f"A roundup holds up to {MAX_PEOPLE} people")
    return out


def _check_people(ids: list[str]) -> list[str]:
    v = views.get()
    for pid in ids:
        p = v.snap.entities.get(pid)
        if p is None or p.kind != "person":
            raise LookupError("One of those people isn't in your book")
        if p.is_self:
            raise RoundupError("A roundup is about other people, so you can't be on it")
    return ids


def create(title: str | None, event: str | None, audience: str | None, group: str | None, people: list[str] | None) -> dict:
    ids = _add([], _members(group) if group else [])
    ids = _add(ids, _check_people(people or []))
    title = _clean(title, 200) or (f"{_origin_name(group)} roundup" if group else "Roundup")
    rid, now = db.new_id(), _now()
    db.execute("INSERT INTO crm_roundups (id, title, event, audience, origin, people, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (rid, title, _clean(event), _clean(audience, 200), group or "", json.dumps(ids), now, now))
    _changed(rid)
    return detail(rid)


def update(rid: str, fields: dict) -> dict:
    row = _row(rid)
    changes: dict = {}
    if "title" in fields:
        if not (title := _clean(fields["title"], 200)):
            raise RoundupError("Give the roundup a title")
        changes["title"] = title
    for key, limit in (("event", MAX_TEXT), ("audience", 200)):
        if key in fields:
            changes[key] = _clean(fields[key], limit)
    if "people" in fields:
        ids = _check_people([str(p) for p in fields["people"] or []])
        changes["people"] = json.dumps(_add([], ids))
    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)
        db.execute(f"UPDATE crm_roundups SET {sets}, updated_at = ? WHERE id = ?", (*changes.values(), _now(), row["id"]))
        _changed(rid)
    return detail(rid)


def add_people(rid: str, group: str | None, people: list[str] | None) -> dict:
    row = _row(rid)
    ids = _add(_ids(row, views.get()), _members(group) if group else [])
    ids = _add(ids, _check_people(people or []))
    db.execute("UPDATE crm_roundups SET people = ?, updated_at = ? WHERE id = ?", (json.dumps(ids), _now(), rid))
    _changed(rid)
    return detail(rid)


def delete(rid: str) -> None:
    _row(rid)
    jobs.cancel_for("crm", rid)
    db.execute("DELETE FROM crm_roundups WHERE id = ?", (rid,))
    _changed(rid)


def prepare(rid: str) -> dict:
    row = _row(rid)
    if not _ids(row, views.get()):
        raise RoundupError("Add some people first")
    prov = profiles.provider()
    if not prov["ready"]:
        raise RoundupError(prov["reason"] or "No AI is set up for this yet (Settings → AI)")
    jobs.enqueue("crm", KIND, rid)
    _changed(rid)
    return detail(rid)


# ── The packet ────────────────────────────────────────────────────────

def _first(name: str) -> str:
    return name.split()[0] if name.split() else name


def _overview(pid: str) -> str | None:
    row = db.one("SELECT body FROM crm_overviews WHERE entity_id = ?", (pid,))
    return row["body"].strip() if row and row["body"].strip() else None


def _short(text: str, cap: int) -> str:
    """Up to `cap` characters, cut at the end of a paragraph or a sentence."""
    text = text.strip()
    if len(text) <= cap:
        return text
    cut = text[:cap]
    for mark in ("\n\n", ". ", "\n"):
        if (at := cut.rfind(mark)) > cap // 2:
            return cut[:at + 1].strip()
    return cut.rsplit(" ", 1)[0] + "…"


def _picture(pid: str) -> dict | None:
    got = pictures.get(pid)
    return {"mime": got[1], "data": base64.b64encode(got[0]).decode()} if got else None


def _section(v: views.Views, p: Entity, in_packet: set[str], owner: str) -> dict:
    """Everything about one person that goes in the packet, but the AI's lines."""
    a = p.attributes or {}
    ctx = v.context(p.id)
    org = v.employer(p.id)
    title = a.get("title")

    orgs, earlier = [], []
    for af in ctx.affiliations:
        role = next((r.title or r.label for r in af.roles), None)
        (orgs if af.current else earlier).append({"name": af.org.name, "role": role, "current": af.current})
    orgs += earlier[:EARLIER_ORGS]

    def weight(link) -> tuple:
        close = any(w in link.relation for w in ("colleague", "reports to", "manages", "knows", "introduced", "related"))
        return (link.person.id not in in_packet, not close, -TIER_RANK[link.tier], link.person.name.lower())

    connections = [{"name": link.person.name, "headline": link.person.subtitle, "relation": link.relation,
                    "in_packet": link.person.id in in_packet}
                   for link in sorted((link for link in ctx.people if link.current), key=weight)[:CONNECTIONS]]

    with_owner = None
    if ctx.connection and ctx.connection.tier in WITH_OWNER:
        c = ctx.connection
        with_owner = f"{_first(owner)} {WITH_OWNER[c.tier]}"
        if c.meetings:
            with_owner += f": {c.meetings} meeting{'s' if c.meetings != 1 else ''}"
            if c.last_met_at:
                with_owner += f", the latest on {c.last_met_at.day} {c.last_met_at:%B %Y}"
        if c.context:
            with_owner += f". {c.context.strip().rstrip('.')}"
        with_owner += "."

    overview = _overview(p.id)
    summary = overview or (_short(p.summary, SUMMARY_CAP) if (p.summary or "").strip() else None)
    return {
        "id": p.id, "name": p.name, "title": title, "org": org.name if org else None,
        "headline": " at ".join(x for x in (title, org.name if org else None) if x) or None,
        "location": a.get("location"), "email": a.get("email"), "linkedin": a.get("linkedin_url"),
        "website": a.get("website"), "picture": _picture(p.id),
        "summary": summary, "summary_from": "overview" if overview else ("profile" if summary else None),
        "organizations": orgs, "connections": connections, "with_owner": with_owner, "blurb": None,
    }


def _facts(s: dict) -> str:
    """One person's section as text for the model. No addresses: they stay out of what the model sees."""
    lines = [f"Name: {s['name']}"]
    if s["headline"]:
        lines.append(f"Role: {s['headline']}")
    if s["location"]:
        lines.append(f"Location: {s['location']}")
    if s["organizations"]:
        lines.append("Organizations: " + "; ".join(
            f"{o['name']}" + (f" ({o['role']})" if o["role"] else "") + ("" if o["current"] else ", earlier") for o in s["organizations"]))
    if s["with_owner"]:
        lines.append(f"Connection to the owner: {s['with_owner']}")
    if s["connections"]:
        lines.append("Closest connections: " + "; ".join(
            f"{c['name']} ({c['relation']}{', also in this packet' if c['in_packet'] else ''})" for c in s["connections"]))
    if s["summary"]:
        lines.append(("The overview on file" if s["summary_from"] == "overview" else "The profile summary on file")
                     + f":\n{s['summary']}")
    else:
        lines.append("Nothing else is on file about them.")
    return "\n".join(lines)


def _setting(row: dict, owner: str) -> str:
    reader = row["audience"] or "a colleague of the owner"
    event = row["event"] or "(no event described: write for meeting them in general)"
    return (f"The owner is {owner}. In what you write, call the owner {_first(owner)}, never \"you\".\n"
            f"The packet is for {reader}.\nThe event, and what to look out for there: {event}")


def _blurb_prompt(row: dict, owner: str, s: dict) -> str:
    reader = row["audience"] or "the reader"
    return (f"{_setting(row, owner)}\n\nRecords about {s['name']}:\n{_facts(s)}\n\n"
            f"Write two sentences, 60 words at most, for {reader}: who {s['name']} is, and what is most useful to know "
            "about them or to bring up with them at this event. Plain text: no heading, no list, no preamble.")


def _intro_prompt(row: dict, owner: str, people: list[dict]) -> str:
    lines = []
    for s in people:
        line = f"- {s['name']}" + (f", {s['headline']}" if s["headline"] else "")
        if s["blurb"]:
            line += f": {s['blurb']}"
        others = [c["name"] for c in s["connections"] if c["in_packet"]]
        if others:
            line += f" (connected to {', '.join(others)})"
        lines.append(line)
    orgs: dict[str, int] = {}
    for s in people:
        for o in {o["name"] for o in s["organizations"] if o["current"]}:
            orgs[o] = orgs.get(o, 0) + 1
    shared = ", ".join(f"{name} ({n})" for name, n in sorted(orgs.items(), key=lambda kv: -kv[1]) if n > 1)
    return (f"{_setting(row, owner)}\nThe packet's title: {row['title']}\n\n"
            f"The people in it ({len(people)}):\n" + "\n".join(lines)
            + (f"\n\nOrganizations more than one of them is at now: {shared}" if shared else "")
            + "\n\nWrite the opening of the packet in Markdown, 120 to 250 words: what the packet is for, the people at a "
              "glance (who they are as a group, who matters most for this event and why), and connections among them "
              "worth knowing. Short paragraphs, or a short list where it helps. Use only what's above. No title or "
              "heading at the top, no preamble, no sign-off.")


def _write(prompt: str) -> tuple[str, str]:
    try:
        text, pid = ai.complete(prompt, SYSTEM, profiles.choice(), purpose="Roundups", models=profiles.models())
    except ai.AIError as e:
        if e.provider_down:
            raise jobs.Wait(str(e)) from e
        raise
    return text.strip(), pid


def handle(job: jobs.Job) -> None:
    """Prepares a roundup's packet. Lines already written for the same person, event and records are kept in
    `progress`, so a job that restarts carries on rather than starting over."""
    row = db.one("SELECT * FROM crm_roundups WHERE id = ?", (job.target,))
    if not row:
        return
    v = views.get()
    ids = _ids(row, v)
    if not ids:
        return
    owner = v.me.name if v.me else "the owner"
    in_packet = set(ids)
    people = [_section(v, v.snap.entities[pid], in_packet, owner) for pid in ids]
    progress = json.loads(row["progress"] or "{}")
    done: dict = progress.get("blurbs", {})
    for n, s in enumerate(people, 1):
        prompt = _blurb_prompt(row, owner, s)
        key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        if done.get(s["id"], {}).get("key") == key:
            s["blurb"] = done[s["id"]]["text"]
            continue
        job.stage(f"Writing about {s['name']} ({n} of {len(people)})")
        s["blurb"], _ = _write(prompt)
        done[s["id"]] = {"key": key, "text": s["blurb"]}
        db.execute("UPDATE crm_roundups SET progress = ? WHERE id = ?", (json.dumps({"blurbs": done}), row["id"]))
    job.stage("Writing the opening")
    intro, pid = _write(_intro_prompt(row, owner, people))
    packet = {
        "title": row["title"], "event": row["event"], "audience": row["audience"], "owner": owner,
        "prepared_at": _now(), "written_by": profiles._written_by(pid),
        "fingerprint": _fingerprint(row, ids), "intro": intro, "people": people,
    }
    db.execute("UPDATE crm_roundups SET packet = ?, progress = '{}' WHERE id = ?", (json.dumps(packet), row["id"]))
    _changed(row["id"])


# ── Exports ───────────────────────────────────────────────────────────

def _safe(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:120] or "Roundup"


def export(rid: str, fmt: str) -> dict:
    """Writes the prepared packet as a file in the roundup's folder, replacing an earlier one of the same name."""
    from . import roundup_files
    if fmt not in FORMATS:
        raise RoundupError("Choose Word, PDF or Markdown")
    row = _row(rid)
    if not row["packet"]:
        raise RoundupError("Prepare the packet first")
    packet = json.loads(row["packet"])
    when = datetime.fromisoformat(packet["prepared_at"].replace("Z", "+00:00")).strftime("%Y-%m-%d")
    d = folder(rid)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_safe(packet['title'])} {when}.{fmt}"
    path.write_bytes(roundup_files.render(packet, fmt))
    _changed(rid)
    return {"name": path.name, "folder": str(d), "path": str(path), "bytes": path.stat().st_size}


def file_path(rid: str, name: str):
    _row(rid)
    path = folder(rid) / name
    if path.parent != folder(rid) or not path.is_file() or path.suffix.lstrip(".") not in FORMATS:
        raise LookupError("That file is gone")
    return path


def export_rows() -> list[dict]:
    """The roundups for the host's JSON export, without the pictures in their packets."""
    out = []
    for row in db.query("SELECT * FROM crm_roundups ORDER BY created_at, id"):
        packet = json.loads(row["packet"]) if row["packet"] else None
        for person in (packet or {}).get("people", []):
            person.pop("picture", None)
        out.append({**{k: row[k] for k in ("id", "title", "event", "audience", "origin", "created_at", "updated_at")},
                    "people": json.loads(row["people"]), "packet": packet})
    return out
