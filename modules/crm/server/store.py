"""The CRM's tables (crm_*) and every query on them. Only this module touches these tables.

Graph model in plain tables: every node (person, organization, meeting, document, topic) is a row in
crm_entities with its kind-specific fields as JSON; every edge is a row in crm_relationships.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

from core.server import db, events
from core.server.tags import normalize_tags  # noqa: F401 - also used as store.normalize_tags

from .kinds import RELATIONSHIP_KINDS
from .model import Entity, Note, Relationship, iso, parse_date, parse_dt

MIGRATIONS = [
    """
    CREATE TABLE crm_entities (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        name        TEXT NOT NULL,
        summary     TEXT,
        attributes  TEXT NOT NULL DEFAULT '{}',      -- JSON: title, email, aliases, ...
        tags        TEXT NOT NULL DEFAULT '[]',      -- JSON array
        occurred_at TEXT,                            -- meetings and documents
        is_self     INTEGER NOT NULL DEFAULT 0,      -- the owner's own person record ("me")
        source      TEXT NOT NULL DEFAULT 'manual',  -- manual | ai | ingest | spreadsheet | linkedin | webhook | demo
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX crm_entities_kind ON crm_entities(kind);
    CREATE INDEX crm_entities_name ON crm_entities(name COLLATE NOCASE);
    CREATE INDEX crm_entities_occurred ON crm_entities(occurred_at);
    CREATE INDEX crm_entities_email ON crm_entities(lower(json_extract(attributes, '$.email')));
    CREATE UNIQUE INDEX crm_entities_single_self ON crm_entities(is_self) WHERE is_self = 1;

    CREATE TABLE crm_relationships (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        target_id   TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL,
        properties  TEXT NOT NULL DEFAULT '{}',
        strength    INTEGER NOT NULL DEFAULT 3 CHECK (strength BETWEEN 1 AND 5),
        started_at  TEXT,
        ended_at    TEXT,
        source      TEXT NOT NULL DEFAULT 'manual',
        evidence_id TEXT REFERENCES crm_entities(id) ON DELETE SET NULL,  -- the meeting or document it came from
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        UNIQUE (source_id, target_id, kind),
        CHECK (source_id <> target_id)
    );
    CREATE INDEX crm_relationships_source ON crm_relationships(source_id);
    CREATE INDEX crm_relationships_target ON crm_relationships(target_id);
    CREATE INDEX crm_relationships_kind ON crm_relationships(kind);

    CREATE TABLE crm_notes (
        id          TEXT PRIMARY KEY,
        entity_id   TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        body        TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        source      TEXT NOT NULL DEFAULT 'manual',
        evidence_id TEXT REFERENCES crm_entities(id) ON DELETE SET NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX crm_notes_entity ON crm_notes(entity_id);

    -- Everything that came in through the inbox: raw text, the AI's proposal, and what was applied.
    CREATE TABLE crm_inbox (
        id           TEXT PRIMARY KEY,
        source       TEXT NOT NULL,       -- manual_note | webhook | linkedin_csv | document | spreadsheet | meeting
        status       TEXT NOT NULL,       -- pending | processing | review | applied | failed | discarded | skipped
        content_hash TEXT,                -- so re-imports and "(1)" copies are skipped
        title        TEXT,
        occurred_at  TEXT,
        raw_text     TEXT,
        payload      TEXT NOT NULL DEFAULT '{}',
        proposal     TEXT,
        result       TEXT,
        error        TEXT,
        extractor    TEXT,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );
    CREATE INDEX crm_inbox_status ON crm_inbox(status);
    CREATE INDEX crm_inbox_hash ON crm_inbox(content_hash);

    CREATE VIRTUAL TABLE crm_fts USING fts5(id UNINDEXED, name, summary, aliases, details, tokenize='porter unicode61');
    """,
    # Saved views of the network: a name and the groups (wells) that were switched on.
    """
    CREATE TABLE crm_views (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        wells      TEXT NOT NULL DEFAULT '[]',   -- JSON array of group ids ("org:…", "topic:…", "tag:…")
        created_at TEXT NOT NULL
    );
    """,
    # What each automatic sync (Granola, calendars) did last and where it got to.
    """
    CREATE TABLE crm_sync (
        name       TEXT PRIMARY KEY,
        state      TEXT NOT NULL DEFAULT '{}',   -- JSON
        updated_at TEXT NOT NULL
    );
    """,
    # AI overviews of people and the questions asked about them (profiles.py).
    """
    CREATE TABLE crm_overviews (
        id          TEXT PRIMARY KEY,
        entity_id   TEXT NOT NULL UNIQUE REFERENCES crm_entities(id) ON DELETE CASCADE,
        body        TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        written_by  TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE crm_questions (
        id          TEXT PRIMARY KEY,
        entity_id   TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        question    TEXT NOT NULL,
        answer      TEXT,
        status      TEXT NOT NULL DEFAULT 'queued',   -- queued, done, error
        error       TEXT,
        written_by  TEXT,
        created_at  TEXT NOT NULL,
        answered_at TEXT
    );
    CREATE INDEX crm_questions_entity ON crm_questions(entity_id, created_at);
    """,
    # The shared Google Sheet (sheet_sync.py): for each record on it, the values both sides last agreed on.
    """
    CREATE TABLE crm_sheet_rows (
        entity_id TEXT PRIMARY KEY,           -- no foreign key: a deleted record's row is recognized, then taken off
        tab       TEXT NOT NULL,
        base      TEXT NOT NULL DEFAULT '{}', -- JSON: field -> value
        synced_at TEXT NOT NULL
    );
    """,
    # Records that are probably the same one twice (duplicates.py), and every merge with what's needed to undo it.
    """
    CREATE TABLE crm_duplicates (
        id         TEXT PRIMARY KEY,
        a_id       TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,   -- a_id < b_id
        b_id       TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL,
        score      REAL NOT NULL,
        reasons    TEXT NOT NULL DEFAULT '[]',   -- JSON: why they look like one record
        status     TEXT NOT NULL DEFAULT 'open', -- open | not_same
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (a_id, b_id)
    );
    CREATE INDEX crm_duplicates_status ON crm_duplicates(status);
    CREATE TABLE crm_merges (
        id         TEXT PRIMARY KEY,
        source_id  TEXT NOT NULL,   -- the record folded in; no foreign key, it's gone until the merge is undone
        target_id  TEXT NOT NULL,   -- the record kept
        kind       TEXT NOT NULL,
        name       TEXT NOT NULL,   -- the folded-in record's name, to show
        snapshot   TEXT NOT NULL,   -- JSON: everything needed to undo it
        created_at TEXT NOT NULL,
        undone_at  TEXT
    );
    CREATE INDEX crm_merges_source ON crm_merges(source_id);
    CREATE INDEX crm_merges_target ON crm_merges(target_id);
    """,
    # Research The Lodge runs itself with Gemini (gemini_research.py): one row per person per run.
    """
    CREATE TABLE crm_research_runs (
        id          TEXT PRIMARY KEY,
        entity_id   TEXT NOT NULL REFERENCES crm_entities(id) ON DELETE CASCADE,
        level       TEXT NOT NULL,                  -- quick | better | best
        batch       INTEGER NOT NULL DEFAULT 0,     -- through Google's Batch API
        status      TEXT NOT NULL,                  -- queued | running | waiting | done | failed | cancelled
        stage       TEXT NOT NULL DEFAULT 'ask',    -- ask | check | more | write | done
        batch_name  TEXT,                           -- Google's batch in flight ("batches/…")
        findings    TEXT NOT NULL DEFAULT '[]',     -- JSON: each question, the answer and its sources
        usage       TEXT NOT NULL DEFAULT '{}',     -- JSON: model -> tokens in, out, cached, calls
        searches    INTEGER NOT NULL DEFAULT 0,
        cost        REAL NOT NULL DEFAULT 0,        -- dollars, from what Google reported
        inbox_id    TEXT,                           -- the report, waiting in the Inbox
        error       TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX crm_research_runs_entity ON crm_research_runs(entity_id, created_at);
    CREATE INDEX crm_research_runs_status ON crm_research_runs(status);
    """,
    # Network presets (presets.py): the ones you saved, and the lists you asked the AI to write.
    """
    CREATE TABLE crm_presets (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        about       TEXT NOT NULL DEFAULT '',
        spec        TEXT NOT NULL,                  -- JSON: {"kind": "at" | "intro" | … | "rule", …what it's about}
        source      TEXT NOT NULL DEFAULT 'you',    -- you | ai
        created_at  TEXT NOT NULL
    );
    CREATE TABLE crm_preset_asks (
        id          TEXT PRIMARY KEY,
        request     TEXT NOT NULL DEFAULT '',       -- what you asked for; empty = "suggest some"
        status      TEXT NOT NULL DEFAULT 'queued', -- queued | done | error
        ideas       TEXT NOT NULL DEFAULT '[]',     -- JSON: the presets the AI wrote, each with how many it finds
        error       TEXT,
        written_by  TEXT,
        created_at  TEXT NOT NULL,
        answered_at TEXT
    );
    """,
]

_version = 0
_lock = threading.Lock()


def version() -> int:
    """Moves on every write, so caches built from the tables know when to rebuild."""
    return _version


def _now() -> str:
    return iso(datetime.now(timezone.utc))  # type: ignore[arg-type]


def _touch() -> None:
    global _version
    with _lock:
        _version += 1
    events.publish("crm.changed", {})


class NotFound(LookupError):
    pass


class EdgeExists(ValueError):
    pass


class MergeError(ValueError):
    pass


@contextmanager
def _use(conn: sqlite3.Connection | None):
    if conn is not None:
        yield conn
    else:
        with db.connect() as c:
            yield c


# ── Conversions ───────────────────────────────────────────────────────

def _entity(row: sqlite3.Row | dict) -> Entity:
    return Entity(
        id=row["id"], kind=row["kind"], name=row["name"], summary=row["summary"],
        attributes=json.loads(row["attributes"] or "{}"), tags=json.loads(row["tags"] or "[]"),
        occurred_at=parse_dt(row["occurred_at"]), is_self=bool(row["is_self"]), source=row["source"],
        created_at=parse_dt(row["created_at"]), updated_at=parse_dt(row["updated_at"]),
    )


def _edge(row: sqlite3.Row | dict) -> Relationship:
    return Relationship(
        id=row["id"], source_id=row["source_id"], target_id=row["target_id"], kind=row["kind"],
        properties=json.loads(row["properties"]) if row["properties"] not in (None, "", "{}") else {}, strength=row["strength"],
        started_at=parse_date(row["started_at"]), ended_at=parse_date(row["ended_at"]), source=row["source"],
        evidence_id=row["evidence_id"], created_at=parse_dt(row["created_at"]),
    )


def _note(row: sqlite3.Row | dict) -> Note:
    return Note(id=row["id"], entity_id=row["entity_id"], body=row["body"], occurred_at=parse_dt(row["occurred_at"]),
                source=row["source"], evidence_id=row["evidence_id"], created_at=parse_dt(row["created_at"]))


def _day(value: date | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)[:10]


def _when(value: datetime | str | None) -> str | None:
    return iso(value) if isinstance(value, datetime) else (iso(parse_dt(value)) if value else None)


# ── Search index ──────────────────────────────────────────────────────

def _reindex(conn: sqlite3.Connection, e: Entity) -> None:
    a = e.attributes or {}
    details = " ".join(
        str(a[k]) for k in ("title", "email", "location", "industry", "website", "doc_type") if a.get(k)
    ) + " " + " ".join(e.tags or [])
    conn.execute("DELETE FROM crm_fts WHERE id = ?", (e.id,))
    conn.execute(
        "INSERT INTO crm_fts (id, name, summary, aliases, details) VALUES (?, ?, ?, ?, ?)",
        (e.id, e.name, e.summary or "", " ".join(a.get("aliases") or []), details),
    )


# ── Entities ──────────────────────────────────────────────────────────

def create_entity(kind: str, name: str, *, summary: str | None = None, attributes: dict | None = None,
                  tags: list[str] | None = None, occurred_at: datetime | str | None = None, source: str = "manual",
                  is_self: bool = False, conn: sqlite3.Connection | None = None) -> Entity:
    stamp = _now()
    e_id = db.new_id()
    with _use(conn) as c:
        if is_self:
            c.execute("UPDATE crm_entities SET is_self = 0 WHERE is_self = 1")
        c.execute(
            "INSERT INTO crm_entities (id, kind, name, summary, attributes, tags, occurred_at, is_self, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e_id, kind, name.strip()[:300], summary, json.dumps(attributes or {}),
             json.dumps(normalize_tags(tags or [])), _when(occurred_at), int(is_self), source, stamp, stamp),
        )
        entity = _entity(c.execute("SELECT * FROM crm_entities WHERE id = ?", (e_id,)).fetchone())
        _reindex(c, entity)
    _touch()
    return entity


def get_entity(entity_id: str, conn: sqlite3.Connection | None = None) -> Entity | None:
    with _use(conn) as c:
        row = c.execute("SELECT * FROM crm_entities WHERE id = ?", (entity_id,)).fetchone()
    return _entity(row) if row else None


def require_entity(entity_id: str) -> Entity:
    e = get_entity(entity_id)
    if e is None:
        raise NotFound("Entity not found")
    return e


def all_entities(kind: str | None = None, conn: sqlite3.Connection | None = None) -> list[Entity]:
    with _use(conn) as c:
        if kind:
            rows = c.execute("SELECT * FROM crm_entities WHERE kind = ?", (kind,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM crm_entities").fetchall()
    return [_entity(r) for r in rows]


def update_entity(entity_id: str, *, conn: sqlite3.Connection | None = None, **fields: Any) -> Entity:
    """Fields: name, summary, attributes, tags, occurred_at, source."""
    cols: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "name":
            cols["name"] = value.strip()[:300]
        elif key == "attributes":
            cols["attributes"] = json.dumps(value)
        elif key == "tags":
            cols["tags"] = json.dumps(normalize_tags(value))
        elif key == "occurred_at":
            cols["occurred_at"] = _when(value)
        elif key in ("summary", "source"):
            cols[key] = value
        else:
            raise ValueError(f"Can't update {key}")
    cols["updated_at"] = _now()
    with _use(conn) as c:
        changed = c.execute(
            f"UPDATE crm_entities SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), entity_id)
        ).rowcount
        if not changed:
            raise NotFound("Entity not found")
        entity = _entity(c.execute("SELECT * FROM crm_entities WHERE id = ?", (entity_id,)).fetchone())
        _reindex(c, entity)
    _touch()
    return entity


def delete_entity(entity_id: str) -> None:
    with db.connect() as c:
        if not c.execute("DELETE FROM crm_entities WHERE id = ?", (entity_id,)).rowcount:
            raise NotFound("Entity not found")
        c.execute("DELETE FROM crm_fts WHERE id = ?", (entity_id,))
    _touch()


def get_me() -> Entity | None:
    row = db.one("SELECT * FROM crm_entities WHERE is_self = 1")
    return _entity(row) if row else None


def set_me(entity_id: str | None = None, name: str | None = None) -> Entity:
    """Mark an existing person as "me", or create one from a name."""
    with db.connect() as c:
        if entity_id:
            row = c.execute("SELECT * FROM crm_entities WHERE id = ? AND kind = 'person'", (entity_id,)).fetchone()
            if row is None:
                raise NotFound("Person not found")
            c.execute("UPDATE crm_entities SET is_self = 0 WHERE is_self = 1")
            c.execute("UPDATE crm_entities SET is_self = 1, updated_at = ? WHERE id = ?", (_now(), entity_id))
            me_id = entity_id
        else:
            c.execute("UPDATE crm_entities SET is_self = 0 WHERE is_self = 1")
            me_id = create_entity("person", name or "Me", is_self=True, conn=c).id
    _touch()
    return require_entity(me_id)


def list_entities(kind: str | None = None, q: str | None = None, tag: str | None = None, sort: str = "name",
                  limit: int = 50, offset: int = 0) -> tuple[list[Entity], int]:
    where, args = [], []
    if kind:
        kinds = kind.split(",")
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if tag:
        where.append("EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)")
        args.append(tag.lower())
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(name LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR attributes LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = {
        "name": "name COLLATE NOCASE", "recent": "created_at DESC", "updated": "updated_at DESC",
        "occurred": "occurred_at IS NULL, occurred_at DESC",
    }[sort]
    total = db.one(f"SELECT count(*) AS n FROM crm_entities {clause}", args)["n"]
    rows = db.query(f"SELECT * FROM crm_entities {clause} ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, offset])
    return [_entity(r) for r in rows], total


# ── Relationships ─────────────────────────────────────────────────────

def find_edge(source_id: str, target_id: str, kind: str, conn: sqlite3.Connection | None = None) -> Relationship | None:
    rel = RELATIONSHIP_KINDS.get(kind)
    with _use(conn) as c:
        row = c.execute(
            "SELECT * FROM crm_relationships WHERE source_id = ? AND target_id = ? AND kind = ?",
            (source_id, target_id, kind),
        ).fetchone()
        if row is None and rel and rel.symmetric:
            row = c.execute(
                "SELECT * FROM crm_relationships WHERE source_id = ? AND target_id = ? AND kind = ?",
                (target_id, source_id, kind),
            ).fetchone()
    return _edge(row) if row else None


_EDGE_COLS = ("strength", "started_at", "ended_at", "source", "evidence_id")


def create_edge(source_id: str, target_id: str, kind: str, *, properties: dict | None = None,
                conn: sqlite3.Connection | None = None, **fields: Any) -> Relationship:
    """Raises EdgeExists when the edge (either direction, for symmetric kinds) is already there."""
    with _use(conn) as c:
        if find_edge(source_id, target_id, kind, c):
            raise EdgeExists("That relationship already exists")
        stamp = _now()
        e_id = db.new_id()
        vals = {k: fields[k] for k in _EDGE_COLS if fields.get(k) is not None}
        vals.setdefault("strength", 3)
        vals.setdefault("source", "manual")
        for k in ("started_at", "ended_at"):
            if k in vals:
                vals[k] = _day(vals[k])
        cols = ["id", "source_id", "target_id", "kind", "properties", "created_at", "updated_at", *vals]
        c.execute(
            f"INSERT INTO crm_relationships ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            (e_id, source_id, target_id, kind, json.dumps(properties or {}), stamp, stamp, *vals.values()),
        )
        edge = _edge(c.execute("SELECT * FROM crm_relationships WHERE id = ?", (e_id,)).fetchone())
    _touch()
    return edge


def upsert_edge(source_id: str, target_id: str, kind: str, *, properties: dict | None = None,
                conn: sqlite3.Connection | None = None, **fields: Any) -> tuple[Relationship, bool]:
    """Create the edge, or fill gaps on the existing one. Returns (edge, created).

    Existing values win: an import never overwrites what the user curated."""
    with _use(conn) as c:
        existing = find_edge(source_id, target_id, kind, c)
        if existing is None:
            return create_edge(source_id, target_id, kind, properties=properties, conn=c, **fields), True
        updates: dict[str, Any] = {}
        if properties:
            updates["properties"] = json.dumps({**properties, **(existing.properties or {})})
        for key in ("started_at", "ended_at", "evidence_id"):
            if fields.get(key) is not None and getattr(existing, key) is None:
                updates[key] = _day(fields[key]) if key != "evidence_id" else fields[key]
        if updates:
            updates["updated_at"] = _now()
            c.execute(f"UPDATE crm_relationships SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
                      (*updates.values(), existing.id))
            existing = _edge(c.execute("SELECT * FROM crm_relationships WHERE id = ?", (existing.id,)).fetchone())
    if updates:
        _touch()
    return existing, False


def get_edge(edge_id: str) -> Relationship | None:
    row = db.one("SELECT * FROM crm_relationships WHERE id = ?", (edge_id,))
    return _edge(row) if row else None


def update_edge(edge_id: str, **fields: Any) -> Relationship:
    cols: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "properties":
            cols[key] = json.dumps(value)
        elif key in ("started_at", "ended_at"):
            cols[key] = _day(value)
        elif key == "strength":
            cols[key] = value
        else:
            raise ValueError(f"Can't update {key}")
    cols["updated_at"] = _now()
    with db.connect() as c:
        if not c.execute(f"UPDATE crm_relationships SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                         (*cols.values(), edge_id)).rowcount:
            raise NotFound("Relationship not found")
        edge = _edge(c.execute("SELECT * FROM crm_relationships WHERE id = ?", (edge_id,)).fetchone())
    _touch()
    return edge


def delete_edge(edge_id: str) -> None:
    if not db.execute("DELETE FROM crm_relationships WHERE id = ?", (edge_id,)):
        raise NotFound("Relationship not found")
    _touch()


def all_edges(conn: sqlite3.Connection | None = None) -> list[Relationship]:
    with _use(conn) as c:
        return [_edge(r) for r in c.execute("SELECT * FROM crm_relationships").fetchall()]


def edges_of(entity_id: str) -> list[Relationship]:
    rows = db.query(
        "SELECT * FROM crm_relationships WHERE source_id = ? OR target_id = ? ORDER BY created_at",
        (entity_id, entity_id),
    )
    return [_edge(r) for r in rows]


# ── Notes ─────────────────────────────────────────────────────────────

def add_note(entity_id: str, body: str, *, occurred_at: datetime | str | None = None, source: str = "manual",
             evidence_id: str | None = None, conn: sqlite3.Connection | None = None) -> Note:
    n_id, stamp = db.new_id(), _now()
    with _use(conn) as c:
        c.execute(
            "INSERT INTO crm_notes (id, entity_id, body, occurred_at, source, evidence_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (n_id, entity_id, body.strip(), _when(occurred_at) or stamp, source, evidence_id, stamp),
        )
        note = _note(c.execute("SELECT * FROM crm_notes WHERE id = ?", (n_id,)).fetchone())
    _touch()
    return note


def notes_of(entity_id: str) -> list[Note]:
    return [_note(r) for r in db.query(
        "SELECT * FROM crm_notes WHERE entity_id = ? ORDER BY occurred_at DESC", (entity_id,))]


def all_notes(conn: sqlite3.Connection | None = None) -> list[Note]:
    with _use(conn) as c:
        return [_note(r) for r in c.execute("SELECT * FROM crm_notes").fetchall()]


def delete_note(note_id: str) -> None:
    if not db.execute("DELETE FROM crm_notes WHERE id = ?", (note_id,)):
        raise NotFound("Note not found")
    _touch()


# ── Merge ─────────────────────────────────────────────────────────────

def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def merge_entities(source_id: str, target_id: str) -> Entity:
    """Fold `source` into `target`. Target values win; the source's name is kept as an alias so future notes match
    the survivor. Nothing is lost: the source record, every edge as it was, and what moved where are kept in
    crm_merges, so the merge can be undone (unmerge) and links to the old record still lead somewhere (describe)."""
    if source_id == target_id:
        raise MergeError("Cannot merge a record into itself")
    with db.connect() as c:
        src = get_entity(source_id, c)
        tgt = get_entity(target_id, c)
        if src is None or tgt is None:
            raise NotFound("Entity not found")
        if src.kind != tgt.kind:
            raise MergeError(f"Cannot merge a {src.kind} into a {tgt.kind}")
        snap: dict = {
            "source": _row(c.execute("SELECT * FROM crm_entities WHERE id = ?", (source_id,)).fetchone()),
            "target_before": {"attributes": tgt.attributes, "tags": tgt.tags, "summary": tgt.summary,
                              "occurred_at": _when(tgt.occurred_at), "is_self": tgt.is_self},
            "edges": [],
            "notes": [r["id"] for r in c.execute("SELECT id FROM crm_notes WHERE entity_id = ?", (source_id,))],
            "note_evidence": [r["id"] for r in c.execute("SELECT id FROM crm_notes WHERE evidence_id = ?", (source_id,))],
            "edge_evidence": [r["id"] for r in c.execute("SELECT id FROM crm_relationships WHERE evidence_id = ?", (source_id,))],
            "questions": [r["id"] for r in c.execute("SELECT id FROM crm_questions WHERE entity_id = ?", (source_id,))],
            "overview": _row(c.execute("SELECT * FROM crm_overviews WHERE entity_id = ?", (source_id,)).fetchone()),
        }

        for row in c.execute("SELECT * FROM crm_relationships WHERE source_id = ? OR target_id = ?", (source_id, source_id)).fetchall():
            edge = _edge(row)
            kept = {"row": dict(row)}
            new_s = target_id if edge.source_id == source_id else edge.source_id
            new_t = target_id if edge.target_id == source_id else edge.target_id
            if new_s == new_t:
                c.execute("DELETE FROM crm_relationships WHERE id = ?", (edge.id,))
                kept["fate"] = "dropped"
            elif (dup := find_edge(new_s, new_t, edge.kind, c)) is not None and dup.id != edge.id:
                kept.update(fate="folded", into=dup.id, into_before={"strength": dup.strength, "properties": dup.properties})
                props = {**(edge.properties or {}), **(dup.properties or {})}
                c.execute("UPDATE crm_relationships SET strength = ?, properties = ?, updated_at = ? WHERE id = ?",
                          (max(dup.strength, edge.strength), json.dumps(props), _now(), dup.id))
                c.execute("DELETE FROM crm_relationships WHERE id = ?", (edge.id,))
            else:
                c.execute("UPDATE crm_relationships SET source_id = ?, target_id = ?, updated_at = ? WHERE id = ?",
                          (new_s, new_t, _now(), edge.id))
                kept["fate"] = "moved"
            snap["edges"].append(kept)

        c.execute("UPDATE crm_notes SET entity_id = ? WHERE entity_id = ?", (target_id, source_id))
        c.execute("UPDATE crm_notes SET evidence_id = ? WHERE evidence_id = ?", (target_id, source_id))
        c.execute("UPDATE crm_relationships SET evidence_id = ? WHERE evidence_id = ?", (target_id, source_id))
        c.execute("UPDATE crm_questions SET entity_id = ? WHERE entity_id = ?", (target_id, source_id))

        attrs = {**src.attributes, **tgt.attributes}
        aliases = set(attrs.get("aliases") or []) | set(src.attributes.get("aliases") or [])
        if src.name.strip().lower() != tgt.name.strip().lower():
            aliases.add(src.name)
        if aliases:
            attrs["aliases"] = sorted(aliases)
        tags = list(dict.fromkeys([*tgt.tags, *src.tags]))
        c.execute("DELETE FROM crm_entities WHERE id = ?", (source_id,))  # frees the single "me" slot too
        c.execute("DELETE FROM crm_fts WHERE id = ?", (source_id,))
        if src.is_self:
            c.execute("UPDATE crm_entities SET is_self = 1 WHERE id = ?", (target_id,))
        merged = update_entity(
            target_id, attributes=attrs, tags=tags, summary=tgt.summary or src.summary,
            occurred_at=tgt.occurred_at or src.occurred_at, conn=c,
        )
        snap["target_after"] = {"attributes": merged.attributes, "tags": merged.tags, "summary": merged.summary,
                                "occurred_at": _when(merged.occurred_at)}
        c.execute("INSERT INTO crm_merges (id, source_id, target_id, kind, name, snapshot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (db.new_id(), source_id, target_id, src.kind, src.name, json.dumps(snap, default=str), _now()))
    _touch()
    return merged


def merges_into(entity_id: str) -> list[dict]:
    """Merges into this record that can still be undone, newest first."""
    return [{k: r[k] for k in ("id", "source_id", "target_id", "kind", "name", "created_at")} for r in db.query(
        "SELECT * FROM crm_merges WHERE target_id = ? AND undone_at IS NULL ORDER BY created_at DESC", (entity_id,))]


def merged_into(entity_id: str) -> str | None:
    """Where a record merged away lives now, following merges of merges. None if it wasn't merged."""
    current, seen = entity_id, set()
    while current not in seen:
        seen.add(current)
        row = db.one("SELECT target_id FROM crm_merges WHERE source_id = ? AND undone_at IS NULL ORDER BY created_at DESC LIMIT 1",
                     (current,))
        if row is None:
            return None if current == entity_id else current
        current = row["target_id"]
    return None


def unmerge(merge_id: str) -> Entity:
    """Undo a merge: the record comes back with its own id, its edges, notes and questions return to it, and what the
    merge added to the kept record is taken off again. Anything added to either since stays where it is now."""
    m = db.one("SELECT * FROM crm_merges WHERE id = ?", (merge_id,))
    if m is None:
        raise NotFound("That merge isn't on record")
    if m["undone_at"]:
        raise MergeError("That merge was already undone")
    snap = json.loads(m["snapshot"])
    src, tid, sid = snap["source"], m["target_id"], m["source_id"]
    with db.connect() as c:
        tgt = get_entity(tid, c)
        if tgt is None:
            raise MergeError("The record it was merged into is gone, so it can't be split again")
        if c.execute("SELECT 1 FROM crm_entities WHERE id = ?", (sid,)).fetchone():
            raise MergeError(f"{m['name']} is already back")
        if src["is_self"]:
            c.execute("UPDATE crm_entities SET is_self = 0 WHERE id = ?", (tid,))
        cols = list(src)
        c.execute(f"INSERT INTO crm_entities ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [src[k] for k in cols])
        _reindex(c, _entity(src))

        exists = lambda eid: eid == sid or c.execute("SELECT 1 FROM crm_entities WHERE id = ?", (eid,)).fetchone() is not None  # noqa: E731
        for kept in snap["edges"]:
            row = kept["row"]
            if not (exists(row["source_id"]) and exists(row["target_id"])):
                continue   # the record at the other end was deleted since
            if kept["fate"] == "moved":
                c.execute("UPDATE OR IGNORE crm_relationships SET source_id = ?, target_id = ? WHERE id = ?",
                          (row["source_id"], row["target_id"], row["id"]))
            else:
                cols = list(row)
                c.execute(f"INSERT OR IGNORE INTO crm_relationships ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                          [row[k] for k in cols])
                if kept["fate"] == "folded":
                    before = kept["into_before"]
                    c.execute("UPDATE crm_relationships SET strength = ?, properties = ? WHERE id = ?",
                              (before["strength"], json.dumps(before["properties"] or {}), kept["into"]))

        def back(table: str, column: str, ids: list[str]) -> None:
            for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
                c.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ? AND id IN ({', '.join('?' for _ in chunk)})",
                          (sid, tid, *chunk))

        back("crm_notes", "entity_id", snap["notes"])
        back("crm_notes", "evidence_id", snap["note_evidence"])
        back("crm_relationships", "evidence_id", snap["edge_evidence"])
        back("crm_questions", "entity_id", snap["questions"])
        if (ov := snap.get("overview")) and not c.execute("SELECT 1 FROM crm_overviews WHERE entity_id = ?", (sid,)).fetchone():
            cols = list(ov)
            c.execute(f"INSERT OR IGNORE INTO crm_overviews ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [ov[k] for k in cols])

        # Take off the kept record only what the merge put there and is still as the merge left it.
        before, after = snap["target_before"], snap.get("target_after") or {}
        attrs = dict(tgt.attributes or {})
        for key, value in (after.get("attributes") or {}).items():
            if key == "aliases":
                continue
            if key not in before["attributes"] and attrs.get(key) == value:
                attrs.pop(key)
        added = set((after.get("attributes") or {}).get("aliases") or []) - set(before["attributes"].get("aliases") or [])
        aliases = [a for a in attrs.get("aliases") or [] if a not in added]
        if aliases:
            attrs["aliases"] = aliases
        else:
            attrs.pop("aliases", None)
        added_tags = set(after.get("tags") or []) - set(before["tags"] or [])
        fields: dict = {"attributes": attrs, "tags": [t for t in tgt.tags if t not in added_tags]}
        if not before["summary"] and tgt.summary and tgt.summary == after.get("summary"):
            fields["summary"] = None
        if not before["occurred_at"] and _when(tgt.occurred_at) == after.get("occurred_at"):
            fields["occurred_at"] = None
        update_entity(tid, conn=c, **fields)
        c.execute("UPDATE crm_merges SET undone_at = ? WHERE id = ?", (_now(), merge_id))
        restored = get_entity(sid, c)
    _touch()
    return restored  # type: ignore[return-value]


# ── For the host: search and links ────────────────────────────────────

def describe(entity_id: str) -> dict | None:
    """A link's title and address. A record merged into another leads to the one it's part of now."""
    row = db.one("SELECT name FROM crm_entities WHERE id = ?", (entity_id,))
    if row is None and (now := merged_into(entity_id)):
        row, entity_id = db.one("SELECT name FROM crm_entities WHERE id = ?", (now,)), now
    return {"title": row["name"], "href": f"#/crm/e/{entity_id}"} if row else None


def search(q: str, limit: int) -> list[dict]:
    words = " ".join(f'"{w}"*' for w in q.replace('"', " ").split())
    if not words:
        return []
    rows = db.query(
        "SELECT f.id, e.name, e.kind, snippet(crm_fts, -1, '', '', '…', 10) AS snippet "
        "FROM crm_fts f JOIN crm_entities e ON e.id = f.id WHERE crm_fts MATCH ? ORDER BY bm25(crm_fts, 0.0, 10.0, 1.0, 5.0, 2.0) LIMIT ?",
        (words, limit),
    )
    return [{"id": r["id"], "title": r["name"], "snippet": r["kind"].capitalize()} for r in rows]
