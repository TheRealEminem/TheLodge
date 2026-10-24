"""Backups and restore, and a plain-JSON export of what you have.

A backup is a complete copy of the database made with SQLite's own online backup, so it is consistent even while the
app is writing, and it holds everything every module keeps, plus settings and keys. They live in the data
folder's `backups/` (private to you, like the database) and are not sent anywhere. One is made each hour, and they
roll over each other the way Time Machine's do: the newest in each of the last few hours, each of the last week's
days and each of the last month's weeks stay, and the rest are let go. "Back up now" makes another, a restore first
makes one of the state it replaces, so a restore can itself be undone, and the first start of a new version makes
one before its migrations change anything. Those are kept a few at a time for a month, and the newest of each kind
stays however old it is, so there is always a copy from before the last update.

Restoring copies a backup over the live database (SQLite takes the lock for the moment it needs), brings an older
one up to date with the app's migrations, and tells modules to drop what they had cached.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import config, db, events, jobs, module

log = logging.getLogger("core.backup")

DIR = config.DATA_DIR / "backups"
EXPORT_DIR = config.DATA_DIR / "exports"
ROTATE = {"hour": 4, "day": 7, "week": 4}     # automatic copies: the newest in each of the last N hours, days, weeks that have one
KEEP = {"manual": 5, "before-restore": 3, "before-update": 2}   # the others: the newest N of each kind...
KEEP_DAYS = 31                                  # ...while they're this young, except the newest of each, which always stays
HOURLY_AFTER_MINUTES = 50       # the hourly one is skipped if there is already one this recent (the app restarts often)
_NAME = re.compile(rf"^{re.escape(config.APP_ID)}-\d{{8}}-\d{{6}}(?:-(manual|before-restore|before-update))?\.db$")

router = APIRouter()


class BackupError(ValueError):
    pass


def _dir() -> Path:
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        DIR.chmod(0o700)
    except OSError:
        pass
    return DIR


def _kind(name: str) -> str:
    m = _NAME.match(name)
    return (m.group(1) if m and m.group(1) else "auto") if m else "auto"


def _stamp_of(name: str) -> datetime:
    m = re.search(r"-(\d{8})-(\d{6})", name)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) if m else datetime.fromtimestamp(0, timezone.utc)


def _counts(path: Path) -> dict:
    """What's in a backup, by looking: each module that keeps a count says what it holds ({"people": 381})."""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
            out = {r[0]: r[1] for r in c.execute("SELECT module, version FROM core_migrations")}
            counts: dict[str, int] = {}
            for m in module.all_modules():
                if m.count and m.id in out:
                    try:
                        counts.update(m.count(c))
                    except sqlite3.Error:
                        log.warning("couldn't count %s in %s", m.id, path.name)
        return {"migrations": out, "counts": counts}
    except sqlite3.Error as e:
        raise BackupError(f"That backup can't be read ({e}).") from e


def listing() -> list[dict]:
    out = []
    for p in _dir().glob("*.db"):
        if not _NAME.match(p.name):
            continue
        out.append({"name": p.name, "kind": _kind(p.name), "created_at": _stamp_of(p.name).isoformat().replace("+00:00", "Z"),
                    "bytes": p.stat().st_size})
    return sorted(out, key=lambda b: b["name"], reverse=True)


def make(kind: str = "auto", spare: tuple[str, ...] = ()) -> dict:
    """A consistent copy of the database right now. The pruning after it leaves `spare` alone."""
    when = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = "" if kind == "auto" else f"-{kind}"
    name = f"{config.APP_ID}-{when.strftime('%Y%m%d-%H%M%S')}{suffix}.db"
    while (_dir() / name).exists():          # two in the same second: the later one is stamped a second on, never overwrites
        when += timedelta(seconds=1)
        name = f"{config.APP_ID}-{when.strftime('%Y%m%d-%H%M%S')}{suffix}.db"
    target, partial = _dir() / name, _dir() / f".{name}.part"
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("The copy didn't pass SQLite's own check, so it was thrown away.")
        dst.execute("PRAGMA journal_mode = DELETE")     # one self-contained file, no -wal beside it
    except Exception:
        dst.close()
        src.close()
        partial.unlink(missing_ok=True)
        raise
    dst.close()
    src.close()
    partial.chmod(0o600)
    partial.rename(target)
    prune(spare)
    log.info("backup %s", name)
    return next(b for b in listing() if b["name"] == name)


def _period(name: str, unit: str) -> tuple:
    """The hour, day or week (Monday to Sunday) a copy was made in, on this Mac's clock."""
    local = _stamp_of(name).astimezone()
    if unit == "hour":
        return local.timetuple()[:4]
    if unit == "day":
        return local.timetuple()[:3]
    return local.isocalendar()[:2]


def _rotation(autos: list[dict]) -> set[str]:
    """Which automatic copies stay. Each unit keeps the newest copy in each of its last N periods that have one, so
    a week the app wasn't opened doesn't use up a slot, and a copy that is the last of its day is kept as that day's
    until the day rolls off the end."""
    keep: set[str] = set()
    for unit, n in ROTATE.items():
        seen: list[tuple] = []
        for b in autos:                                  # newest first
            p = _period(b["name"], unit)
            if p in seen:
                continue
            if len(seen) == n:
                break
            seen.append(p)
            keep.add(b["name"])
    return keep


