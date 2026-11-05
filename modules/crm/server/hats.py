"""Hats: the parts of your life (a company, a committee, personal), and who and what belongs to each.

A hat is a lens on one book, not a separate book: the same person can be in two hats, and "All hats" shows everything.
It follows a Trailmix workspace when there is one, so a meeting's hat comes from where you filed it there.

Who's in a hat is worked out, not stored one by one:
    a meeting or document is in a hat when it was stamped with it (how "source") or you put it there (how "you")
    a person or organization is in a hat when they're on one of its meetings or documents, or you put them there
    an organization is also in a hat when someone in the hat works there now
    you can take anyone out (how "no"), and that stays, whatever comes in later

    crm_hats         a name, what you are in it, where, and the Trailmix workspace it follows
    crm_hat_links    hat, record, how
(the tables are created in store.py, with the module's other tables)
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field

from core.server import db, settings

from . import snapshot, store
from .kinds import EVENT_KINDS

ACTIVE = "active"     # as a filter: whichever hat you're wearing
ALL = "all"
NONE = "none"         # as a filter: what isn't in any hat yet
HOWS = ("you", "no")


class HatError(ValueError):
    pass


@dataclass
class _Members:
    people: set[str] = field(default_factory=set)
    orgs: set[str] = field(default_factory=set)
    events: set[str] = field(default_factory=set)


@contextmanager
def _use(conn: sqlite3.Connection | None):
    if conn is not None:
        yield conn
    else:
        with db.connect() as c:
            yield c


_cache: tuple[int, dict[str, _Members]] | None = None


def _members() -> dict[str, _Members]:
    global _cache
    version = store.version()
    if _cache is not None and _cache[0] == version:
        return _cache[1]
    snap = snapshot.load()
    ents = snap.entities
    me = snap.me.id if snap.me else None
    links = db.query("SELECT hat_id, entity_id, how FROM crm_hat_links")
    out: dict[str, _Members] = {r["id"]: _Members() for r in db.query("SELECT id FROM crm_hats")}
    removed: dict[str, set[str]] = {hat: set() for hat in out}

    def put(m: _Members, eid: str) -> None:
        e = ents.get(eid)
        if e is None or eid == me:
            return
        if e.kind == "person":
            m.people.add(eid)
        elif e.kind == "organization":
            m.orgs.add(eid)
        elif e.kind in EVENT_KINDS:
            m.events.add(eid)

    for r in links:
        if r["hat_id"] not in out:
            continue
        if r["how"] == "no":
            removed[r["hat_id"]].add(r["entity_id"])
        else:
            put(out[r["hat_id"]], r["entity_id"])
    for hat, m in out.items():
        for event in list(m.events):
            for edge in snap.by_entity.get(event, ()):
                put(m, edge.target_id if edge.source_id == event else edge.source_id)
        m.people -= removed[hat]
        for pid in m.people:
            for edge in snap.by_entity.get(pid, ()):
                if edge.kind == "works_at" and edge.source_id == pid and not edge.ended_at:
                    m.orgs.add(edge.target_id)
        m.orgs -= removed[hat]
        m.events -= removed[hat]
    _cache = (version, out)
    return out


def people_in(hat_id: str) -> set[str]:
    m = _members().get(hat_id)
    return m.people if m else set()


# ── Which hat you're wearing ──────────────────────────────────────────

def active() -> str | None:
    wanted = settings.section("crm").get("active_hat") or None
    return wanted if wanted and wanted in _members() else None


def set_active(hat_id: str | None) -> None:
    if hat_id and db.one("SELECT 1 AS x FROM crm_hats WHERE id = ?", (hat_id,)) is None:
        raise store.NotFound("That hat isn't on record")
    settings.update({"crm.active_hat": hat_id or ""})
    store._touch()   # every list on screen is wearing the old one


def _resolve(value: str | None) -> str | None:
    """A filter's value as a hat id, None for no filter, or NONE."""
    if not value or value == ALL:
        return None
    if value == ACTIVE:
        return active()
    return value


def _lens(value: str | None, part: str, every: set[str]) -> set[str] | None:
    hat = _resolve(value)
    if hat is None:
        return None
    members = _members()
    if hat == NONE:
        hatted: set[str] = set()
        for m in members.values():
            hatted |= getattr(m, part)
        return every - hatted
    m = members.get(hat)
    return getattr(m, part) if m else set()


def lens_people(value: str | None) -> set[str] | None:
    """Who a filter's value lets through; None when it doesn't filter at all."""
    snap = snapshot.load()
    me = snap.me.id if snap.me else None
    return _lens(value, "people", {e.id for e in snap.of_kind("person") if e.id != me})


def lens_orgs(value: str | None) -> set[str] | None:
    return _lens(value, "orgs", {e.id for e in snapshot.load().of_kind("organization")})


def lens_events(value: str | None) -> set[str] | None:
    return _lens(value, "events", {e.id for e in snapshot.load().of_kind(*EVENT_KINDS)})


# ── The hats themselves ───────────────────────────────────────────────

def _out(row: dict, members: dict[str, _Members]) -> dict:
    m = members.get(row["id"]) or _Members()
    org = snapshot.load().entities.get(row["org_id"]) if row["org_id"] else None
    return {"id": row["id"], "name": row["name"], "title": row["title"], "org_id": row["org_id"],
            "org_name": org.name if org else None, "workspace": row["workspace"],
            "people": len(m.people), "orgs": len(m.orgs), "events": len(m.events)}


def listing() -> dict:
    members = _members()
    rows = db.query("SELECT * FROM crm_hats ORDER BY position, created_at")
    unhatted = lens_people(NONE) or set()
    return {"hats": [_out(r, members) for r in rows], "active": active(), "unhatted": len(unhatted)}


