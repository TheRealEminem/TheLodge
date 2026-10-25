"""Backups and restore, and a plain-JSON export of what you have.

A backup is a complete copy of the database made with SQLite's own online backup, so it is consistent even while the
app is writing, and it holds everything every module keeps, plus settings and keys. They live in the data
folder's `backups/` (private to you, like the database) and are not sent anywhere.

They roll over; they are never a list that grows (ARCHITECTURE.md §7). One is made each hour while the app is open, if
the data changed since the newest, and they thin out like Time Machine's: the newest in each of the last 3 hours, 9 days
and 4 weeks that have one stays. "Back up now", a restore (which
first keeps the state it replaces, so a restore can itself be undone) and the first start of a new version (before its
migrations change anything) make one too, under the same rule, plus a little protection each: the newest 3 made by you
stay for a day, the newest 2 from before an update stay, and the newest from before a restore stays for a week. The
same data is never copied twice: when nothing changed since the newest copy, that copy is labelled with the new kind
instead (in a small sidecar, `<name>.json`, which also remembers what the copy holds).

Restoring copies a backup over the live database (SQLite takes the lock for the moment it needs), brings an older
one up to date with the app's migrations, and tells modules to drop what they had cached.
"""
import hashlib
import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import config, db, events, jobs, module

log = logging.getLogger("core.backup")

DIR = config.DATA_DIR / "backups"
EXPORT_DIR = config.DATA_DIR / "exports"
ROTATE = {"hour": 3, "day": 9, "week": 4}     # the newest copy in each of the last N hours, days, weeks that have one
PINNED = {"manual": (3, timedelta(hours=24)), "before-restore": (1, timedelta(days=7)), "before-update": (2, None)}
CEILING = 2 * 1024 ** 3          # past this, the protections and the copies on their way to a slot go first
HOURLY_AFTER_MINUTES = 50        # the hourly one is skipped if there is already one this recent (the app restarts often)
NOT_DATA = ("core_jobs",)        # bookkeeping that changes by itself (the backup job is one), so not a reason to copy
KINDS = ("before-update", "before-restore", "manual", "auto")    # the label a copy shows when it has several
_NAME = re.compile(rf"^{re.escape(config.APP_ID)}-\d{{8}}-\d{{6}}(?:-(manual|before-restore|before-update))?\.db$")

router = APIRouter()


class BackupError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


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
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as c:
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


def _fingerprint(c: sqlite3.Connection) -> str:
    """What the data is, whatever order the rows are in: so the same data is never copied twice."""
    h = hashlib.sha256()
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if table in NOT_DATA:
            continue
        total = 0
        for row in c.execute(f'SELECT * FROM "{table}"'):
            total += int.from_bytes(hashlib.blake2b(repr(row).encode(), digest_size=16).digest(), "big")
        h.update(f"{table}:{total % (1 << 128)}\n".encode())
    return h.hexdigest()


def _fingerprint_of(path: Path) -> str | None:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as c:
            return _fingerprint(c)
    except sqlite3.Error:
        return None


# ── The copies on disk, and what each is for ──────────────────────────

def _side(name: str) -> Path:
    return _dir() / f"{name}.json"


def _save_side(name: str, meta: dict) -> None:
    part = _dir() / f".{name}.json.part"
    part.write_text(json.dumps(meta))
    part.chmod(0o600)
    part.rename(_side(name))


def _items() -> list[dict]:
    """Every copy, newest first, with the kinds it holds and when each was given ({"manual": <when>})."""
    out = []
    for p in _dir().glob("*.db"):
        if not _NAME.match(p.name):
            continue
        try:
            meta = json.loads(_side(p.name).read_text())
        except (OSError, ValueError):
            meta = {}
        at = _stamp_of(p.name)
        tags = {_kind(p.name): at, **{k: datetime.fromisoformat(v.replace("Z", "+00:00")) for k, v in meta.get("tagged", {}).items()}}
        out.append({"name": p.name, "at": at, "tags": tags, "bytes": p.stat().st_size, "meta": meta})
    return sorted(out, key=lambda b: (b["at"], b["name"]), reverse=True)


def _public(b: dict) -> dict:
    kinds = [k for k in KINDS if k in b["tags"]]
    out = {"name": b["name"], "kind": kinds[0], "kinds": kinds, "created_at": _iso(b["at"]), "bytes": b["bytes"]}
    if b["meta"].get("update"):
        out["update"] = b["meta"]["update"]
    return out


