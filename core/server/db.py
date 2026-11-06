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
    """
    CREATE TABLE core_ai_usage (
        id         TEXT PRIMARY KEY,
        at         TEXT NOT NULL,
        provider   TEXT NOT NULL,
        model      TEXT NOT NULL,
        source     TEXT NOT NULL,      -- what the call was for ("Note summaries")
        tokens_in  INTEGER NOT NULL,
        tokens_out INTEGER NOT NULL,
        searches   INTEGER NOT NULL DEFAULT 0,
        cost       REAL NOT NULL,      -- estimated dollars; 0 for local or unpriced
        local      INTEGER NOT NULL,   -- ran on this computer
        priced     INTEGER NOT NULL    -- cost is a real estimate (a local model is priced at 0)
    );
    CREATE INDEX core_ai_usage_at ON core_ai_usage(at);
    """,
    lambda conn: _one_ai_tally(conn),
]


def _one_ai_tally(conn: sqlite3.Connection) -> None:
    """core_ai_usage was created two ways before the family had one tally (the step above, from the apps that counted
    tokens and dollars, and pricing.py's, from the app that logged each call with its job, cache reads, failures and
    Lockdown stops). Both are at the same version, so this step looks at the table it finds and brings either to the one
    shape pricing.write() fills (tokens_in and tokens_out stay readable, as generated columns). Dollars the first kind couldn't price were stored as 0 with priced = 0: those become
    NULL (cost not known), as the second kind has them."""
    # table_xinfo, not table_info, which leaves generated columns out: a step cut off before its version was noted runs
    # again, and must find the columns it already added.
    cols = {r[1] for r in conn.execute("PRAGMA table_xinfo(core_ai_usage)")}
    if "input_tokens" in cols:                                  # pricing.py's table: add what the other kind has
        for name, spec in (("source", "TEXT NOT NULL DEFAULT ''"), ("searches", "INTEGER NOT NULL DEFAULT 0"),
                           ("local", "INTEGER NOT NULL DEFAULT 0")):
            if name not in cols:
                conn.execute(f"ALTER TABLE core_ai_usage ADD COLUMN {name} {spec}")
        conn.execute("UPDATE core_ai_usage SET local = 1 WHERE provider = 'ollama'")
        for name, value in (("tokens_in", "COALESCE(input_tokens, 0)"), ("tokens_out", "COALESCE(output_tokens, 0)"),
                            ("priced", "cost IS NOT NULL")):
            if name not in cols:
                conn.execute(f"ALTER TABLE core_ai_usage ADD COLUMN {name} INTEGER GENERATED ALWAYS AS ({value}) VIRTUAL")
        return
    conn.executescript("""
    BEGIN;
    CREATE TABLE core_ai_usage_one (
        id            TEXT PRIMARY KEY,
        at            TEXT NOT NULL,   -- when it finished
        module        TEXT NOT NULL,   -- whose job asked ("inbox"), "core" for Settings' Test button, "" for neither
        job           TEXT NOT NULL,   -- that job's kind ("extract"), "test", or ""
        call          TEXT NOT NULL,   -- complete | structured
        provider      TEXT NOT NULL,
        model         TEXT NOT NULL,   -- the one that answered, when the reply says
        input_tokens  INTEGER,         -- NULL: the provider didn't say (or never answered)
        cached_tokens INTEGER,         -- how many of input_tokens were read from the provider's cache
        output_tokens INTEGER,         -- thinking included
        cost          REAL,            -- US dollars; NULL when the price isn't known, or nothing was spent
        failed        INTEGER NOT NULL DEFAULT 0,
        error         TEXT,
        source        TEXT NOT NULL DEFAULT '',   -- what the call was for ("Note summaries")
        searches      INTEGER NOT NULL DEFAULT 0, -- web searches paid for
        local         INTEGER NOT NULL DEFAULT 0, -- ran on this computer
        -- what the apps that counted before there was one tally called them, for anything that still reads those names,
        -- such as the version before this one after Go back
        tokens_in     INTEGER GENERATED ALWAYS AS (COALESCE(input_tokens, 0)) VIRTUAL,
        tokens_out    INTEGER GENERATED ALWAYS AS (COALESCE(output_tokens, 0)) VIRTUAL,
        priced        INTEGER GENERATED ALWAYS AS (cost IS NOT NULL) VIRTUAL
    );
    INSERT INTO core_ai_usage_one (id, at, module, job, call, provider, model, input_tokens, output_tokens, cost, source,
                                   searches, local)
        SELECT id, at, '', '', 'complete', provider, model, tokens_in, tokens_out, CASE WHEN priced = 1 THEN cost END,
               source, searches, local FROM core_ai_usage;
    DROP TABLE core_ai_usage;
    ALTER TABLE core_ai_usage_one RENAME TO core_ai_usage;
    CREATE INDEX core_ai_usage_at ON core_ai_usage(at);
    COMMIT;
    """)


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
    _keep_private()


def _keep_private() -> None:
    """The data folder holds everything the app knows, including API keys: only you may read it. (SQLite's
    -wal and -shm files are made with the database's own permissions.)"""
    try:
        config.DATA_DIR.chmod(0o700)
        for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")):
            if path.exists():
                path.chmod(0o600)
    except OSError:
        pass  # e.g. a folder on a drive that has no permissions: nothing to protect there


def migrate(module: str, steps: list) -> None:
    """Applies the steps this database hasn't seen yet. Never edit or reorder a step once released; add a new one."""
    with connect() as conn:
        row = conn.execute("SELECT version FROM core_migrations WHERE module = ?", (module,)).fetchone()
        done = row["version"] if row else 0
        for i, sql in enumerate(steps[done:], start=done + 1):
            if callable(sql):                       # a step that has to look at the database before it changes it
                sql(conn)
                conn.commit()
            else:
                conn.executescript(f"BEGIN; {sql}; COMMIT;")
            conn.execute(
                "INSERT INTO core_migrations (module, version) VALUES (?, ?) "
                "ON CONFLICT(module) DO UPDATE SET version = excluded.version",
                (module, i),
            )
