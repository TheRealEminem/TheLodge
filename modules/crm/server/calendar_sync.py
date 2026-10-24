"""Calendars through their secret iCal addresses (no sign-in): meetings are on the book before they happen, with
who is invited, so notes that arrive later join the same meeting by time and people.

Google Calendar: Settings for the calendar, Integrate calendar, "Secret address in iCal format". Anyone with the
address can read the calendar, so it is kept like a key.

What becomes a meeting: a timed event in the last week or the next two, that you haven't declined or cancelled, with
2 to 20 invitees, at least one of whom is someone already in your people (matched by email). Invitees The Lodge
doesn't know aren't added as people (a calendar is full of strangers); their emails are kept on the meeting, and a
note taken at the meeting adds them properly. An event that's later cancelled or removed from the calendar is
removed again, unless something has been written into it since. Everything made here is stamped source "calendar".
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx

from core.server import db, jobs, lockdown, settings

from . import capture, store
from .ics import Event, parse

log = logging.getLogger("crm.calendar")

PAST_DAYS = 7
AHEAD_DAYS = 14
MAX_INVITEES = 20
MAX_BYTES = 20 * 1024 * 1024

_transport: httpx.BaseTransport | None = None   # tests put a fake one here


class CalendarError(RuntimeError):
    pass


def feeds() -> list[str]:
    raw = settings.get_all().get("crm.calendar_secret") or ""
    urls = [u.strip() for u in raw.replace(",", " ").split() if u.strip()]
    return ["https://" + u[len("webcal://"):] if u.lower().startswith("webcal://") else u for u in urls]


def configured() -> bool:
    return bool(feeds())


def locked() -> str | None:
    """Why calendar sync is off right now (Lockdown), or None."""
    return lockdown.blocked("Reading your calendars")


def seconds() -> int:
    """Hourly once there's an address; never before."""
    return 3600 if configured() and not locked() else 0


def _label(url: str) -> str:
    """Enough to tell feeds apart without showing the secret in the address."""
    host = url.split("/")[2] if "//" in url else url
    return f"{host}…{url[-4:]}"


def fetch(url: str) -> str:
    if not url.lower().startswith(("https://", "http://")):
        raise CalendarError("That isn't a web address.")
    try:
        with httpx.Client(timeout=30, follow_redirects=True, transport=_transport) as client:
            r = client.get(url)
    except httpx.HTTPError as e:
        raise CalendarError(f"Couldn't reach the calendar ({type(e).__name__}).") from e
    if r.status_code in (401, 403, 404):
        raise CalendarError("The calendar didn't accept that address. Copy the secret iCal address again.")
    if r.status_code >= 400:
        raise CalendarError(f"The calendar answered {r.status_code}.")
    if len(r.content) > MAX_BYTES:
        raise CalendarError("The calendar file is larger than 20 MB.")
    if "BEGIN:VCALENDAR" not in r.text[:2000].upper():
        raise CalendarError("That address isn't an iCal calendar.")
    return r.text


def _people_by_email() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in store.all_entities("person"):
        email = (p.attributes or {}).get("email")
        if email:
            out[email.strip().lower()] = p.id
    return out


def _wanted(event: Event, my_email: str | None) -> bool:
    if event.cancelled or not (2 <= len(event.invitees) <= MAX_INVITEES):
        return False
    return not any(i.email == my_email and i.status == "DECLINED" for i in event.invitees)


def _existing(key: str):
    row = db.one("SELECT id FROM crm_entities WHERE kind = 'meeting' AND json_extract(attributes, '$.external_ids.calendar') = ?", (key,))
    return store.get_entity(row["id"]) if row else None


