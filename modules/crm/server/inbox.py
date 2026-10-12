"""The inbox: everything that came in (a pasted note, a document, a recorded meeting) with the AI's proposal for it
and what was applied. One row per item, in crm_inbox.

    pending     waiting its turn (the host's job runner reads it, extracts, and builds the proposal)
    processing  being read right now
    review      a proposal is ready for you to look at (or to be applied automatically if nothing is in doubt)
    applied     in the graph
    failed      couldn't be read or applied; Retry
    discarded   you threw it away; it stays here so re-importing the same folder doesn't bring it back
    skipped     not worth reading (empty, a duplicate, an unsupported type, a saved web page); the reason is in `error`

The work itself (core_jobs) is the host's; this table is the content and its review state.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from core.server import db, events

LIVE = ("pending", "processing", "review", "applied")
write_lock = threading.Lock()   # bulk writes to the graph (applying a proposal, a spreadsheet, an import) go one at a time
_JSON = ("payload", "proposal", "result")


class NotFound(LookupError):
    pass


def _row(r: sqlite3.Row | dict) -> dict:
    out = dict(r)
    for key in _JSON:
        out[key] = json.loads(out[key]) if out.get(key) else ({} if key == "payload" else None)
    return out


@contextmanager
def _use(conn: sqlite3.Connection | None):
    if conn is not None:
        yield conn
    else:
        with db.connect() as c:
            yield c


def create(source: str, *, title: str | None = None, status: str = "pending", raw_text: str | None = None,
           payload: dict | None = None, content_hash: str | None = None, occurred_at: str | None = None,
           error: str | None = None) -> dict:
    row_id, stamp = db.new_id(), db.now()
    with db.connect() as c:
        c.execute(
            "INSERT INTO crm_inbox (id, source, status, content_hash, title, occurred_at, raw_text, payload, error, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, source, status, content_hash, title, occurred_at, raw_text, json.dumps(payload or {}), error, stamp, stamp),
        )
    events.publish("crm.inbox.changed", {})
    return get(row_id)  # type: ignore[return-value]


def get(row_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    with _use(conn) as c:
        r = c.execute("SELECT * FROM crm_inbox WHERE id = ?", (row_id,)).fetchone()
    return _row(r) if r else None


def require(row_id: str) -> dict:
    row = get(row_id)
    if row is None:
        raise NotFound("Inbox item not found")
    return row


def update(row_id: str, conn: sqlite3.Connection | None = None, **fields) -> None:
    """Fields: status, title, error, extractor, occurred_at, payload, proposal, result."""
    fields["updated_at"] = db.now()
    values = [json.dumps(v) if k in _JSON and v is not None else v for k, v in fields.items()]
    with _use(conn) as c:
        c.execute(f"UPDATE crm_inbox SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*values, row_id))
    events.publish("crm.inbox.changed", {})


def listing(statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Newest first, without the text and the proposal (those are for one item at a time)."""
    where, args = "", []
    if statuses:
        where = f"WHERE status IN ({','.join('?' * len(statuses))})"
        args = list(statuses)
    rows = db.query(
        "SELECT id, source, status, title, occurred_at, error, extractor, created_at, updated_at, result, "
        "json_extract(payload, '$.filename') AS filename, json_extract(payload, '$.triage.category') AS category, "
        f"json_extract(payload, '$.words') AS words FROM crm_inbox {where} "
        "ORDER BY created_at DESC, title LIMIT ?", [*args, min(limit, 500)])
    for r in rows:
        r["result"] = json.loads(r["result"]) if r["result"] else None
    return rows


def counts() -> dict[str, int]:
    return {r["status"]: r["n"] for r in db.query("SELECT status, count(*) AS n FROM crm_inbox GROUP BY status")}


def known_hashes() -> dict[str, str]:
    """content hash -> status, for everything already imported, in the queue, or deliberately discarded."""
    marks = ",".join("?" * (len(LIVE) + 1))
    return {r["content_hash"]: r["status"] for r in db.query(
        f"SELECT content_hash, status FROM crm_inbox WHERE content_hash IS NOT NULL AND status IN ({marks})",
        (*LIVE, "discarded"))}


def with_hash(digest: str) -> dict | None:
    marks = ",".join("?" * (len(LIVE) + 1))
    row = db.one(f"SELECT id FROM crm_inbox WHERE content_hash = ? AND status IN ({marks}) LIMIT 1", (digest, *LIVE, "discarded"))
    return get(row["id"]) if row else None
