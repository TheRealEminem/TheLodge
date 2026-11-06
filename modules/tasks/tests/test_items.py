"""Work items: status, where they live, subtasks, blockers, lists and counts, assignees, deleting, and action items
from other modules."""
import pytest

from core.server import contracts, db, events, links
from modules.tasks.server import hooks, items, projects


def test_status_keeps_done_and_completed_at_in_step():
    item = items.create("Draft the brief")
    assert items.get(item)["status"] == "todo" and not items.get(item)["done"]
    done = items.set_status(item, "done")
    assert done["done"] and done["completed_at"]
    first = done["completed_at"]
    assert items.set_status(item, "done")["completed_at"] == first          # done again keeps when it was done
    back = items.update(item, {"status": "doing"})
    assert (back["status"], back["done"], back["completed_at"]) == ("doing", False, None)
    assert items.update(item, {"done": True})["status"] == "done"           # the old {done} still works
    assert items.update(item, {"done": False})["status"] == "todo"


def test_values_are_checked_with_a_sentence_a_person_can_read():
    for bad, message in [({"status": "finished"}, "Status must be one of"), ({"priority": 7}, "Priority must be"),
                         ({"priority": "high"}, "Priority must be"), ({"due_on": "Friday"}, "isn't a date"),
                         ({"due_on": "2026-02-30"}, "isn't a date"), ({"assignee_ref": "Ana"}, "reference like"),
                         ({"tags": "a,b"}, "list of words"), ({"notes": 5}, "should be text"),
                         ({"estimate_min": -5}, "whole number of minutes")]:
        with pytest.raises(ValueError, match=message):
            items.create("Something", **bad)
    with pytest.raises(ValueError, match="needs some text"):
        items.create("   ")
    with pytest.raises(ValueError, match="Can't change"):
        items.update(items.create("x"), {"created_at": "now"})


def test_an_item_lives_in_a_project_and_a_milestone_that_agree():
    p1, p2 = projects.create("Relaunch"), projects.create("Hiring")
    m1 = projects.add_milestone(p1, "Designs")["id"]
    item = items.create("Wireframes", milestone_id=m1)
    assert items.get(item)["project_id"] == p1                                # the milestone decides the project
    with pytest.raises(ValueError, match="belongs to another project"):
        items.create("Wrong", project_id=p2, milestone_id=m1)
    moved = items.update(item, {"project_id": p2})
    assert (moved["project_id"], moved["milestone_id"]) == (p2, None)         # a new project leaves the milestone
    with pytest.raises(ValueError, match="doesn't exist"):
        items.create("Nowhere", project_id="nope")


def test_subtasks_live_with_their_parent_and_can_not_loop():
    p = projects.create("Relaunch")
    parent = items.create("Launch page", project_id=p)
    child = items.create("Hero copy", parent_id=parent)
    grandchild = items.create("Headline", parent_id=child)
    assert items.get(child)["project_id"] == p
    other = projects.create("Other")
    items.update(parent, {"project_id": other})
    assert items.get(child)["project_id"] == other and items.get(grandchild)["project_id"] == other
    with pytest.raises(ValueError, match="inside itself"):
        items.update(parent, {"parent_id": grandchild})
    with pytest.raises(ValueError, match="moves with its parent"):
        items.move(child, project_id=p)
    assert [i["text"] for i in items.query(project=other)] == ["Launch page"]   # lists show top-level items
    assert items.query(project=other)[0]["subtask_count"] == 1


def test_blockers_mark_an_item_blocked_until_done_and_refuse_loops():
    a, b, c = items.create("Sign contract"), items.create("Kickoff"), items.create("Plan")
    items.block(b, a)
    items.block(c, b)
    assert items.get(b)["blocked"] and [x["text"] for x in items.get(a)["blocks"]] == ["Kickoff"]
    with pytest.raises(ValueError, match="wait on each other"):
        items.block(a, c)                                                      # a ← b ← c ← a would be a loop
    with pytest.raises(ValueError, match="itself"):
        items.block(a, a)
    items.set_status(a, "done")
    assert not items.get(b)["blocked"]
    assert not items.unblock(c, b)["blocked_by"]


def test_lists_filter_by_project_assignee_status_and_when():
    p = projects.create("Relaunch")
    late = items.create("Late one", due_on="2026-10-15", project_id=p, assignee_ref="core:me")
    today = items.create("Due today", due_on="2026-10-19", priority=4)
    week = items.create("This week", due_on="2026-10-24")
    later = items.create("Later", due_on="2026-11-30")
    nodate = items.create("No date", status="waiting")
    done = items.create("Finished", due_on="2026-10-10", status="done")
    ids = lambda rows: [r["id"] for r in rows]  # noqa: E731
    assert ids(items.query(when="late")) == [late]
    assert ids(items.query(when="today")) == [late, today]
    assert ids(items.query(when="week")) == [late, today, week]
    assert ids(items.query(when="waiting")) == [nodate]
    assert ids(items.query(project="none", status="open")) == [today, week, later, nodate]
    assert ids(items.query(assignee="core:me")) == [late]
    assert ids(items.query())[-1] == done                                     # finished ones last
    assert ids(items.query(q="finish")) == [done]
    assert items.counts() == {"open": 5, "due_today": 1, "late": 1}
    assert items.counts("core:me") == {"open": 1, "due_today": 0, "late": 1}