def listing() -> list[dict]:
    return [_public(b) for b in _items()]


def _period(at: datetime, unit: str) -> tuple:
    """The hour, day or week (Monday to Sunday) a copy was made in, on this Mac's clock."""
    local = at.astimezone()
    if unit == "hour":
        return local.timetuple()[:4]
    if unit == "day":
        return local.timetuple()[:3]
    return local.isocalendar()[:2]


def _rotation(items: list[dict]) -> set[str]:
    """Each unit keeps the newest copy in each of its last N periods that have one, so a week the app wasn't opened
    doesn't use up a place. 3 hours always hold one at least an hour old, and 9 days one at least 7 days old."""
    keep: set[str] = set()
    for unit, n in ROTATE.items():
        seen: list[tuple] = []
        for b in items:                                  # newest first
            p = _period(b["at"], unit)
            if p in seen:
                continue
            if len(seen) == n:
                break
            seen.append(p)
            keep.add(b["name"])
    return keep


def _slots(items: list[dict], now: datetime) -> dict[str, str | None]:
    """The restore choices: the newest copy, the newest at least an hour old, the newest from before today (on this
    Mac's clock), and the newest at least a week old."""
    midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return {"latest": items[0]["name"] if items else None,
            "hour": next((b["name"] for b in items if now - b["at"] >= timedelta(hours=1)), None),
            "day": next((b["name"] for b in items if b["at"] < midnight), None),
            "week": next((b["name"] for b in items if now - b["at"] >= timedelta(days=7)), None)}


def _roles(items: list[dict], now: datetime, spare: tuple[str, ...] = ()) -> dict[str, set[str]]:
    """Why each copy stays; one with none goes."""
    roles: dict[str, set[str]] = {b["name"]: set() for b in items}
    for name in _rotation(items):
        roles[name].add("rotation")
    for kind, (n, keep_for) in PINNED.items():
        mine = sorted((b for b in items if kind in b["tags"]), key=lambda b: b["tags"][kind], reverse=True)[:n]
        for i, b in enumerate(mine):
            if keep_for is None or now - b["tags"][kind] < keep_for:
                roles[b["name"]].add(kind if i == 0 or kind != "before-update" else "before-update-older")
    for name in spare:
        if name in roles:
            roles[name].add("restoring")
    for slot, name in _slots([b for b in items if roles[b["name"]]], now).items():    # chosen from what stays
        if name:
            roles[name].add(slot)
    return roles


_NEVER_TRIMMED = {"latest", "hour", "day", "week", "before-update", "restoring"}


def _trim(items: list[dict], roles: dict[str, set[str]]) -> None:
    """Past CEILING (a very large book), let copies go, oldest first, until it fits: a day's pin on what you made, then
    the rotation's copies that aren't a restore choice, then the older pre-update copy and the pre-restore one. The four
    restore choices and the newest pre-update copy always stay."""
    total = sum(b["bytes"] for b in items if roles[b["name"]])
    for role in ("manual", "rotation", "before-update-older", "before-restore"):
        for b in reversed(items):
            if total <= CEILING:
                return
            mine = roles[b["name"]]
            if role in mine and not mine & _NEVER_TRIMMED:
                mine.discard(role)
                if not mine:
                    total -= b["bytes"]


def prune(spare: tuple[str, ...] = ()) -> None:
    items = _items()
    roles = _roles(items, _now(), spare)
    _trim(items, roles)
    for b in items:
        if not roles[b["name"]]:
            (_dir() / b["name"]).unlink(missing_ok=True)
            _side(b["name"]).unlink(missing_ok=True)
    for side in _dir().glob("*.db.json"):                 # a label whose copy is gone
        if not (_dir() / side.name[:-5]).exists():
            side.unlink(missing_ok=True)


# ── Making one ────────────────────────────────────────────────────────

def _unchanged(newest: dict) -> bool:
    """Has nothing changed since the newest copy? Its fingerprint is kept beside it, or worked out once."""
    known = newest["meta"].get("fingerprint")
    if not known:
        known = _fingerprint_of(_dir() / newest["name"])
        if not known:
            return False
        newest["meta"]["fingerprint"] = known
        _save_side(newest["name"], newest["meta"])
    return _fingerprint_of(db.DB_PATH) == known


