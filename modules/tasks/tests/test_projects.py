"""Projects, milestones and updates, what the module gives the host (export, backup label, search), and the API."""
import sqlite3

import pytest

from core.server import db, module
from modules.tasks.server import hooks, items, projects


def test_progress_counts_top_level_items_and_leaves_dropped_ones_out():
    p = projects.create("Relaunch", due_on="2026-12-01")
    m = projects.add_milestone(p, "Designs", "2026-11-01")["id"]
    a = items.create("Wireframes", milestone_id=m, status="done")
    items.create("Copy", milestone_id=m)
    items.create("Old idea", project_id=p, status="dropped")
    items.create("Late", project_id=p, due_on="2026-10-01")
    items.create("A subtask", parent_id=a)                                   # not counted on its own
    got = projects.get(p)
    assert (got["rollup"]["done"], got["rollup"]["counted"], got["rollup"]["late"]) == (1, 3, 1)
    assert got["rollup"]["progress"] == pytest.approx(1 / 3) and got["rollup"]["next_due"] == "2026-10-01"
    assert got["milestones"][0]["rollup"]["progress"] == 0.5
    assert projects.get(projects.create("Empty"))["rollup"]["progress"] is None


def test_a_status_update_with_health_sets_the_projects_health():
    p = projects.create("Relaunch")
    projects.add_update(project_id=p, kind="status", body="Designs slipped a week", health="at_risk")
    got = projects.get(p)
    assert got["health"] == "at_risk" and got["latest_status"]["body"] == "Designs slipped a week"
    with pytest.raises(ValueError, match="Only a project's status update"):
        projects.add_update(project_id=p, kind="comment", body="x", health="on_track")
    item = items.create("Copy", project_id=p)
    projects.add_update(item_id=item, body="Ana has it", author_ref="crm:ana1", author_name="Ana Ruiz")
    assert items.get(item)["updates"][0]["author_name"] == "Ana Ruiz"
    ai = projects.add_update(project_id=p, kind="summary", body="Two of five done.", author_ref=None, written_by="anthropic")
    assert (ai["author_ref"], ai["written_by"]) == (None, "anthropic")


def test_archiving_hides_a_project_and_deleting_leaves_its_items_unfiled():
    keep, gone = projects.create("Keep"), projects.create("Gone")
    item = items.create("Survivor", project_id=gone)
    projects.update(keep, {"archived": True})
    assert [p["name"] for p in projects.query()] == ["Gone"]
    assert [p["name"] for p in projects.query(archived=True)] == ["Keep"]
    assert projects.delete(gone)
    assert items.get(item)["project_id"] is None


def test_milestones_tick_off_and_keep_your_order():
    p = projects.create("Relaunch")
    a = projects.add_milestone(p, "Designs")["id"]
    b = projects.add_milestone(p, "Build")["id"]
    assert projects.update_milestone(a, {"done": True})["done"]
    projects.update_milestone(b, {"after_id": None})
    assert [m["name"] for m in projects.get(p)["milestones"]] == ["Build", "Designs"]
    item = items.create("Wireframes", milestone_id=a)
    projects.delete_milestone(a)
    assert (items.get(item)["project_id"], items.get(item)["milestone_id"]) == (p, None)


def test_projects_keep_your_order():
    a, b, c = (projects.create(n) for n in ("A", "B", "C"))
    projects.move(c, a)
    assert [p["name"] for p in projects.query()] == ["A", "C", "B"]


def test_search_finds_projects_and_items_and_describe_names_them():
    p = projects.create("Riverbend relaunch", summary="New site by December")
    item = items.create("Draft the riverbend outline")
    found = {r["id"]: r for r in hooks.search("riverbend", 10)}
    assert found[p]["snippet"] == "Project" and found[item]["snippet"] == "To do"
    assert module.describe(f"tasks:{p}")["title"] == "Riverbend relaunch"
    assert module.describe(f"tasks:{item}")["title"] == "Draft the riverbend outline"
    assert module.describe(f"tasks:{item}")["href"] == f"#/tasks/t/{item}"
    assert module.describe(f"tasks:{p}")["href"] == f"#/tasks/projects/{p}"


def test_export_and_the_backup_label(tmp_path):
    p = projects.create("Relaunch", tags=["Client Work"])
    items.create("Open one", project_id=p)
    items.create("Done one", status="done")
    out = hooks.export()
    assert out["projects"][0]["tags"] == ["client-work"] and len(out["items"]) == 2
    with sqlite3.connect(db.DB_PATH) as conn:
        assert hooks.count(conn) == {"projects": 1, "open tasks": 1}
    old = sqlite3.connect(tmp_path / "v1.db")                                # a backup from before step 2
    old.execute("CREATE TABLE tasks_items (id TEXT, text TEXT, done INTEGER, source_ref TEXT, created_at TEXT)")
    old.execute("INSERT INTO tasks_items VALUES ('a', 'x', 0, NULL, 'now')")
    assert hooks.count(old) == {"open tasks": 1}


# ── The API ───────────────────────────────────────────────────────────

def test_the_api_round_trips_projects_milestones_items_and_updates(client):
    pid = client.post("/api/tasks/projects", json={"name": "Relaunch", "due_on": "2026-12-01", "owner_ref": "core:me"}).json()["id"]
    mid = client.post(f"/api/tasks/projects/{pid}/milestones", json={"name": "Designs"}).json()["id"]
    tid = client.post("/api/tasks", json={"text": "Wireframes", "milestone_id": mid, "priority": 3,
                                          "assignee_ref": "core:me", "tags": ["design"]}).json()["id"]
    sub = client.post("/api/tasks", json={"text": "Mobile", "parent_id": tid}).json()["id"]
    got = client.get(f"/api/tasks/{tid}").json()
    assert (got["project_id"], got["priority"], got["tags"], got["subtasks"][0]["id"]) == (pid, 3, ["design"], sub)
    assert client.patch(f"/api/tasks/{tid}", json={"status": "doing", "due_on": "2026-11-01"}).json()["status"] == "doing"
    client.post(f"/api/tasks/{tid}/updates", json={"body": "Halfway"})
    client.post(f"/api/tasks/projects/{pid}/updates", json={"kind": "status", "body": "On track", "health": "on_track"})
    project = client.get(f"/api/tasks/projects/{pid}").json()
    assert project["health"] == "on_track" and project["milestones"][0]["id"] == mid
    assert [p["id"] for p in client.get("/api/tasks/projects").json()] == [pid]   # not taken for a task id
    assert client.get("/api/tasks/meta").json()["priorities"][4]["label"] == "Urgent"
    assert client.get("/api/tasks/count").json()["open"] == 2
    assert client.delete(f"/api/tasks/projects/{pid}").status_code == 204
    assert client.get(f"/api/tasks/{tid}").json()["project_id"] is None


def test_the_api_says_what_went_wrong(client):
    assert client.post("/api/tasks", json={}).json()["detail"] == "A task needs some text"
    assert client.post("/api/tasks", json={"text": "x", "colour": "red"}).json()["detail"] == "Can't set colour"
    r = client.post("/api/tasks", json={"text": "x", "due_on": "next week"})
    assert r.status_code == 400 and "isn't a date" in r.json()["detail"]
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.patch("/api/tasks/nope", json={"done": True}).status_code == 404
    assert client.delete("/api/tasks/nope").status_code == 404
    assert client.get("/api/tasks/projects/nope").status_code == 404
    tid = client.post("/api/tasks", json={"text": "x"}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/blockers", json={}).status_code == 400
    assert client.get("/api/tasks", params={"when": "someday"}).status_code == 400
