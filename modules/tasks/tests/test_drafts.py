"""AI in the app (chunk 12), with the fake AI: drafting a project's status update and breaking a task down. The AI runs
only in the tasks/draft job, what it wrote always says which AI wrote it, and nothing counts until you post or accept
it. Posting an update where a linked task also lives only asks, through the shared contract; the tests stand in for
whoever takes it, the way any module would."""
import pytest

from core.server import ai, contracts, db, events, jobs, links
from modules.tasks.server import drafts, items, projects
from modules.tasks.server.drafts import Breakdown, StatusDraft, Step

DRAFT = StatusDraft(body="We're close, but the enclosures are late.\n\n**Watch**\n- Order enclosures (Sam) is late",
                    why="A task is late and the beta milestone was missed.", health="At risk")


def _project() -> tuple[str, dict]:
    pid = projects.create("Hardware launch", summary="Ship 50 units", due_on="2026-11-30")
    beta = projects.add_milestone(pid, "Beta units built", due_on="2026-10-16")        # missed: today is 2026-10-19
    t = {"late": items.create("Order enclosures", project_id=pid, milestone_id=beta["id"], due_on="2026-10-15",
                              assignee_name="Sam"),
         "done": items.create("Finish the BOM", project_id=pid, status="done"),
         "quote": items.create("Get the supplier quote", project_id=pid, status="waiting", assignee_name="Alex"),
         "drops": items.create("Book the drop tests", project_id=pid, status="doing", due_on="2026-10-23")}
    items.block(t["drops"], t["quote"])
    projects.add_update(project_id=pid, kind="comment", body="Kicked off with the supplier.")
    return pid, t


def _draft(client, pid: str) -> dict:
    r = client.post(f"/api/tasks/projects/{pid}/draft")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "drafting" and r.json()["job"]["kind"] == "draft"
    jobs.drain()
    return client.get(f"/api/tasks/projects/{pid}/draft").json()


# ── A status draft ────────────────────────────────────────────────────

def test_a_status_draft_reads_the_project_and_says_who_wrote_it(client, fake_structured):
    pid, _ = _project()
    fake_structured.reply = DRAFT
    draft = _draft(client, pid)
    assert draft["status"] == "ready" and draft["job"]["status"] == "done"
    assert draft["body"].startswith("We're close") and draft["health"] == "at_risk" and draft["edited"] is False
    assert draft["why"] == "A task is late and the beta milestone was missed."
    assert draft["written_by"].startswith("Claude")                     # which AI wrote it, shown with it
    [call] = fake_structured.calls
    assert call["schema"] is StatusDraft and call["system"] == drafts.STATUS_SYSTEM
    prompt = call["prompt"]
    for fact in ("TODAY: Monday 2026-10-19", "PROJECT: Hardware launch", "WHAT DONE LOOKS LIKE: Ship 50 units",
                 "PROGRESS: 1 of 4 tasks done (25% done); 1 doing, 1 waiting, 1 to do, 1 late",
                 "- Beta units built: missed: due 2026-10-16; 0 of 1 done, 1 late",
                 "DONE IN THE LAST TWO WEEKS:\n- Finish the BOM",
                 "LATE:\n- Order enclosures (Sam, due 2026-10-15)",
                 "IN PROGRESS:\n- Book the drop tests (due 2026-10-23)",
                 "- Book the drop tests: blocked by Get the supplier quote", "- Get the supplier quote: waiting on Alex",
                 "Kicked off with the supplier."):
        assert fact in prompt, fact
    # Nothing is posted until you post it.
    assert [u["kind"] for u in projects.updates(pid)] == ["comment"] and projects.get(pid)["health"] is None


def test_a_draft_can_be_edited_then_posted_as_the_status_update(client, fake_structured):
    pid, _ = _project()
    fake_structured.reply = DRAFT
    draft = _draft(client, pid)
    edited = client.patch(f"/api/tasks/drafts/{draft['id']}", json={"body": "We're close. Enclosures are late."}).json()
    assert edited["edited"] is True and edited["written_by"] == draft["written_by"] and edited["health"] == "at_risk"
    assert client.patch(f"/api/tasks/drafts/{draft['id']}", json={"health": "sideways"}).status_code == 400

    r = client.post(f"/api/tasks/drafts/{draft['id']}/post", json={})
    assert r.status_code == 201, r.text
    update = r.json()
    assert (update["kind"], update["health"], update["body"]) == ("status", "at_risk", "We're close. Enclosures are late.")
    assert update["author_ref"] == "core:me" and update["written_by"] == draft["written_by"] and update["edited"] == 1
    project = client.get(f"/api/tasks/projects/{pid}").json()
    assert project["health"] == "at_risk" and project["latest_status"]["id"] == update["id"]
    assert project["latest_status"]["written_by"].startswith("Claude") and project["latest_status"]["shared"] == []
    assert client.get(f"/api/tasks/projects/{pid}/draft").json() is None        # the draft is gone once posted