def make(kind: str = "auto", spare: tuple[str, ...] = (), update: str | None = None) -> dict:
    """A consistent copy of the database right now, or, when nothing changed since the newest copy, that copy labelled
    `kind` too. The pruning after it leaves `spare` alone. `update` says which versions a pre-update copy sits between."""
    items = _items()
    if items and _unchanged(items[0]):
        newest = items[0]
        if kind != "auto":
            newest["meta"].setdefault("tagged", {})[kind] = _iso(_now())
            if update:
                newest["meta"]["update"] = update
            _save_side(newest["name"], newest["meta"])
        prune(spare)
        return next(b for b in listing() if b["name"] == newest["name"])
    when = _now()
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
        meta = {"fingerprint": _fingerprint(dst), **({"update": update} if update else {})}
    except Exception:
        dst.close()
        src.close()
        partial.unlink(missing_ok=True)
        raise
    dst.close()
    src.close()
    partial.chmod(0o600)
    partial.rename(target)
    _save_side(name, meta)
    prune(spare)
    log.info("backup %s", name)
    return next(b for b in listing() if b["name"] == name)


def delete(name: str) -> None:
    path = _path(name)
    path.unlink()
    _side(name).unlink(missing_ok=True)


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
    copy of it as the previous version left it (kind "before-update", named for the versions it sits between; the newest
    two always stay), so an update can be undone. Nothing on a fresh install. A backup that fails is logged and the app
    starts anyway."""
    if not db.DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True) as c:
            row = c.execute("SELECT value FROM core_settings WHERE key = ?", (VERSION_KEY,)).fetchone()
    except sqlite3.Error:
        row = None                                   # no settings table yet: an old database, so back it up
    previous = json.loads(row[0]) if row else None
    if previous == config.VERSION:
        return None
    try:
        return make("before-update", update=f"{previous or 'an earlier version'} → {config.VERSION}")
    except Exception:  # noqa: BLE001 - never stop the app from starting over a backup
        log.exception("couldn't back up before the update to %s", config.VERSION)
        return None


def record_version() -> None:
    """After startup's migrations: this version has now opened the database."""
    db.execute("INSERT INTO core_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (VERSION_KEY, json.dumps(config.VERSION)))


# ── Each hour ─────────────────────────────────────────────────────────

def handle_hourly(job: jobs.Job) -> None:
    """A copy if the data changed (make() copies nothing otherwise), and the roll-over, which moves on with the clock
    even when nothing else does."""
    job.stage("Backing up")
    newest = _items()[:1]
    if newest and _now() - newest[0]["at"] < timedelta(minutes=HOURLY_AFTER_MINUTES):
        prune()
    else:
        make("auto")


# ── Export ────────────────────────────────────────────────────────────

def export_all() -> dict:
    """Everything the modules hold, as one readable JSON file in the data folder's `exports/`. No settings, so no keys."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        EXPORT_DIR.chmod(0o700)
    except OSError:
        pass
    now = _now()
    body = {"app": config.APP_ID, "version": config.VERSION, "exported_at": now.isoformat(),
            "modules": {m.id: m.export() for m in module.all_modules() if m.export}}
    path = EXPORT_DIR / f"{config.APP_ID}-export-{now.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str))
    path.chmod(0o600)
    return {"name": path.name, "folder": str(EXPORT_DIR), "bytes": path.stat().st_size,
            "counts": {mid: {k: len(v) for k, v in data.items() if isinstance(v, list)} for mid, data in body["modules"].items()}}


# ── API ───────────────────────────────────────────────────────────────

def _holds(b: dict) -> dict:
    """What a copy holds, worked out once and kept beside it (a copy never changes)."""
    if "counts" not in b["meta"]:
        try:
            b["meta"]["counts"] = _counts(_dir() / b["name"])["counts"]
        except BackupError:
            return {}
        _save_side(b["name"], b["meta"])
    return b["meta"]["counts"]


@router.get("/backups")
def list_backups():
    """Every copy, with what it holds and the restore choices it fills, so the page never works out the rule itself."""
    items = _items()
    slots = _slots(items, _now())
    return {"items": [{**_public(b), "counts": _holds(b), "slots": [s for s, n in slots.items() if n == b["name"]]} for b in items],
            "slots": slots, "folder": str(DIR)}


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
