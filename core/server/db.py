"""SQLite: one database file per app, shared by every module.

Each module owns the tables whose names start with its id (notes_items, tasks_items…) and never touches
anyone else's. Schema changes are an append-only list of SQL steps per module, applied once each and
recorded in core_migrations, so an old database is brought up to date on startup.

Every row a module creates gets a random text id (new_id()), never an autoincrement number: when apps that
were separate are merged into one, their rows can be copied into one database without colliding.
"""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

DB_PATH = config.DATA_DIR / f"{config.APP_ID}.db"

CORE_MIGRATIONS = [
    """
    CREATE TABLE core_settings (
        key   TEXT PRIMARY KEY,        -- "<namespace>.<name>", e.g. "ai.provider", "notes.auto_summarize"
        value TEXT NOT NULL            -- JSON
    );
    CREATE TABLE core_jobs (
        id          TEXT PRIMARY KEY,
        module      TEXT NOT NULL,
        kind        TEXT NOT NULL,     -- what to do, e.g. "summarize"
        target      TEXT NOT NULL,     -- the id of the thing it's done to
        status      TEXT NOT NULL,     -- queued | running | waiting | done | error
        stage       TEXT,              -- progress in words while running ("Summarizing part 2 of 3")
        wait_reason TEXT,              -- why it's waiting ("Needs you", "Not enough free memory")
        approved    INTEGER NOT NULL DEFAULT 0,
        forced      INTEGER NOT NULL DEFAULT 0,
        error       TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX core_jobs_target ON core_jobs(module, target);
    CREATE TABLE core_links (
        from_ref   TEXT NOT NULL,      -- "<module>:<id>"
        to_ref     TEXT NOT NULL,
        kind       TEXT NOT NULL DEFAULT 'related',
        created_at TEXT NOT NULL,
        PRIMARY KEY (from_ref, to_ref, kind)
    );
    CREATE INDEX core_links_to ON core_links(to_ref);
    """,
]


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@contextmanager
def connect():
    """Short-lived connection per operation; safe across FastAPI's worker threads."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def query(sql: str, args: tuple | list = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql: str, args: tuple | list = ()) -> dict | None:
    with connect() as conn:
        row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def execute(sql: str, args: tuple | list = ()) -> int:
    """Runs one statement; returns how many rows it changed."""
    with connect() as conn:
        return conn.execute(sql, args).rowcount


def init() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS core_migrations (module TEXT PRIMARY KEY, version INTEGER NOT NULL)")
    migrate("core", CORE_MIGRATIONS)


def migrate(module: str, steps: list[str]) -> None:
    """Applies the steps this database hasn't seen yet. Never edit or reorder a step once released; add a new one."""
    with connect() as conn:
        row = conn.execute("SELECT version FROM core_migrations WHERE module = ?", (module,)).fetchone()
        done = row["version"] if row else 0
        for i, sql in enumerate(steps[done:], start=done + 1):
            conn.executescript(f"BEGIN; {sql}; COMMIT;")
            conn.execute(
                "INSERT INTO core_migrations (module, version) VALUES (?, ?) "
                "ON CONFLICT(module) DO UPDATE SET version = excluded.version",
                (module, i),
            )
