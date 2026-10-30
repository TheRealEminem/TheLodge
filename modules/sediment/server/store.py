"""Sediment's tables (sediment_*) and the queries on them. Only this module touches these tables.

    sediment_subjects   what readings can be about besides you and your company: products you describe, and people
                        or organizations from your book you've read against (by ref, "crm:<id>")
    sediment_readings   one reading of how a person feels about a subject: the stance, the confidence, the rest of
                        the AI's answer as JSON, and the fingerprint of the records it was read from
    sediment_portraits  one per person: a written model of them, and the fingerprint of what it was written from
    sediment_conversations, sediment_messages
                        rehearsals with a simulated person: an optional scenario, then your lines and theirs, each of
                        theirs with the phrases the AI made up (guesses) and what the rest rests on (grounds)
"""
import json
import sqlite3

from core.server import db

MIGRATIONS = [
    """
    CREATE TABLE sediment_subjects (
        id           TEXT PRIMARY KEY,
        kind         TEXT NOT NULL,              -- product | person | organization
        ref          TEXT,                       -- "crm:<id>" for someone or something in your book
        name         TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        terms        TEXT NOT NULL DEFAULT '[]', -- other names it goes by
        created_at   TEXT NOT NULL
    );
    CREATE UNIQUE INDEX sediment_subjects_ref ON sediment_subjects(ref) WHERE ref IS NOT NULL;
    CREATE TABLE sediment_readings (
        id            TEXT PRIMARY KEY,
        person_ref    TEXT NOT NULL,
        person_name   TEXT NOT NULL,
        subject_key   TEXT NOT NULL,             -- me | company | crm:<id> | product:<id>
        subject_name  TEXT NOT NULL,
        status        TEXT NOT NULL,             -- queued | done | error
        stance        TEXT,
        confidence    TEXT,
        body          TEXT NOT NULL DEFAULT '{}',
        fingerprint   TEXT NOT NULL DEFAULT '',
        written_by    TEXT,
        error         TEXT,
        created_at    TEXT NOT NULL,
        read_at       TEXT
    );
    CREATE INDEX sediment_readings_person ON sediment_readings(person_ref, subject_key, created_at);
    """,
    """
    CREATE TABLE sediment_portraits (
        id           TEXT PRIMARY KEY,
        person_ref   TEXT NOT NULL UNIQUE,
        body         TEXT NOT NULL,
        fingerprint  TEXT NOT NULL DEFAULT '',
        written_by   TEXT,
        created_at   TEXT NOT NULL
    );
    CREATE TABLE sediment_conversations (
        id           TEXT PRIMARY KEY,
        person_ref   TEXT NOT NULL,
        person_name  TEXT NOT NULL,
        scenario     TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );
    CREATE INDEX sediment_conversations_person ON sediment_conversations(person_ref, updated_at);
    CREATE TABLE sediment_messages (
        id               TEXT PRIMARY KEY,
        conversation_id  TEXT NOT NULL,
        role             TEXT NOT NULL,          -- you | them
        body             TEXT NOT NULL DEFAULT '',
        guesses          TEXT NOT NULL DEFAULT '[]',
        grounds          TEXT NOT NULL DEFAULT '[]',
        status           TEXT NOT NULL,          -- queued | done | error (yours are always done)
        error            TEXT,
        written_by       TEXT,
        created_at       TEXT NOT NULL
    );
    CREATE INDEX sediment_messages_conversation ON sediment_messages(conversation_id, created_at);
    """,
]


def _subject(row: dict) -> dict:
    return {**row, "terms": json.loads(row["terms"] or "[]"),
            "key": row["ref"] if row["ref"] else f"product:{row['id']}"}


def subjects() -> list[dict]:
    return [_subject(r) for r in db.query("SELECT * FROM sediment_subjects ORDER BY kind = 'product' DESC, name COLLATE NOCASE")]


def subject(subject_id: str) -> dict | None:
    row = db.one("SELECT * FROM sediment_subjects WHERE id = ?", (subject_id,))
    return _subject(row) if row else None


def subject_by_ref(ref: str) -> dict | None:
    row = db.one("SELECT * FROM sediment_subjects WHERE ref = ?", (ref,))
    return _subject(row) if row else None


