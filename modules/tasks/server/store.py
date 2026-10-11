"""The tasks module's table (tasks_items) and how it takes in action items from other modules."""
from core.server import db, events, links

MIGRATIONS = [
    """
    CREATE TABLE tasks_items (
        id          TEXT PRIMARY KEY,
        text        TEXT NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        source_ref  TEXT,                 -- where it came from ("notes:<id>"), if anywhere
        created_at  TEXT NOT NULL
    );
    CREATE INDEX tasks_items_source ON tasks_items(source_ref);
    """,
]


def create(text: str, source_ref: str | None = None) -> str:
    task_id = db.new_id()
    db.execute("INSERT INTO tasks_items (id, text, source_ref, created_at) VALUES (?, ?, ?, ?)",
               (task_id, text, source_ref, db.now()))
    if source_ref:
        links.add(source_ref, links.ref("tasks", task_id), "action-item")
    return task_id


def take_actions(payload: dict) -> None:
    """contracts.ACTIONS_FOUND: replace the open tasks from that source with the new list (ticked ones stay)."""
    source = payload["source_ref"]
    for row in db.query("SELECT id FROM tasks_items WHERE source_ref = ? AND done = 0", (source,)):
        links.forget(links.ref("tasks", row["id"]))
    db.execute("DELETE FROM tasks_items WHERE source_ref = ? AND done = 0", (source,))
    kept = {r["text"] for r in db.query("SELECT text FROM tasks_items WHERE source_ref = ?", (source,))}
    for text in payload.get("items", []):
        if text not in kept:
            create(text, source)
    events.publish("tasks.changed", {"source_ref": source})


def source_deleted(payload: dict) -> None:
    """contracts.ITEM_DELETED: tasks outlive their source, but no longer point at it."""
    db.execute("UPDATE tasks_items SET source_ref = NULL WHERE source_ref = ?", (payload["ref"],))


def all_tasks() -> list[dict]:
    rows = db.query("SELECT * FROM tasks_items ORDER BY done, created_at DESC")
    return [{**r, "done": bool(r["done"])} for r in rows]


def set_done(task_id: str, done: bool) -> bool:
    return db.execute("UPDATE tasks_items SET done = ? WHERE id = ?", (int(done), task_id)) > 0


def delete(task_id: str) -> None:
    db.execute("DELETE FROM tasks_items WHERE id = ?", (task_id,))
    links.forget(links.ref("tasks", task_id))


def open_count() -> int:
    return db.one("SELECT count(*) AS n FROM tasks_items WHERE done = 0")["n"]


def describe(task_id: str) -> dict | None:
    row = db.one("SELECT text FROM tasks_items WHERE id = ?", (task_id,))
    return {"title": row["text"], "href": "#/tasks"} if row else None


def search(q: str, limit: int) -> list[dict]:
    rows = db.query("SELECT id, text FROM tasks_items WHERE text LIKE ? ORDER BY done, created_at DESC LIMIT ?",
                    (f"%{q}%", limit))
    return [{"id": r["id"], "title": r["text"], "snippet": ""} for r in rows]
