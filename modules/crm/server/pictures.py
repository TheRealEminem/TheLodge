"""Pictures of people (and anything else with a record): added by hand, or looked up from Gravatar when you allow it.

The page sizes a picture down to a small square before it comes here, so the database only ever holds a few KB
per person, and a backup holds them too. Nothing here reads LinkedIn: it doesn't hand out other people's photos, so
the way to use one is to save it from the profile and drop it on theirs.

Gravatar is a setting that starts off. When it's on, a hash of a person's email address (never the address itself)
goes to gravatar.com, and only people with an email address and no picture are asked about. Lockdown refuses it.
"""
import hashlib
import logging
from datetime import datetime, timezone

import httpx

from core.server import db, jobs, settings

from . import store
from .model import iso

log = logging.getLogger("crm.pictures")

MAX_BYTES = 600_000                       # the page sends about 15 KB; this only stops a mistake
TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png", b"RIFF": "image/webp", b"GIF8": "image/gif"}
GRAVATAR = "https://gravatar.com/avatar/{hash}?s=256&d=404"
SETTING = "crm.gravatar"


class PictureError(ValueError):
    """The message is shown to the person."""


def _kind(data: bytes) -> str | None:
    for magic, mime in TYPES.items():
        if data.startswith(magic):
            return mime if mime != "image/webp" or data[8:12] == b"WEBP" else None
    return None


def _now() -> str:
    return iso(datetime.now(timezone.utc))  # type: ignore[arg-type]


def versions() -> dict[str, str]:
    """{entity id: when its picture last changed}: the page uses it to know who has one, and to refresh a changed one."""
    return {r["entity_id"]: r["updated_at"] for r in db.query("SELECT entity_id, updated_at FROM crm_pictures")}


def get(entity_id: str) -> tuple[bytes, str, str] | None:
    row = db.one("SELECT data, mime, updated_at FROM crm_pictures WHERE entity_id = ?", (entity_id,))
    return (bytes(row["data"]), row["mime"], row["updated_at"]) if row else None


def put(entity_id: str, data: bytes, source: str = "you") -> None:
    store.require_entity(entity_id)
    if not data:
        raise PictureError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise PictureError("That picture is too big to keep. Use a smaller one.")
    mime = _kind(data)
    if mime is None:
        raise PictureError("That isn't a picture The Lodge can show. Use a JPEG, PNG, WebP or GIF.")
    db.execute(
        "INSERT INTO crm_pictures (entity_id, mime, data, source, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(entity_id) DO UPDATE SET mime = excluded.mime, data = excluded.data, source = excluded.source, "
        "updated_at = excluded.updated_at", (entity_id, mime, data, source, _now()))
    store._touch()


def remove(entity_id: str) -> None:
    db.execute("DELETE FROM crm_pictures WHERE entity_id = ?", (entity_id,))
    store._touch()


# ── Gravatar ──────────────────────────────────────────────────────────

def blocked() -> str | None:
    """Why a look-up can't run right now, or None."""
    if not settings.get_all().get(SETTING):
        return "Looking up pictures is off. Turn it on in Settings first."
    return None


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _fetch(client: httpx.Client, email: str) -> bytes | None:
    r = client.get(GRAVATAR.format(hash=_email_hash(email)))
    if r.status_code == 404:
        return None                        # no picture for that address: the normal answer
    r.raise_for_status()
    return r.content if _kind(r.content) else None


def look_up(entity_id: str) -> bool:
    """Ask Gravatar about one person. True if a picture was saved. Raises PictureError when it can't ask."""
    if (why := blocked()):
        raise PictureError(why)
    e = store.require_entity(entity_id)
    email = (e.attributes or {}).get("email")
    if not email:
        raise PictureError("They have no email address to look up.")
    try:
        with httpx.Client(timeout=15) as client:
            data = _fetch(client, email)
    except httpx.HTTPError as err:
        raise PictureError("Gravatar didn't answer. Try again in a minute.") from err
    if data is None:
        return False
    put(entity_id, data, "gravatar")
    return True


def look_up_everyone(job: jobs.Job | None = None) -> dict:
    """Every person with an email address and no picture. A person Gravatar has nothing for is simply skipped."""
    if (why := blocked()):
        raise PictureError(why)
    have = set(versions())
    todo = [e for e in store.list_entities("person", limit=100000)[0]
            if e.id not in have and (e.attributes or {}).get("email")]
    found = 0
    with httpx.Client(timeout=15) as client:
        for i, e in enumerate(todo):
            if job:
                job.stage(f"Looking up pictures ({i + 1} of {len(todo)})")
            try:
                data = _fetch(client, e.attributes["email"])
            except httpx.HTTPError:
                log.warning("Gravatar didn't answer for one person; stopping this round")
                break
            if data:
                put(e.id, data, "gravatar")
                found += 1
    return {"asked": len(todo), "found": found}


def handle_lookup(job: jobs.Job) -> None:
    look_up_everyone(job)
