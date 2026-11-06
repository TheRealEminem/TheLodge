"""The day's briefing (core/server/briefing.py): every module's part, merged; refs, titles and hrefs filled in; a module
that fails left out rather than breaking the rest. Uses stand-in modules, so it holds whatever modules an app has."""
from datetime import date

import pytest

from core.server import briefing, module

TODAY = date(2026, 10, 21)


@pytest.fixture
def stand_ins():
    """Registers stand-in modules with a brief for one test, and takes them away again."""
    added = []

    def add(module_id: str, brief, describe=None):
        module.register(module.Module(id=module_id, name=module_id.title(), brief=brief, describe=describe))
        added.append(module_id)

    yield add
    for module_id in added:
        module._loaded.pop(module_id, None)


def _of(found: dict, module_id: str) -> dict:
    return {s: [e for e in entries if e["module"] == module_id] for s, entries in found["sections"].items()}


def test_each_modules_part_is_merged_with_its_refs(stand_ins):
    asked = []

    def brief(since, today):
        asked.append((since, today))
        return {"today": [{"id": "a1", "title": "Ring the hut", "href": "#/ridge/a1", "what": "Due today", "tone": "sun",
                           "when": "2026-10-21", "minutes": 20}],
                "moved": [{"id": "a2", "what": "Done", "who": "Sam", "project": "Hut", "tone": "forest"}],
                "nonsense": [{"id": "x", "what": "Ignored"}]}

    stand_ins("ridge", brief, describe=lambda i: {"title": f"Thing {i}", "href": f"#/ridge/{i}"})
    found = briefing.gather("2026-10-20T07:00:00.000Z", TODAY)
    assert asked == [("2026-10-20T07:00:00.000Z", TODAY)]
    assert (found["today"], found["since"], found["failed"]) == ("2026-10-21", "2026-10-20T07:00:00.000Z", [])
    mine = _of(found, "ridge")
    assert mine["today"] == [{"ref": "ridge:a1", "module": "ridge", "module_name": "Ridge", "title": "Ring the hut",
                              "href": "#/ridge/a1", "what": "Due today", "who": None, "when": "2026-10-21",
                              "project": None, "kind": None, "tone": "sun", "minutes": 20, "url": None}]
    moved = mine["moved"][0]
    assert (moved["title"], moved["href"], moved["who"], moved["project"]) == ("Thing a2", "#/ridge/a2", "Sam", "Hut")
    assert mine["waiting"] == mine["ahead"] == []
    assert set(found["sections"]) == {"today", "waiting", "moved", "ahead"}


def test_a_module_that_fails_is_left_out_and_named(stand_ins):
    def broken(since, today):
        raise RuntimeError("the hut burned down")

    stand_ins("ridge", lambda since, today: {"waiting": [{"id": "w", "title": "Sign the log", "href": "#/", "what": "Waiting",
                                                           "tone": "violet"}]})
    stand_ins("scree", broken)
    found = briefing.gather(None, TODAY)
    assert found["failed"] == ["Scree"]
    assert [e["title"] for e in _of(found, "ridge")["waiting"]] == ["Sign the log"]
    assert _of(found, "ridge")["waiting"][0]["tone"] == "neutral"      # not one of the family's tones
    assert found["since"] < briefing.stamp(briefing.datetime.now(briefing.timezone.utc))


def test_the_api_checks_its_moments(client, stand_ins):
    stand_ins("ridge", lambda since, today: {"ahead": [{"id": "c", "title": "Cycle", "href": "#/", "what": f"{today}"}]})
    found = client.get("/api/briefing", params={"since": "2026-10-20T07:00:00Z", "today": "2026-10-24"}).json()
    assert _of(found, "ridge")["ahead"][0]["what"] == "2026-10-24"
    assert client.get("/api/briefing", params={"today": "Friday"}).status_code == 400
    assert client.get("/api/briefing", params={"since": "yesterday"}).status_code == 400


def test_a_moment_has_a_local_day():
    assert briefing.local_day("2026-10-21T12:00:00.000Z").isoformat() in ("2026-10-21", "2026-10-22", "2026-10-20")
    assert briefing.stamp(briefing.datetime(2026, 10, 21, 7, 30, tzinfo=briefing.timezone.utc)) == "2026-10-21T07:30:00.000Z"
