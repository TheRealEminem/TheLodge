"""The shared Google Sheet: your people and organizations in a spreadsheet that anyone you share it with can read,
correct and add to, kept in step with The Lodge both ways.

The Lodge stays the database. The app reads and writes its own tables, and this runs in the background (every couple
of minutes, and within about half a minute of a change here), so nothing in the app waits on Google.

How it reaches the sheet: a short Apps Script (sheet_script.py) pasted into the spreadsheet and deployed as a web app.
Its link is kept like a key. There's no Google Cloud project and no sign-in to expire.

What goes on it: a People tab and an Organizations tab with contact details, tags and the summary. Your own record,
anyone tagged "private", and everything else (how well you know people, notes, meetings, documents, overviews) stay
here.

How the two sides agree, cell by cell: the value both last agreed on is kept (crm_sheet_rows). A value changed only on
the sheet is copied in; one changed only here is written out; one changed on both keeps The Lodge's, and the sheet's
goes into a note on the record so nothing anyone typed is lost.

- A row without a Lodge ID is someone new: matched to a record by email, LinkedIn or exact name, or else made into a
  new one (source "sheet"). The row gets the record's id.
- "Add a note": whatever is typed there becomes a note on the record, and the cell is emptied.
- A row deleted on the sheet comes back at the next sync. Deleting the record here takes its row off.
- Columns The Lodge doesn't know are left alone.
- Many values cleared or overwritten at once (a sort or a paste gone wrong) aren't copied in: that tab waits until
  you choose, in Settings, between taking the sheet's values and putting The Lodge's back.
"""
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import httpx

from core.server import db, jobs, settings
from core.server.tags import normalize_tags

from . import capture, snapshot, store
from .connections import build_index, current_org
from .model import Entity
from .sheet_script import VERSION as SCRIPT_VERSION

log = logging.getLogger("crm.sheet")

EVERY_SECONDS = 120       # how often the sheet is read
SOON_SECONDS = 30         # how soon a change made here goes out
TIMEOUT = 90
PRIVATE_TAG = "private"
ID_HEADER = "Lodge ID"
NOTE_HEADER = "Add a note"
HOLD_AT = 10              # values cleared or overwritten on a tab in one go (or a fifth of its rows) that wait for you

_transport: httpx.BaseTransport | None = None   # tests put a fake one here
_synced_version: int | None = None              # store.version() as of the last sync


@dataclass(frozen=True)
class Tab:
    name: str
    kind: str
    fields: tuple[tuple[str, str], ...]   # (field, header), in column order

    @property
    def headers(self) -> list[str]:
        return [h for _, h in self.fields] + [NOTE_HEADER, ID_HEADER]


PEOPLE = Tab("People", "person", (
    ("name", "Name"), ("organization", "Organization"), ("title", "Title"), ("email", "Email"), ("phone", "Phone"),
    ("linkedin", "LinkedIn"), ("location", "Location"), ("tags", "Tags"), ("summary", "Summary"),
))
ORGS = Tab("Organizations", "organization", (
    ("name", "Name"), ("website", "Website"), ("location", "Location"), ("email", "Email"), ("tags", "Tags"),
    ("summary", "Summary"),
))
TABS = (PEOPLE, ORGS)
ATTRS = {"title": "title", "email": "email", "phone": "phone", "linkedin": "linkedin_url", "location": "location",
         "website": "website"}
HEADER_NOTES = {
    ID_HEADER: "Filled in by The Lodge. Leave it blank on a new row.",
    NOTE_HEADER: "Type a note here and The Lodge files it on their record, then empties the cell.",
}

ACCESS = ("Google asked for a sign-in instead of running the script. In Apps Script, deploy it as a web app with "
          "Execute as “Me” and Who has access “Anyone”, then paste the new link.")
OUTDATED = ("The script in the sheet is older than this version of The Lodge. Copy it again from here, paste it over the "
            "old one, and deploy a new version (Deploy, Manage deployments, Edit, Version: New version).")


