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


class Clock:
    def __init__(self):
        self.now = datetime(2026, 3, 2, 12, tzinfo=timezone.utc)

    def ago(self, **kw) -> datetime:
        return self.now - timedelta(**kw)


@pytest.fixture
def clock(monkeypatch):
    """The backups' own clock, moved by hand, with this Mac's days and weeks counted in UTC so the tests don't depend on
    where they run."""
    c = Clock()
    monkeypatch.setattr(backup, "_now", lambda: c.now)
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield c
    monkeypatch.undo()
    time.tzset()


def stamp(when: datetime) -> str:
    return when.strftime("%Y%m%d-%H%M%S")


def fake(when: datetime, kind: str = "auto", size: int = 1) -> str:
    """A stand-in copy: only its name (when, what kind) and size matter to the roll-over."""
    name = f"{config.APP_ID}-{stamp(when)}{'' if kind == 'auto' else '-' + kind}.db"
    (backup.DIR / name).write_bytes(b"x" * size)
    return name


def on_disk() -> set[str]:
    return {b["name"] for b in backup.listing()}


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
    assert oct((backup.DIR / f"{made['name']}.json").stat().st_mode & 0o777) == "0o600"     # and its label, too


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
    assert client.get("/api/backups").json()["items"][0]["counts"]["probes"] == 3
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


# ── Rolling over (ARCHITECTURE.md §7) ─────────────────────────────────

def test_the_choices_are_the_newest_and_the_newest_at_least_an_hour_a_day_and_a_week_old(client, clock):
    at = {age: fake(clock.ago(**{unit: n})) for age, (unit, n) in {
        "now": ("hours", 0), "30m": ("minutes", 30), "1h": ("hours", 1), "3h": ("hours", 3),
        "1d": ("days", 1), "2d": ("days", 2), "7d": ("days", 7), "9d": ("days", 9)}.items()}
    r = client.get("/api/backups").json()
    assert r["slots"] == {"latest": at["now"], "hour": at["1h"], "day": at["1d"], "week": at["7d"]}
    assert {b["name"]: b["slots"] for b in r["items"]}[at["1d"]] == ["day"]
    assert r["folder"] == str(backup.DIR)


def test_one_copy_can_fill_every_choice(client, clock):
    only = fake(clock.ago(days=8))
    backup.prune()
    assert on_disk() == {only}
    assert client.get("/api/backups").json()["items"][0]["slots"] == ["latest", "hour", "day", "week"]


def test_two_months_of_hourly_copies_stay_few_with_every_choice_there(clock):
    """60 days of a copy every hour: never more than 14 files, and once there has been time for them, an hour ago is an
    hour old, yesterday is from yesterday, and last week is 7 to 9 days old."""
    start = clock.now
    most = 0
    for h in range(60 * 24):
        clock.now = start + timedelta(hours=h)
        fake(clock.now)
        backup.prune()
        items = backup._items()
        most = max(most, len(items))
        slots = backup._slots(items, clock.now)
        at = {s: next(b["at"] for b in items if b["name"] == n) for s, n in slots.items() if n}
        if h >= 2:
            assert clock.now - at["hour"] == timedelta(hours=1)
        if h >= 24:
            assert at["day"].date() == (clock.now - timedelta(days=1)).date()
        if h >= 8 * 24:
            assert timedelta(days=7) <= clock.now - at["week"] <= timedelta(days=9)
    assert most <= 14 and len(items) <= 14


def test_the_newest_in_each_hour_day_and_week_stays_and_the_rest_go(clock):
    clock.now = datetime(2026, 3, 4, 12, tzinfo=timezone.utc)             # a Wednesday
    today = [fake(clock.ago(hours=h, minutes=m)) for h in range(6) for m in (0, 30)]     # 12:00, 11:30, 11:00, 10:30…
    days = [fake(datetime(2026, 3, d, 23, tzinfo=timezone.utc)) for d in (2, 3)] + [fake(datetime(2026, 3, 3, 9, tzinfo=timezone.utc))]
    week = fake(datetime(2026, 2, 22, 23, tzinfo=timezone.utc))            # the Sunday of two weeks back
    backup.prune()
    # today: the newest of this hour, and of the two before; then the last of Monday and Tuesday; then that Sunday
    assert on_disk() == {today[0], today[1], today[3], days[0], days[1], week}
    clock.now += timedelta(hours=1)
    fake(clock.now)
    backup.prune()
    assert today[3] not in on_disk()                                       # its hour has rolled off the end


