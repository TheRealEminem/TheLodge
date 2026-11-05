"""Putting right what the AI got wrong about a record.

An import can tie a meeting or a document to the wrong person: nothing was merged, so there's nothing to unmerge, but
everything that source said about them is now on their page. Every link and every fact an import makes remembers its
source (evidence_id), so all of it can be taken off together, given to whoever it really belongs to, and put back.

    detach      take one source off a record: remove it, or move it to someone else
    undo        put it back
    checks      links the old matching only guessed at (from what each import wrote down), for you to look through
    rename_text the old name in the summaries of what's linked to someone, after you correct their name

    crm_corrections   what was taken off, and enough to put it back
    crm_name_blocks   a full name a record isn't, so the next import doesn't link it again
    crm_link_checks   links you've looked at and said are right
(the tables are created in store.py, with the module's other tables)
"""
import json
import re

from core.server import db
from core.server.tags import normalize_tags

from . import resolve, snapshot, store, views
from .duplicates import _plain
from .kinds import EVENT_KINDS, RELATIONSHIP_KINDS


FIELDS = {"title": "Title", "email": "Email", "location": "Location", "linkedin_url": "LinkedIn", "website": "Website"}
# Records that didn't start with an import: their tags were yours or your spreadsheet's before any source agreed.
OWN_TAGS = ("manual", "spreadsheet", "linkedin")


class CorrectionError(ValueError):
    pass


def _ends(entity_id: str, evidence_id: str, c) -> list[dict]:
    """The links this source gave the record: to the source itself, or anywhere with the source as their evidence.
    A rating you gave yourself isn't the source's to take away."""
    rows = c.execute("SELECT * FROM crm_relationships WHERE (source_id = ? AND (target_id = ? OR evidence_id = ?)) "
                     "OR (target_id = ? AND (source_id = ? OR evidence_id = ?))",
                     (entity_id, evidence_id, evidence_id, entity_id, evidence_id, evidence_id)).fetchall()
    return [dict(r) for r in rows if not json.loads(r["properties"] or "{}").get("user_set")]


def _written(entity_id: str, evidence_id: str) -> str | None:
    """How the source wrote the name that was linked to this record."""
    for row in db.query("SELECT proposal, result FROM crm_inbox WHERE status = 'applied' AND json_extract(result, '$.record_id') = ?", (evidence_id,)):
        result, proposal = json.loads(row["result"] or "{}"), json.loads(row["proposal"] or "{}")
        for ent in proposal.get("entities") or []:
            if (result.get("entity_ids") or {}).get(ent.get("ref")) == entity_id:
                return ent.get("name")
    return None


def _says(text: str, name: str) -> bool:
    """Whether every word of a name is in the text."""
    found = set(re.findall(r"[a-z0-9]+", _plain(text)))
    return all(w in found for w in re.findall(r"[a-z0-9]+", _plain(name)))


def _source_text(evidence_id: str) -> str:
    rows = db.query("SELECT title, raw_text, payload FROM crm_inbox WHERE status = 'applied' AND json_extract(result, '$.record_id') = ?", (evidence_id,))
    parts: list[str] = []
    for r in rows:
        attendees = json.loads(r["payload"] or "{}").get("attendees") or []
        parts += [r["title"] or "", r["raw_text"] or "", *((a.get("name") or "") for a in attendees)]
    return " ".join(parts)


def _sources(entity_id: str) -> list[tuple[str, dict, str]]:
    """Every import that named this record: (the meeting or document it made, what it said about them, the import)."""
    out = []
    for row in db.query("SELECT id, proposal, result FROM crm_inbox WHERE status = 'applied' AND proposal IS NOT NULL "
                        "AND EXISTS (SELECT 1 FROM json_each(result, '$.entity_ids') WHERE value = ?)", (entity_id,)):
        result, proposal = json.loads(row["result"] or "{}"), json.loads(row["proposal"] or "{}")
        for ent in proposal.get("entities") or []:
            if (result.get("entity_ids") or {}).get(ent.get("ref")) == entity_id:
                out.append((result.get("record_id"), ent, row["id"]))
    return out