def test_a_draft_can_be_discarded_and_an_empty_one_isnt_posted(client, fake_structured):
    pid, _ = _project()
    fake_structured.reply = DRAFT
    draft = _draft(client, pid)
    assert client.delete(f"/api/tasks/drafts/{draft['id']}").status_code == 204
    assert client.get(f"/api/tasks/projects/{pid}/draft").json() is None
    assert client.delete(f"/api/tasks/drafts/{draft['id']}").status_code == 404
    draft = _draft(client, pid)
    client.patch(f"/api/tasks/drafts/{draft['id']}", json={"body": "  "})
    assert "empty" in client.post(f"/api/tasks/drafts/{draft['id']}/post", json={}).json()["detail"]
    assert [u["kind"] for u in projects.updates(pid)] == ["comment"]


def test_since_the_last_status_update_and_a_health_it_cant_read(client, fake_structured):
    pid, t = _project()
    projects.add_update(project_id=pid, kind="status", body="All good so far.", health="on_track")
    db.execute("UPDATE tasks_updates SET created_at = '2026-10-17T09:00:00.000Z' WHERE kind = 'status'")
    db.execute("UPDATE tasks_items SET completed_at = '2026-10-16T09:00:00.000Z' WHERE id = ?", (t["done"],))
    fake_structured.reply = StatusDraft(body="Fine.", why="", health="probably fine")
    draft = _draft(client, pid)
    assert draft["health"] is None and draft["why"] is None               # a health it can't read is left for you
    prompt = fake_structured.calls[0]["prompt"]
    assert "DONE SINCE THE LAST STATUS UPDATE (2026-10-17):\n- nothing" in prompt
    assert "health last reported: On track" in prompt and "(status, On track): All good so far." in prompt


def test_a_label_with_nothing_under_it_and_a_health_line_are_left_out(client, fake_structured):
    """What qwen2.5:7b wrote for a real project on 2026-10-21 (names shortened): an empty Done, and the health again."""
    pid, _ = _project()
    fake_structured.reply = StatusDraft(health="at_risk", why="A deliverable is late.", body=(
        "No tasks completed yet.\n\n**Done:**\n- Nothing\n\n**Next:**\n- Week 2 deliverables (me, due 2026-10-16)\n\n"
        "**Watch:**\n- Week 2 deliverables - this task is late.\n\n**Health:** at_risk\n\nThe project is at risk."))
    draft = _draft(client, pid)
    assert draft["body"] == ("No tasks completed yet.\n\n**Next:**\n- Week 2 deliverables (me, due 2026-10-16)\n\n"
                             "**Watch:**\n- Week 2 deliverables - this task is late.\n\nThe project is at risk.")
    assert drafts.tidy_body("Fine.\n\n**Done**\n\n**Watch**\n- None.\n**Next**\n- Ship it") == "Fine.\n\n**Next**\n- Ship it"


def test_a_failed_draft_says_why_and_tries_again(client, fake_structured):
    pid, _ = _project()
    fake_structured.reply = ai.AIError("Claude didn't answer: the key isn't set")
    draft = _draft(client, pid)
    assert draft["status"] == "drafting" and draft["job"]["status"] == "error"
    assert "key isn't set" in draft["job"]["error"]
    fake_structured.reply = DRAFT
    jobs.retry(draft["job"]["id"])                                        # "Try again"
    jobs.drain()
    assert client.get(f"/api/tasks/projects/{pid}/draft").json()["status"] == "ready"


# ── Breaking a task down ──────────────────────────────────────────────

