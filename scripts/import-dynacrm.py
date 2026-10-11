#!/usr/bin/env python
"""One-off: copy the old DynaCRM (Postgres) into The Lodge's SQLite database.

    .venv/bin/python scripts/import-dynacrm.py                  # into ./data (a scratch copy; safe)
    .venv/bin/python scripts/import-dynacrm.py --data-dir "$HOME/Library/Application Support/The Lodge"

Needs the old Postgres running (default postgresql://dynacrm:dynacrm@127.0.0.1:5433/dynacrm; pass --dsn to
change) and `pip install "psycopg[binary]"` (development only; the app doesn't ship it).

Copies entities, relationships, notes (including every original transcript) and the inbox history
(content hashes and statuses, so re-importing a folder still skips what's already in and what was discarded).
It does not touch settings or API keys. Safe to run again: rows are matched by id and updated.
Ids: every UUID becomes its 32-character hex form, everywhere it appears (including inside JSON).
Quit The Lodge before importing into its real data folder.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def hexid(value) -> str | None:
    return str(value).replace("-", "").lower() if value is not None else None


def j(value) -> str:
    """JSON text with every UUID in it turned into hex."""
    return UUID.sub(lambda m: m.group(0).replace("-", "").lower(), json.dumps(value if value is not None else {}))


def stamp(value: datetime | None) -> str | None:
    from modules.crm.server.model import iso
    return iso(value) if value else None


def day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default="postgresql://dynacrm:dynacrm@127.0.0.1:5433/dynacrm")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()

    os.environ["LODGE_DATA_DIR"] = args.data_dir
    os.environ.setdefault("LODGE_UI_DIR", "/nonexistent")
    sys.path.insert(0, str(ROOT))
    import psycopg

    from core.server import db
    from core.server.app import setup
    from modules.crm.server import store

    setup()  # opens the database and applies every module's migrations
    print(f"Writing to {db.DB_PATH}")
    old = psycopg.connect(args.dsn)
    counts: dict[str, int] = {}

    with db.connect() as c:
        cur = old.cursor(row_factory=psycopg.rows.dict_row)

        cur.execute("SELECT * FROM entities")
        for r in cur.fetchall():
            c.execute(
                "INSERT INTO crm_entities (id, kind, name, summary, attributes, tags, occurred_at, is_self, source, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "kind=excluded.kind, name=excluded.name, summary=excluded.summary, attributes=excluded.attributes, "
                "tags=excluded.tags, occurred_at=excluded.occurred_at, is_self=excluded.is_self, "
                "source=excluded.source, created_at=excluded.created_at, updated_at=excluded.updated_at",
                (hexid(r["id"]), r["kind"], r["name"], r["summary"], j(r["attributes"]), j(r["tags"] or []),
                 stamp(r["occurred_at"]), int(r["is_self"]), r["source"], stamp(r["created_at"]), stamp(r["updated_at"])),
            )
        counts["entities"] = c.execute("SELECT count(*) FROM crm_entities").fetchone()[0]
        for row in c.execute("SELECT * FROM crm_entities").fetchall():
            store._reindex(c, store._entity(row))

        cur.execute("SELECT * FROM relationships")
        for r in cur.fetchall():
            c.execute(
                "INSERT INTO crm_relationships (id, source_id, target_id, kind, properties, strength, started_at, "
                "ended_at, source, evidence_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET properties=excluded.properties, strength=excluded.strength, "
                "started_at=excluded.started_at, ended_at=excluded.ended_at, evidence_id=excluded.evidence_id, "
                "updated_at=excluded.updated_at",
                (hexid(r["id"]), hexid(r["source_id"]), hexid(r["target_id"]), r["kind"], j(r["properties"]),
                 r["strength"], day(r["started_at"]), day(r["ended_at"]), r["source"], hexid(r["evidence_id"]),
                 stamp(r["created_at"]), stamp(r["updated_at"])),
            )
        counts["relationships"] = c.execute("SELECT count(*) FROM crm_relationships").fetchone()[0]

        cur.execute("SELECT * FROM notes")
        for r in cur.fetchall():
            c.execute(
                "INSERT INTO crm_notes (id, entity_id, body, occurred_at, source, evidence_id, created_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, "
                "occurred_at=excluded.occurred_at, source=excluded.source, evidence_id=excluded.evidence_id",
                (hexid(r["id"]), hexid(r["entity_id"]), r["body"], stamp(r["occurred_at"]), r["source"],
                 hexid(r["evidence_id"]), stamp(r["created_at"])),
            )
        counts["notes"] = c.execute("SELECT count(*) FROM crm_notes").fetchone()[0]

        cur.execute("SELECT * FROM ingestion_jobs")
        for r in cur.fetchall():
            c.execute(
                "INSERT INTO crm_inbox (id, source, status, content_hash, title, occurred_at, raw_text, payload, "
                "proposal, result, error, extractor, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, proposal=excluded.proposal, "
                "result=excluded.result, error=excluded.error, updated_at=excluded.updated_at",
                (hexid(r["id"]), r["source"], r["status"], r["content_hash"], r["title"], stamp(r["occurred_at"]),
                 r["raw_text"], j(r["payload"]), j(r["proposal"]) if r["proposal"] is not None else None,
                 j(r["result"]) if r["result"] is not None else None, r["error"], r["extractor"],
                 stamp(r["created_at"]), stamp(r["updated_at"])),
            )
        counts["inbox"] = c.execute("SELECT count(*) FROM crm_inbox").fetchone()[0]
        bad = c.execute("PRAGMA foreign_key_check").fetchall()
    store._touch()
    print("Copied:", ", ".join(f"{v} {k}" for k, v in counts.items()))
    if bad:
        print(f"WARNING: {len(bad)} rows point at something that isn't there", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