def _upsert(event: Event, people: dict[str, str], me, my_email: str | None, calendar_name: str | None) -> str | None:
    """The meeting's id, or None when nobody on it is someone you know."""
    known = {i.email: people[i.email] for i in event.invitees
             if i.email in people and i.email != my_email and i.status != "DECLINED"}
    if not known:
        return None
    strangers = sorted(i.email for i in event.invitees if i.email not in people and i.email != my_email)
    meeting = _existing(event.key)
    if meeting is None:
        attrs = {"external_ids": {"calendar": event.key}, "calendar": calendar_name, "invitees_not_in_people": strangers}
        if event.location:
            attrs["location"] = event.location
        meeting = store.create_entity("meeting", event.title, attributes=attrs, occurred_at=event.start, source="calendar")
    else:
        attrs = {**(meeting.attributes or {}), "invitees_not_in_people": strangers}
        fields: dict = {"attributes": attrs}
        if meeting.occurred_at != event.start:
            fields["occurred_at"] = event.start
        if meeting.source == "calendar" and meeting.name != event.title and not meeting.summary:
            fields["name"] = event.title
        store.update_entity(meeting.id, **fields)
    for person_id in [*known.values(), *([me.id] if me else [])]:
        store.upsert_edge(person_id, meeting.id, "attended", source="calendar")
    return meeting.id


def _plain_calendar_meeting(meeting_id: str) -> bool:
    """Still only what the calendar made: nothing has been written into it."""
    m = store.get_entity(meeting_id)
    if m is None or m.source != "calendar" or m.summary:
        return False
    attrs = m.attributes or {}
    return not ({*(attrs.get("external_ids") or {})} - {"calendar"} or attrs.get("key_points") or attrs.get("action_items")
                or store.notes_of(meeting_id))


def sync() -> dict:
    """One pass over every address. Records what went wrong for the Settings page instead of raising."""
    now = datetime.now(UTC)
    if locked():
        return {"skipped": "lockdown"}
    addresses = feeds()
    if not addresses:
        return {"skipped": "no address"}
    lo, hi = now - timedelta(days=PAST_DAYS), now + timedelta(days=AHEAD_DAYS)
    me = store.get_me()
    my_email = ((me.attributes or {}).get("email") or "").strip().lower() or None if me else None
    people = _people_by_email()
    counts = {"calendars": 0, "events": 0, "meetings": 0, "removed": 0}
    names: list[str] = []
    kept: set[str] = set()
    problems: list[str] = []
    for url in addresses:
        try:
            name, events = parse(fetch(url), lo, hi)
        except CalendarError as e:
            problems.append(f"{_label(url)}: {e}")
            continue
        counts["calendars"] += 1
        names.append(name or _label(url))
        counts["events"] += len(events)
        for event in events:
            if _wanted(event, my_email) and (meeting_id := _upsert(event, people, me, my_email, name)):
                kept.add(meeting_id)
                counts["meetings"] += 1
    if not problems:
        # Calendar meetings in the window that are no longer on any calendar (cancelled, deleted, or you declined).
        for r in db.query("SELECT id FROM crm_entities WHERE kind = 'meeting' AND source = 'calendar' AND occurred_at BETWEEN ? AND ?",
                          (store.iso(lo), store.iso(hi))):
            if r["id"] not in kept and _plain_calendar_meeting(r["id"]):
                store.delete_entity(r["id"])
                counts["removed"] += 1
    capture.set_state("calendar", last_run_at=db.now(), calendars=names, error="; ".join(problems) or None,
                      **({"last_ok_at": db.now(), "last_counts": counts} if not problems else {}))
    return counts


def handle_sync(job: jobs.Job) -> None:
    job.stage("Reading calendars")
    sync()


def test() -> dict:
    """Do the addresses work? Reads them and says what it found, adds nothing."""
    if (why := locked()):
        raise CalendarError(why)
    addresses = feeds()
    if not addresses:
        raise CalendarError("Paste a calendar's secret iCal address first.")
    now = datetime.now(UTC)
    found = []
    for url in addresses:
        name, events = parse(fetch(url), now - timedelta(days=PAST_DAYS), now + timedelta(days=AHEAD_DAYS))
        found.append({"name": name or _label(url), "events": len(events)})
    return {"ok": True, "calendars": found}