def test_breaking_a_task_down_proposes_subtasks_you_edit_drop_and_accept(client, fake_structured):
    pid, _ = _project()
    tid = items.create("Run the drop tests", project_id=pid, notes="Five units, from two heights.", estimate_min=240)
    items.create("Write the test plan", parent_id=tid)
    fake_structured.reply = Breakdown(subtasks=[Step(text="Write the test plan", estimate_min=30),
                                                Step(text="Charge five units.", estimate_min=20),
                                                Step(text="Drop from 1 m and 1.5 m", estimate_min=97),
                                                Step(text="Log the damage", estimate_min=-5)])
    assert client.post(f"/api/tasks/{tid}/breakdown").status_code == 201
    jobs.drain()
    draft = client.get(f"/api/tasks/{tid}/breakdown").json()
    assert draft["status"] == "ready" and draft["written_by"].startswith("Claude")
    assert [(p["text"], p["estimate_min"], p["state"]) for p in draft["proposals"]] == [
        ("Charge five units", 20, "proposed"), ("Drop from 1 m and 1.5 m", 90, "proposed"), ("Log the damage", None, "proposed")]
    prompt = fake_structured.calls[0]["prompt"]
    for fact in ("TASK: Run the drop tests", "PROJECT: Hardware launch (Ship 50 units)",
                 "ESTIMATE FOR THE WHOLE TASK: 240 minutes", "SUBTASKS IT HAS ALREADY:\n- Write the test plan",
                 "NOTES:\nFive units, from two heights."):
        assert fact in prompt, fact
    charge, drop, log = (p["id"] for p in draft["proposals"])
    assert items.get(tid)["subtasks"][0]["text"] == "Write the test plan" and len(items.get(tid)["subtasks"]) == 1

    url = f"/api/tasks/drafts/{draft['id']}"
    client.patch(f"{url}/proposals/{charge}", json={"text": "Charge all five units", "estimate_min": 30})
    client.patch(f"{url}/proposals/{log}", json={"state": "dropped"})
    accepted = client.post(f"{url}/accept", json={}).json()
    assert [p["state"] for p in accepted["proposals"]] == ["accepted", "accepted", "dropped"]
    subtasks = items.get(tid)["subtasks"]
    assert [(s["text"], s["estimate_min"], s["source"]) for s in subtasks] == [
        ("Write the test plan", None, "manual"), ("Charge all five units", 30, "ai"), ("Drop from 1 m and 1.5 m", 90, "ai")]
    assert subtasks[1]["attributes"] == {"written_by": draft["written_by"], "edited": True}
    assert subtasks[2]["attributes"]["edited"] is False
    assert "subtask already" in client.patch(f"{url}/proposals/{charge}", json={"text": "x"}).json()["detail"]

    # Again: what you decided stays decided, and nothing it already has is proposed twice.
    fake_structured.reply = Breakdown(subtasks=[Step(text="Charge all five units", estimate_min=30),
                                                Step(text="Photograph each unit", estimate_min=15)])
    client.post(f"/api/tasks/{tid}/breakdown")
    jobs.drain()
    again = client.get(f"/api/tasks/{tid}/breakdown").json()
    assert [(p["text"], p["state"]) for p in again["proposals"]] == [
        ("Charge all five units", "accepted"), ("Drop from 1 m and 1.5 m", "accepted"), ("Log the damage", "dropped"),
        ("Photograph each unit", "proposed")]
    photo = again["proposals"][3]["id"]
    client.patch(f"{url}/proposals/{log}", json={"state": "proposed"})                # bring a dropped one back
    one = client.post(f"{url}/accept", json={"ids": [photo]}).json()
    assert [p["state"] for p in one["proposals"]] == ["accepted", "accepted", "proposed", "accepted"]
    assert len(items.get(tid)["subtasks"]) == 4


def test_a_task_deleted_while_drafting_takes_its_draft_with_it(client, fake_structured):
    tid = items.create("Write the launch post")
    fake_structured.reply = Breakdown(subtasks=[Step(text="Outline it", estimate_min=30)])
    client.post(f"/api/tasks/{tid}/breakdown")
    jobs.drain()
    items.delete(tid)
    assert db.one("SELECT count(*) AS n FROM tasks_drafts")["n"] == 0
    assert client.get(f"/api/tasks/{tid}/breakdown").status_code == 404


# ── Posting it where a linked task also lives (contracts.WORK_COMMENT_REQUESTED) ──

@pytest.fixture
def taker(monkeypatch, probe_item):
    """Stands in for the module that posts elsewhere: records each request and links the update to a waiting request
    (kind "share"), as the contract asks."""
    asked: list[dict] = []

    def take(payload):
        asked.append(payload)
        links.add(payload["update_ref"], probe_item("Waiting for you to post it"), "share")

    monkeypatch.setitem(events._subscribers, contracts.WORK_COMMENT_REQUESTED, [take])
    return asked


