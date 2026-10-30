"""Sediment's tables (sediment_*) and the queries on them. Only this module touches these tables.

    sediment_subjects   what readings can be about besides you and your company: products you describe, and people
                        or organizations from your book you've read against (by ref, "crm:<id>")
    sediment_readings   one reading of how a person feels about a subject: the stance, the confidence, the rest of
                        the AI's answer as JSON, and the fingerprint of the records it was read from
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


def repoint(old_ref: str, new_ref: str) -> None:
    """The person was merged into someone else: their readings go with them."""
    db.execute("UPDATE sediment_readings SET person_ref = ? WHERE person_ref = ?", (new_ref, old_ref))


def delete_readings_of(person_ref: str) -> list[str]:
    ids = [r["id"] for r in db.query("SELECT id FROM sediment_readings WHERE person_ref = ?", (person_ref,))]
    db.execute("DELETE FROM sediment_readings WHERE person_ref = ?", (person_ref,))
    return ids


# ── For the host ──────────────────────────────────────────────────────

def describe(item_id: str) -> dict | None:
    row = reading(item_id)
    if not row:
        return None
    return {"title": f"{row['person_name']} on {row['subject_name']}", "href": f"#/sediment/{row['person_ref']}"}


def export() -> dict:
    return {"subjects": subjects(), "readings": [reading_out(r) for r in db.query("SELECT * FROM sediment_readings ORDER BY created_at")]}


def count(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        n = conn.execute("SELECT COUNT(*) FROM sediment_readings WHERE status = 'done'").fetchone()[0]
    except sqlite3.OperationalError:  # a backup from before Sediment
        return {}
    return {"readings": n} if n else {}
