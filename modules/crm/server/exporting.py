"""Everything the People module holds as plain data, for the host's JSON export: readable, and enough to rebuild
the book elsewhere. The inbox is left out (it's working state, and holds every original text twice): the original
text of what you imported is in the notes."""
import json

from core.server import db

_JSON = ("attributes", "tags", "properties", "wells", "snapshot", "spec")


def _parsed(row: dict) -> dict:
    return {k: (json.loads(v) if k in _JSON and isinstance(v, str) else v) for k, v in row.items()}


def export() -> dict:
    return {
        "entities": [_parsed(r) for r in db.query("SELECT * FROM crm_entities ORDER BY kind, name COLLATE NOCASE")],
        "relationships": [_parsed(r) for r in db.query("SELECT * FROM crm_relationships ORDER BY created_at, id")],
        "notes": [_parsed(r) for r in db.query("SELECT * FROM crm_notes ORDER BY occurred_at, id")],
        "views": [_parsed(r) for r in db.query("SELECT * FROM crm_views ORDER BY created_at")],
        "presets": [_parsed(r) for r in db.query("SELECT * FROM crm_presets ORDER BY created_at")],
        # Records merged into others, each with all it held when it was merged, so nothing a merge folded away is lost.
        "merges": [_parsed(r) for r in db.query("SELECT * FROM crm_merges ORDER BY created_at, id")],
    }


def count(conn) -> dict:
    """How many people a database holds (a backup's, opened read-only), to label it in Settings → Your data."""
    return {"people": conn.execute("SELECT count(*) FROM crm_entities WHERE kind = 'person'").fetchone()[0]}


def on_restored(payload: dict) -> None:
    """A backup replaced the database: drop everything built from the old one."""
    from . import duplicates, ingest, store
    ingest._down.clear()
    duplicates.forget_check()
    store._touch()
