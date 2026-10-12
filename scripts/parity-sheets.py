#!/usr/bin/env python
"""Does The Lodge import spreadsheets exactly as DynaCRM did? Runs DynaCRM's own importer and this one over the
same recorded column mappings (the AI step isn't deterministic), from the same starting records and in the same
order, and compares the per-sheet counts and every person, organization and line that results.

    docker start dynacrm-db-1      # the old database container (its image dynacrm-api must still be built)
    .venv/bin/python scripts/parity-sheets.py [--data-dir ./data] [--files _reference/DynaCRM-old/FirstData]

The recorded mappings come from the imported inbox rows (scripts/import-dynacrm.py). Two starting states are tried:
only you and Cinder Labs, and with your team already there. Development only; needs Docker.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYMMETRIC = {"knows", "partner_of", "related_to"}


def run_old(work: Path, files: Path) -> dict:
    sql = lambda q: subprocess.run(["docker", "exec", "dynacrm-db-1", "psql", "-U", "dynacrm", "-d", "postgres", "-c", q],  # noqa: E731
                                   check=True, capture_output=True)
    sql("DROP DATABASE IF EXISTS dynacrm_sheets")
    sql("CREATE DATABASE dynacrm_sheets")
    try:
        done = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "python", "-w", "/app", "-e", "PYTHONPATH=/app", "-v", f"{work}:/work",
             "-v", f"{files}:/files:ro", "dynacrm-api", "/work/old_side.py"], check=True, capture_output=True, text=True)
    finally:
        sql("DROP DATABASE IF EXISTS dynacrm_sheets")
    return json.loads(done.stdout)


def run_new(cfg: dict, mappings: dict, files: Path) -> dict:
    os.environ["LODGE_DATA_DIR"] = tempfile.mkdtemp(prefix="lodge-sheets-")
    os.environ["LODGE_UI_DIR"] = "/nonexistent"
    sys.path.insert(0, str(ROOT))
    import logging
    logging.disable(logging.INFO)
    from core.server import db
    from core.server.app import setup
    from modules.crm.server import ingest, store
    from modules.crm.server.documents import parse_spreadsheet
    from modules.crm.server.spreadsheets import SheetImporter, SheetMapping

    setup()
    with db.connect() as c:
        for table in ("crm_relationships", "crm_notes", "crm_entities", "crm_fts"):
            c.execute(f"DELETE FROM {table}")
    me = store.create_entity("person", cfg["me"], is_self=True)
    cc = store.create_entity("organization", "Cinder Labs")
    store.create_edge(me.id, cc.id, "works_at")
    for name in cfg["team"]:
        mate = store.create_entity("person", name)
        store.create_edge(mate.id, cc.id, "works_at")
    stats = {}
    for title in cfg["order"]:
        owner, _, _, team = ingest.owner_context()   # worked out again for each file, as DynaCRM did
        with db.connect() as c:
            imp = SheetImporter(c, owner, [*team, owner], "spreadsheet")
            for sheet in parse_spreadsheet(title + ".xlsx", (files / f"{title}.xlsx").read_bytes()):
                imp.import_sheet(sheet, SheetMapping.model_validate(mappings[title][sheet.name]), None)
        store._touch()
        stats[title] = imp.stats
    names = {e.id: e.name for e in store.all_entities()}
    return {"stats": stats, "entities": sorted((e.kind, e.name) for e in store.all_entities()),
            "edges": sorted((r.kind, names[r.source_id], names[r.target_id]) for r in store.all_edges())}


def norm(edges) -> list:
    return sorted((k, *((a, b) if k not in SYMMETRIC else sorted((a, b)))) for k, a, b in map(tuple, edges))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--files", default=str(ROOT / "_reference/DynaCRM-old/FirstData"))
    args = ap.parse_args()
    files = Path(args.files).resolve()
    src = sqlite3.connect(Path(args.data_dir) / "lodge.db")
    mappings = {t: json.loads(p)["sheets"] for t, p in src.execute(
        "SELECT title, proposal FROM crm_inbox WHERE source = 'spreadsheet' AND status = 'applied'")}
    me = src.execute("SELECT name FROM crm_entities WHERE is_self = 1").fetchone()[0]
    titles = sorted(mappings)
    print(f"{len(titles)} spreadsheets with a recorded mapping: {', '.join(titles)}\n")
    cases = {
        "you and Cinder Labs only": {"team": [], "order": titles},
        "your team already there": {"team": ["Mickey Fairweather", "Elena Ashworth", "Isaac Kessler"], "order": titles[::-1]},
    }
    failed = 0
    for label, case in cases.items():
        cfg = {"me": me, **case}
        work = Path(tempfile.mkdtemp(prefix="lodge-oldside-"))
        (work / "config.json").write_text(json.dumps(cfg))
        (work / "mappings.json").write_text(json.dumps(mappings))
        (work / "old_side.py").write_text((Path(__file__).parent / "parity_sheets" / "old_side.py").read_text())
        old, new = run_old(work, files), run_new(cfg, mappings, files)
        keys = ("rows", "skipped_rows", "people_created", "people_updated", "orgs_created", "relationships", "notes")
        print(f"Starting with {label}:")
        for t in case["order"]:
            diffs = {k: (old["stats"][t][k], new["stats"][t][k]) for k in keys if old["stats"][t][k] != new["stats"][t][k]}
            print(f"  {'OK  ' if not diffs else 'FAIL'} {t.strip()}: {dict((k, new['stats'][t][k]) for k in keys)}" + (f"  old vs new {diffs}" if diffs else ""))
            failed += bool(diffs)
        same_e = [tuple(x) for x in old["entities"]] == [tuple(x) for x in new["entities"]]
        same_r = norm(old["edges"]) == norm(new["edges"])
        print(f"  {'OK  ' if same_e else 'FAIL'} the same {len(new['entities'])} people and organizations\n  {'OK  ' if same_r else 'FAIL'} the same {len(new['edges'])} lines\n")
        failed += (not same_e) + (not same_r)
    print("No differences." if not failed else f"{failed} difference(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
