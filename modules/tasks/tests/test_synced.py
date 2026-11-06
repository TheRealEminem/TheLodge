"""Linked tasks: work kept elsewhere too arrives through the shared work.* contracts and follows the other side for
fields you haven't changed, flags the ones you have, and is never deleted by it. Nothing here knows about Plane:
the tests publish the contracts the way any module would."""
import pytest

from core.server import contracts, db, events, links
from modules.tasks.server import items, projects, synced

FIELDS = {"text": "Share the GitHub repos", "notes": "Both of them", "status": "doing", "priority": 3,
          "start_on": None, "due_on": "2026-10-24", "assignee_ref": "core:me", "assignee_name": None}


def _arrive(ref="elsewhere:item1", project_ref="elsewhere:proj1", **changes):
    events.publish(contracts.WORK_ARRIVED, {"ref": ref, "fields": {**FIELDS, **changes}, "project_ref": project_ref,
                                            "source": "Elsewhere", "url": "https://example.test/item1"})
    return links.sources(ref, "synced")[0].split(":", 1)[1]


def _there(ref="elsewhere:item1", **changes):
    events.publish(contracts.WORK_UPDATED_ELSEWHERE, {"ref": ref, "fields": {**FIELDS, **changes}, "source": "Elsewhere"})


def _about(item_id):
    return synced.about([item_id])[item_id]


def test_a_project_and_its_work_arrive_as_a_linked_project_and_task():
    events.publish(contracts.WORK_PROJECT_ARRIVED, {"ref": "elsewhere:proj1", "name": "Software", "summary": None,
                                                    "source": "Elsewhere"})
    events.publish(contracts.WORK_PROJECT_ARRIVED, {"ref": "elsewhere:proj1", "name": "Again", "source": "Elsewhere"})
    assert [p["name"] for p in projects.query()] == ["Software"]           # only once
    pid = projects.query()[0]["id"]
    assert links.targets(f"tasks:{pid}", "synced") == ["elsewhere:proj1"]
    item_id = _arrive()
    task = items.get(item_id)
    assert (task["text"], task["status"], task["priority"], task["due_on"], task["project_id"], task["source"]) == \
        ("Share the GitHub repos", "doing", 3, "2026-10-24", pid, "linked")
    assert _about(item_id)["url"] == "https://example.test/item1" and _about(item_id)["conflicts"] == []
    assert _arrive() == item_id and len(items.query()) == 1               # bringing it in again doesn't copy it


def test_untouched_fields_follow_the_other_side():
    item_id = _arrive(project_ref=None)
    _there(text="Share the repos with Dale", due_on="2026-10-31", assignee_ref="elsewhere:sam", assignee_name="Sam")
    task = items.get(item_id)
    assert (task["text"], task["due_on"], task["assignee_ref"], task["assignee_name"]) == \
        ("Share the repos with Dale", "2026-10-31", "elsewhere:sam", "Sam")
    assert _about(item_id)["conflicts"] == [] and _about(item_id)["edited"] == []


def test_a_field_you_changed_stays_yours_and_both_changes_are_flagged():
    item_id = _arrive(project_ref=None)
    items.update(item_id, {"due_on": "2026-11-07", "notes": "Mine now"})
    _there(due_on="2026-10-31", text="Renamed there")
    task = items.get(item_id)
    assert task["due_on"] == "2026-11-07" and task["text"] == "Renamed there"      # yours kept, theirs followed
    about = _about(item_id)
    assert about["conflicts"] == [{"field": "due_on", "label": "Due", "theirs": {"due_on": "2026-10-31"}}]
    assert about["edited"] == ["notes"]                                            # changed here only: just yours
    _there(due_on="2026-10-31", text="Renamed there")                              # the next pull: no change
    assert len(_about(item_id)["conflicts"]) == 1


def test_choosing_theirs_or_yours():
    item_id = _arrive(project_ref=None)
    items.update(item_id, {"due_on": "2026-11-07", "priority": 1})
    _there(due_on="2026-10-31", priority=4)
    synced.resolve(item_id, "due_on", "theirs")
    assert items.get(item_id)["due_on"] == "2026-10-31"
    synced.resolve(item_id, "priority", "mine")
    about = _about(item_id)
    assert items.get(item_id)["priority"] == 1 and about["conflicts"] == [] and about["edited"] == ["priority"]
    _there(due_on="2026-10-31", priority=4)                                       # theirs is the base now: no flag
    assert _about(item_id)["conflicts"] == [] and items.get(item_id)["priority"] == 1


