"""Trailmix sync: meetings recorded on this Mac come in on their own, once each, without the workspaces you leave
out, and a meeting Trailmix took from Granola isn't brought in again by the Granola sync. Trailmix is a fake (httpx's
MockTransport) answering the way its /api/meetings does; the AI is conftest's fake_structured."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from crm_helpers import entity, extraction
from test_capture import fake_granola, me, meetings, run_granola  # noqa: F401 - fixtures and helpers

from core.server import db, jobs, settings
from modules.crm.server import hats, trailmix

NOW = datetime.now(UTC).replace(microsecond=0)


class FakeTrailmix:
    def __init__(self):
        self.meetings: dict[int, dict] = {}
        self.calls: list[str] = []
        self.down = False

    def add(self, mid=1, title="Helio pilot sync", days_ago=1, workspace=1, status="done", source=None, external_id=None,
            summary="Priya shared pilot results and Frostline wants 50 trucks.", tasks=("Send Priya the pricing",)):
        self.meetings[mid] = {
            "id": mid, "uid": f"uid{mid:029d}", "title": title, "created_at": (NOW - timedelta(days=days_ago)).isoformat(),
            "duration_sec": 1800.0, "status": status, "workspace_id": workspace, "ask_first": 0, "merges_to_review": 0, "tags": [],
            "source": source, "external_id": external_id, "summary": summary, "transcript": "[00:00] You: So how did it go?",
            "segments": [{"start": 0.0, "end": 2.0, "speaker": "You", "text": "So how did the pilot go?"},
                         {"start": 2.0, "end": 4.0, "speaker": "Them", "text": "It went well."},
                         {"start": 4.0, "end": 5.0, "speaker": "Them", "text": "Fifty trucks."}],
            "speaker_names": {"You": "Alex", "Them": "Priya Nair"},
            "tasks": [{"id": i, "text": t, "done": False} for i, t in enumerate(tasks)], "my_notes": [],
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("refused")
        path = request.url.path
        if path == "/api/meetings":
            keys = ("id", "title", "created_at", "duration_sec", "status", "workspace_id", "ask_first", "merges_to_review", "tags")
            return httpx.Response(200, json=[{k: m[k] for k in keys} for m in self.meetings.values()])
        if path == "/api/workspaces":
            return httpx.Response(200, json=[{"id": 1, "name": "Work", "meetings": 2}, {"id": 3, "name": "Personal", "meetings": 1}])
        m = self.meetings.get(int(path.rsplit("/", 1)[1]))
        return httpx.Response(200, json=m) if m else httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture
def fake_trailmix(monkeypatch):
    fake = FakeTrailmix()
    monkeypatch.setattr(trailmix, "_transport", httpx.MockTransport(fake))
    settings.update({"crm.trailmix_sync": True})
    yield fake
    settings.update({"crm.trailmix_sync": False, "crm.trailmix_skip_workspaces": [], "crm.trailmix_days": 90})


def run():
    counts = trailmix.sync()
    jobs.drain()
    return counts


def test_a_trailmix_meeting_is_read_and_added_with_its_source_marked(client, fake_trailmix, fake_structured, me):  # noqa: F811
    fake_trailmix.add()
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")], title="Helio pilot sync")
    assert run()["imported"] == 1
    [m] = meetings(client)
    assert m["source"] == "trailmix" and m["attributes"]["external_ids"] == {"trailmix": "uid" + "0" * 28 + "1"}
    prompt = fake_structured.calls[0]["prompt"]
    assert "Me: So how did the pilot go?" in prompt and "Priya Nair: It went well. Fifty trucks." in prompt
    assert "Attendees: Priya Nair" in prompt and "- Send Priya the pricing" in prompt


def test_running_again_adds_nothing_and_a_meeting_still_being_written_waits(client, fake_trailmix, fake_structured, me):  # noqa: F811
    fake_trailmix.add()
    fake_trailmix.add(2, title="Board prep", status="summarizing")
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    assert run()["imported"] == 1
    again = run()
    assert again["imported"] == 0 and again["known"] == 1 and again["not_ready"] == 1 and again["total"] == 1
    fake_trailmix.meetings[2]["status"] = "done"
    assert run()["imported"] == 1


def test_left_out_workspaces_and_older_meetings_never_come_in(client, fake_trailmix, fake_structured, me):  # noqa: F811
    settings.update({"crm.trailmix_skip_workspaces": ["3"], "crm.trailmix_days": 30})
    fake_trailmix.add(1)
    fake_trailmix.add(2, title="Dentist", workspace=3)
    fake_trailmix.add(3, title="Old intro", days_ago=200)
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    counts = run()
    assert counts["imported"] == 1 and counts["left_out"] == 1 and counts["checked"] == 2
    fake_trailmix.add(4, title="Next week", days_ago=0)
    assert run()["imported"] == 1                                       # the window stays where the first run put it


def test_a_meeting_trailmix_took_from_granola_comes_in_once(client, fake_trailmix, fake_granola, fake_structured, me):  # noqa: F811
    fake_granola.add("not_aaaaaaaaaaaaaa")
    fake_trailmix.add(source="granola", external_id="not_aaaaaaaaaaaaaa")
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    assert run()["imported"] == 1
    assert run_granola()["imported"] == 0
    [m] = meetings(client)
    assert set(m["attributes"]["external_ids"]) == {"trailmix", "granola"}


def test_a_trailmix_that_isnt_running_is_said_for_settings_and_nothing_else_happens(client, fake_trailmix, me):  # noqa: F811
    fake_trailmix.down = True
    run()
    status = client.get("/api/crm/capture").json()["trailmix"]
    assert status["configured"] and "isn't answering" in status["error"]
    assert client.post("/api/crm/capture/trailmix/test").status_code == 422
    fake_trailmix.down = False
    fake_trailmix.add()
    found = client.post("/api/crm/capture/trailmix/test").json()
    assert found["done"] == 1 and found["workspaces"][1]["name"] == "Personal" and meetings(client) == []


def test_it_is_off_until_you_turn_it_on(client):
    assert trailmix.seconds() == 0 and trailmix.sync() == {"skipped": "off"}
    assert not client.get("/api/crm/capture").json()["trailmix"]["configured"]


def test_a_workspace_is_a_hat_and_a_meeting_wears_it_with_its_tags(client, fake_trailmix, fake_structured, me):  # noqa: F811
    fake_trailmix.add()
    fake_trailmix.meetings[1]["tags"] = ["Cold Chain", "pilot"]
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")], title="Helio pilot sync")
    run()
    [m] = meetings(client)
    work = next(h for h in client.get("/api/crm/hats").json()["hats"] if h["name"] == "Work")
    assert work["workspace"] == 1 and hats.source_hat(m["id"]) == work["id"]
    assert set(m["tags"]) >= {"cold-chain", "pilot"}
    assert [r["person"]["name"] for r in client.get("/api/crm/people", params={"hat": work["id"]}).json()["items"]] == ["Priya Nair"]

    # Filed elsewhere and retagged in Trailmix: it follows, with no second copy.
    fake_trailmix.meetings[1].update(workspace_id=3, tags=["pilot", "renewal"])
    run()
    [m] = meetings(client)
    personal = next(h for h in client.get("/api/crm/hats").json()["hats"] if h["name"] == "Personal")
    assert hats.source_hat(m["id"]) == personal["id"]
    assert "cold-chain" not in m["tags"] and {"pilot", "renewal"} <= set(m["tags"])


def test_only_the_tags_and_workspaces_you_chose_come_in(client, fake_trailmix, fake_structured, me):  # noqa: F811
    fake_trailmix.add(1, title="Tagged")
    fake_trailmix.meetings[1]["tags"] = ["parks"]
    fake_trailmix.add(2, title="Not tagged")
    fake_trailmix.add(3, title="No workspace", workspace=None)
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    settings.update({"crm.trailmix_only_tags": ["Parks"]})
    try:
        assert run()["imported"] == 1
        settings.update({"crm.trailmix_only_tags": [], "crm.trailmix_skip_workspaces": ["0", "1"]})
        counts = run()
        assert counts["imported"] == 0 and counts["left_out"] == 3
    finally:
        settings.update({"crm.trailmix_only_tags": []})


def test_a_meeting_waiting_for_review_stops_waiting_once_it_is_left_out_and_can_come_back(client, fake_trailmix, fake_structured, me):  # noqa: F811
    fake_trailmix.add()
    fake_structured.reply = extraction([entity("p1", "Priya Nair", role="attendee")])
    settings.update({"crm.trailmix_auto_apply": False})
    try:
        run()
        assert db.one("SELECT status FROM crm_inbox WHERE source = 'meeting'")["status"] == "review"
        settings.update({"crm.trailmix_skip_workspaces": ["1"]})
        run()
        assert db.one("SELECT status FROM crm_inbox WHERE source = 'meeting'")["status"] == "skipped"
        settings.update({"crm.trailmix_skip_workspaces": []})
        assert run()["imported"] == 1
    finally:
        settings.update({"crm.trailmix_auto_apply": True})
