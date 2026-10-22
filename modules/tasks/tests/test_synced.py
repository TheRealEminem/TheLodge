"""Linked tasks: work kept elsewhere too arrives through the shared work.* contracts and follows the other side for
fields you haven't changed, flags the ones you have, and is never deleted by it. Nothing here knows about Plane:
the tests publish the contracts the way any module would."""
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
    _there(text="Share the repos with Sam", due_on="2026-10-31", assignee_ref="elsewhere:mick", assignee_name="Mickey")
    task = items.get(item_id)
    assert (task["text"], task["due_on"], task["assignee_ref"], task["assignee_name"]) == \
        ("Share the repos with Sam", "2026-10-31", "elsewhere:mick", "Mickey")
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