def test_the_same_change_on_both_sides_or_a_change_undone_there_clears_the_flag():
    item_id = _arrive(project_ref=None)
    items.update(item_id, {"status": "done"})
    _there(status="done")
    assert _about(item_id)["conflicts"] == [] and _about(item_id)["edited"] == []
    items.update(item_id, {"priority": 1})
    _there(status="done", priority=2)
    assert _about(item_id)["conflicts"][0]["field"] == "priority"
    _there(status="done", priority=3)                                             # back to what you both had
    assert _about(item_id)["conflicts"] == [] and _about(item_id)["edited"] == ["priority"]


def test_removed_there_keeps_the_task_and_coming_back_clears_the_mark():
    item_id = _arrive(project_ref=None)
    events.publish(contracts.WORK_REMOVED_ELSEWHERE, {"ref": "elsewhere:item1", "source": "Elsewhere"})
    assert items.get(item_id) and _about(item_id)["removed_at"]
    _there()
    assert _about(item_id)["removed_at"] is None


def test_unlinking_keeps_the_task_and_deleting_it_forgets_the_link():
    item_id = _arrive(project_ref=None)
    assert synced.unlink(item_id) and items.get(item_id)["text"] == FIELDS["text"]
    assert links.sources("elsewhere:item1", "synced") == [] and synced.about([item_id]) == {}
    _there(text="Not followed any more")
    assert items.get(item_id)["text"] == FIELDS["text"]
    again = _arrive()
    items.delete(again)
    assert links.sources("elsewhere:item1", "synced") == []
    assert not db.one("SELECT 1 FROM tasks_synced WHERE ref = 'elsewhere:item1'")


def test_a_value_that_doesnt_fit_is_left_out_not_fatal():
    item_id = _arrive(project_ref=None, due_on="soon", priority=9)
    task = items.get(item_id)
    assert (task["due_on"], task["priority"], task["text"]) == (None, 0, FIELDS["text"])


def test_the_api_shows_linked_tasks_and_takes_choices(client):
    item_id = _arrive(project_ref=None)
    client.patch(f"/api/tasks/{item_id}", json={"text": "My name for it"})
    _there(text="Their name for it")
    got = client.get(f"/api/tasks/{item_id}").json()
    assert got["synced"]["conflicts"][0]["theirs"] == {"text": "Their name for it"}
    assert client.get("/api/tasks").json()[0]["synced"]["ref"] == "elsewhere:item1"
    r = client.post(f"/api/tasks/{item_id}/synced", json={"field": "text", "keep": "theirs"})
    assert r.json()["text"] == "Their name for it" and r.json()["synced"]["conflicts"] == []
    assert client.post(f"/api/tasks/{item_id}/synced", json={"field": "text", "keep": "theirs"}).status_code == 400
    assert client.delete(f"/api/tasks/{item_id}/synced").json()["synced"] is None
    assert client.delete(f"/api/tasks/{item_id}/synced").status_code == 404


# ── Sending your changes (contracts.WORK_SHARE_REQUESTED) ──────────────

@pytest.fixture
def listener(monkeypatch, probe_item):
    """Stands in for the module that sends elsewhere: records each request and links the task to a waiting request
    (kind "share"), as the contract asks."""
    asked: list[dict] = []

    def take(payload):
        asked.append(payload)
        links.add(payload["local_ref"], probe_item("Waiting to send it"), "share")

    monkeypatch.setitem(events._subscribers, contracts.WORK_SHARE_REQUESTED, [take])
    return asked


def test_send_asks_for_only_what_you_changed_with_its_base(listener, client):
    item_id = _arrive()
    items.update(item_id, {"due_on": "2026-11-07", "assignee_ref": "elsewhere:sam", "assignee_name": "Sam"})
    r = client.post(f"/api/tasks/{item_id}/share")
    assert r.status_code == 200 and r.json()["asked"] == {"fields": ["due_on", "assignee"], "new": False}
    [asked] = listener
    project = links.sources("elsewhere:proj1", "synced")
    assert asked == {"ref": "elsewhere:item1", "local_ref": f"tasks:{item_id}",
                     "fields": {"due_on": "2026-11-07", "assignee_ref": "elsewhere:sam", "assignee_name": "Sam"},
                     "base": {"due_on": "2026-10-24", "assignee_ref": "core:me", "assignee_name": None},
                     "project_ref": project[0] if project else None}
    assert r.json()["sharing"] == [{"title": "Waiting to send it", "href": r.json()["sharing"][0]["href"]}]


