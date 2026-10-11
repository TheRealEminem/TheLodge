"""The notes module's tables (notes_*) and the queries on them. Only this module touches these tables."""
from core.server import db

MIGRATIONS = [
    """
    CREATE TABLE notes_items (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL DEFAULT '',
        summary     TEXT,
        summary_by  TEXT,                 -- which AI provider wrote it
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE notes_fts USING fts5(id UNINDEXED, title, body, summary, tokenize='porter unicode61');
    """,
    # Later changes go here as new steps, e.g. "ALTER TABLE notes_items ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
]

LIST_COLUMNS = "id, title, created_at, updated_at"


def _reindex(conn, note_id: str) -> None:
    conn.execute("DELETE FROM notes_fts WHERE id = ?", (note_id,))
    conn.execute("INSERT INTO notes_fts (id, title, body, summary) "
                 "SELECT id, title, body, coalesce(summary, '') FROM notes_items WHERE id = ?", (note_id,))


def create(title: str, body: str) -> str:
    note_id, stamp = db.new_id(), db.now()
    with db.connect() as conn:
        conn.execute("INSERT INTO notes_items (id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     (note_id, title, body, stamp, stamp))
        _reindex(conn, note_id)
    return note_id


def update(note_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = db.now()
    with db.connect() as conn:
        conn.execute(f"UPDATE notes_items SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), note_id))
        _reindex(conn, note_id)


def get(note_id: str) -> dict | None:
    return db.one("SELECT * FROM notes_items WHERE id = ?", (note_id,))


def all_notes() -> list[dict]:
    return db.query(f"SELECT {LIST_COLUMNS} FROM notes_items ORDER BY updated_at DESC")


def delete(note_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM notes_items WHERE id = ?", (note_id,))
        conn.execute("DELETE FROM notes_fts WHERE id = ?", (note_id,))


def describe(note_id: str) -> dict | None:
    """How other modules show a link to a note."""
    note = db.one("SELECT title FROM notes_items WHERE id = ?", (note_id,))
    return {"title": note["title"] or "Untitled note", "href": f"#/notes/{note_id}"} if note else None


def search(q: str, limit: int) -> list[dict]:
    words = " ".join(f'"{w}"*' for w in q.replace('"', " ").split())
    if not words:
        return []
    rows = db.query(
        "SELECT id, snippet(notes_fts, -1, '', '', '…', 10) AS snippet FROM notes_fts WHERE notes_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (words, limit),
    )
    titles = {r["id"]: r["title"] for r in db.query(
        f"SELECT id, title FROM notes_items WHERE id IN ({','.join('?' * len(rows))})", [r["id"] for r in rows])} if rows else {}
    return [{"id": r["id"], "title": titles.get(r["id"], ""), "snippet": r["snippet"]} for r in rows]
