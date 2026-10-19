"""People in the host's backups and export: an old People backup is brought up to date, a backup is labelled
with how many people it holds, and the export carries everyone."""
import json
import sqlite3

import pytest

from core.server import backup, db, module


@pytest.fixture(autouse=True)
def tidy_backups():
    for p in backup.DIR.glob("*"):
        p.unlink()
    yield
    for p in backup.DIR.glob("*"):
        p.unlink()


def test_an_older_people_backup_is_brought_up_to_date_when_restored(client):
    made = backup.make("manual")
    path = backup.DIR / made["name"]
    with sqlite3.connect(path) as c:                                  # make it look like it came from before crm's saved views, sync, overview and sheet tables
        for table in ("crm_views", "crm_sync", "crm_overviews", "crm_questions", "crm_sheet_rows", "crm_duplicates", "crm_merges"):
            c.execute(f"DROP TABLE {table}")
        c.execute("UPDATE core_migrations SET version = 1 WHERE module = 'crm'")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.status_code == 200
    assert db.one("SELECT version FROM core_migrations WHERE module = 'crm'")["version"] == len(module.get("crm").migrations)
    assert db.query("SELECT * FROM crm_views") == [] and db.query("SELECT * FROM crm_sync") == []
    assert db.query("SELECT * FROM crm_overviews") == [] and db.query("SELECT * FROM crm_questions") == []
    assert db.query("SELECT * FROM crm_sheet_rows") == []
    assert db.query("SELECT * FROM crm_duplicates") == [] and db.query("SELECT * FROM crm_merges") == []


def test_a_backup_counts_its_people(client):
    client.post("/api/crm/entities", json={"kind": "person", "name": "Ana Ruiz"})
    people = db.one("SELECT count(*) AS n FROM crm_entities WHERE kind = 'person'")["n"]
    made = backup.make("manual")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.json()["counts"]["people"] == people >= 1


def test_the_export_carries_people(client):
    client.post("/api/crm/entities", json={"kind": "person", "name": "Priya Nair", "tags": ["investor"], "attributes": {"email": "p@x.example"}})
    r = client.post("/api/export").json()
    data = json.loads((backup.EXPORT_DIR / r["name"]).read_text())
    [priya] = [e for e in data["modules"]["crm"]["entities"] if e["name"] == "Priya Nair"]
    assert priya["tags"] == ["investor"] and priya["attributes"]["email"] == "p@x.example"
    assert r["counts"]["crm"]["entities"] >= 1
