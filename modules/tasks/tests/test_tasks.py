from core.server import contracts, events


def test_new_action_items_replace_open_ones_but_ticked_tasks_stay(client):
    source = "notes:feedcafe"
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": source, "items": ["One", "Two"]})
    tasks = {t["text"]: t for t in client.get("/api/tasks").json() if t["source_ref"] == source}
    client.patch(f"/api/tasks/{tasks['One']['id']}", json={"done": True})

    events.publish(contracts.ACTIONS_FOUND, {"source_ref": source, "items": ["One", "Three"]})
    now = sorted((t["text"], t["done"]) for t in client.get("/api/tasks").json() if t["source_ref"] == source)
    assert now == [("One", True), ("Three", False)]


def test_count_is_open_tasks_only(client):
    before = client.get("/api/tasks/count").json()["open"]
    task_id = client.post("/api/tasks", json={"text": "Count me"}).json()["id"]
    assert client.get("/api/tasks/count").json()["open"] == before + 1
    client.patch(f"/api/tasks/{task_id}", json={"done": True})
    assert client.get("/api/tasks/count").json()["open"] == before