def prune(spare: tuple[str, ...] = ()) -> None:
    items = listing()
    keep = _rotation([b for b in items if b["kind"] == "auto"]) | set(spare)
    young = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    for kind, n in KEEP.items():
        mine = [b for b in items if b["kind"] == kind][:n]
        keep |= {b["name"] for i, b in enumerate(mine) if i == 0 or _stamp_of(b["name"]) >= young}
    for b in items:
        if b["name"] not in keep:
            (_dir() / b["name"]).unlink(missing_ok=True)


def delete(name: str) -> None:
    path = _path(name)
    path.unlink()


def _path(name: str) -> Path:
    if not _NAME.match(name) or not (_dir() / name).exists():
        raise BackupError("There's no such backup.")
    return _dir() / name


def verify(name: str) -> dict:
    """Is it a database this app can use? Refuses one made by a newer version (it would be missing tables' worth of
    meaning), and one that fails SQLite's check."""
    path = _path(name)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        raise BackupError("That backup is damaged (it fails SQLite's own check).")
    info = _counts(path)
    known = {"core": len(db.CORE_MIGRATIONS), **{m.id: len(m.migrations) for m in module.all_modules()}}
    for mod, version in info["migrations"].items():
        if mod in known and version > known[mod]:
            raise BackupError("That backup was made by a newer version of the app. Update the app first.")
    return info


def restore(name: str) -> dict:
    """Replaces what the app holds with a backup. A backup of what was there is made first."""
    info = verify(name)
    before = make("before-restore", spare=(name,))
    src = sqlite3.connect(f"file:{_path(name)}?mode=ro", uri=True)
    dst = sqlite3.connect(db.DB_PATH, timeout=60)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    try:
        db.init()                                       # an older backup: bring it up to date
        for m in module.all_modules():
            db.migrate(m.id, m.migrations)
    except Exception as e:  # noqa: BLE001 - leave things as they were rather than half-way
        log.exception("restore of %s failed while updating it", name)
        back = sqlite3.connect(_path(before["name"]))
        live = sqlite3.connect(db.DB_PATH, timeout=60)
        try:
            back.backup(live)
        finally:
            back.close()
            live.close()
        raise BackupError(f"That backup couldn't be brought up to date ({e}). Nothing was changed.") from e
    jobs.recover()
    events.publish("core.restored", {"name": name})
    log.info("restored %s (kept %s)", name, before["name"])
    return {"restored": name, "kept": before["name"], **info}


# ── Each new version ──────────────────────────────────────────────────

VERSION_KEY = "core.opened_by_version"   # in core_settings, undeclared, so it never shows in Settings


def before_update() -> dict | None:
    """At startup, before any migration: when this version of the app hasn't opened the database before, keep a
    copy of it as the previous version left it (kind "before-update"; the newest always stays), so an update can be undone.
    Nothing on a fresh install. A backup that fails is logged and the app starts anyway."""
    if not db.DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True) as c:
            row = c.execute("SELECT value FROM core_settings WHERE key = ?", (VERSION_KEY,)).fetchone()
    except sqlite3.Error:
        row = None                                   # no settings table yet: an old database, so back it up
    if row and json.loads(row[0]) == config.VERSION:
        return None
    try:
        return make("before-update")
    except Exception:  # noqa: BLE001 - never stop the app from starting over a backup
        log.exception("couldn't back up before the update to %s", config.VERSION)
        return None


def record_version() -> None:
    """After startup's migrations: this version has now opened the database."""
    db.execute("INSERT INTO core_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (VERSION_KEY, json.dumps(config.VERSION)))


# ── Each hour ─────────────────────────────────────────────────────────

def handle_hourly(job: jobs.Job) -> None:
    job.stage("Backing up")
    recent = [b for b in listing() if b["kind"] == "auto"][:1]
    if recent and (datetime.now(timezone.utc) - _stamp_of(recent[0]["name"])).total_seconds() < HOURLY_AFTER_MINUTES * 60:
        return
    make("auto")


# ── Export ────────────────────────────────────────────────────────────

def export_all() -> dict:
    """Everything the modules hold, as one readable JSON file in the data folder's `exports/`. No settings, so no keys."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        EXPORT_DIR.chmod(0o700)
    except OSError:
        pass
    now = datetime.now(timezone.utc)
    body = {"app": config.APP_ID, "version": config.VERSION, "exported_at": now.isoformat(),
            "modules": {m.id: m.export() for m in module.all_modules() if m.export}}
    path = EXPORT_DIR / f"{config.APP_ID}-export-{now.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str))
    path.chmod(0o600)
    return {"name": path.name, "folder": str(EXPORT_DIR), "bytes": path.stat().st_size,
            "counts": {mid: {k: len(v) for k, v in data.items() if isinstance(v, list)} for mid, data in body["modules"].items()}}


# ── API ───────────────────────────────────────────────────────────────



@router.get("/backups")
def list_backups():
    return {"items": listing(), "folder": str(DIR)}


@router.post("/backups", status_code=201)
def back_up_now():
    return make("manual")


@router.post("/backups/{name}/restore")
def restore_backup(name: str):
    try:
        return restore(name)
    except BackupError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/backups/{name}", status_code=204)
def delete_backup(name: str):
    try:
        delete(name)
    except BackupError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/export")
def export():
    return export_all()