def test_the_same_data_is_never_copied_twice(clock):
    first = backup.make("auto")
    again = backup.make("manual")                                       # Back up now, with nothing changed
    assert again["name"] == first["name"] and again["kinds"] == ["manual", "auto"] and again["kind"] == "manual"
    assert backup.make("before-restore")["name"] == first["name"]
    assert len(backup.listing()) == 1
    put("test.marker", f"changed at {clock.now}")
    clock.now += timedelta(minutes=5)
    assert backup.make("manual")["name"] != first["name"]
    assert len(backup.listing()) == 2


def test_a_quiet_app_makes_no_copies_and_a_busy_one_one_an_hour(clock):
    def hourly():
        clock.now += timedelta(hours=1)
        jobs.enqueue("core", "backup", f"at {clock.now}")
        jobs.drain()

    hourly()
    hourly()
    hourly()
    assert len(backup.listing()) == 1
    put("test.marker", f"changed at {clock.now}")
    hourly()
    assert len(backup.listing()) == 2


def test_what_you_make_is_kept_for_a_day_then_rolls_over_like_the_rest(clock):
    mine = [fake(clock.ago(hours=h), "manual") for h in (2, 3, 4, 5)]
    for h in range(7):
        fake(clock.ago(hours=h))
    backup.prune()
    assert {b["name"] for b in backup.listing() if b["kind"] == "manual"} == set(mine[:3])
    clock.now += timedelta(hours=25)
    backup.prune()
    assert not [b for b in backup.listing() if b["kind"] == "manual"]


def test_copies_from_before_an_update_and_the_newest_before_a_restore_survive_the_roll_over(clock):
    updates = [fake(clock.ago(days=d), "before-update") for d in (90, 120, 150)]
    restores = [fake(clock.ago(hours=h, minutes=30), "before-restore") for h in (2, 3)]
    for h in range(30 * 24):
        fake(clock.ago(hours=h))
    backup.prune()
    assert {b["name"] for b in backup.listing() if b["kind"] == "before-update"} == set(updates[:2])
    assert {b["name"] for b in backup.listing() if b["kind"] == "before-restore"} == {restores[0]}
    clock.now += timedelta(days=8)                                      # a week on, with the app closed
    backup.prune()
    assert {b["name"] for b in backup.listing() if b["kind"] == "before-update"} == set(updates[:2])
    assert not [b for b in backup.listing() if b["kind"] == "before-restore"]


def test_past_the_size_ceiling_only_the_choices_and_the_last_update_copy_stay(clock, monkeypatch):
    update = [fake(clock.ago(days=d), "before-update", 100) for d in (10, 20)]
    for h in (2, 3, 4):
        fake(clock.ago(hours=h), "manual", 100)
    fake(clock.ago(hours=5), "before-restore", 100)
    for h in range(30 * 24):
        fake(clock.ago(hours=h), size=100)
    monkeypatch.setattr(backup, "CEILING", 450)
    backup.prune()
    slots = backup._slots(backup._items(), clock.now)
    assert on_disk() == set(slots.values()) | {update[0]}


def test_a_new_version_names_the_versions_its_copy_sits_between(monkeypatch):
    backup.record_version()
    was = config.VERSION
    monkeypatch.setattr(config, "VERSION", "99.0.0")
    assert backup.before_update()["update"] == f"{was} → 99.0.0"


def test_an_update_with_nothing_changed_labels_the_newest_copy_instead(monkeypatch):
    backup.record_version()
    made = backup.make("manual")
    monkeypatch.setattr(config, "VERSION", "99.0.0")
    kept = backup.before_update()
    assert kept["name"] == made["name"] and kept["kind"] == "before-update" and "99.0.0" in kept["update"]


def test_restoring_a_copy_that_would_be_pruned_still_works(client):
    put("test.marker", "long ago")
    made = backup.make("manual")
    put("test.marker", "later")
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
