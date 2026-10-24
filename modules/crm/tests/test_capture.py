"""Granola and calendar sync: new meetings arrive on their own, are stamped with where they came from, join the
calendar's meeting, and can be taken back. Granola and the calendar are fakes (httpx's MockTransport); the AI is
conftest's fake_structured."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from crm_helpers import entity, extraction, link, make

from core.server import jobs, settings
from modules.crm.server import calendar_sync, capture, granola, ingest

NOW = datetime.now(UTC).replace(microsecond=0)


def stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


# ── A fake Granola ────────────────────────────────────────────────────

class FakeGranola:
    def __init__(self):
        self.notes: dict[str, dict] = {}
        self.calls: list[str] = []
        self.status: int | None = None          # answer everything with this
        self.too_large: set[str] = set()
        self.not_ready: set[str] = set()
        self.rate_limited = 0

    def add(self, note_id="not_aaaaaaaaaaaaaa", title="Helio pilot sync", start=None, attendees=(("Priya Nair", "priya@helio.example"),),
            summary="Priya shared pilot results and Frostline wants 50 trucks.", transcript=(("microphone", "So how did the pilot go?"), ("speaker", "It went well."))):
        start = start or NOW - timedelta(days=1)
        self.notes[note_id] = {
            "id": note_id, "object": "note", "title": title, "owner": {"name": "Alex Rivera", "email": "alex@cinderlabs.example"},
            "created_at": start.isoformat(), "updated_at": start.isoformat(), "deleted_at": None,
            "web_url": f"https://notes.granola.ai/{note_id}",
            "calendar_event": {"event_title": title, "invitees": [{"email": e} for _, e in attendees] + [{"email": "alex@cinderlabs.example"}],
                               "organiser": "alex@cinderlabs.example", "calendar_event_id": "x",
                               "scheduled_start_time": start.isoformat(), "scheduled_end_time": (start + timedelta(hours=1)).isoformat()},
            "attendees": [{"name": n, "email": e} for n, e in attendees],
            "summary_text": summary, "summary_markdown": summary, "private_notes_text": None, "private_notes_markdown": None,
            "transcript": [{"speaker": {"source": s}, "text": t, "start_time": start.isoformat(), "end_time": start.isoformat()}
                           for s, t in transcript],
        }
        return note_id

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if request.headers.get("authorization") != "Bearer grn_test":
            return httpx.Response(401, json={"error": "bad key"})
        if self.status:
            return httpx.Response(self.status, json={})
        if self.rate_limited:
            self.rate_limited -= 1
            return httpx.Response(429, headers={"retry-after": "0"}, json={})
        path = request.url.path.removeprefix("/v1")
        if path == "/notes":
            summaries = [{k: n[k] for k in ("id", "object", "title", "owner", "created_at", "updated_at", "deleted_at")}
                         for n in self.notes.values() if n["id"] not in self.not_ready]
            return httpx.Response(200, json={"notes": summaries, "hasMore": False, "cursor": None})
        parts = path.split("/")
        note = self.notes.get(parts[2]) if len(parts) > 2 else None
        if note is None or note["id"] in self.not_ready:
            return httpx.Response(404, json={})
        if len(parts) == 4:
            return httpx.Response(200, json={"transcript": note["transcript"], "hasMore": False, "cursor": None})
        if note["id"] in self.too_large and request.url.params.get("include"):
            return httpx.Response(413, json={"code": "TRANSCRIPT_TOO_LARGE"})
        if not request.url.params.get("include"):
            note = {**note, "transcript": None}
        return httpx.Response(200, json=note)


@pytest.fixture
def fake_granola(monkeypatch):
    fake = FakeGranola()
    monkeypatch.setattr(granola, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(granola, "PACE_SECONDS", 0)
    settings.update({"crm.granola_api_key": "grn_test"})
    return fake


def run_granola():
    counts = granola.sync()
    jobs.drain()
    return counts


@pytest.fixture
def me(client):
    return client.put("/api/crm/me", json={"name": "Alex Rivera"}).json()


def meetings(client):
    return client.get("/api/crm/entities", params={"kind": "meeting"}).json()["items"]


# ── Granola ───────────────────────────────────────────────────────────

def test_a_new_granola_meeting_is_read_and_added_with_its_source_marked(client, fake_granola, fake_structured, me):
    client.patch(f"/api/crm/entities/{me['id']}", json={"attributes": {"email": "alex@cinderlabs.example"}})
    fake_granola.add()
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee", email="priya@helio.example")],
                                       title="Helio pilot sync", summary="Pilot results.", tags=["pilot"])
    assert run_granola() == {"checked": 1, "imported": 1, "known": 0, "not_ready": 0, "failed": 0}
    [m] = meetings(client)
    assert m["source"] == "granola" and m["name"] == "Helio pilot sync" and m["tags"] == ["pilot"]   # no "granola" tag
    people = {p["name"]: p for p in client.get("/api/crm/entities", params={"kind": "person"}).json()["items"]}
    assert people["Priya Nair"]["source"] == "granola" and people["Priya Nair"]["attributes"]["email"] == "priya@helio.example"
    assert people["Alex Rivera"]["source"] == "manual"                  # you are not stamped, or removed
    detail = client.get(f"/api/crm/entities/{m['id']}").json()
    assert {r["source"] for r in detail["relationships"]} == {"granola"}
    prompt = fake_structured.calls[0]["prompt"]
    assert "Priya Nair <priya@helio.example>" in prompt and "alex@cinderlabs.example" in prompt and "(the CRM owner)" in prompt
    assert "Me: So how did the pilot go?" in prompt and "Others: It went well." in prompt


def test_running_it_again_adds_nothing_and_asks_granola_for_each_note_only_once(client, fake_granola, fake_structured, me):
    fake_granola.add()
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    run_granola()
    fetches = len([c for c in fake_granola.calls if c.endswith("not_aaaaaaaaaaaaaa")])
    assert run_granola() == {"checked": 1, "imported": 0, "known": 1, "not_ready": 0, "failed": 0}
    assert len([c for c in fake_granola.calls if c.endswith("not_aaaaaaaaaaaaaa")]) == fetches
    assert len(meetings(client)) == 1


def test_a_note_granola_has_not_finished_is_picked_up_on_a_later_run(client, fake_granola, fake_structured, me):
    fake_granola.add()
    fake_granola.not_ready.add("not_aaaaaaaaaaaaaa")
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    assert run_granola()["checked"] == 0
    fake_granola.not_ready.clear()
    assert run_granola()["imported"] == 1


def test_a_transcript_too_large_to_send_is_read_in_pages(client, fake_granola, fake_structured, me):
    fake_granola.add()
    fake_granola.too_large.add("not_aaaaaaaaaaaaaa")
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    assert run_granola()["imported"] == 1
    assert any(c.endswith("/transcript") for c in fake_granola.calls)
    assert "Others: It went well." in fake_structured.calls[0]["prompt"]


def test_a_key_granola_refuses_is_recorded_for_the_settings_page_and_nothing_else_happens(client, fake_granola, me):
    settings.update({"crm.granola_api_key": "wrong"})
    fake_granola.add()
    granola.sync()
    state = client.get("/api/crm/capture").json()["granola"]
    assert state["configured"] and state["key_problem"] and "didn't accept the key" in state["error"]
    assert meetings(client) == []
    settings.update({"crm.granola_api_key": "grn_test"})
    granola.sync()
    assert client.get("/api/crm/capture").json()["granola"]["error"] is None


def test_a_busy_granola_is_retried(client, fake_granola, fake_structured, me, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    fake_granola.add()
    fake_granola.rate_limited = 2
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    assert run_granola()["imported"] == 1


def test_trying_a_key_says_what_is_missing_and_imports_nothing(client, fake_granola, me):
    fake_granola.add()
    r = client.post("/api/crm/capture/granola/test")
    assert r.status_code == 200 and r.json() == {"ok": True, "has_notes": True, "needs_my_email": True}
    assert meetings(client) == []
    settings.update({"crm.granola_api_key": "wrong"})
    assert client.post("/api/crm/capture/granola/test").status_code == 422


def test_it_does_nothing_without_a_key_and_is_not_scheduled(client):
    assert granola.sync() == {"skipped": "no key"} and granola.seconds() == 0
    settings.update({"crm.granola_api_key": "grn_test"})
    assert granola.seconds() == 900


def test_everything_from_granola_can_be_taken_back_and_does_not_come_back(client, fake_granola, fake_structured, me):
    known = make(client, "person", "Tom Albright", attributes={"email": "tom@frostline.example"})
    fake_granola.add(attendees=(("Priya Nair", "priya@helio.example"), ("Tom Albright", "tom@frostline.example")))
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee"), entity("p2", "Tom Albright", role="attendee")])
    run_granola()
    assert len(meetings(client)) == 1
    plan = client.get("/api/crm/capture/granola/preview").json()
    assert plan["meetings"] == 1 and plan["people"] == 1                  # Priya was made by it; Tom was already here
    assert client.post("/api/crm/capture/granola/remove").json()["meetings"] == 1
    names = [p["name"] for p in client.get("/api/crm/entities", params={"kind": "person"}).json()["items"]]
    assert "Priya Nair" not in names and "Tom Albright" in names and meetings(client) == []
    assert client.get(f"/api/crm/entities/{known['id']}").json()["relationships"] == []
    assert run_granola()["imported"] == 0                                 # the same note is not brought in again


# ── The calendar feed ─────────────────────────────────────────────────

def ics(*events, name="Work"):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:" + name + "\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def vevent(uid, title, start, attendees=(), extra=""):
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTART:{stamp(start)}", f"DTEND:{stamp(start + timedelta(hours=1))}", f"SUMMARY:{title}"]
    lines += [f"ATTENDEE;CN=\"{n}\";PARTSTAT={s}:mailto:{e}" for n, e, s in attendees]
    return "\r\n".join(lines) + "\r\n" + extra + "END:VEVENT\r\n"


MARK = ("Alex Rivera", "alex@cinderlabs.example", "ACCEPTED")
PRIYA = ("Priya Nair", "priya@helio.example", "ACCEPTED")


class FakeCalendar:
    def __init__(self):
        self.text = ics()
        self.status = 200

    def __call__(self, request):
        return httpx.Response(self.status, text=self.text)


@pytest.fixture
def fake_calendar(monkeypatch):
    fake = FakeCalendar()
    monkeypatch.setattr(calendar_sync, "_transport", httpx.MockTransport(fake))
    settings.update({"crm.calendar_secret": "webcal://calendar.example/private-abc123/basic.ics"})
    return fake


@pytest.fixture
def priya(client, me):
    client.patch(f"/api/crm/entities/{me['id']}", json={"attributes": {"email": "alex@cinderlabs.example"}})
    return make(client, "person", "Priya Nair", attributes={"email": "priya@helio.example"})


def test_the_reader_handles_zones_repeats_edits_and_all_day_events():
    from modules.crm.server.ics import parse
    text = ics(
        "BEGIN:VEVENT\r\nUID:a\r\nDTSTART;TZID=America/Los_Angeles:20261012T090000\r\nDTEND;TZID=America/Los_Angeles:20261012T093000\r\n"
        "SUMMARY:Standup\\, daily\r\nRRULE:FREQ=DAILY;COUNT=5\r\nEXDATE;TZID=America/Los_Angeles:20261014T090000\r\n"
        "ATTENDEE;CN=Priya Nair;PARTSTAT=DECLINED:mailto:Priya@Helio.example\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:a\r\nRECURRENCE-ID;TZID=America/Los_Angeles:20261013T090000\r\nDTSTART;TZID=America/Los_Angeles:20261013T110000\r\n"
        "SUMMARY:Standup (moved)\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:b\r\nDTSTART;VALUE=DATE:20261012\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:c\r\nDTSTART:20261012T170000Z\r\nSUMMARY:Cancelled thing\r\nSTATUS:CANCELLED\r\nEND:VEVENT\r\n")
    name, events = parse(text, datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC))
    assert name == "Work"
    standups = [e for e in events if e.uid == "a"]
    assert [e.start.isoformat() for e in standups] == ["2026-10-12T16:00:00+00:00", "2026-10-13T18:00:00+00:00", "2026-10-15T16:00:00+00:00", "2026-10-16T16:00:00+00:00"]
    assert standups[1].title == "Standup (moved)" and standups[0].title == "Standup, daily"
    assert standups[0].invitees[0].email == "priya@helio.example" and standups[0].invitees[0].status == "DECLINED"
    assert not any(e.uid == "b" for e in events) and next(e for e in events if e.uid == "c").cancelled


def test_a_calendar_event_with_someone_you_know_becomes_a_meeting_marked_as_from_the_calendar(client, fake_calendar, priya):
    start = NOW - timedelta(days=2)
    fake_calendar.text = ics(
        vevent("1", "Helio check-in", start, [MARK, PRIYA, ("Stranger", "stranger@elsewhere.example", "ACCEPTED")]),
        vevent("2", "Strangers only", start, [MARK, ("Stranger", "stranger@elsewhere.example", "ACCEPTED")]),
        vevent("3", "Declined by me", start, [("Alex Rivera", "alex@cinderlabs.example", "DECLINED"), PRIYA]),
        vevent("4", "Focus time", start, [MARK]))
    assert calendar_sync.sync() == {"calendars": 1, "events": 4, "meetings": 1, "removed": 0}
    [m] = meetings(client)
    assert m["name"] == "Helio check-in" and m["source"] == "calendar"
    assert m["attributes"]["invitees_not_in_people"] == ["stranger@elsewhere.example"]
    people = client.get("/api/crm/entities", params={"kind": "person"}).json()["items"]
    assert sorted(p["name"] for p in people) == ["Alex Rivera", "Priya Nair"]          # strangers are not made people
    detail = client.get(f"/api/crm/entities/{m['id']}").json()
    assert len(detail["relationships"]) == 2 and {r["source"] for r in detail["relationships"]} == {"calendar"}


def test_syncing_again_changes_nothing_and_a_moved_or_cancelled_event_follows_the_calendar(client, fake_calendar, priya):
    start = NOW - timedelta(days=2)
    fake_calendar.text = ics(vevent("1", "Helio check-in", start, [MARK, PRIYA]))
    calendar_sync.sync()
    calendar_sync.sync()
    assert len(meetings(client)) == 1
    fake_calendar.text = ics(vevent("1", "Helio check-in", start + timedelta(hours=2), [MARK, PRIYA]))
    calendar_sync.sync()
    # a moved event is a different occurrence (the key holds the start), so the old one goes and a new one is made
    [m] = meetings(client)
    assert m["occurred_at"].startswith((start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))
    fake_calendar.text = ics()
    assert calendar_sync.sync()["removed"] == 1 and meetings(client) == []


def test_a_calendar_that_cannot_be_read_leaves_everything_as_it_was(client, fake_calendar, priya):
    fake_calendar.text = ics(vevent("1", "Helio check-in", NOW - timedelta(days=1), [MARK, PRIYA]))
    calendar_sync.sync()
    fake_calendar.status = 404
    calendar_sync.sync()
    assert len(meetings(client)) == 1
    state = client.get("/api/crm/capture").json()["calendar"]
    assert "didn't accept that address" in state["error"]
    assert client.post("/api/crm/capture/calendar/test").status_code == 422


def test_a_meeting_still_to_come_is_not_counted_as_having_met(client, fake_calendar, priya):
    fake_calendar.text = ics(vevent("1", "Next week", NOW + timedelta(days=3), [MARK, PRIYA]),
                             vevent("2", "Last week", NOW - timedelta(days=3), [MARK, PRIYA]))
    calendar_sync.sync()
    assert len(meetings(client)) == 2
    conn = client.get(f"/api/crm/entities/{priya['id']}/context").json()["connection"]
    assert conn["meetings"] == 1


def test_a_granola_note_joins_the_calendar_meeting_instead_of_making_a_second(client, fake_calendar, fake_granola, fake_structured, priya):
    start = NOW - timedelta(days=1)
    fake_calendar.text = ics(vevent("1", "Helio pilot sync", start, [MARK, PRIYA]))
    calendar_sync.sync()
    fake_granola.add(start=start)
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")], title="Helio pilot sync", summary="Pilot results.",
                                       key_points=["Frostline wants 50 trucks"])
    assert run_granola()["imported"] == 1
    [m] = meetings(client)
    assert m["summary"] == "Pilot results." and m["attributes"]["external_ids"] == {"calendar": m["attributes"]["external_ids"]["calendar"], "granola": "not_aaaaaaaaaaaaaa"}
    assert "Frostline wants 50 trucks" in m["attributes"]["key_points"]


def test_removing_the_calendars_events_leaves_a_meeting_notes_have_since_been_written_into(client, fake_calendar, fake_granola, fake_structured, priya):
    start = NOW - timedelta(days=1)
    other = NOW - timedelta(days=4)
    fake_calendar.text = ics(vevent("1", "Helio pilot sync", start, [MARK, PRIYA]), vevent("2", "Coffee", other, [MARK, PRIYA]))
    calendar_sync.sync()
    fake_granola.add(start=start)
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")], title="Helio pilot sync", summary="Pilot results.")
    run_granola()
    assert client.get("/api/crm/capture/calendar/preview").json() | {} == {"origin": "calendar", "label": "Calendar", "meetings": 1, "people": 0, "kept": 1, "lines": 0}
    client.post("/api/crm/capture/calendar/remove")
    assert [m["name"] for m in meetings(client)] == ["Helio pilot sync"]
    line_sources = {r["source"] for r in client.get(f"/api/crm/entities/{meetings(client)[0]['id']}").json()["relationships"]}
    assert "calendar" in line_sources                                     # the kept meeting keeps its attendees


def test_pasting_a_key_or_address_tries_it_straight_away(client, fake_granola, fake_calendar, fake_structured, priya):
    fake_granola.add(start=NOW - timedelta(days=6))
    fake_calendar.text = ics(vevent("1", "Helio check-in", NOW - timedelta(days=1), [MARK, PRIYA]))
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    client.put("/api/settings", json={"crm.granola_api_key": "grn_test", "crm.calendar_secret": "https://calendar.example/x/basic.ics"})
    jobs.drain()
    assert {m["source"] for m in meetings(client)} >= {"calendar", "granola"}