def test_mine_means_nobodys_or_yours_and_waiting_collects_the_rest():
    yours = items.create("Yours", assignee_ref="core:me")
    nobody = items.create("Nobody's")
    ana = items.create("Ana's", assignee_ref="crm:ana1", assignee_name="Ana Ruiz")
    typed = items.create("Ben's", assignee_name="Ben")
    stuck = items.create("Waiting on a reply", status="waiting")
    doing = items.create("Doing", status="doing")
    ids = lambda rows: sorted(r["id"] for r in rows)  # noqa: E731
    assert ids(items.query(assignee="mine", status="todo,doing")) == sorted([yours, nobody, doing])
    assert ids(items.query(when="waiting")) == sorted([ana, typed, stuck])
    assert ids(items.query(assignee="others")) == sorted([ana, typed])
    assert items.counts("mine")["open"] == 4
    with pytest.raises(ValueError, match="Status must be one of"):
        items.query(status="todo,finished")


def test_an_assignee_is_a_column_and_a_link_and_you_need_no_link():
    item = items.create("Send the outline", assignee_ref="crm:ana1", assignee_name="Ana Ruiz")
    ref = f"tasks:{item}"
    assert db.one("SELECT kind FROM core_links WHERE from_ref = ? AND to_ref = 'crm:ana1'", (ref,))["kind"] == "assigned"
    items.update(item, {"assignee_ref": "core:me"})
    assert db.query("SELECT * FROM core_links WHERE from_ref = ?", (ref,)) == []
    assert items.get(item)["assignee_name"] is None                           # a new person, so the old name goes


def test_deleting_says_so_for_the_item_and_its_subtasks():
    heard = []
    events.subscribe(contracts.ITEM_DELETED, lambda payload: heard.append(payload["ref"]))
    parent = items.create("Launch page")
    child = items.create("Hero copy", parent_id=parent)
    links.add("notes:n1", f"tasks:{parent}", "action-item")
    assert items.delete(parent) and items.get(child) is None
    assert {f"tasks:{parent}", f"tasks:{child}"} <= set(heard)
    assert db.query("SELECT * FROM core_links WHERE to_ref = ?", (f"tasks:{parent}",)) == []
    assert not items.delete(parent)


def test_moving_puts_an_item_where_you_drop_it():
    p = projects.create("Relaunch")
    a, b, c = (items.create(t, project_id=p) for t in ("A", "B", "C"))
    items.move(c, project_id=p, after_id=a)
    assert [i["text"] for i in items.query(project=p)] == ["A", "C", "B"]
    items.move(b, project_id=p, after_id=None)
    assert [i["text"] for i in items.query(project=p)] == ["B", "A", "C"]


def test_the_board_orders_across_milestones_and_changes_status_in_one_step():
    p = projects.create("Relaunch")
    m1, m2 = projects.add_milestone(p, "Designs")["id"], projects.add_milestone(p, "Build")["id"]
    a = items.create("A", milestone_id=m1)
    b = items.create("B", milestone_id=m2)
    c = items.create("C", milestone_id=m1, status="doing")
    # In the To do column (A, B), drop C after B: it keeps its milestone, takes the column's status.
    moved = items.move(c, project_id=p, milestone_id=m1, after_id=b, within="project", status="todo")
    assert (moved["status"], moved["milestone_id"]) == ("todo", m1)
    todo = [i["text"] for i in items.query(project=p, status="todo")]
    assert todo.index("C") == todo.index("B") + 1
    with pytest.raises(ValueError, match="within must be one of"):
        items.move(a, project_id=p, milestone_id=m1, within="everywhere")


def test_action_items_go_to_the_project_their_source_is_linked_to():
    p = projects.create("Riverbend relaunch")
    links.add(f"tasks:{p}", "crm:meeting1", "discussed-in")
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "crm:meeting1", "items": [
        "Send the outline", {"text": "Book the venue", "due_on": "2026-10-30", "assignee_name": "Ana Ruiz"}]})
    found = {i["text"]: i for i in items.query(project=p)}
    assert set(found) == {"Send the outline", "Book the venue"}
    assert found["Book the venue"]["due_on"] == "2026-10-30" and found["Book the venue"]["source"] == "action-item"
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "crm:other", "items": ["Unfiled"]})
    assert [i["text"] for i in items.query(project="none")] == ["Unfiled"]


def test_new_action_items_never_throw_away_what_you_changed():
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "notes:n1", "items": ["One", "Two", "Three"]})
    by_text = {i["text"]: i["id"] for i in items.query()}
    items.update(by_text["Two"], {"notes": "Ana said Friday"})               # touched: stays
    items.update(by_text["Three"], {"status": "doing"})                     # touched: stays
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "notes:n1", "items": ["Four"]})
    assert sorted(i["text"] for i in items.query()) == ["Four", "Three", "Two"]


def test_when_a_person_or_source_is_deleted_the_names_stay():
    item = items.create("Call Ana", assignee_ref="crm:ana1", assignee_name="Ana Ruiz", source_ref="crm:meeting1")
    p = projects.create("Relaunch", owner_ref="crm:ana1", owner_name="Ana Ruiz")
    hooks.source_deleted({"ref": "crm:ana1"})
    got = items.get(item)
    assert (got["assignee_ref"], got["assignee_name"], got["source_ref"]) == (None, "Ana Ruiz", "crm:meeting1")
    assert projects.get(p)["owner_ref"] is None and projects.get(p)["owner_name"] == "Ana Ruiz"


def test_action_items_announced_again_keep_their_ids():
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "notes:n2", "items": ["Send the outline"]})
    first = {i["text"]: i["id"] for i in items.query() if i["source_ref"] == "notes:n2"}
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": "notes:n2", "items": ["Send the outline", "Book the venue"]})
    again = {i["text"]: i["id"] for i in items.query() if i["source_ref"] == "notes:n2"}
    assert again["Send the outline"] == first["Send the outline"]          # the same task, not a remade one
    assert set(again) == {"Send the outline", "Book the venue"}
