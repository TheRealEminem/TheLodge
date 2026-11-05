"""The Research page: a first pass with Gemini that hands over to deep research on your plan, deep research starting
from what the first pass found, and everyone sorted by how far their research has got. Google and the AI tools are
stand-ins (see test_gemini_research and test_cli_research)."""
import json

from crm_helpers import make
from test_cli_research import tool  # noqa: F401 - the fixture
from test_gemini_research import google  # noqa: F401 - the fixture

from core.server import db, jobs, settings
from modules.crm.server import cli_research as cr


def person(client, name="Jordan Reyes"):
    return make(client, "person", name, attributes={"title": "Head of Fleet", "email": "jordan@frostline.example"})


def desk(client, show):
    return client.get("/api/crm/research/desk", params={"show": show}).json()


def runs(pid):
    return db.query("SELECT * FROM crm_research_runs WHERE entity_id = ? ORDER BY created_at", (pid,))


def test_a_first_pass_hands_over_to_deep_research_which_starts_from_what_it_found(client, google, tool):  # noqa: F811
    jordan = person(client)
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "via": "api", "level": "better",
                                                      "batch": False, "then": "claude"})
    assert r.status_code == 202 and r.json()["started"] == 1
    jobs.drain()
    first, deep = runs(jordan["id"])
    assert (first["via"], first["status"], first["then_via"]) == ("api", "done", None)
    assert (deep["via"], deep["status"]) == ("claude", "done")
    prompt = tool.seen()["prompt"]
    assert "What an earlier search found" in prompt and "runs fleet operations" in prompt   # the first pass's report
    item = desk(client, "deep")["items"][0]
    assert item["row"]["person"]["id"] == jordan["id"]
    assert item["first"]["via"] == "api" and item["deep"]["via"] == "claude" and item["deep"]["waiting"]


def test_a_first_pass_that_finds_nothing_still_hands_over(client, google, tool, monkeypatch):  # noqa: F811
    monkeypatch.setattr(google, "reply", lambda model, body: {"candidates": []})
    tool.mode("codex")
    jordan = person(client)
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "via": "api", "batch": False, "then": "codex"})
    jobs.drain()
    first, deep = runs(jordan["id"])
    assert first["status"] == "failed" and (deep["via"], deep["status"]) == ("codex", "done")
    assert "What an earlier search found" not in tool.seen()["prompt"]


def test_handing_over_to_a_tool_that_isnt_ready_is_refused_up_front(client, google, tool, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cr, "find", lambda via: None)
    r = client.post("/api/crm/research/gemini", json={"person_ids": [person(client)["id"]], "via": "api", "then": "codex"})
    assert r.status_code == 422 and "isn't installed" in r.json()["detail"]


def test_reports_are_added_by_themselves_unless_settings_say_wait(client, tool):  # noqa: F811
    jordan = person(client)
    cr.start([jordan["id"]], "claude")
    jobs.drain()
    inbox_id = runs(jordan["id"])[0]["inbox_id"]
    assert json.loads(db.one("SELECT payload FROM crm_inbox WHERE id = ?", (inbox_id,))["payload"])["auto_apply"] is True
    settings.update({"crm.research_auto_add": False})
    sam = person(client, "Sam Okafor")
    cr.start([sam["id"]], "claude")
    jobs.drain()
    inbox_id = runs(sam["id"])[0]["inbox_id"]
    assert "auto_apply" not in json.loads(db.one("SELECT payload FROM crm_inbox WHERE id = ?", (inbox_id,))["payload"])
    settings.update({"crm.research_auto_add": True})


def test_everyone_is_sorted_by_how_far_their_research_has_got(client, tool):  # noqa: F811
    jordan, sam, kim, lee = person(client), person(client, "Sam Okafor"), person(client, "Kim Lau"), person(client, "Lee")
    client.post(f"/api/crm/people/{kim['id']}/research", json={"action": "dismiss"})
    cr.start([jordan["id"]], "claude")
    assert desk(client, "running")["items"][0]["run"]["via"] == "claude"
    jobs.drain()
    counts = desk(client, "new")["counts"]
    assert counts["deep"] == 1 and counts["running"] == 0 and counts["skipped"] == 2   # Kim dismissed, Lee has no surname
    assert [i["row"]["person"]["name"] for i in desk(client, "new")["items"]] == ["Sam Okafor"]
    tool.mode("broken")
    cr.start([sam["id"]], "codex")
    jobs.drain()
    failed = desk(client, "new")["items"][0]
    assert failed["run"]["status"] == "failed"                                          # shown with its error, to try again
    assert client.get("/api/crm/research/desk", params={"show": "new", "q": "frost"}).json()["total"] == 0
    assert lee["id"]


def test_depth_sets_the_model_effort_and_length_each_tool_is_given(client, tool):  # noqa: F811
    jordan, sam = person(client), person(client, "Sam Okafor")
    cr.start([jordan["id"]], "claude", "light")
    jobs.drain()
    seen = tool.seen()
    assert seen["argv"][-4:] == ["--model", "sonnet", "--effort", "low"]
    assert "light pass" in seen["prompt"] and "Aim for 600 to 900 words" in seen["prompt"]
    tool.mode("codex")
    cr.start([sam["id"]], "codex", "deep")
    jobs.drain()
    seen = tool.seen()
    assert 'model_reasoning_effort="high"' in seen["argv"] and "40 or more searches" in seen["prompt"]
    report = db.one("SELECT raw_text FROM crm_inbox WHERE id = ?", (runs(sam["id"])[0]["inbox_id"],))["raw_text"]
    assert "with Codex (deep)" in report


def test_an_overnight_run_waits_for_the_night_hours(client, tool, monkeypatch):  # noqa: F811
    jordan = person(client)
    monkeypatch.setattr(cr, "is_night", lambda hour=None: False)
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "via": "claude", "night": True})
    assert r.status_code == 202
    jobs.enqueue("crm", "research_cli", "scheduled")
    jobs.drain()
    [waiting] = runs(jordan["id"])
    assert waiting["status"] == "queued" and waiting["night"] == 1
    assert client.get("/api/crm/research/gemini").json()["waiting_for_night"] == 1
    monkeypatch.setattr(cr, "is_night", lambda hour=None: True)
    jobs.enqueue("crm", "research_cli", "scheduled")
    jobs.drain()
    assert runs(jordan["id"])[0]["status"] == "done"


def test_the_usual_depth_and_time_come_from_settings_and_follow_a_first_pass(client, google, tool, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cr, "is_night", lambda hour=None: False)
    settings.update({"crm.research_depth": "deep", "crm.research_when": "night"})
    jordan = person(client)
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "via": "api", "batch": False, "then": "claude"})
    jobs.drain()
    first, deep = runs(jordan["id"])
    assert first["status"] == "done"                                     # the first pass goes now
    assert (deep["depth"], deep["night"], deep["status"]) == ("deep", 1, "queued")
    settings.update({"crm.research_depth": "standard", "crm.research_when": "now"})


def test_the_night_hours_can_run_past_midnight():
    settings.update({"crm.research_night_from": 22, "crm.research_night_to": 6})
    assert cr.is_night(23) and cr.is_night(3) and not cr.is_night(6) and not cr.is_night(12)
    settings.update({"crm.research_night_from": 1, "crm.research_night_to": 6})
    assert cr.is_night(1) and not cr.is_night(0) and not cr.is_night(7)
