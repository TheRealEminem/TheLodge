"""The tasks module's part of the day's briefing (Module.brief): yours late, due today and in progress; linked tasks
waiting for a choice; done and added since a moment; the week ahead with milestones and projects at risk. And a task
ticked somewhere else (work.marked_done) is done here."""
from core.server import contracts, db, events, links
from modules.tasks.server import briefing, hooks, items, projects
from modules.tasks.tests.conftest import TODAY

FIELDS = {"text": "Share the GitHub repos", "notes": "", "status": "todo", "priority": 0, "start_on": None,
          "due_on": None, "assignee_ref": "core:me", "assignee_name": None}


def _titles(entries: list[dict]) -> list[tuple]:
    return [(e["title"], e["what"]) for e in entries]


def test_today_is_yours_late_due_and_doing_and_nobody_elses():
    pid = projects.create("Hut")
    items.create("Late one", due_on="2026-10-15", project_id=pid, estimate_min=30)
    items.create("Due today", due_on=TODAY.isoformat())
    items.create("Doing it", status="doing")
    items.create("Sam's", due_on="2026-10-15", assignee_name="Sam")
    items.create("Later", due_on="2026-10-23")
    items.create("Done already", due_on="2026-10-15", status="done")
    found = briefing.brief("2026-10-19T00:00:00.000Z", TODAY)["today"]
    assert _titles(found) == [("Late one", "Late"), ("Due today", "Due today"), ("Doing it", "Doing")]
    late = found[0]
    assert (late["kind"], late["tone"], late["when"], late["project"], late["minutes"], late["who"]) == \
        ("late", "trail", "2026-10-15", "Hut", 30, "You")
    assert [e["tone"] for e in found] == ["trail", "sun", "sky"]


def test_moved_is_done_and_added_since_then():
    old = items.create("Old and open")
    db.execute("UPDATE tasks_items SET created_at = '2026-10-01T00:00:00.000Z' WHERE id = ?", (old,))
    since = db.now()
    finished = items.create("Write the brief")
    items.set_status(finished, "done")
    items.create("From the meeting", source="action-item", source_ref="probe:nothing")
    added = items.create("New one", assignee_name="Alex")
    moved = briefing.brief(since, TODAY)["moved"]
    assert ("Write the brief", "Done") in _titles(moved)
    assert ("New one", "Added") in _titles(moved) and ("From the meeting", "Added") in _titles(moved)
    assert ("Old and open", "Added") not in _titles(moved)
    assert next(e for e in moved if e["id"] == added)["who"] == "Alex"
    assert next(e for e in moved if e["id"] == finished)["tone"] == "forest"


def test_linked_tasks_changed_or_removed_there_wait_for_you():
    events.publish(contracts.WORK_ARRIVED, {"ref": "elsewhere:1", "fields": FIELDS, "project_ref": None,
                                            "source": "Plane", "url": "https://plane.test/1"})
    item_id = links.sources("elsewhere:1", "synced")[0].split(":", 1)[1]
    items.update(item_id, {"due_on": "2026-11-07"})
    events.publish(contracts.WORK_UPDATED_ELSEWHERE, {"ref": "elsewhere:1", "fields": {**FIELDS, "due_on": "2026-10-31"},
                                                      "source": "Plane"})
    waiting = briefing.brief(db.now(), TODAY)["waiting"]
    assert _titles(waiting) == [("Share the GitHub repos", "Changed in Plane too: due")]
    assert (waiting[0]["tone"], waiting[0]["url"]) == ("sun", "https://plane.test/1")
    events.publish(contracts.WORK_REMOVED_ELSEWHERE, {"ref": "elsewhere:1", "source": "Plane"})
    assert _titles(briefing.brief(db.now(), TODAY)["waiting"]) == [("Share the GitHub repos", "Changed in Plane too: due")]


def test_ahead_is_the_week_milestones_and_projects_at_risk():
    pid = projects.create("Riverbend", health="at_risk", due_on="2026-11-28")
    projects.create("Fine", health="on_track")
    ms = projects.add_milestone(pid, "Site built", due_on="2026-10-22")
    projects.add_milestone(pid, "Far off", due_on="2026-12-01")
    late_ms = projects.add_milestone(pid, "Designs signed off", due_on="2026-10-16")
    items.create("Thursday's", due_on="2026-10-22")
    items.create("Doing, due Thursday", due_on="2026-10-22", status="doing")
    items.create("Next month", due_on="2026-11-20")
    found = briefing.brief(db.now(), TODAY)
    assert _titles(found["ahead"]) == [("Thursday's", "Due"), ("Site built", "Milestone due"), ("Riverbend", "At risk")]
    assert found["ahead"][1]["project"] == "Riverbend"            # the host's describe gives it its href
    assert ("Designs signed off", "Milestone late") in _titles(found["today"])
    assert hooks.describe(ms["id"]) == {"title": "Site built", "href": f"#/tasks/projects/{pid}", "done": False}
    assert hooks.describe(late_ms["id"])["done"] is False


def test_describe_says_when_a_task_is_done():
    item_id = items.create("Tick me")
    assert hooks.describe(item_id)["done"] is False
    items.set_status(item_id, "done")
    assert hooks.describe(item_id)["done"] is True


def test_a_task_ticked_elsewhere_is_done_here_and_unticked_open_again():
    item_id = items.create("Ring the hut", status="doing")
    events.publish(contracts.WORK_MARKED_DONE, {"ref": f"tasks:{item_id}", "done": True})
    assert items.get(item_id)["status"] == "done"
    events.publish(contracts.WORK_MARKED_DONE, {"ref": f"tasks:{item_id}", "done": False})
    assert items.get(item_id)["status"] == "todo"
    events.publish(contracts.WORK_MARKED_DONE, {"ref": "plane:whatever", "done": True})     # not ours: nothing
    events.publish(contracts.WORK_MARKED_DONE, {"ref": "tasks:missing", "done": True})
