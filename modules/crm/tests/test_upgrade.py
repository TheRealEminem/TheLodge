"""An old database meeting a newer app: every step after the one it has is applied, and nothing already there is lost."""
from core.server import db
from modules.crm.server import store


def test_a_database_from_the_first_release_is_brought_up_to_date_with_its_data_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old.db")
    db.init()
    db.migrate("crm", store.MIGRATIONS[:1])                       # what the first release shipped
    with db.connect() as c:
        c.execute("INSERT INTO crm_entities (id, kind, name, attributes, tags, source, created_at, updated_at) "
                  "VALUES ('p1', 'person', 'Priya Nair', '{\"email\": \"p@x.example\"}', '[\"investor\"]', 'manual', 't', 't')")
        c.execute("INSERT INTO crm_entities (id, kind, name, attributes, tags, source, created_at, updated_at) "
                  "VALUES ('m1', 'meeting', 'Call', '{}', '[]', 'ingest', 't', 't')")
        c.execute("INSERT INTO crm_relationships (id, source_id, target_id, kind, created_at, updated_at) "
                  "VALUES ('r1', 'p1', 'm1', 'attended', 't', 't')")
        c.execute("INSERT INTO crm_notes (id, entity_id, body, occurred_at, created_at) VALUES ('n1', 'p1', 'Met at the depot', 't', 't')")
        c.execute("INSERT INTO crm_inbox (id, source, status, created_at, updated_at) VALUES ('i1', 'manual_note', 'applied', 't', 't')")
    with db.connect() as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE name = 'crm_views'").fetchone() is None

    db.migrate("crm", store.MIGRATIONS)                           # the app starts: everything newer is applied

    assert db.one("SELECT version FROM core_migrations WHERE module = 'crm'")["version"] == len(store.MIGRATIONS)
    assert db.query("SELECT count(*) AS n FROM crm_views")[0]["n"] == 0 and db.query("SELECT count(*) AS n FROM crm_sync")[0]["n"] == 0
    assert [r["name"] for r in db.query("SELECT name FROM crm_entities ORDER BY name")] == ["Call", "Priya Nair"]
    assert db.one("SELECT body FROM crm_notes")["body"] == "Met at the depot"
    assert db.one("SELECT status FROM crm_inbox")["status"] == "applied"
    db.migrate("crm", store.MIGRATIONS)                           # and starting again changes nothing
    assert db.one("SELECT version FROM core_migrations WHERE module = 'crm'")["version"] == len(store.MIGRATIONS)