def _linked(project_ref="elsewhere:proj1") -> tuple[str, str]:
    """A project kept elsewhere too, and a linked task in it."""
    events.publish(contracts.WORK_PROJECT_ARRIVED, {"ref": project_ref, "name": "Software", "source": "Elsewhere"})
    events.publish(contracts.WORK_ARRIVED, {"ref": "elsewhere:item1", "project_ref": project_ref, "source": "Elsewhere",
                                            "fields": {"text": "Share the GitHub repos", "status": "doing"}})
    tid = links.sources("elsewhere:item1", "synced")[0].split(":", 1)[1]
    return items.get(tid)["project_id"], tid


def test_a_comment_on_a_linked_task_asks_to_be_posted_there(taker, client):
    _, tid = _linked()
    update = client.post(f"/api/tasks/{tid}/updates", json={"body": "Shared both repos with Dale."}).json()
    r = client.post(f"/api/tasks/updates/{update['id']}/share", json={})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Waiting for you to post it"
    assert taker == [{"ref": "elsewhere:item1", "local_ref": f"tasks:{tid}", "update_ref": f"tasks:{update['id']}",
                      "body": "Shared both repos with Dale.", "written_by": None}]
    [shown] = client.get(f"/api/tasks/{tid}").json()["updates"]
    assert shown["shared"] == [{"title": "Waiting for you to post it", "href": r.json()["href"], "state": "waiting"}]

    there = links.targets(f"tasks:{update['id']}", "share")[0]                 # once it's there
    links.remove(f"tasks:{update['id']}", there, "share")
    links.add(f"tasks:{update['id']}", there, "posted")
    assert client.get(f"/api/tasks/{tid}").json()["updates"][0]["shared"][0]["state"] == "posted"
    assert "already" in client.post(f"/api/tasks/updates/{update['id']}/share", json={}).json()["detail"]


def test_a_posted_status_draft_goes_on_one_of_the_projects_linked_tasks(taker, client, fake_structured):
    pid, tid = _linked()
    mine = items.create("Write the docs", project_id=pid)                        # not linked
    elsewhere = items.create("Something else")
    fake_structured.reply = DRAFT
    draft = _draft(client, pid)
    url = f"/api/tasks/drafts/{draft['id']}/post"
    assert "isn't linked anywhere" in client.post(url, json={"share_on": mine}).json()["detail"]
    assert "isn't in this project" in client.post(url, json={"share_on": elsewhere}).json()["detail"]
    assert projects.updates(pid) == [] and taker == []                         # a wrong choice posts nothing
    update = client.post(url, json={"share_on": tid}).json()
    assert update["kind"] == "status" and update["asked"]["title"] == "Waiting for you to post it"
    [asked] = taker
    assert asked["ref"] == "elsewhere:item1" and asked["local_ref"] == f"tasks:{tid}"
    assert asked["update_ref"] == f"tasks:{update['id']}" and asked["written_by"] == draft["written_by"]
    assert client.get(f"/api/tasks/projects/{pid}").json()["latest_status"]["shared"][0]["state"] == "waiting"
    # A project's update can be offered later too, but it has to say which task it goes on.
    other = client.post(f"/api/tasks/projects/{pid}/updates", json={"body": "A note."}).json()
    assert "Choose which" in client.post(f"/api/tasks/updates/{other['id']}/share", json={}).json()["detail"]
    assert client.post(f"/api/tasks/updates/{other['id']}/share", json={"item_id": tid}).status_code == 200


def test_posting_there_with_nothing_listening_says_so(client, monkeypatch):
    monkeypatch.setitem(events._subscribers, contracts.WORK_COMMENT_REQUESTED, [])
    _, tid = _linked()
    update = client.post(f"/api/tasks/{tid}/updates", json={"body": "Done."}).json()
    r = client.post(f"/api/tasks/updates/{update['id']}/share", json={})
    assert r.status_code == 400 and "Nothing took it" in r.json()["detail"]
    plain = items.create("My own task")
    note = client.post(f"/api/tasks/{plain}/updates", json={"body": "Hm."}).json()
    assert "isn't linked anywhere" in client.post(f"/api/tasks/updates/{note['id']}/share", json={}).json()["detail"]