def _planted(entity, evidence_id: str | None, inbox_id: str | None = None) -> dict:
    """What this source alone put on the record and is still there as it wrote it: its title, website, summary, tags.
    A value another source still linked here also gave, or that you've changed since, stays."""
    snap = snapshot.load()
    sources = _sources(entity.id)
    is_mine = lambda rid, row_id: row_id == inbox_id if inbox_id else rid == evidence_id  # noqa: E731
    mine = [ent for rid, ent, row_id in sources if is_mine(rid, row_id)]
    linked = {(e.target_id if e.source_id == entity.id else e.source_id) for e in snap.by_entity.get(entity.id, ())}
    others = [ent for rid, ent, row_id in sources if not is_mine(rid, row_id) and (rid is None or rid in linked)]
    attrs, out = entity.attributes or {}, {"fields": {}, "tags": [], "summary": None}
    for ent in mine:
        for key in FIELDS:
            value = ent.get(key)
            if value and str(attrs.get(key)) == str(value)[:300] and not any(str(o.get(key) or "")[:300] == str(value)[:300] for o in others):
                out["fields"][key] = attrs[key]
        given = (ent.get("summary") or "").strip()
        if given and given == (entity.summary or "").strip() and not any((o.get("summary") or "").strip() == given for o in others):
            out["summary"] = entity.summary
        if entity.source not in OWN_TAGS:
            kept = {t for o in others for t in normalize_tags(o.get("tags") or [])}
            out["tags"] += [t for t in normalize_tags(ent.get("tags") or []) if t in (entity.tags or []) and t not in kept and t not in out["tags"]]
    return out


def _require(entity_id: str, evidence_id: str):
    entity, evidence = store.get_entity(entity_id), store.get_entity(evidence_id)
    if entity is None or evidence is None:
        raise store.NotFound("Entity not found")
    if evidence.kind not in EVENT_KINDS:
        raise CorrectionError("Only a meeting or a document can be taken off a record")
    return entity, evidence


def unlink_report(entity_id: str, inbox_id: str) -> None:
    """A research report about someone else named a person, but not this one: it stops showing on their page, and the
    full name it used is remembered as one this record isn't."""
    row = db.one("SELECT proposal, result FROM crm_inbox WHERE id = ? AND status = 'applied'", (inbox_id,))
    if row is None:
        raise store.NotFound("That report isn't on record")
    result, proposal = json.loads(row["result"] or "{}"), json.loads(row["proposal"] or "{}")
    if result.get("subject_id") == entity_id:
        raise CorrectionError("That report is about them")
    held = result.get("entity_ids") or {}
    refs = [ref for ref, eid in held.items() if eid == entity_id]
    if not refs:
        raise CorrectionError("That report isn't linked to them")
    with db.connect() as c:
        for ref in refs:
            del held[ref]
            name = next((e.get("name") for e in proposal.get("entities") or [] if e.get("ref") == ref), None)
            if name and len(name.split()) > 1:
                c.execute("INSERT OR IGNORE INTO crm_name_blocks (entity_id, name, created_at) VALUES (?, ?, ?)", (entity_id, name.strip().lower(), db.now()))
        c.execute("UPDATE crm_inbox SET result = ? WHERE id = ?", (json.dumps({**result, "entity_ids": held}), inbox_id))
    store._touch()


