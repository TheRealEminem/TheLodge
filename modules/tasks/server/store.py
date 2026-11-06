"""The tasks module's tables, and the helpers every part of it shares: checking values, the search index, and
saying that something changed.

Since step 2 the module holds the whole of "work" (Traverse PLAN.md chunk 2, the Lodge blueprint §3-4): projects with
milestones, work items (the to-dos that came before, grown up) with subtasks and blockers, and updates. The functions
live in items.py and projects.py; hooks.py is what the host calls (contracts, describe, search, export).

Step 2 is the Lodge guide's schema/tasks-v2-projects.sql, with priorities on Plane's five-level scale (D7). Step 3 adds
tasks_synced: items that are also kept somewhere else (synced.py). Step 4 adds tasks_drafts: what the AI drafted for you
to look over, a project's status update or a task's subtasks (drafts.py). Once a step has shipped, never edit it: later
changes are step 5, 6… and are made only in TrailmixFamily (the one-lineage rule).
"""
import json
import re
from datetime import date

from core.server import db, events
from core.server.tags import normalize_tags

from . import vocab

MIGRATIONS = [
    """
    CREATE TABLE tasks_items (
        id          TEXT PRIMARY KEY,
        text        TEXT NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        source_ref  TEXT,                 -- where it came from ("notes:<id>"), if anywhere
        created_at  TEXT NOT NULL
    );
    CREATE INDEX tasks_items_source ON tasks_items(source_ref);
    """,
    """
    CREATE TABLE tasks_projects (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        summary     TEXT,                              -- one line: what done looks like
        brief       TEXT NOT NULL DEFAULT '',          -- the longer write-up, markdown
        status      TEXT NOT NULL DEFAULT 'active',    -- planned | active | paused | done | dropped
        health      TEXT,                              -- on_track | at_risk | off_track; NULL = not judged yet
        start_on    TEXT,                              -- YYYY-MM-DD
        due_on      TEXT,                              -- YYYY-MM-DD
        owner_ref   TEXT,                              -- "core:me", "crm:<person id>"…; NULL = nobody yet
        owner_name  TEXT,
        attributes  TEXT NOT NULL DEFAULT '{}',        -- JSON: anything not worth a column yet
        tags        TEXT NOT NULL DEFAULT '[]',        -- JSON array, normalized like People's ("client-work")
        sort        REAL NOT NULL DEFAULT 0,           -- your order in lists (fractional: insert between = average)
        source      TEXT NOT NULL DEFAULT 'manual',    -- manual | ai | import | template
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        archived_at TEXT                               -- set = out of the lists, kept for history and search
    );
    CREATE INDEX tasks_projects_status ON tasks_projects(status, archived_at);

    CREATE TABLE tasks_milestones (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES tasks_projects(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        due_on      TEXT,                              -- YYYY-MM-DD
        done_at     TEXT,
        sort        REAL NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX tasks_milestones_project ON tasks_milestones(project_id, sort);

    ALTER TABLE tasks_items ADD COLUMN project_id    TEXT REFERENCES tasks_projects(id) ON DELETE SET NULL;
    ALTER TABLE tasks_items ADD COLUMN milestone_id  TEXT REFERENCES tasks_milestones(id) ON DELETE SET NULL;
    ALTER TABLE tasks_items ADD COLUMN parent_id     TEXT REFERENCES tasks_items(id) ON DELETE CASCADE;  -- subtasks
    ALTER TABLE tasks_items ADD COLUMN status        TEXT NOT NULL DEFAULT 'todo';   -- todo | doing | waiting | done | dropped
    ALTER TABLE tasks_items ADD COLUMN notes         TEXT NOT NULL DEFAULT '';       -- markdown
    ALTER TABLE tasks_items ADD COLUMN priority      INTEGER NOT NULL DEFAULT 0;     -- 0 none, 1 low, 2 medium, 3 high, 4 urgent (Plane's scale)
    ALTER TABLE tasks_items ADD COLUMN start_on      TEXT;                           -- YYYY-MM-DD
    ALTER TABLE tasks_items ADD COLUMN due_on        TEXT;                           -- YYYY-MM-DD
    ALTER TABLE tasks_items ADD COLUMN assignee_ref  TEXT;                           -- "core:me", "crm:<person id>"; NULL = nobody
    ALTER TABLE tasks_items ADD COLUMN assignee_name TEXT;
    ALTER TABLE tasks_items ADD COLUMN estimate_min  INTEGER;
    ALTER TABLE tasks_items ADD COLUMN sort          REAL NOT NULL DEFAULT 0;
    ALTER TABLE tasks_items ADD COLUMN attributes    TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE tasks_items ADD COLUMN tags          TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE tasks_items ADD COLUMN source        TEXT NOT NULL DEFAULT 'manual'; -- manual | action-item | ai | import
    ALTER TABLE tasks_items ADD COLUMN completed_at  TEXT;
    ALTER TABLE tasks_items ADD COLUMN updated_at    TEXT;
    UPDATE tasks_items SET status       = CASE WHEN done THEN 'done' ELSE 'todo' END,
                           completed_at = CASE WHEN done THEN created_at END,
                           source       = CASE WHEN source_ref IS NULL THEN 'manual' ELSE 'action-item' END,
                           updated_at   = created_at;
    CREATE INDEX tasks_items_project  ON tasks_items(project_id, status, sort);
    CREATE INDEX tasks_items_assignee ON tasks_items(assignee_ref, status);
    CREATE INDEX tasks_items_due      ON tasks_items(due_on) WHERE due_on IS NOT NULL;
    CREATE INDEX tasks_items_parent   ON tasks_items(parent_id);

    CREATE TABLE tasks_blockers (
        item_id     TEXT NOT NULL REFERENCES tasks_items(id) ON DELETE CASCADE,
        blocked_by  TEXT NOT NULL REFERENCES tasks_items(id) ON DELETE CASCADE,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (item_id, blocked_by),
        CHECK (item_id <> blocked_by)
    );
    CREATE INDEX tasks_blockers_by ON tasks_blockers(blocked_by);

    CREATE TABLE tasks_updates (
        id          TEXT PRIMARY KEY,
        project_id  TEXT REFERENCES tasks_projects(id) ON DELETE CASCADE,
        item_id     TEXT REFERENCES tasks_items(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL DEFAULT 'comment',   -- comment | status | summary
        body        TEXT NOT NULL,                     -- markdown
        health      TEXT,                              -- kind = status: the health it reported
        author_ref  TEXT,                              -- "core:me", "crm:<person id>"; NULL when AI wrote it
        author_name TEXT,
        written_by  TEXT,                              -- the AI provider that wrote it, shown next to it
        created_at  TEXT NOT NULL,
        CHECK ((project_id IS NULL) <> (item_id IS NULL))
    );
    CREATE INDEX tasks_updates_project ON tasks_updates(project_id, created_at);
    CREATE INDEX tasks_updates_item    ON tasks_updates(item_id, created_at);

    CREATE VIRTUAL TABLE tasks_fts USING fts5(id UNINDEXED, kind UNINDEXED, title, body, tokenize='porter unicode61');
    INSERT INTO tasks_fts (id, kind, title, body) SELECT id, 'item', text, notes FROM tasks_items;
    """,
    """
    CREATE TABLE tasks_synced (
        item_id     TEXT PRIMARY KEY REFERENCES tasks_items(id) ON DELETE CASCADE,
        ref         TEXT NOT NULL UNIQUE,              -- the same work elsewhere ("plane:<work item id>")
        source      TEXT NOT NULL,                     -- where that is, for the screen ("Plane")
        url         TEXT,                              -- where it opens there
        base        TEXT NOT NULL DEFAULT '{}',        -- JSON: each field as both sides last agreed (contracts.WORK_FIELDS)
        conflicts   TEXT NOT NULL DEFAULT '{}',        -- JSON: field -> its value there, where both sides changed it
        removed_at  TEXT,                              -- gone from there; the task stays
        synced_at   TEXT NOT NULL,                     -- when it last heard from there
        created_at  TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE tasks_drafts (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,                     -- status (a project's status update) | breakdown (a task's subtasks)
        project_id  TEXT REFERENCES tasks_projects(id) ON DELETE CASCADE,
        item_id     TEXT REFERENCES tasks_items(id) ON DELETE CASCADE,
        status      TEXT NOT NULL DEFAULT 'drafting',  -- drafting (its job runs, or failed) | ready
        body        TEXT NOT NULL DEFAULT '',          -- status: the update, markdown
        health      TEXT,                              -- status: the health it suggests
        why         TEXT,                              -- status: why that health, in a sentence
        proposals   TEXT NOT NULL DEFAULT '[]',        -- breakdown: JSON [{id, text, estimate_min, state, item_id}]
        written_by  TEXT,                              -- the AI that wrote it ("Claude · claude-sonnet-5-5")
        edited      INTEGER NOT NULL DEFAULT 0,        -- you've changed what it wrote
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        CHECK ((project_id IS NULL) <> (item_id IS NULL))
    );
    CREATE UNIQUE INDEX tasks_drafts_one ON tasks_drafts(kind, coalesce(project_id, item_id));
    ALTER TABLE tasks_updates ADD COLUMN edited INTEGER NOT NULL DEFAULT 0;   -- written by AI (written_by), then changed by its author
    """,
]