class SheetError(RuntimeError):
    def __init__(self, message: str, *, link_problem: bool = False):
        super().__init__(message)
        self.link_problem = link_problem


# ── Talking to the sheet ──────────────────────────────────────────────

def link() -> str:
    return str(settings.get_all().get("crm.sheet_secret") or "").strip()


def configured() -> bool:
    return bool(link())


def seconds() -> int:
    """Nothing until there's a link; then soon after a change here, and every couple of minutes otherwise."""
    if not configured():
        return 0
    return SOON_SECONDS if store.version() != _synced_version else EVERY_SECONDS


def call(body: dict) -> dict:
    url = link()
    if not url:
        raise SheetError("Paste the sheet's script link first.", link_problem=True)
    if not url.startswith("https://script.google.com/"):
        raise SheetError("That isn't an Apps Script web app link. It starts with https://script.google.com/ and ends with /exec.",
                         link_problem=True)
    if url.rstrip("/").endswith("/dev"):
        raise SheetError("That's the script's test link, which only works in your own browser. Use the Web app URL "
                         "from Deploy, Manage deployments (it ends with /exec).", link_problem=True)
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, transport=_transport) as client:
            r = client.post(url, content=json.dumps(body), headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise SheetError(f"Couldn't reach Google ({type(e).__name__}). It will try again.") from e
    if r.status_code in (401, 403):
        raise SheetError(ACCESS, link_problem=True)
    if r.status_code == 404:
        raise SheetError("There's no script at that link any more. Copy the Web app URL again from Deploy, Manage "
                         "deployments.", link_problem=True)
    if r.status_code >= 400:
        raise SheetError(f"Google answered {r.status_code}. It will try again.")
    try:
        data = r.json()
    except ValueError:
        raise SheetError(ACCESS, link_problem=True) from None   # a sign-in page instead of the script's answer
    if not isinstance(data, dict) or "version" not in data:
        raise SheetError(ACCESS, link_problem=True)
    if int(data.get("version") or 0) < SCRIPT_VERSION:
        raise SheetError(OUTDATED, link_problem=True)
    if not data.get("ok"):
        raise SheetError(f"The sheet's script couldn't do it: {data.get('error') or 'no reason given'}. It will try again.")
    return data


def test() -> dict:
    """Does the link work? Says which spreadsheet it opens, changes nothing."""
    return {"ok": True, "spreadsheet": call({"action": "hello"}).get("spreadsheet")}


# ── Records as rows ───────────────────────────────────────────────────

def _split_tags(text: str) -> list[str]:
    return normalize_tags([t for t in re.split(r"[,;\n]", text or "") if t.strip()])


def _canon(f: str, value: str) -> str:
    """What a value means, for comparing: "Investor,friend" and "investor, friend" are the same tags."""
    value = (value or "").strip()
    if f == "tags":
        return ", ".join(_split_tags(value))
    if f == "email":
        return value.lower()
    return value


def _linkedin_key(url: str) -> str:
    u = re.sub(r"^https?://", "", (url or "").strip().lower())
    u = re.sub(r"^(www|[a-z]{2})\.", "", u).split("?")[0].split("#")[0].rstrip("/")
    return u if u.startswith("linkedin.com/") else ""


def _wanted(e: Entity) -> bool:
    return not e.is_self and PRIVATE_TAG not in (e.tags or [])


def _employers(snap: snapshot.Snapshot) -> dict[str, str]:
    ix = build_index(snap)
    return {p.id: (org.name if (org := current_org(snap, ix, p.id)) else "") for p in snap.of_kind("person")}


def _project(e: Entity, employer: str = "") -> dict[str, str]:
    a = e.attributes or {}
    out = {}
    for f, _ in (PEOPLE if e.kind == "person" else ORGS).fields:
        if f == "name":
            v = e.name
        elif f == "organization":
            v = employer
        elif f == "tags":
            v = ", ".join(e.tags or [])
        elif f == "summary":
            v = e.summary or ""
        else:
            v = a.get(ATTRS[f]) or ""
        out[f] = str(v).strip()
    return out


def _fresh(entity_id: str) -> dict[str, str]:
    e = store.require_entity(entity_id)
    if e.kind != "person":
        return _project(e)
    snap = snapshot.load()
    org = current_org(snap, build_index(snap), entity_id)
    return _project(e, org.name if org else "")


# ── Writing the sheet's values into records ───────────────────────────

def _named(kind: str, name: str) -> list[Entity]:
    needle = name.strip().lower()
    return [e for e in store.all_entities(kind)
            if e.name.strip().lower() == needle or needle in {str(x).strip().lower() for x in (e.attributes or {}).get("aliases") or []}]


def _match(kind: str, values: dict[str, str]) -> Entity | None:
    """The record a new row is about, when that's clear: one record with its email, its LinkedIn or its exact name."""
    pool = store.all_entities(kind)
    email = values.get("email", "").strip().lower()
    if email:
        hits = [e for e in pool if str((e.attributes or {}).get("email") or "").strip().lower() == email]
        if len(hits) == 1:
            return hits[0]
    key = _linkedin_key(values.get("linkedin", ""))
    if key:
        hits = [e for e in pool if _linkedin_key(str((e.attributes or {}).get("linkedin_url") or "")) == key]
        if len(hits) == 1:
            return hits[0]
    hits = _named(kind, values.get("name", ""))
    return hits[0] if len(hits) == 1 else None


def _org_called(name: str) -> Entity:
    hits = _named("organization", name)
    if hits:
        return min(hits, key=lambda e: (e.created_at.isoformat() if e.created_at else "", e.id))
    return store.create_entity("organization", name.strip(), source="sheet")


def _set_employer(person_id: str, name: str) -> None:
    """They work at `name` now: the job the sheet showed is ended, and this one added (or picked up again)."""
    name = name.strip()
    snap = snapshot.load()
    current = current_org(snap, build_index(snap), person_id)
    if current and name and current.name.strip().lower() == name.lower():
        return
    if current:
        edge = store.find_edge(person_id, current.id, "works_at")
        if edge and edge.ended_at is None:
            store.update_edge(edge.id, ended_at=date.today())
    if not name:
        return
    org = _org_called(name)
    edge = store.find_edge(person_id, org.id, "works_at")
    if edge is None:
        edge = store.create_edge(person_id, org.id, "works_at", source="sheet")
    elif edge.ended_at is not None:
        edge = store.update_edge(edge.id, ended_at=None)
    snap = snapshot.load()
    shown = current_org(snap, build_index(snap), person_id)
    if shown is None or shown.id != org.id:   # another job with a start date would still win: this one starts today
        store.update_edge(edge.id, started_at=date.today())


def _apply(e: Entity, changes: dict[str, str]) -> None:
    fields: dict = {}
    attrs = dict(e.attributes or {})
    for f, v in changes.items():
        if f == "name":
            if v and v != e.name:
                fields["name"] = v
        elif f == "tags":
            if _split_tags(v) != (e.tags or []):
                fields["tags"] = _split_tags(v)
        elif f == "summary":
            if (v or None) != e.summary:
                fields["summary"] = v or None
        elif f in ATTRS:
            if v:
                attrs[ATTRS[f]] = v
            else:
                attrs.pop(ATTRS[f], None)
    if attrs != (e.attributes or {}):
        fields["attributes"] = attrs
    if fields:
        store.update_entity(e.id, **fields)
    if "organization" in changes and e.kind == "person":
        _set_employer(e.id, changes["organization"])


def _fill_gaps(e: Entity, values: dict[str, str]) -> int:
    """A row meeting its record for the first time: the sheet fills what the record doesn't have, nothing more."""
    have = _fresh(e.id)
    gaps = {f: v for f, v in values.items() if f != "name" and v and not _canon(f, have.get(f, ""))}
    if gaps:
        _apply(store.require_entity(e.id), gaps)
    return len(gaps)


def _create(tab: Tab, values: dict[str, str]) -> Entity:
    attrs = {ATTRS[f]: v for f, v in values.items() if f in ATTRS and v}
    e = store.create_entity(tab.kind, values["name"], summary=values.get("summary") or None, attributes=attrs,
                            tags=_split_tags(values.get("tags", "")), source="sheet")
    if tab.kind == "person" and values.get("organization"):
        _set_employer(e.id, values["organization"])
    return e


def _note(entity_id: str, body: str) -> bool:
    """Files a note from the sheet, once: the same words already noted from the sheet aren't added again (a sync that
    noted them but couldn't empty the cell)."""
    body = body.strip()
    if not body or db.one("SELECT 1 AS x FROM crm_notes WHERE entity_id = ? AND source = 'sheet' AND body = ?", (entity_id, body)):
        return False
    store.add_note(entity_id, body, source="sheet")
    return True


# ── One sync ──────────────────────────────────────────────────────────

@dataclass
class Row:
    num: int                    # row number on the sheet when it was read
    raw: dict[str, str]         # header -> the cell as shown, for writing back only over what was read
    values: dict[str, str]      # field -> value, for columns that were there before this sync
    lodge_id: str
    note: str


def _rows(tab: Tab, data: dict) -> list[Row]:
    col: dict[str, int] = {}
    for i, h in enumerate(data.get("headers") or []):
        col.setdefault(str(h).strip().lower(), i)
    added = {str(h).strip().lower() for h in data.get("added") or []}
    out = []
    for num, cells in enumerate(data.get("rows") or [], start=2):
        raw = {h: str(cells[col[h.lower()]]) if h.lower() in col and col[h.lower()] < len(cells) else "" for h in tab.headers}
        if not any(v.strip() for v in raw.values()):
            continue
        values = {f: raw[h].strip() for f, h in tab.fields if h.lower() in col and h.lower() not in added}
        out.append(Row(num, raw, values, raw[ID_HEADER].strip(), raw[NOTE_HEADER].strip()))
    return out


def _at(row: Row, *, by_name: bool = False) -> dict:
    at = {"row": row.num, "id": row.raw[ID_HEADER]}
    return {**at, "name": row.raw["Name"]} if by_name or not row.lodge_id else at


@dataclass
class _Run:
    read: dict
    decision: str | None                          # "apply" or "restore": your answer to a tab that was held
    counts: Counter = field(default_factory=Counter)
    held: dict[str, dict] = field(default_factory=dict)
    skip: set[str] = field(default_factory=set)
    links: dict[str, dict[str, Row]] = field(default_factory=dict)    # tab -> record id -> its row
    claims: dict[str, set[str]] = field(default_factory=dict)         # tab -> records whose row needs their id
    drops: dict[str, list[Row]] = field(default_factory=dict)         # tab -> rows to take off
    final: dict[str, dict[str, dict]] = field(default_factory=dict)   # tab -> record id -> what the row now says
    changed_app: bool = False

    # Phase 1: what the sheet says goes into the records.
    def take_in(self) -> None:
        for tab in TABS:
            data = (self.read.get("tabs") or {}).get(tab.name)
            if data is None:
                self.skip.add(tab.name)
                continue
            snap = snapshot.load()   # again for each tab: the one before may have added organizations
            self._take_in(tab, data, snap, _employers(snap))

    def _take_in(self, tab: Tab, data: dict, snap: snapshot.Snapshot, employers: dict[str, str]) -> None:
        rows = _rows(tab, data)
        self.counts["rows"] += len(rows)
        base = {r["entity_id"]: json.loads(r["base"]) for r in db.query("SELECT entity_id, base FROM crm_sheet_rows WHERE tab = ?", (tab.name,))}
        ents = {e.id: e for e in snap.of_kind(tab.kind)}
        links: dict[str, Row] = {}
        drops: list[Row] = []
        fresh: list[tuple[Row, bool]] = []   # (row, copied from another to start someone new)
        for row in rows:
            rid = row.lodge_id
            if rid and (rid in base or rid in ents):
                e = ents.get(rid)
                if rid in links:   # a copy of a row that's already there
                    if e and row.values.get("name") and row.values["name"].strip().lower() != e.name.strip().lower():
                        fresh.append((row, True))   # copied to start someone new from: a new record
                    else:
                        drops.append(row)
                elif e and _wanted(e):
                    links[rid] = row
                else:
                    drops.append(row)   # deleted here, or now kept off the sheet
            else:
                fresh.append((row, False))   # someone new, or an id The Lodge never gave out

        # Linked rows: what changed on the sheet since both sides last agreed.
        planned: dict[str, tuple[dict, list]] = {}
        overwritten: Counter = Counter()
        for rid, row in links.items():
            mine, agreed = _project(ents[rid], employers.get(rid, "")), base.get(rid, {})
            changes, conflicts = {}, []
            for f, s in row.values.items():
                sc, ac = _canon(f, s), _canon(f, mine[f])
                if f == "name" and not sc:
                    continue   # a name can't be emptied; it's put back
                if f not in agreed:   # never compared before: the sheet only fills a gap
                    if sc and not ac:
                        changes[f] = s
                    continue
                bc = _canon(f, agreed[f])
                if sc in (bc, ac):
                    continue
                if ac == bc:
                    changes[f] = s
                    if ac:
                        overwritten[dict(tab.fields)[f]] += 1
                else:
                    conflicts.append((f, s, mine[f]))
            planned[rid] = (changes, conflicts)
        if sum(overwritten.values()) > max(HOLD_AT, len(links) // 5) and self.decision != "apply":
            if self.decision != "restore":
                self.held[tab.name] = {"cells": sum(overwritten.values()), "columns": [h for h, _ in overwritten.most_common(3)]}
                self.skip.add(tab.name)
                return
            planned = {rid: ({}, []) for rid in planned}   # you chose to put The Lodge's values back

        headers = dict(tab.fields)
        for rid, (changes, conflicts) in planned.items():
            if changes:
                _apply(store.require_entity(rid), changes)
                self.counts["changes_in"] += len(changes)
                self.changed_app = True
            for f, s, kept in conflicts:
                said = f"On the shared sheet, {headers[f]} was changed to “{s}”" if s else f"On the shared sheet, {headers[f]} was emptied"
                if _note(rid, f"{said}, but it had changed here too, so “{kept}” was kept."):
                    self.counts["conflicts"] += 1
                    self.changed_app = True
            if links[rid].note and _note(rid, links[rid].note):
                self.counts["notes"] += 1
                self.changed_app = True
        for row in drops:
            if row.note and row.lodge_id in ents and _note(row.lodge_id, row.note):
                self.counts["notes"] += 1
                self.changed_app = True

        # New rows: someone already here, or someone new.
        claims: set[str] = set()
        for row, copied in fresh:
            if not row.values.get("name"):
                continue   # still being typed, or not about anyone
            e = None if copied else _match(tab.kind, row.values)   # a copy still has the original's email
            if e is not None:
                self.counts["matched"] += 1
                if _fill_gaps(e, row.values):
                    self.changed_app = True
                e = store.require_entity(e.id)
                if e.id in links or not _wanted(e):   # they already have a row, or are kept off the sheet
                    drops.append(row)
                    if row.note and _note(e.id, row.note):
                        self.counts["notes"] += 1
                    continue
            else:
                e = _create(tab, row.values)
                self.counts["new"] += 1
                self.changed_app = True
            if row.note and _note(e.id, row.note):
                self.counts["notes"] += 1
            links[e.id] = row
            claims.add(e.id)
        self.links[tab.name], self.claims[tab.name], self.drops[tab.name] = links, claims, drops

    # Phase 2: what the records now say goes out, worked out from the graph as it is after phase 1.
    def writes(self) -> dict:
        snap = snapshot.load()
        employers = _employers(snap)
        out = {}
        for tab in TABS:
            if tab.name in self.skip:
                continue
            links, claims = self.links[tab.name], self.claims[tab.name]
            wanted = sorted((e for e in snap.of_kind(tab.kind) if _wanted(e)), key=lambda e: (e.name.lower(), e.id))
            updates, appends, deletes, finals = [], [], [], {}
            for e in wanted:
                values = _project(e, employers.get(e.id, ""))
                finals[e.id] = values
                row = links.get(e.id)
                if row is None:
                    appends.append({**{h: values[f] for f, h in tab.fields}, ID_HEADER: e.id})
                    continue
                cells = {h: {"was": row.raw[h], "value": values[f]} for f, h in tab.fields if _canon(f, row.raw[h]) != _canon(f, values[f])}
                self.counts["cells_out"] += len(cells)
                if row.note:
                    cells[NOTE_HEADER] = {"was": row.raw[NOTE_HEADER], "value": ""}
                if e.id in claims:
                    cells[ID_HEADER] = {"was": row.raw[ID_HEADER], "value": e.id}
                if cells:
                    updates.append({"at": _at(row, by_name=e.id in claims), "cells": cells})
            deletes = [_at(row, by_name=True) for row in self.drops[tab.name]]
            deletes += [_at(row) for eid, row in links.items() if eid not in finals]
            self.counts["rows_added"] += len(appends)
            self.counts["rows_removed"] += len(deletes)
            self.final[tab.name] = finals
            if updates or appends or deletes:
                out[tab.name] = {"keys": {"id": ID_HEADER, "name": "Name"}, "updates": updates, "appends": appends, "deletes": deletes}
        return out

    # Phase 3, once the sheet has taken the writes: this is what both sides now agree on.
    def remember(self) -> None:
        stamp = db.now()
        with db.connect() as c:
            for tab in TABS:
                if tab.name in self.skip:
                    continue
                c.execute("DELETE FROM crm_sheet_rows WHERE tab = ?", (tab.name,))
                c.executemany("INSERT INTO crm_sheet_rows (entity_id, tab, base, synced_at) VALUES (?, ?, ?, ?)",
                              [(eid, tab.name, json.dumps(values), stamp) for eid, values in self.final[tab.name].items()])


def _wire(tab: Tab) -> dict:
    return {"name": tab.name, "headers": tab.headers, "notes": HEADER_NOTES, "quiet": [ID_HEADER]}


def sync() -> dict:
    """One pass. Never raises for what's wrong with the sheet or the link: it records it for the Settings page."""
    global _synced_version
    if not configured():
        return {"skipped": "no link"}
    from .ingest import _apply_lock   # the same lock the inbox uses when it writes
    started = store.version()
    decision = capture.get_state("sheet").get("decision")
    run = None
    try:
        read = call({"action": "read", "tabs": [_wire(t) for t in TABS]})
        run = _Run(read, decision)
        with _apply_lock:
            run.take_in()
        writes = run.writes()
        if writes:
            call({"action": "write", "tabs": writes})
        run.remember()
        capture.set_state("sheet", error=None, link_problem=None, last_ok_at=db.now(), last_counts=dict(run.counts),
                          spreadsheet=read.get("spreadsheet"), held=run.held or None, decision=None)
    except SheetError as e:
        capture.set_state("sheet", error=str(e), link_problem=e.link_problem or None)
        log.warning("Shared sheet: %s", e)
    capture.set_state("sheet", last_run_at=db.now())
    # What this pass wrote into the records is already on the sheet, so it doesn't count as a change to send.
    _synced_version = store.version() if run and run.changed_app else started
    return dict(run.counts) if run else {}


def handle_sync(job: jobs.Job) -> None:
    job.stage("Syncing the shared sheet")
    sync()


def decide(choice: str) -> None:
    """Your answer to a held tab: take the sheet's values ("apply") or put The Lodge's back ("restore")."""
    if choice not in ("apply", "restore"):
        raise ValueError("Choose apply or restore")
    capture.set_state("sheet", decision=choice)