def move_report(entity_id: str, inbox_id: str, *, to_id: str | None = None, new_name: str | None = None) -> dict:
    """A research report about someone else was filed on this person. Everything it gave them goes to whoever it's really
    about: its links, facts and full text, and the title, summary and tags only it gave. Can be undone."""
    row = db.one("SELECT title, raw_text, proposal, result FROM crm_inbox WHERE id = ? AND status = 'applied'", (inbox_id,))
    entity = store.get_entity(entity_id)
    if row is None or entity is None:
        raise store.NotFound("That report isn't on record")
    result, proposal = json.loads(row["result"] or "{}"), json.loads(row["proposal"] or "{}")
    held = result.get("entity_ids") or {}
    refs = [ref for ref, eid in held.items() if eid == entity_id]
    if not refs:
        raise CorrectionError("That report isn't linked to them")
    new_name = (new_name or "").strip() or None
    target = store.get_entity(to_id) if to_id else None
    if to_id and (target is None or target.kind != entity.kind or to_id == entity_id):
        raise CorrectionError("That record can't take this over")
    if not target and not new_name:
        raise CorrectionError("Say who it's really about")
    ents = [e for e in proposal.get("entities") or [] if e.get("ref") in refs]
    planted = _planted(entity, None, inbox_id)
    if not target:
        target = store.create_entity(entity.kind, new_name, source="manual")
    facts = {f.strip() for e in ents for f in e.get("facts") or [] if f and f.strip()}
    raw = (row["raw_text"] or "").strip()
    with db.connect() as c:
        kept: list[dict] = []
        for rel in proposal.get("relationships") or []:
            if not rel.get("include", True) or (rel.get("source") not in refs and rel.get("target") not in refs):
                continue
            s, t = held.get(rel.get("source")), held.get(rel.get("target"))
            found = c.execute("SELECT * FROM crm_relationships WHERE source_id = ? AND target_id = ? AND kind = ? AND evidence_id IS NULL AND source != 'manual'", (s, t, rel["kind"])).fetchone()
            if found is None or json.loads(found["properties"] or "{}").get("user_set"):
                continue
            e = dict(found)
            ns, nt = (target.id if s == entity_id else s), (target.id if t == entity_id else t)
            if ns == nt or c.execute("SELECT 1 FROM crm_relationships WHERE source_id = ? AND target_id = ? AND kind = ?", (ns, nt, e["kind"])).fetchone():
                c.execute("DELETE FROM crm_relationships WHERE id = ?", (e["id"],))
                kept.append({"row": e, "fate": "removed"})
            else:
                c.execute("UPDATE crm_relationships SET source_id = ?, target_id = ? WHERE id = ?", (ns, nt, e["id"]))
                kept.append({"row": e, "fate": "moved"})
        notes = [dict(n) for n in c.execute("SELECT * FROM crm_notes WHERE entity_id = ? AND evidence_id IS NULL", (entity_id,))
                 if n["body"].strip() in facts or (raw and n["body"].strip().endswith(raw))]
        for n in notes:
            c.execute("UPDATE crm_notes SET entity_id = ? WHERE id = ?", (target.id, n["id"]))
        names = {e["name"].strip().lower() for e in ents if len((e.get("name") or "").split()) > 1 and e["name"].strip().lower() != target.name.strip().lower()}
        block = None
        for name in names:
            if c.execute("INSERT OR IGNORE INTO crm_name_blocks (entity_id, name, created_at) VALUES (?, ?, ?)", (entity_id, name, db.now())).rowcount:
                block = name
        given = _take_planted(entity, target, planted, c)
        new_result = {**result, "entity_ids": {ref: (target.id if eid == entity_id else eid) for ref, eid in held.items()}}
        if result.get("subject_id") == entity_id:
            new_result["subject_id"] = target.id
        c.execute("UPDATE crm_inbox SET result = ? WHERE id = ?", (json.dumps(new_result), inbox_id))
        snap = {"edges": kept, "notes": notes, "block": block, "created": bool(new_name and not to_id), "planted": planted, "given": given,
                "report": {"inbox_id": inbox_id, "result": result}}
        cid = db.new_id()
        c.execute("INSERT INTO crm_corrections (id, entity_id, evidence_id, to_id, name, snapshot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (cid, entity_id, inbox_id, target.id, row["title"] or "Research report", json.dumps(snap), db.now()))
    store._touch()
    return {"id": cid, "to": {"id": target.id, "name": target.name}, "links": len(kept), "notes": len(notes)}


def preview(entity_id: str, evidence_id: str) -> dict:
    """What taking this source off the record would take with it."""
    entity, evidence = _require(entity_id, evidence_id)
    ents = snapshot.load().entities
    with db.connect() as c:
        edges = _ends(entity_id, evidence_id, c)
        notes = c.execute("SELECT id, body FROM crm_notes WHERE entity_id = ? AND evidence_id = ?", (entity_id, evidence_id)).fetchall()
    links = []
    for e in edges:
        other = e["target_id"] if e["source_id"] == entity_id else e["source_id"]
        if other == evidence_id or other not in ents:
            continue
        rel = RELATIONSHIP_KINDS.get(e["kind"])
        label = (rel.label if e["source_id"] == entity_id else rel.inverse) if rel else e["kind"]
        links.append({"id": e["id"], "label": label, "other": ents[other].name})
    planted = _planted(entity, evidence_id)
    fields = [{"label": FIELDS[k], "value": str(v)} for k, v in planted["fields"].items()]
    if planted["summary"]:
        fields.append({"label": "Summary", "value": planted["summary"]})
    if planted["tags"]:
        fields.append({"label": "Tags", "value": ", ".join(planted["tags"])})
    return {"entity": {"id": entity.id, "name": entity.name}, "evidence": {"id": evidence.id, "name": evidence.name, "kind": evidence.kind},
            "written": _written(entity_id, evidence_id), "links": links, "notes": [dict(n) for n in notes], "fields": fields}


def detach(entity_id: str, evidence_id: str, *, to_id: str | None = None, new_name: str | None = None) -> dict:
    """Take a source off a record. With `to_id` or `new_name` everything it said moves to that person; otherwise it's
    removed. A full name the source used is remembered as one this record isn't. Can be undone."""
    entity, evidence = _require(entity_id, evidence_id)
    new_name = (new_name or "").strip() or None
    if to_id and to_id == entity_id:
        raise CorrectionError("That's the same record")
    target = store.get_entity(to_id) if to_id else None
    if to_id and (target is None or target.kind != entity.kind):
        raise CorrectionError("That record can't take this over")
    written = _written(entity_id, evidence_id)
    # Only a full name the source really used: one the AI filled in from your book says nothing about this record.
    blocked = written.strip().lower() if written and len(written.split()) > 1 and _says(_source_text(evidence_id), written) else None
    planted = _planted(entity, evidence_id)
    if new_name and not target:
        target = store.create_entity(entity.kind, new_name, source="manual")
    with db.connect() as c:
        edges = _ends(entity_id, evidence_id, c)
        notes = [dict(r) for r in c.execute("SELECT * FROM crm_notes WHERE entity_id = ? AND evidence_id = ?", (entity_id, evidence_id))]
        if not edges and not notes:
            raise CorrectionError(f"{evidence.name} isn't linked to {entity.name}")
        kept: list[dict] = []
        for e in edges:
            if target is None:
                c.execute("DELETE FROM crm_relationships WHERE id = ?", (e["id"],))
                kept.append({"row": e, "fate": "removed"})
                continue
            s = target.id if e["source_id"] == entity_id else e["source_id"]
            t = target.id if e["target_id"] == entity_id else e["target_id"]
            if s == t or c.execute("SELECT 1 FROM crm_relationships WHERE source_id = ? AND target_id = ? AND kind = ?", (s, t, e["kind"])).fetchone():
                c.execute("DELETE FROM crm_relationships WHERE id = ?", (e["id"],))
                kept.append({"row": e, "fate": "removed"})
            else:
                c.execute("UPDATE crm_relationships SET source_id = ?, target_id = ? WHERE id = ?", (s, t, e["id"]))
                kept.append({"row": e, "fate": "moved"})
        if target is None:
            c.execute("DELETE FROM crm_notes WHERE entity_id = ? AND evidence_id = ?", (entity_id, evidence_id))
        else:
            c.execute("UPDATE crm_notes SET entity_id = ? WHERE entity_id = ? AND evidence_id = ?", (target.id, entity_id, evidence_id))
        added_block = False
        if blocked:
            added_block = c.execute("INSERT OR IGNORE INTO crm_name_blocks (entity_id, name, created_at) VALUES (?, ?, ?)",
                                    (entity_id, blocked, db.now())).rowcount > 0
        given = _take_planted(entity, target, planted, c)
        snap = {"edges": kept, "notes": notes, "block": blocked if added_block else None, "created": bool(new_name and target),
                "planted": planted, "given": given}
        cid = db.new_id()
        c.execute("INSERT INTO crm_corrections (id, entity_id, evidence_id, to_id, name, snapshot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (cid, entity_id, evidence_id, target.id if target else None, evidence.name, json.dumps(snap), db.now()))
    store._touch()
    return {"id": cid, "to": {"id": target.id, "name": target.name} if target else None, "links": len(edges), "notes": len(notes)}


def _take_planted(entity, target, planted: dict, c) -> dict:
    """Take what the source planted off the record, and give it to `target` where it has nothing of its own.
    Returns what the target was given, so undo can take back exactly that."""
    attrs = dict(entity.attributes or {})
    fields: dict = {"attributes": attrs}
    given: dict = {"fields": {}, "tags": [], "summary": None}
    for key in planted["fields"]:
        attrs.pop(key, None)
    if planted["summary"]:
        fields["summary"] = None
    if planted["tags"]:
        fields["tags"] = [t for t in entity.tags or [] if t not in planted["tags"]]
    if planted["fields"] or planted["summary"] or planted["tags"]:
        store.update_entity(entity.id, conn=c, **fields)
    if target is not None:
        theirs = dict(target.attributes or {})
        for key, value in planted["fields"].items():
            if not theirs.get(key):
                theirs[key] = value
                given["fields"][key] = value
        changes: dict = {}
        if given["fields"]:
            changes["attributes"] = theirs
        if planted["summary"] and not target.summary:
            changes["summary"] = given["summary"] = planted["summary"]
        new_tags = [t for t in planted["tags"] if t not in (target.tags or [])]
        if new_tags:
            given["tags"] = new_tags
            changes["tags"] = [*(target.tags or []), *new_tags]
        if changes:
            store.update_entity(target.id, conn=c, **changes)
    return given


def _put_planted_back(row: dict, snap: dict, c) -> None:
    planted, given = snap.get("planted"), snap.get("given")
    if not planted:
        return
    entity = store.get_entity(row["entity_id"], c)
    if planted["fields"] or planted["summary"] or planted["tags"]:
        attrs = dict(entity.attributes or {})
        for key, value in planted["fields"].items():
            attrs.setdefault(key, value)
        changes: dict = {"attributes": attrs, "tags": list(dict.fromkeys([*(entity.tags or []), *planted["tags"]]))}
        if planted["summary"] and not entity.summary:
            changes["summary"] = planted["summary"]
        store.update_entity(entity.id, conn=c, **changes)
    target = store.get_entity(row["to_id"], c) if row["to_id"] else None
    if target is not None and given and (given["fields"] or given["summary"] or given["tags"]):
        attrs = dict(target.attributes or {})
        for key, value in given["fields"].items():
            if attrs.get(key) == value:
                attrs.pop(key)
        changes = {"attributes": attrs, "tags": [t for t in target.tags or [] if t not in given["tags"]]}
        if given["summary"] and target.summary == given["summary"]:
            changes["summary"] = None
        store.update_entity(target.id, conn=c, **changes)


def undo(correction_id: str) -> dict:
    row = db.one("SELECT * FROM crm_corrections WHERE id = ?", (correction_id,))
    if row is None:
        raise store.NotFound("That correction isn't on record")
    if row["undone_at"]:
        raise CorrectionError("That was already put back")
    if store.get_entity(row["entity_id"]) is None:
        raise CorrectionError("The record it came off is gone")
    snap = json.loads(row["snapshot"])
    with db.connect() as c:
        exists = lambda eid: c.execute("SELECT 1 FROM crm_entities WHERE id = ?", (eid,)).fetchone() is not None  # noqa: E731
        for kept in snap["edges"]:
            e = kept["row"]
            if not (exists(e["source_id"]) and exists(e["target_id"])):
                continue   # the record at the other end was deleted since
            if kept["fate"] == "moved" and c.execute("UPDATE OR IGNORE crm_relationships SET source_id = ?, target_id = ? WHERE id = ?",
                                                     (e["source_id"], e["target_id"], e["id"])).rowcount:
                continue
            cols = list(e)
            c.execute(f"INSERT OR IGNORE INTO crm_relationships ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [e[k] for k in cols])
        for note in snap["notes"]:
            if not c.execute("UPDATE crm_notes SET entity_id = ? WHERE id = ?", (row["entity_id"], note["id"])).rowcount:
                cols = list(note)
                c.execute(f"INSERT OR IGNORE INTO crm_notes ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [note[k] for k in cols])
        if snap.get("block"):
            c.execute("DELETE FROM crm_name_blocks WHERE entity_id = ? AND name = ?", (row["entity_id"], snap["block"]))
        _put_planted_back(row, snap, c)
        if snap.get("report"):
            c.execute("UPDATE crm_inbox SET result = ? WHERE id = ?", (json.dumps(snap["report"]["result"]), snap["report"]["inbox_id"]))
        if snap.get("created") and row["to_id"]:
            # The record made for it goes again, if nothing else has come to it since.
            busy = (c.execute("SELECT 1 FROM crm_relationships WHERE source_id = ? OR target_id = ?", (row["to_id"], row["to_id"])).fetchone()
                    or c.execute("SELECT 1 FROM crm_notes WHERE entity_id = ?", (row["to_id"],)).fetchone())
            if not busy:
                c.execute("DELETE FROM crm_entities WHERE id = ?", (row["to_id"],))
                c.execute("DELETE FROM crm_fts WHERE id = ?", (row["to_id"],))
        c.execute("UPDATE crm_corrections SET undone_at = ? WHERE id = ?", (db.now(), correction_id))
    store._touch()
    return {"id": correction_id}


def of(entity_id: str) -> list[dict]:
    """What's been taken off this record and can still be put back, newest first."""
    ents = snapshot.load().entities
    rows = db.query("SELECT id, evidence_id, to_id, name, created_at FROM crm_corrections WHERE entity_id = ? AND undone_at IS NULL ORDER BY created_at DESC", (entity_id,))
    return [{**r, "to_name": ents[r["to_id"]].name if r["to_id"] in ents else None} for r in rows]


# ── Links worth a second look ─────────────────────────────────────────

_checks: tuple[int, list[dict]] | None = None


def checks() -> dict:
    """Links the matching guessed at: a name that only looks like the record's, or a surname the source never gave.
    Worked out from what each import wrote down. Anything you've since fixed or said is right drops off the list."""
    global _checks
    version = store.version()
    if _checks is None or _checks[0] != version:
        _checks = (version, _find_checks())
    return {"total": len(_checks[1]), "items": _checks[1]}


def _find_checks() -> list[dict]:
    v = views.get()
    snap = v.snap
    done = {(r["entity_id"], r["evidence_id"]) for r in db.query("SELECT entity_id, evidence_id FROM crm_link_checks")}
    rows = []
    # Who a source of each hat named in full. "Theo" in a Parks Board meeting is no worry when another Parks Board meeting says
    # "Theo Marsh"; "Dana" in a Parks Board meeting is, when "Dana Whitfield" only ever came from a document about something else.
    named_in: dict[str, set[str]] = {}
    hat_of = {r["entity_id"]: r["hat_id"] for r in db.query("SELECT entity_id, hat_id FROM crm_hat_links WHERE how = 'source'")}
    for row in db.query("SELECT title, raw_text, payload, proposal, result FROM crm_inbox WHERE status = 'applied' AND proposal IS NOT NULL ORDER BY created_at DESC"):
        proposal, result = json.loads(row["proposal"]), json.loads(row["result"] or "{}")
        evidence = result.get("record_id")
        if not evidence or evidence not in snap.entities:
            continue
        payload = json.loads(row["payload"] or "{}")
        text = " ".join([row["title"] or "", row["raw_text"] or "", *((a.get("name") or "") for a in payload.get("attendees") or [])])
        rows.append((proposal, result, evidence, text))
        for ent in proposal.get("entities") or []:
            eid = (result.get("entity_ids") or {}).get(ent.get("ref"))
            name = ent.get("name") or ""
            if eid and hat_of.get(evidence) and len(name.split()) > 1 and resolve.as_written(name, text) == name:
                named_in.setdefault(eid, set()).add(hat_of[evidence])
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for proposal, result, evidence, text in rows:
        for ent in proposal.get("entities") or []:
            eid = (result.get("entity_ids") or {}).get(ent.get("ref"))
            doubt = _doubt(ent, text)
            if not doubt or not eid or eid not in snap.entities or snap.entities[eid].is_self or (eid, evidence) in done or (eid, evidence) in seen:
                continue
            why, firm = doubt
            if not firm and hat_of.get(evidence) in named_in.get(eid, ()):
                continue
            if not any(evidence in (e.source_id, e.target_id) for e in snap.by_entity.get(eid, ())):
                continue   # already taken off
            seen.add((eid, evidence))
            out.append({"entity": v.summary(eid).model_dump(mode="json"), "evidence": v.summary(evidence).model_dump(mode="json"),
                        "written": ent.get("name"), "why": why, "firm": firm})
    out.sort(key=lambda x: (x["entity"]["kind"] != "person", not x["firm"], x["entity"]["name"].lower()))
    return out


def _doubt(ent: dict, text: str) -> tuple[str, bool] | None:
    """(why this link is in doubt, whether it's plainly another name rather than just a name left short)."""
    if ent.get("action") != "link" or ent.get("is_self") or ent.get("kind") not in ("person", "organization"):
        return None
    name = ent.get("name") or ""
    chosen = next((c for c in ent.get("candidates") or [] if c.get("id") == ent.get("match_id")), None)
    if chosen and chosen.get("reason") == "similar name":
        fit = resolve.name_fit(ent["kind"], name, chosen.get("name") or "")
        if fit == "partial":
            return f"The source only says “{name}”, which could be anyone with that name.", False
        if fit == "different":
            return f"“{name}” only looks like “{chosen.get('name')}”.", True
    if ent["kind"] == "person":
        written = resolve.as_written(name, text)
        if written != name:
            return f"The source only says “{written}”. The surname came from your book, not from the source.", False
    return None


def looks_right(entity_id: str, evidence_id: str) -> None:
    db.execute("INSERT OR IGNORE INTO crm_link_checks (entity_id, evidence_id, created_at) VALUES (?, ?, ?)", (entity_id, evidence_id, db.now()))
    store._touch()


# ── A corrected name, everywhere it was written ───────────────────────

def rename_text(entity_id: str, old: str, new: str) -> int:
    """Change a full name in the summaries of what's linked to this person and in the notes about them. The original
    text of a meeting or document is left as it was. Returns how many records changed."""
    entity = store.get_entity(entity_id)
    if entity is None:
        raise store.NotFound("Entity not found")
    old, new = (old or "").strip(), (new or "").strip()
    if len(old.split()) < 2 or not new:
        raise CorrectionError("Give the old full name and the new one")
    pattern = re.compile(rf"(?<!\w){re.escape(old)}(?!\w)", re.I)
    swap = lambda s: pattern.sub(lambda _: new, s)  # noqa: E731
    snap = snapshot.load()
    changed = 0
    with db.connect() as c:
        for edge in snap.by_entity.get(entity_id, ()):
            other = snap.entities.get(edge.target_id if edge.source_id == entity_id else edge.source_id)
            if other is None or other.kind not in EVENT_KINDS:
                continue
            attrs = dict(other.attributes or {})
            for key in ("key_points", "action_items"):
                if attrs.get(key):
                    attrs[key] = [swap(x) if isinstance(x, str) else x for x in attrs[key]]
            summary = swap(other.summary) if other.summary else other.summary
            if summary != other.summary or attrs != (other.attributes or {}):
                store.update_entity(other.id, attributes=attrs, summary=summary, conn=c)
                changed += 1
        for n in c.execute("SELECT id, body FROM crm_notes WHERE entity_id = ?", (entity_id,)).fetchall():
            body = swap(n["body"])
            if body != n["body"]:
                c.execute("UPDATE crm_notes SET body = ? WHERE id = ?", (body, n["id"]))
                changed += 1
    store._touch()
    return changed
