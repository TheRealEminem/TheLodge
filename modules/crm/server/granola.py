"""Granola: new meetings come in on their own.

Granola's public API (https://docs.granola.ai) takes a personal API key made in the Granola app under Settings,
Connectors, API keys; it needs a Business or Enterprise plan. Each run lists the notes made in the last few days
(or the first run's backfill), fetches the ones The Lodge hasn't seen, and hands each to the same path as a meeting
sent to /ingest/meeting: the invitees' emails match people, the AI reads the summary and transcript, and the result
waits in the Inbox unless auto-add is on. A meeting is remembered by Granola's note id, so running twice, or
asking for the same days again, adds nothing.

Everything it creates is stamped source "granola" (see capture.py).
"""
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from core.server import db, jobs, settings

from . import capture, ingest, store

log = logging.getLogger("crm.granola")

BASE_URL = "https://public-api.granola.ai/v1"
PAGE_SIZE = 30
MAX_PAGES = 20            # 600 notes in one run; a bigger backlog carries on at the next one
LOOKBACK_DAYS = 3         # notes become available (summary and transcript ready) a while after they start
PACE_SECONDS = 0.25       # Granola allows 5 requests a second; stay under it
RETRIES = 3

_transport: httpx.BaseTransport | None = None   # tests put a fake one here


class GranolaError(RuntimeError):
    def __init__(self, message: str, *, key_problem: bool = False):
        super().__init__(message)
        self.key_problem = key_problem


def configured() -> bool:
    return bool(settings.get_all().get("crm.granola_api_key"))


def _client(key: str) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=30, transport=_transport)


def _get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    for attempt in range(RETRIES):
        time.sleep(PACE_SECONDS)
        try:
            r = client.get(path, params=params)
        except httpx.HTTPError as e:
            raise GranolaError(f"Couldn't reach Granola ({type(e).__name__}).") from e
        if r.status_code == 429 and attempt < RETRIES - 1:
            time.sleep(min(float(r.headers.get("retry-after", 2) or 2), 30))
            continue
        break
    if r.status_code == 401:
        raise GranolaError("Granola didn't accept the key. Make a new one under Settings, Connectors, API keys in the Granola app.", key_problem=True)
    if r.status_code == 403:
        raise GranolaError("Granola says this key can't read notes. API keys need a Business or Enterprise plan.", key_problem=True)
    if r.status_code == 429:
        raise GranolaError("Granola is asking for fewer requests; it will try again next time.")
    return r


def _check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        raise GranolaError(f"Granola answered {r.status_code}.")
    return r.json()


# ── Reading a note ────────────────────────────────────────────────────

def _speaker(item: dict) -> str:
    who = item.get("speaker") or {}
    if who.get("name"):
        return who["name"]
    if who.get("attribution") in ("me", "them"):
        return {"me": "Me", "them": "Them"}[who["attribution"]]
    if who.get("diarization_label"):
        return who["diarization_label"]
    return "Me" if who.get("source") == "microphone" else "Others"


def transcript_text(items: list[dict] | None) -> str:
    """One line per turn, adjacent lines from the same speaker joined."""
    lines: list[list[str]] = []
    for item in items or []:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        who = _speaker(item)
        if lines and lines[-1][0] == who:
            lines[-1][1] += " " + text
        else:
            lines.append([who, text])
    return "\n".join(f"{who}: {text}" for who, text in lines)


def _full_transcript(client: httpx.Client, note_id: str) -> list[dict]:
    items: list[dict] = []
    cursor = None
    for _ in range(200):
        data = _check(_get(client, f"/notes/{note_id}/transcript", {"cursor": cursor} if cursor else None))
        items += data.get("transcript") or data.get("items") or data.get("data") or []
        if not data.get("hasMore") or not data.get("cursor"):
            break
        cursor = data["cursor"]
    return items


def fetch_note(client: httpx.Client, note_id: str) -> dict | None:
    """The note with its transcript, or None when Granola doesn't have it ready yet (no summary or transcript)."""
    r = _get(client, f"/notes/{note_id}", {"include": "transcript"})
    if r.status_code == 404:
        return None
    if r.status_code == 413:
        r = _get(client, f"/notes/{note_id}")
        note = _check(r)
        note["transcript"] = _full_transcript(client, note_id)
        return note
    return _check(r)


def attendees_of(note: dict, my_email: str | None) -> list[dict]:
    """Everyone on the invite, with names from Granola's attendee list where it has them."""
    people: dict[str, dict] = {}
    for a in note.get("attendees") or []:
        if a.get("email"):
            people[a["email"].lower()] = {"name": a.get("name"), "email": a["email"]}
    for a in (note.get("calendar_event") or {}).get("invitees") or []:
        if a.get("email"):
            people.setdefault(a["email"].lower(), {"name": None, "email": a["email"]})
    me = (my_email or "").lower()
    return [{**p, "is_self": bool(me) and p["email"].lower() == me} for p in people.values()]