def add_subject(kind: str, name: str, *, ref: str | None = None, description: str = "", terms: list[str] | None = None) -> dict:
    sid = db.new_id()
    db.execute("INSERT INTO sediment_subjects (id, kind, ref, name, description, terms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (sid, kind, ref, name, description, json.dumps(terms or []), db.now()))
    return subject(sid)  # type: ignore[return-value]


def update_subject(subject_id: str, name: str, description: str, terms: list[str]) -> None:
    db.execute("UPDATE sediment_subjects SET name = ?, description = ?, terms = ? WHERE id = ?",
               (name, description, json.dumps(terms), subject_id))


def delete_subject(subject_id: str) -> None:
    db.execute("DELETE FROM sediment_subjects WHERE id = ?", (subject_id,))


READING_FIELDS = ("id", "person_ref", "person_name", "subject_key", "subject_name", "status", "stance", "confidence",
                  "fingerprint", "written_by", "error", "created_at", "read_at")


def reading_out(row: dict) -> dict:
    return {**{k: row[k] for k in READING_FIELDS}, "body": json.loads(row["body"] or "{}")}


def reading(reading_id: str) -> dict | None:
    return db.one("SELECT * FROM sediment_readings WHERE id = ?", (reading_id,))


def readings_of(person_ref: str) -> list[dict]:
    return [reading_out(r) for r in db.query(
        "SELECT * FROM sediment_readings WHERE person_ref = ? ORDER BY created_at DESC, id DESC", (person_ref,))]


def latest_done(person_ref: str, subject_key: str) -> dict | None:
    return db.one("SELECT * FROM sediment_readings WHERE person_ref = ? AND subject_key = ? AND status = 'done' "
                  "ORDER BY created_at DESC, id DESC LIMIT 1", (person_ref, subject_key))


def recent(limit: int = 12) -> list[dict]:
    return [reading_out(r) for r in db.query(
        "SELECT * FROM sediment_readings WHERE status = 'done' ORDER BY read_at DESC LIMIT ?", (limit,))]


def add_reading(person_ref: str, person_name: str, subject_key: str, subject_name: str) -> str:
    rid = db.new_id()
    db.execute("INSERT INTO sediment_readings (id, person_ref, person_name, subject_key, subject_name, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, 'queued', ?)", (rid, person_ref, person_name, subject_key, subject_name, db.now()))
    return rid


def finish_reading(reading_id: str, *, stance: str, confidence: str, body: dict, fingerprint: str, written_by: str,
                   person_name: str, subject_name: str) -> None:
    db.execute("UPDATE sediment_readings SET status = 'done', stance = ?, confidence = ?, body = ?, fingerprint = ?, "
               "written_by = ?, error = NULL, read_at = ?, person_name = ?, subject_name = ? WHERE id = ?",
               (stance, confidence, json.dumps(body), fingerprint, written_by, db.now(), person_name, subject_name, reading_id))


def fail_reading(reading_id: str, error: str) -> None:
    db.execute("UPDATE sediment_readings SET status = 'error', error = ? WHERE id = ?", (error, reading_id))


def requeue_reading(reading_id: str) -> None:
    db.execute("UPDATE sediment_readings SET status = 'queued', error = NULL WHERE id = ?", (reading_id,))


def delete_reading(reading_id: str) -> None:
    db.execute("DELETE FROM sediment_readings WHERE id = ?", (reading_id,))


# ── Portraits ─────────────────────────────────────────────────────────

def portrait(person_ref: str) -> dict | None:
    return db.one("SELECT * FROM sediment_portraits WHERE person_ref = ?", (person_ref,))


def save_portrait(person_ref: str, body: str, fingerprint: str, written_by: str) -> None:
    db.execute(
        "INSERT INTO sediment_portraits (id, person_ref, body, fingerprint, written_by, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(person_ref) DO UPDATE SET body = excluded.body, fingerprint = excluded.fingerprint, "
        "written_by = excluded.written_by, created_at = excluded.created_at",
        (db.new_id(), person_ref, body, fingerprint, written_by, db.now()))


def stale_portrait(person_ref: str) -> None:
    """Asked to write it again: the one on file no longer counts as current."""
    db.execute("UPDATE sediment_portraits SET fingerprint = '' WHERE person_ref = ?", (person_ref,))


# ── Conversations ─────────────────────────────────────────────────────

MESSAGE_FIELDS = ("id", "conversation_id", "role", "body", "status", "error", "written_by", "created_at")


def message_out(row: dict) -> dict:
    return {**{k: row[k] for k in MESSAGE_FIELDS}, "guesses": json.loads(row["guesses"] or "[]"),
            "grounds": json.loads(row["grounds"] or "[]")}


def conversation(conversation_id: str) -> dict | None:
    return db.one("SELECT * FROM sediment_conversations WHERE id = ?", (conversation_id,))


def conversations_of(person_ref: str) -> list[dict]:
    return db.query(
        "SELECT c.*, (SELECT COUNT(*) FROM sediment_messages m WHERE m.conversation_id = c.id) AS messages "
        "FROM sediment_conversations c WHERE person_ref = ? ORDER BY updated_at DESC", (person_ref,))


def add_conversation(person_ref: str, person_name: str, scenario: str) -> str:
    cid, now = db.new_id(), db.now()
    db.execute("INSERT INTO sediment_conversations (id, person_ref, person_name, scenario, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, ?, ?)", (cid, person_ref, person_name, scenario, now, now))
    return cid


def messages(conversation_id: str) -> list[dict]:
    return [message_out(r) for r in db.query(
        "SELECT * FROM sediment_messages WHERE conversation_id = ? ORDER BY created_at, rowid", (conversation_id,))]


def message(message_id: str) -> dict | None:
    return db.one("SELECT * FROM sediment_messages WHERE id = ?", (message_id,))


def add_message(conversation_id: str, role: str, body: str = "", status: str = "done") -> str:
    mid, now = db.new_id(), db.now()
    db.execute("INSERT INTO sediment_messages (id, conversation_id, role, body, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (mid, conversation_id, role, body, status, now))
    db.execute("UPDATE sediment_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
    return mid


def finish_message(message_id: str, body: str, guesses: list[str], grounds: list[dict], written_by: str) -> None:
    db.execute("UPDATE sediment_messages SET status = 'done', body = ?, guesses = ?, grounds = ?, error = NULL, written_by = ? "
               "WHERE id = ?", (body, json.dumps(guesses), json.dumps(grounds), written_by, message_id))


def fail_message(message_id: str, error: str) -> None:
    db.execute("UPDATE sediment_messages SET status = 'error', error = ? WHERE id = ?", (error, message_id))


def requeue_message(message_id: str) -> None:
    db.execute("UPDATE sediment_messages SET status = 'queued', error = NULL WHERE id = ?", (message_id,))


def delete_conversation(conversation_id: str) -> list[str]:
    ids = [r["id"] for r in db.query("SELECT id FROM sediment_messages WHERE conversation_id = ?", (conversation_id,))]
    db.execute("DELETE FROM sediment_messages WHERE conversation_id = ?", (conversation_id,))
    db.execute("DELETE FROM sediment_conversations WHERE id = ?", (conversation_id,))
    return ids


# ── A person as a whole ───────────────────────────────────────────────

def repoint(old_ref: str, new_ref: str) -> None:
    """The person was merged into someone else: their readings and conversations go with them. The old portrait goes;
    the kept person's is written from the merged records."""
    db.execute("UPDATE sediment_readings SET person_ref = ? WHERE person_ref = ?", (new_ref, old_ref))
    db.execute("UPDATE sediment_conversations SET person_ref = ? WHERE person_ref = ?", (new_ref, old_ref))
    db.execute("DELETE FROM sediment_portraits WHERE person_ref = ?", (old_ref,))


def delete_person(person_ref: str) -> list[str]:
    """Everything Sediment holds about someone. Returns the ids of readings and messages (for their jobs)."""
    ids = [r["id"] for r in db.query("SELECT id FROM sediment_readings WHERE person_ref = ?", (person_ref,))]
    db.execute("DELETE FROM sediment_readings WHERE person_ref = ?", (person_ref,))
    for c in db.query("SELECT id FROM sediment_conversations WHERE person_ref = ?", (person_ref,)):
        ids += delete_conversation(c["id"])
    db.execute("DELETE FROM sediment_portraits WHERE person_ref = ?", (person_ref,))
    return ids


# ── For the host ──────────────────────────────────────────────────────

def describe(item_id: str) -> dict | None:
    row = reading(item_id)
    if not row:
        return None
    return {"title": f"{row['person_name']} on {row['subject_name']}", "href": f"#/sediment/{row['person_ref']}"}


def export() -> dict:
    """Plain data for the JSON export. Conversations are marked as simulated, so nobody reads them as what was said."""
    convs = db.query("SELECT * FROM sediment_conversations ORDER BY created_at")
    return {"subjects": subjects(),
            "readings": [reading_out(r) for r in db.query("SELECT * FROM sediment_readings ORDER BY created_at")],
            "portraits": db.query("SELECT person_ref, body, written_by, created_at FROM sediment_portraits ORDER BY created_at"),
            "conversations": [{**c, "simulated": True, "messages": messages(c["id"])} for c in convs]}


def count(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for name, sql in (("readings", "SELECT COUNT(*) FROM sediment_readings WHERE status = 'done'"),
                      ("rehearsals", "SELECT COUNT(*) FROM sediment_conversations")):
        try:
            n = conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:  # a backup from before Sediment, or before rehearsals
            continue
        if n:
            out[name] = n
    return out