def test_send_says_why_when_theres_nothing_to_send(listener, client):
    item_id = _arrive(project_ref=None)
    r = client.post(f"/api/tasks/{item_id}/share")
    assert r.status_code == 400 and "Nothing to send" in r.json()["detail"]
    items.update(item_id, {"due_on": "2026-11-07"})
    _there(due_on="2026-10-31")
    r = client.post(f"/api/tasks/{item_id}/share")                    # only a flagged field: choose first
    assert r.status_code == 400 and "Choose between" in r.json()["detail"]
    events.publish(contracts.WORK_REMOVED_ELSEWHERE, {"ref": "elsewhere:item1", "source": "Elsewhere"})
    assert "no longer in Elsewhere" in client.post(f"/api/tasks/{item_id}/share").json()["detail"]
    assert listener == []


def test_a_task_in_a_linked_project_asks_to_be_made_there(listener, client):
    events.publish(contracts.WORK_PROJECT_ARRIVED, {"ref": "elsewhere:proj1", "name": "Software", "source": "Elsewhere"})
    pid = projects.query()[0]["id"]
    item_id = items.create("Write the docs", project_id=pid, due_on="2026-11-06")
    r = client.post(f"/api/tasks/{item_id}/share")
    assert r.json()["asked"] == {"fields": ["text", "status", "due_on"], "new": True}
    [asked] = listener
    assert asked["ref"] == asked["local_ref"] == f"tasks:{item_id}" and asked["base"] == {}
    assert asked["project_ref"] == f"tasks:{pid}" and set(asked["fields"]) == set(contracts.WORK_FIELDS)
    sub = items.create("A part of it", parent_id=item_id)
    assert "subtask" in client.post(f"/api/tasks/{sub}/share").json()["detail"]
    mine = items.create("Private", project_id=projects.create("Just mine"))
    assert "isn't linked anywhere" in client.post(f"/api/tasks/{mine}/share").json()["detail"]

    # Made there: the task becomes the linked copy, agreeing with what arrived (nothing new is made)
    events.publish(contracts.WORK_ARRIVED, {"ref": "elsewhere:item9", "fields": {**FIELDS, "text": "Write the docs",
                                            "due_on": "2026-11-06", "status": "todo", "notes": "", "priority": 0,
                                            "assignee_ref": None}, "project_ref": "elsewhere:proj1",
                                            "source": "Elsewhere", "url": "https://example.test/9",
                                            "local_ref": f"tasks:{item_id}"})
    assert len([i for i in items.query() if i["text"] == "Write the docs"]) == 1
    about = _about(item_id)
    assert about["ref"] == "elsewhere:item9" and about["edited"] == [] and about["url"] == "https://example.test/9"
    assert links.targets(f"tasks:{item_id}", "synced") == ["elsewhere:item9"]


def test_send_with_nothing_listening_says_so(client, monkeypatch):
    monkeypatch.setitem(events._subscribers, contracts.WORK_SHARE_REQUESTED, [])
    item_id = _arrive()
    items.update(item_id, {"priority": 1})
    r = client.post(f"/api/tasks/{item_id}/share")
    assert r.status_code == 400 and "Nothing took it" in r.json()["detail"]


def test_a_field_you_chose_theirs_for_over_there_follows(client):
    item_id = _arrive(project_ref=None)
    items.update(item_id, {"due_on": "2026-11-07", "priority": 1})
    events.publish(contracts.WORK_UPDATED_ELSEWHERE, {"ref": "elsewhere:item1", "source": "Elsewhere",
                                                      "fields": {**FIELDS, "due_on": "2026-10-31", "priority": 4},
                                                      "take": ["due_on"]})
    task, about = items.get(item_id), _about(item_id)
    assert task["due_on"] == "2026-10-31" and task["priority"] == 1                 # taken; still yours
    assert [c["field"] for c in about["conflicts"]] == ["priority"] and about["edited"] == []