def meeting_from(note: dict, my_email: str | None) -> dict:
    event = note.get("calendar_event") or {}
    notes = (note.get("summary_markdown") or note.get("summary_text") or "").strip()
    private = (note.get("private_notes_markdown") or note.get("private_notes_text") or "").strip()
    if private:
        notes = f"{notes}\n\n## My notes during the meeting\n{private}".strip()
    return {
        "origin": "granola",
        "external_id": note["id"],
        "title": note.get("title") or event.get("event_title"),
        "started_at": event.get("scheduled_start_time") or note.get("created_at"),
        "attendees": attendees_of(note, my_email),
        "notes": notes or None,
        "transcript": transcript_text(note.get("transcript")) or None,
    }


# ── The sync ──────────────────────────────────────────────────────────

def _seen(note_id: str) -> bool:
    return db.one("SELECT 1 AS x FROM crm_inbox WHERE source = 'meeting' AND json_extract(payload, '$.origin') = 'granola' "
                  "AND json_extract(payload, '$.external_id') = ?", (note_id,)) is not None


def _since(state: dict, now: datetime) -> datetime:
    if state.get("window_from"):
        return datetime.fromisoformat(state["window_from"])
    days = int(settings.get_all().get("crm.granola_days") or 30)
    return now - timedelta(days=days)


def sync() -> dict:
    """One pass. Never raises for what's wrong with Granola or the key: it records it for the Settings page."""
    now = datetime.now(UTC)
    key = settings.get_all().get("crm.granola_api_key")
    if not key:
        return {"skipped": "no key"}
    state = capture.get_state("granola")
    counts = {"checked": 0, "imported": 0, "known": 0, "not_ready": 0, "failed": 0}
    me = store.get_me()
    my_email = ((me.attributes or {}).get("email") if me else None) or None
    auto = bool(settings.get_all().get("crm.granola_auto_apply"))
    start = _since(state, now)
    finished = True
    try:
        with _client(key) as client:
            cursor, pages = None, 0
            while pages < MAX_PAGES:
                params = {"created_after": start.isoformat(), "page_size": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
                data = _check(_get(client, "/notes", params))
                pages += 1
                for summary in data.get("notes") or []:
                    counts["checked"] += 1
                    if summary.get("deleted_at") or _seen(summary["id"]):
                        counts["known"] += 1
                        continue
                    try:
                        note = fetch_note(client, summary["id"])
                        if note is None:
                            counts["not_ready"] += 1
                            continue
                        meeting = meeting_from(note, my_email)
                        if not (meeting["notes"] or meeting["transcript"]):
                            counts["not_ready"] += 1
                            continue
                        _, already = ingest.create_meeting_job(**meeting, auto_apply=auto)
                        counts["known" if already else "imported"] += 1
                    except GranolaError:
                        raise
                    except Exception:  # noqa: BLE001 - one odd note must not stop the rest
                        log.exception("could not bring in Granola note %s", summary.get("id"))
                        counts["failed"] += 1
                if not data.get("hasMore") or not data.get("cursor"):
                    break
                cursor = data["cursor"]
            else:
                finished = False   # more than one run's worth: carry on from the same start next time
        # Next time, look back a few days from now rather than from this first start, so a note that only became
        # ready since is still found, and the listing stays short.
        capture.set_state("granola", error=None, key_problem=None, last_ok_at=db.now(), last_counts=counts,
                          window_from=(now - timedelta(days=LOOKBACK_DAYS)).isoformat() if finished else start.isoformat())
    except GranolaError as e:
        capture.set_state("granola", error=str(e), key_problem=e.key_problem or None)
        log.warning("Granola sync: %s", e)
    capture.set_state("granola", last_run_at=db.now())
    return counts


def handle_sync(job: jobs.Job) -> None:
    job.stage("Checking Granola")
    sync()


def seconds() -> int:
    """Every 15 minutes once there's a key; never before."""
    return 900 if configured() else 0


def test() -> dict:
    """Does the key work? Looks at one note, imports nothing."""
    key = settings.get_all().get("crm.granola_api_key")
    if not key:
        raise GranolaError("Paste a Granola API key first.")
    with _client(key) as client:
        data = _check(_get(client, "/notes", {"page_size": 1}))
    me = store.get_me()
    has_email = bool(me and (me.attributes or {}).get("email"))
    return {"ok": True, "has_notes": bool(data.get("notes")), "needs_my_email": not has_email}
