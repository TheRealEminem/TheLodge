import pytest

from core.server import config, contracts, events, jobs, settings

needs_tasks = pytest.mark.skipif("tasks" not in config.enabled_modules(), reason="the tasks module is off in app.json")


def _job(client, note_id):
    jobs.drain()
    return client.get(f"/api/notes/{note_id}").json()["job"]


def test_a_new_note_waits_for_you_then_summarizes_and_announces_its_action_items(client, fake_ai):
    fake_ai.reply = "Plans for the launch.\n\n## Action items\n- [ ] Book the venue\n- [ ] Email Sam"
    heard = []
    events.subscribe(contracts.ACTIONS_FOUND, heard.append)
    note_id = client.post("/api/notes", json={"title": "Launch", "body": "We need a venue and to tell Sam."}).json()["id"]
    job = _job(client, note_id)
    assert (job["status"], job["wait_reason"]) == ("waiting", "Needs you")

    client.post(f"/api/jobs/{job['id']}/go", json={})
    assert _job(client, note_id)["status"] == "done"
    note = client.get(f"/api/notes/{note_id}").json()
    assert note["summary"].startswith("Plans for the launch") and note["summary_by"] == "fake"
    assert {"source_ref": f"notes:{note_id}", "items": ["Book the venue", "Email Sam"]} in heard


@needs_tasks
def test_with_tasks_on_the_action_items_become_linked_tasks(client, fake_ai):
    fake_ai.reply = "Plans for the launch.\n\n## Action items\n- [ ] Book the venue\n- [ ] Email Sam"
    note_id = client.post("/api/notes", json={"title": "Launch", "body": "We need a venue and to tell Sam."}).json()["id"]
    client.post(f"/api/notes/{note_id}/summarize")
    jobs.drain()
    note = client.get(f"/api/notes/{note_id}").json()
    tasks = [t for t in client.get("/api/tasks").json() if t["source_ref"] == f"notes:{note_id}"]
    assert sorted(t["text"] for t in tasks) == ["Book the venue", "Email Sam"]
    assert tasks[0]["source"]["href"] == f"#/notes/{note_id}"
    assert {link["title"] for link in note["links"]} == {"Book the venue", "Email Sam"}


def test_automatic_mode_summarizes_right_away(client, fake_ai):
    settings.update({"notes.auto_summarize": True})
    try:
        note_id = client.post("/api/notes", json={"title": "Auto", "body": "Something to summarize."}).json()["id"]
        assert _job(client, note_id)["status"] == "done"
    finally:
        settings.update({"notes.auto_summarize": False})


def test_search_finds_notes_by_their_words(client):
    client.post("/api/notes", json={"title": "Trail map", "body": "The ridge path is closed in winter."})
    groups = client.get("/api/search", params={"q": "ridge"}).json()
    notes = next(g for g in groups if g["module"] == "notes")
    assert notes["hits"][0]["title"] == "Trail map"
    assert notes["hits"][0]["href"].startswith("#/notes/")


@needs_tasks
def test_deleting_a_note_keeps_its_tasks_but_unlinks_them(client, fake_ai):
    fake_ai.reply = "Short.\n\n## Action items\n- [ ] Keep me"
    note_id = client.post("/api/notes", json={"title": "Doomed", "body": "x"}).json()["id"]
    client.post(f"/api/notes/{note_id}/summarize")
    jobs.drain()
    assert client.delete(f"/api/notes/{note_id}").status_code == 204
    kept = [t for t in client.get("/api/tasks").json() if t["text"] == "Keep me"]
    assert kept and kept[0]["source_ref"] is None
