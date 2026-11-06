"""The tasks module's tools for Claude (tools.py), called the way the MCP server calls them. Today is Monday 19 October
2026 (conftest)."""
import json

from core.server import links, mcp, settings
from modules.tasks.server import items, projects


def call(name: str, **args) -> dict:
    result = mcp.call_tool(f"tasks_{name}", args)
    text = result["content"][0]["text"]
    return {"error": text} if result["isError"] else json.loads(text)


def test_my_plate_groups_this_weeks_open_tasks_and_leaves_others_out(client):
    acme = projects.create("Acme launch")
    items.create("Chase the invoice", due_on="2026-10-16", priority=4, project_id=acme)
    items.create("Call Ana", due_on="2026-10-19", assignee_ref="core:me")
    items.create("Draft the brief", due_on="2026-10-24")
    items.create("Plan Q1", due_on="2026-11-30")
    items.create("Someday", status="todo")
    items.create("Eli's quote", due_on="2026-10-20", assignee_name="Eli")
    items.create("Already done", due_on="2026-10-19", status="done")
    plate = call("my_plate")
    assert plate["today"] == "Monday 2026-10-19"
    assert [(g["name"], [t["text"] for t in g["tasks"]]) for g in plate["groups"]] == [
        ("Late", ["Chase the invoice"]), ("Today", ["Call Ana"]), ("This week", ["Draft the brief"])]
    late = plate["groups"][0]["tasks"][0]
    assert late["priority"] == "Urgent" and late["project"] == "Acme launch" and late["status"] == "To do"
    assert late["href"].startswith("#/tasks/t/") and late["ref"].startswith("tasks:")
    assert "assignee" not in plate["groups"][1]["tasks"][0]          # yours: nothing to say
    assert plate["counts"] == {"open": 5, "due_today": 1, "late": 1}
    assert plate["waiting_on_others"] == 1
    everything = call("my_plate", when="all")
    assert [g["name"] for g in everything["groups"]] == ["Late", "Today", "This week", "Later", "No date"]
    waiting = call("my_plate", when="waiting")["groups"][0]["tasks"]
    assert [(t["text"], t["assignee"]) for t in waiting] == [("Eli's quote", "Eli")]
    assert call("my_plate", when="soon")["error"].startswith("when must be one of")


def test_find_by_words_and_by_project_name(client):
    acme = projects.create("Acme launch", summary="The spring launch")
    items.create("Send Acme the quote", project_id=acme)
    items.create("Book the venue", project_id=acme)
    items.create("Acme retro", status="done", project_id=acme)
    found = call("find", q="acme")
    assert [t["text"] for t in found["tasks"]] == ["Send Acme the quote"]
    assert [(p["name"], p["progress"]) for p in found["projects"]] == [("Acme launch", "1 of 3 done")]
    assert len(call("find", q="acme", include_done=True)["tasks"]) == 2
    listed = call("find", project="acme")
    assert [t["text"] for t in listed["tasks"]] == ["Send Acme the quote", "Book the venue"]
    assert listed["project"]["ref"] == f"tasks:{acme}"
    assert call("find", project="launch", q="venue")["tasks"][0]["text"] == "Book the venue"
    assert call("find")["error"].startswith("Say what to look for")
    assert "There's no project called “Zeta”" in call("find", project="Zeta")["error"]
    assert call("find", q="acme", limit=1).get("more") is None


def test_add_a_task_in_a_project_for_you_or_someone(client):
    settings.update({"core.your_name": "Dale Morgan"})
    try:
        projects.create("Acme launch")
        added = call("add", text="  Send   the deck ", project="Acme", due_on="2026-10-22", priority="high",
                     assignee="me", notes="With the **new** pricing")
        task = added["added"]
        assert task["text"] == "Send the deck" and task["project"] == "Acme launch" and task["priority"] == "High"
        row = items.get(task["ref"].split(":", 1)[1])
        assert (row["assignee_ref"], row["assignee_name"], row["source"], row["notes"]) == (
            "core:me", "Dale Morgan", "ai", "With the **new** pricing")
        assert "note" not in added                                    # the project isn't linked anywhere
        dale = items.get(call("add", text="Mine too", assignee="Dale")["added"]["ref"].split(":", 1)[1])
        assert dale["assignee_ref"] == "core:me"
        ana = items.get(call("add", text="For Ana", assignee="Ana")["added"]["ref"].split(":", 1)[1])
        assert (ana["assignee_ref"], ana["assignee_name"]) == (None, "Ana")
        assert call("add", text="Bad day", due_on="Friday")["error"] == "'Friday' isn't a date like 2026-10-31"
        assert call("add", text="Nowhere", project="Zeta")["error"].startswith("There's no project called")
        assert call("add", text=" ")["error"] == "A task needs some text"
        assert call("add")["error"] == "Missing: text."
    finally:
        settings.update({"core.your_name": ""})


def test_adding_in_a_linked_project_says_it_can_be_proposed(client):
    acme = projects.create("Acme launch")
    links.add(f"tasks:{acme}", "elsewhere:p1", "synced")
    added = call("add", text="Ship it", project="Acme launch")
    assert "tasks_propose_send" in added["note"]


def test_proposing_to_send_explains_when_there_is_nowhere_to_send(client):
    tid = items.create("Private work", project_id=projects.create("Mine"))
    assert call("propose_send", task=f"tasks:{tid}")["error"] == "Its project isn't linked anywhere, so there's nowhere to send it"
    assert call("propose_send", task="tasks:nope")["error"].startswith("There's no task tasks:nope")
