"""What the host and other modules reach the tasks module through: the shared contracts it listens to, how its
things are named and found elsewhere, and what it holds (export, backup labels)."""
import json

from core.server import db

from . import items, store, vocab


def take_actions(payload: dict) -> None:
    """contracts.ACTIONS_FOUND: a source (a note, a meeting) found action items. They replace that source's earlier
    ones you haven't touched; anything you changed, ticked or moved stays. An item is text, or {"text", "due_on"?,
    "assignee_ref"?, "assignee_name"?, "priority"?}. New items go into the project the source is linked to, when
    it's linked to exactly one; otherwise they wait, in no project."""
    source = payload["source_ref"]
    untouched = db.query(
        "SELECT id FROM tasks_items WHERE source_ref = ? AND status = 'todo' AND updated_at = created_at "
        "AND project_id IS NULL AND notes = '' AND parent_id IS NULL", (source,))
    for row in untouched:
        items.delete(row["id"])
    kept = {r["text"] for r in db.query("SELECT text FROM tasks_items WHERE source_ref = ?", (source,))}
    projects = [ref for ref in _linked_projects(source)]
    project_id = projects[0] if len(projects) == 1 else None
    for raw in payload.get("items", []):
        found = {"text": raw} if isinstance(raw, str) else dict(raw)
        text = (found.get("text") or "").strip()
        if not text or text in kept:
            continue
        try:
            items.create(text, project_id=project_id, source="action-item", source_ref=source,
                         due_on=found.get("due_on"), assignee_ref=found.get("assignee_ref"),
                         assignee_name=found.get("assignee_name"), priority=found.get("priority", 0), quiet=True)
        except ValueError:
            items.create(text, project_id=project_id, source="action-item", source_ref=source, quiet=True)
        kept.add(text)
    store.changed(project_id, source_ref=source)


def _linked_projects(source_ref: str) -> list[str]:
    """Projects in this module that source_ref is linked to, either way round."""
    refs = [r["to_ref"] for r in db.query("SELECT to_ref FROM core_links WHERE from_ref = ?", (source_ref,))]
    refs += [r["from_ref"] for r in db.query("SELECT from_ref FROM core_links WHERE to_ref = ?", (source_ref,))]
    ids = [r.split(":", 1)[1] for r in refs if r.startswith("tasks:")]
    if not ids:
        return []
    found = db.query(f"SELECT id FROM tasks_projects WHERE archived_at IS NULL AND id IN ({','.join('?' * len(ids))})", ids)
    return sorted({r["id"] for r in found})


def source_deleted(payload: dict) -> None:
    """contracts.ITEM_DELETED: something elsewhere is gone. Items keep the names they showed, but stop pointing at
    it (where they came from, who's doing them, who owns or wrote them)."""
    ref = payload["ref"]
    if ref.startswith("tasks:"):
        return
    db.execute("UPDATE tasks_items SET source_ref = NULL WHERE source_ref = ?", (ref,))
    db.execute("UPDATE tasks_items SET assignee_ref = NULL WHERE assignee_ref = ?", (ref,))
    db.execute("UPDATE tasks_projects SET owner_ref = NULL WHERE owner_ref = ?", (ref,))
    db.execute("UPDATE tasks_updates SET author_ref = NULL WHERE author_ref = ?", (ref,))


# Where an item or a project opens.
ITEM_HREF = "#/tasks/t/{id}"
PROJECT_HREF = "#/tasks/projects/{id}"


def describe(row_id: str) -> dict | None:
    """Items and projects share the "tasks:" refs (their ids never collide)."""
    item = db.one("SELECT text FROM tasks_items WHERE id = ?", (row_id,))
    if item:
        return {"title": item["text"], "href": ITEM_HREF.format(id=row_id)}
    project = db.one("SELECT name FROM tasks_projects WHERE id = ?", (row_id,))
    return {"title": project["name"], "href": PROJECT_HREF.format(id=row_id)} if project else None


def search(q: str, limit: int) -> list[dict]:
    words = " ".join(f'"{w}"*' for w in q.replace('"', " ").split())
    if not words:
        return []
    rows = db.query("SELECT id, kind, title FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?", (words, limit))
    out = []
    for r in rows:
        if r["kind"] == "project":
            out.append({"id": r["id"], "title": r["title"], "snippet": "Project"})
        else:
            row = db.one("SELECT status FROM tasks_items WHERE id = ?", (r["id"],))
            label = vocab.ITEM_STATUSES.get(row["status"], {}).get("label", "") if row else ""
            out.append({"id": r["id"], "title": r["title"], "snippet": label})
    return out


def export() -> dict:
    """Everything this module holds, as plain data for the host's JSON export."""
    def rows(sql: str) -> list[dict]:
        return [store.parsed(r) for r in db.query(sql)]
    return {
        "projects": rows("SELECT * FROM tasks_projects ORDER BY sort, created_at"),
        "milestones": rows("SELECT * FROM tasks_milestones ORDER BY project_id, sort"),
        "items": rows("SELECT * FROM tasks_items ORDER BY project_id, sort, created_at"),
        "updates": rows("SELECT * FROM tasks_updates ORDER BY created_at"),
        "blockers": rows("SELECT * FROM tasks_blockers ORDER BY created_at"),
        "synced": [{**r, "base": json.loads(r["base"]), "conflicts": json.loads(r["conflicts"])}
                   for r in db.query("SELECT * FROM tasks_synced ORDER BY created_at")],
    }


def count(conn) -> dict:
    """What a database holds (a backup's, opened read-only), to label it: projects, and tasks still open."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    out = {}
    if "tasks_projects" in tables:
        out["projects"] = conn.execute("SELECT count(*) FROM tasks_projects WHERE archived_at IS NULL").fetchone()[0]
    if "tasks_items" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks_items)")}
        open_sql = "status IN ('todo', 'doing', 'waiting')" if "status" in cols else "done = 0"
        out["open tasks"] = conn.execute(f"SELECT count(*) FROM tasks_items WHERE {open_sql}").fetchone()[0]
    return out
