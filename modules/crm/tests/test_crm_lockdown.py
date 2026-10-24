"""Lockdown, for the People module: Gemini research, Granola, the calendars, the shared Sheet and picture look-ups each
stop, their scheduled turns queue nothing, and Settings says why. Every outward path runs with a guard that fails any
request to another computer, so a new feature that reaches out must add itself here (core/tests/test_lockdown.py is
the host's half). Everything that works on data already here is unaffected."""
import httpx
import pytest
from crm_helpers import make

from core.server import jobs, lockdown, schedule, settings

from modules.crm.server import calendar_sync, gemini_research, granola, ingest, pictures, sheet_sync, store


@pytest.fixture
def locked(monkeypatch):
    sent: list[str] = []

    def guard(self, request, *a, **kw):
        if request.url.host not in ("localhost", "127.0.0.1", "::1"):
            sent.append(str(request.url))
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guard)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guard)
    set_up = {"crm.granola_api_key": "grn_test_key_123456", "crm.calendar_secret": "https://calendar.example.com/ical/secret.ics",
              "crm.sheet_secret": "https://script.example.com/macros/s/abc/exec", "crm.gravatar": True,
              "ai.gemini_api_key": "gem-test-key-123456", lockdown.KEY: True}
    before = {k: settings.get_all()[k] for k in set_up}
    settings.update(set_up)
    yield sent
    settings.update(before)


def test_nothing_reaches_out_and_each_says_why(locked, client):
    ana = make(client, "person", "Ana Ruiz", attributes={"email": "ana@helio.example"})

    # Their own turns on the clock queue nothing
    for every in (granola.seconds, calendar_sync.seconds, sheet_sync.seconds, gemini_research.seconds):
        assert every() == 0
    schedule.tick(now=10 ** 9)
    jobs.drain()

    # Syncing by hand does nothing, and trying says why
    for sync in (granola.sync, calendar_sync.sync, sheet_sync.sync):
        assert sync() == {"skipped": "lockdown"}
    for test in (granola.test, calendar_sync.test, sheet_sync.test):
        with pytest.raises(Exception, match="Lockdown"):
            test()
    with pytest.raises(gemini_research.ResearchRunError, match="Lockdown"):
        gemini_research.start([ana["id"]], "better", True)
    jobs.enqueue("crm", "research_advance", "scheduled")          # a run already under way waits, and sends nothing
    jobs.drain()
    assert client.post(f"/api/crm/people/{ana['id']}/picture/lookup").status_code == 422
    assert client.post("/api/crm/pictures/lookup").status_code == 422

    # Settings says why
    status = client.get("/api/crm/capture").json()
    assert "Lockdown" in status["granola"]["locked"] and "Lockdown" in status["calendar"]["locked"]
    assert "Lockdown" in client.get("/api/crm/sheet").json()["locked"]
    assert not gemini_research.overview()["ready"] and "Lockdown" in gemini_research.overview()["reason"]
    assert "Lockdown" in client.get("/api/crm/pictures/lookup").json()["reason"]

    assert locked == []                                            # not one request left this computer


def test_what_stays_on_this_mac_still_works(locked, client):
    settings.update({"crm.extraction_provider": "rules", "crm.utility_provider": "rules"})
    brief = client.get(f"/api/crm/people/{make(client, 'person', 'Ana Ruiz')['id']}/research/brief")
    assert brief.status_code == 200 and brief.json()["text"]       # "Copy research brief": you take it elsewhere yourself
    note = client.post("/api/crm/ingest/notes", json={"text": "Attendees: Ana Ruiz\nA short chat about the depot pilot, with enough words to read."})
    assert note.status_code == 202
    jobs.drain()
    assert client.get("/api/crm/entities", params={"q": "Ana Ruiz"}).json()["total"] >= 1
    assert client.post("/api/export").status_code in (200, 201)
    assert locked == []


def test_everything_returns_when_lockdown_goes_off(locked, client):
    settings.update({lockdown.KEY: False})
    assert granola.locked() is None and calendar_sync.seconds() == 3600 and sheet_sync.seconds() > 0
    assert pictures.blocked() is None