def create(name: str, *, title: str | None = None, org_id: str | None = None, workspace: int | None = None,
           conn: sqlite3.Connection | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise HatError("A hat needs a name")
    hat_id = db.new_id()
    with _use(conn) as c:
        if c.execute("SELECT 1 FROM crm_hats WHERE lower(name) = ?", (name.lower(),)).fetchone():
            raise HatError(f"You already have a hat called {name}")
        position = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM crm_hats").fetchone()[0]
        c.execute("INSERT INTO crm_hats (id, name, title, org_id, workspace, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (hat_id, name[:80], title, org_id, workspace, position, db.now()))
    store._touch()
    return hat_id


def update(hat_id: str, **fields) -> None:
    cols = {k: fields[k] for k in ("name", "title", "org_id", "workspace") if k in fields}
    if "name" in cols:
        cols["name"] = (cols["name"] or "").strip()[:80]
        if not cols["name"]:
            raise HatError("A hat needs a name")
    if not cols:
        return
    with db.connect() as c:
        if not c.execute(f"UPDATE crm_hats SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), hat_id)).rowcount:
            raise store.NotFound("That hat isn't on record")
    store._touch()


def delete(hat_id: str) -> None:
    """The hat goes; everything in it stays in your book."""
    with db.connect() as c:
        if not c.execute("DELETE FROM crm_hats WHERE id = ?", (hat_id,)).rowcount:
            raise store.NotFound("That hat isn't on record")
    if (settings.section("crm").get("active_hat") or "") == hat_id:
        settings.update({"crm.active_hat": ""})
    store._touch()


def owner_in(hat_id: str | None) -> tuple[str | None, str | None]:
    """(what you are, the organization's id) in this hat, for reading what comes in under it."""
    row = db.one("SELECT title, org_id FROM crm_hats WHERE id = ?", (hat_id,)) if hat_id else None
    return (row["title"], row["org_id"]) if row else (None, None)


# ── What's in a hat ───────────────────────────────────────────────────

def stamp(event_id: str, hat_id: str, conn: sqlite3.Connection | None = None) -> None:
    """A meeting or document came from this hat. If it had come from another (moved in Trailmix), it's moved here."""
    with _use(conn) as c:
        c.execute("DELETE FROM crm_hat_links WHERE entity_id = ? AND how = 'source' AND hat_id != ?", (event_id, hat_id))
        c.execute("INSERT INTO crm_hat_links (hat_id, entity_id, how, created_at) VALUES (?, ?, 'source', ?) "
                  "ON CONFLICT(hat_id, entity_id) DO NOTHING", (hat_id, event_id, db.now()))


def source_hat(event_id: str) -> str | None:
    row = db.one("SELECT hat_id FROM crm_hat_links WHERE entity_id = ? AND how = 'source' LIMIT 1", (event_id,))
    return row["hat_id"] if row else None


def place(hat_id: str, ids: list[str], how: str | None, conn: sqlite3.Connection | None = None) -> int:
    """Put records in a hat ("you"), take them out ("no"), or leave it to what they're linked to (None)."""
    if how is not None and how not in HOWS:
        raise HatError("Put in, take out, or leave it")
    with _use(conn) as c:
        if not c.execute("SELECT 1 FROM crm_hats WHERE id = ?", (hat_id,)).fetchone():
            raise store.NotFound("That hat isn't on record")
        for eid in ids:
            if how is None:
                c.execute("DELETE FROM crm_hat_links WHERE hat_id = ? AND entity_id = ? AND how != 'source'", (hat_id, eid))
            else:
                c.execute("INSERT INTO crm_hat_links (hat_id, entity_id, how, created_at) VALUES (?, ?, ?, ?) "
                          "ON CONFLICT(hat_id, entity_id) DO UPDATE SET how = excluded.how", (hat_id, eid, how, db.now()))
    if conn is None:
        store._touch()
    return len(ids)


def of(entity_id: str) -> list[dict]:
    """Every hat, and how this record stands in it: in or not, and whether that's your own doing."""
    members = _members()
    e = snapshot.load().entities.get(entity_id)
    if e is None:
        raise store.NotFound("Entity not found")
    part = "people" if e.kind == "person" else "orgs" if e.kind == "organization" else "events"
    mine = {r["hat_id"]: r["how"] for r in db.query("SELECT hat_id, how FROM crm_hat_links WHERE entity_id = ?", (entity_id,))}
    return [{"id": r["id"], "name": r["name"], "in": entity_id in getattr(members.get(r["id"]) or _Members(), part),
             "how": mine.get(r["id"])} for r in db.query("SELECT id, name FROM crm_hats ORDER BY position, created_at")]


def from_workspaces(spaces: list[dict]) -> dict[int, str]:
    """A hat for every Trailmix workspace: one of the same name if you made it, a new one if not. {workspace: hat}."""
    made = False
    out: dict[int, str] = {}
    with db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT id, name, workspace FROM crm_hats")]
        for w in spaces:
            name = (w.get("name") or "").strip()
            if not name or w.get("id") is None:
                continue
            row = next((r for r in rows if r["workspace"] == w["id"]), None) or next(
                (r for r in rows if r["workspace"] is None and r["name"].lower() == name.lower()), None)
            if row is None:
                hat_id = create(name, workspace=w["id"], conn=c)
                rows.append({"id": hat_id, "name": name, "workspace": w["id"]})
                made = True
            else:
                hat_id = row["id"]
                if row["workspace"] is None:
                    c.execute("UPDATE crm_hats SET workspace = ? WHERE id = ?", (w["id"], hat_id))
                    row["workspace"] = w["id"]
                    made = True
            out[w["id"]] = hat_id
    if made:
        store._touch()
    return out
