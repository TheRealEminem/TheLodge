"""Backups, restore, and the JSON export: a copy that is whole, a restore that brings back exactly that, and an
old database brought up to date."""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from core.server import backup, config, db, jobs, module, settings


@pytest.fixture(autouse=True)
def tidy_backups():
    for p in backup.DIR.glob("*"):
        p.unlink()
    yield
    for p in backup.DIR.glob("*"):
        p.unlink()


@pytest.fixture
def utc(monkeypatch):
    """Hours, days and weeks counted on a UTC clock, so the rotation tests don't depend on where they run."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def stamp(when: datetime) -> str:
    return when.strftime("%Y%m%d-%H%M%S")


def fake(when: datetime, kind: str = "auto") -> str:
    name = f"{config.APP_ID}-{stamp(when)}{'' if kind == 'auto' else '-' + kind}.db"
    (backup.DIR / name).write_bytes(b"x")
    return name


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


def test_hourly_copies_roll_over_into_a_few_hours_a_week_of_days_and_a_month_of_weeks(utc):
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)               # a Thursday
    names = [fake(first + timedelta(hours=h)) for h in range(40 * 24)]
    backup.prune()
    kept = {b["name"] for b in backup.listing()}
    at = {datetime(2026, 2, d, h, tzinfo=timezone.utc) for d, h in [
        (9, 23), (9, 22), (9, 21), (9, 20),                           # the last four hours (Mon Feb 9 is the newest day)
        (8, 23), (7, 23), (6, 23), (5, 23), (4, 23), (3, 23),         # the last of each of the last seven days
    ]} | {datetime(2026, 2, 1, 23, tzinfo=timezone.utc), datetime(2026, 1, 25, 23, tzinfo=timezone.utc)}   # Sundays: weeks
    assert kept == {n for n in names if any(stamp(w) in n for w in at)}


def test_the_rotation_stays_small_and_always_has_yesterday_and_last_week(utc):
    first = datetime(2026, 3, 1, tzinfo=timezone.utc)
    most = 0
    for h in range(60 * 24):
        now = first + timedelta(hours=h)
        fake(now)
        backup.prune()
        made = [backup._stamp_of(b["name"]) for b in backup.listing()]
        most = max(most, len(made))
        if h >= 14 * 24:
            midnight = now.replace(hour=0)
            assert any(midnight - timedelta(days=1) <= m < midnight for m in made)
            assert any(now - timedelta(days=14) <= m <= now - timedelta(days=7) for m in made)
    assert most <= sum(backup.ROTATE.values())


def test_the_other_kinds_keep_a_few_for_a_month_and_always_the_newest():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recent = [fake(now - timedelta(days=d), "manual") for d in range(1, backup.KEEP["manual"] + 3)]
    stale = [fake(now - timedelta(days=d), "before-restore") for d in (40, 50, 60)]
    backup.prune()
    kept = {b["name"] for b in backup.listing()}
    assert kept == set(recent[:backup.KEEP["manual"]]) | {stale[0]}


def test_the_copy_before_the_last_update_stays_and_older_ones_roll_off():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = [fake(now - timedelta(days=d), "before-update") for d in (90, 120, 150)]
    for h in range(48):                                                # plenty of automatic copies made since
        fake(now - timedelta(hours=h))
    backup.prune()
    assert [b["name"] for b in backup.listing() if b["kind"] == "before-update"] == [old[0]]
    newer = [fake(now - timedelta(days=d), "before-update") for d in (1, 2, 3)]
    backup.prune()
    assert [b["name"] for b in backup.listing() if b["kind"] == "before-update"] == newer[:backup.KEEP["before-update"]]


def test_restoring_a_copy_that_would_be_pruned_still_works(client):
    put("test.marker", "long ago")
    made = backup.make("manual")
    backup.make("manual")                                              # a newer one, so the old one is past keeping...
    old = f"{config.APP_ID}-{stamp(datetime.now(timezone.utc) - timedelta(days=90))}-manual.db"
    (backup.DIR / made["name"]).rename(backup.DIR / old)              # ...once it is made old
    put("test.marker", "now")
    r = client.post(f"/api/backups/{old}/restore")
    assert r.status_code == 200 and read("test.marker") == "long ago"


def test_the_hourly_backup_runs_once_an_hour_not_once_a_launch():
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