_REF = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9_.-]+$")


# ── Checking values (each raises ValueError with a sentence a person can read) ──

def text(value, what: str = "A task") -> str:
    value = (value or "").strip() if isinstance(value, str) else ""
    if not value:
        raise ValueError(f"{what} needs some text")
    return value


def words(value, what: str) -> str:
    """Free text that may be empty (notes, a brief); None reads as empty."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} should be text")
    return value


def name_or_none(value, what: str) -> str | None:
    """A short optional label (a summary, a person's name), trimmed; empty reads as None."""
    return words(value, what).strip() or None


def day(value) -> str | None:
    """A calendar day, 'YYYY-MM-DD', or None."""
    if value in (None, ""):
        return None
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise ValueError(f"{value!r} isn't a date like 2026-10-31")


def ref(value, what: str = "That") -> str | None:
    """A ref to something in another module ("core:me", "crm:<id>"), or None."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _REF.match(value):
        raise ValueError(f"{what} should be a reference like core:me or crm:<id>")
    return value


def one_of(value, allowed, what: str):
    if value not in allowed:
        raise ValueError(f"{what} must be one of: {', '.join(map(str, allowed))}")
    return value


def priority(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in vocab.PRIORITIES:
        raise ValueError("Priority must be 0 (none), 1 (low), 2 (medium), 3 (high) or 4 (urgent)")
    return value


def minutes(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("An estimate is a whole number of minutes")
    return value


def tags(value) -> str:
    if value in (None, ""):
        return "[]"
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        raise ValueError("Tags are a list of words")
    return json.dumps(normalize_tags(value))


def attributes(value) -> str:
    if value in (None, ""):
        return "{}"
    if not isinstance(value, dict):
        raise ValueError("Attributes are a set of named values")
    return json.dumps(value)


def parsed(row: dict | None) -> dict | None:
    """A row as plain data: JSON columns as lists and dicts, done as true or false."""
    if row is None:
        return None
    out = dict(row)
    for key in ("tags", "attributes"):
        if key in out and isinstance(out[key], str):
            out[key] = json.loads(out[key])
    if "done" in out:
        out["done"] = bool(out["done"])
    return out


# ── Order ─────────────────────────────────────────────────────────────

def sort_after(table: str, scope_sql: str, scope_args: tuple, after_id: str | None) -> float:
    """A sort value that places a row right after `after_id` among the rows `scope_sql` selects (at the top when
    after_id is None, "first"), by averaging its neighbours, so nothing else has to move."""
    rows = db.query(f"SELECT id, sort FROM {table} WHERE {scope_sql} ORDER BY sort, created_at", scope_args)
    if after_id is None:
        return (rows[0]["sort"] - 1.0) if rows else 0.0
    ids = [r["id"] for r in rows]
    if after_id not in ids:
        raise ValueError("That isn't in the same list")
    i = ids.index(after_id)
    here = rows[i]["sort"]
    return (here + rows[i + 1]["sort"]) / 2 if i + 1 < len(rows) else here + 1.0


def sort_last(table: str, scope_sql: str, scope_args: tuple) -> float:
    row = db.one(f"SELECT max(sort) AS m FROM {table} WHERE {scope_sql}", scope_args)
    return (row["m"] + 1.0) if row and row["m"] is not None else 0.0


# ── Search and change ─────────────────────────────────────────────────

def index(kind: str, row_id: str, title: str, body: str = "") -> None:
    db.execute("DELETE FROM tasks_fts WHERE id = ?", (row_id,))
    db.execute("INSERT INTO tasks_fts (id, kind, title, body) VALUES (?, ?, ?, ?)", (row_id, kind, title, body or ""))


def unindex(row_id: str) -> None:
    db.execute("DELETE FROM tasks_fts WHERE id = ?", (row_id,))


def changed(project_id: str | None = None, **more) -> None:
    """Every write ends here: open screens refresh, and anyone listening hears what changed."""
    events.publish("tasks.changed", {"project_id": project_id, **more})
