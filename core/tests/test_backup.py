"""Backups, restore, and the JSON export: a copy that is whole, a restore that brings back exactly that, and an
old database brought up to date."""
import json
import sqlite3

import pytest

from core.server import backup, config, db, jobs, module, settings


@pytest.fixture(autouse=True)
def tidy_backups():
    for p in backup.DIR.glob("*"):
        p.unlink()
    yield
    for p in backup.DIR.glob("*"):
        p.unlink()


def put(key, value):
    db.execute("INSERT INTO core_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, json.dumps(value)))


def read(key):
    row = db.one("SELECT value FROM core_settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else None


def test_a_backup_is_a_whole_private_copy_you_can_list(client):
    put("test.marker", "before")
    made = backup.make("manual")
    assert made["kind"] == "manual" and made["bytes"] > 0
    path = backup.DIR / made["name"]
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT value FROM core_settings WHERE key = 'test.marker'").fetchone()[0] == '"before"'
    assert [b["name"] for b in client.get("/api/backups").json()["items"]] == [made["name"]]
    assert not list(backup.DIR.glob("*-wal")) and not list(backup.DIR.glob(".*"))


def test_restoring_brings_back_exactly_that_and_keeps_what_it_replaced(client):
    put("test.marker", "before")
    made = backup.make("manual")
    put("test.marker", "after")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.status_code == 200 and r.json()["restored"] == made["name"]
    assert read("test.marker") == "before"
    kept = r.json()["kept"]
    assert "before-restore" in kept
    client.post(f"/api/backups/{kept}/restore")                       # and the restore itself can be undone
    assert read("test.marker") == "after"


def test_a_restore_tells_the_modules_so_they_drop_what_they_cached(client, monkeypatch):
    heard = []
    from core.server import events
    events.subscribe("core.restored", lambda payload: heard.append(payload["name"]))
    made = backup.make("manual")
    client.post(f"/api/backups/{made['name']}/restore")
    assert heard == [made["name"]]


# A stand-in module with two schema steps and a count, so these tests don't depend on the app's real modules.
module.register(module.Module(
    id="probe2",
    name="Probe two",
    migrations=["CREATE TABLE probe2_items (id TEXT PRIMARY KEY)", "CREATE TABLE probe2_extras (id TEXT PRIMARY KEY)"],
    count=lambda c: {"probes": c.execute("SELECT count(*) FROM probe2_items").fetchone()[0]},
))


def test_an_older_backup_is_brought_up_to_date_when_restored(client):
    made = backup.make("manual")
    path = backup.DIR / made["name"]
    with sqlite3.connect(path) as c:                                  # make it look like it came from before probe2's second step
        c.execute("DROP TABLE probe2_extras")
        c.execute("UPDATE core_migrations SET version = 1 WHERE module = 'probe2'")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.status_code == 200
    assert db.one("SELECT version FROM core_migrations WHERE module = 'probe2'")["version"] == 2
    assert db.query("SELECT * FROM probe2_extras") == []


def test_a_backup_says_what_it_holds_by_asking_the_modules(client):
    db.execute("DELETE FROM probe2_items")
    for _ in range(3):
        db.execute("INSERT INTO probe2_items (id) VALUES (?)", (db.new_id(),))
    made = backup.make("manual")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.json()["counts"]["probes"] == 3


def test_a_backup_from_a_newer_app_or_a_damaged_one_is_refused(client):
    made = backup.make("manual")
    path = backup.DIR / made["name"]
    with sqlite3.connect(path) as c:
        c.execute("UPDATE core_migrations SET version = 99 WHERE module = 'core'")
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.status_code == 422 and "newer version" in r.json()["detail"]
    junk = backup.DIR / f"{config.APP_ID}-20200101-000000-manual.db"
    junk.write_bytes(b"not a database at all" * 100)
    assert client.post(f"/api/backups/{junk.name}/restore").status_code == 422
    assert client.post("/api/backups/../../etc/passwd/restore").status_code in (404, 422)
    assert client.post(f"/api/backups/{config.APP_ID}-nope.db/restore").status_code == 422


def test_old_backups_are_pruned_by_kind():
    for i in range(backup.KEEP["manual"] + 3):
        (backup.DIR / f"{config.APP_ID}-20260101-0000{i:02d}-manual.db").write_bytes(b"x")
    backup.prune()
    assert len([b for b in backup.listing() if b["kind"] == "manual"]) == backup.KEEP["manual"]


def test_the_daily_backup_runs_once_a_day_not_once_a_launch():
    jobs.enqueue("core", "backup", "scheduled")
    jobs.drain()
    jobs.enqueue("core", "backup", "scheduled2")
    jobs.drain()
    assert len([b for b in backup.listing() if b["kind"] == "auto"]) == 1


def test_the_export_is_readable_json_without_settings_or_keys(client, monkeypatch):
    monkeypatch.setattr(module.get("probe2"), "export", lambda: {"items": [{"id": "a", "title": "Kept"}]})
    settings.update({"ai.anthropic_api_key": "sk-ant-secret-123456"})
    r = client.post("/api/export").json()
    text = (backup.EXPORT_DIR / r["name"]).read_text()
    data = json.loads(text)
    assert "sk-ant-secret" not in text and "ai.anthropic_api_key" not in text
    assert data["app"] == config.APP_ID and data["modules"]["probe2"]["items"] == [{"id": "a", "title": "Kept"}]
    assert r["counts"]["probe2"]["items"] == 1 and oct((backup.EXPORT_DIR / r["name"]).stat().st_mode & 0o777) == "0o600"


def test_a_new_version_keeps_a_copy_before_it_migrates(monkeypatch):
    backup.record_version()
    assert backup.before_update() is None                            # the same version again: nothing
    monkeypatch.setattr(config, "VERSION", "99.0.0")
    made = backup.before_update()
    assert made["kind"] == "before-update" and made["name"].endswith("-before-update.db")
    backup.record_version()
    assert backup.before_update() is None                            # and only once per version
    assert [b["kind"] for b in backup.listing()] == ["before-update"]


def test_a_database_that_never_recorded_a_version_is_backed_up_once():
    db.execute("DELETE FROM core_settings WHERE key = ?", (backup.VERSION_KEY,))
    assert backup.before_update()["kind"] == "before-update"
    backup.record_version()
    assert backup.before_update() is None


def test_a_fresh_install_makes_no_update_backup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nothing-yet.db")
    assert backup.before_update() is None and backup.listing() == []


def test_update_backups_keep_the_last_three():
    for i in range(5):
        (backup.DIR / f"{config.APP_ID}-20260101-0000{i:02d}-before-update.db").write_bytes(b"x")
    backup.prune()
    assert len([b for b in backup.listing() if b["kind"] == "before-update"]) == 3
