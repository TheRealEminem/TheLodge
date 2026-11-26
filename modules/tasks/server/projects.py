"""Projects, their milestones, and updates (comments and status updates on a project or an item).

Worked out, never stored (the Lodge blueprint §4): progress is done ÷ (all − dropped) over a project's or a
milestone's top-level items (subtasks belong to their parent); late is open and due before today. A status update
with a health sets the project's health, which is your judgment, kept with the update that said it.
"""
from core.server import contracts, db, events, links

from . import items, store, vocab

PROJECT_EDITABLE = {"name", "summary", "brief", "status", "health", "start_on", "due_on", "owner_ref", "owner_name",
                    "tags", "attributes", "archived"}


def _ref(project_id: str) -> str:
    return links.ref("tasks", project_id)


def _row(project_id: str) -> dict | None:
    return db.one("SELECT * FROM tasks_projects WHERE id = ?", (project_id,))


def _health(value):
    return None if value in (None, "") else store.one_of(value, vocab.HEALTH, "Health")


def _link_owner(project_id: str, old: str | None, new: str | None) -> None:
    if old == new:
        return
    if old and not old.startswith("core:"):
        links.remove(_ref(project_id), old, "owner")
    if new and not new.startswith("core:"):
        links.add(_ref(project_id), new, "owner")


# ── Rollups ───────────────────────────────────────────────────────────

def _rollup(where: str, args: tuple) -> dict:
    t = items.today().isoformat()
    row = db.one(
        "SELECT count(*) AS total, sum(status = 'done') AS done, sum(status = 'dropped') AS dropped, "
        "sum(status IN ('todo', 'doing', 'waiting') AND due_on < ?) AS late, "
        "min(CASE WHEN status IN ('todo', 'doing', 'waiting') THEN due_on END) AS next_due "
        f"FROM tasks_items WHERE parent_id IS NULL AND {where}", (t, *args))
    by_status = {r["status"]: r["n"] for r in db.query(
        f"SELECT status, count(*) AS n FROM tasks_items WHERE parent_id IS NULL AND {where} GROUP BY status", args)}
    total, done, dropped = row["total"], row["done"] or 0, row["dropped"] or 0
    counted = total - dropped
    return {"total": total, "done": done, "counted": counted, "progress": (done / counted) if counted else None,
            "late": row["late"] or 0, "next_due": row["next_due"],
            "by_status": {s: by_status.get(s, 0) for s in vocab.ITEM_STATUSES}}


def _shaped(row: dict) -> dict:
    project = store.parsed(row)
    project["archived"] = project["archived_at"] is not None
    project["rollup"] = _rollup("project_id = ?", (row["id"],))
    return project


# ── Projects ──────────────────────────────────────────────────────────

def create(name: str, *, summary=None, brief="", status="active", health=None, start_on=None, due_on=None,
           owner_ref=None, owner_name=None, tags=None, attributes=None, source="manual") -> str:
    name = store.text(name, "A project")
    owner_ref = store.ref(owner_ref, "An owner")
    project_id, now = db.new_id(), db.now()
    db.execute(
        "INSERT INTO tasks_projects (id, name, summary, brief, status, health, start_on, due_on, owner_ref, owner_name, "
        "attributes, tags, sort, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, name, store.name_or_none(summary, "A summary"), store.words(brief, "A brief"),
         store.one_of(status, vocab.PROJECT_STATUSES, "Status"), _health(health), store.day(start_on), store.day(due_on),
         owner_ref, store.name_or_none(owner_name, "An owner's name"), store.attributes(attributes), store.tags(tags),
         store.sort_last("tasks_projects", "1", ()), store.one_of(source, vocab.PROJECT_SOURCES, "Source"), now, now))
    _link_owner(project_id, None, owner_ref)
    store.index("project", project_id, name, "\n".join(filter(None, [summary, brief])))
    store.changed(project_id)
    return project_id


def get(project_id: str) -> dict | None:
    """A project with its rollup, its milestones (each with its own), and its latest status update."""
    row = _row(project_id)
    if row is None:
        return None
    project = _shaped(row)
    project["milestones"] = [
        {**dict(m), "done": m["done_at"] is not None, "rollup": _rollup("milestone_id = ?", (m["id"],))}
        for m in db.query("SELECT * FROM tasks_milestones WHERE project_id = ? ORDER BY sort, created_at", (project_id,))]
    project["latest_status"] = db.one(
        "SELECT * FROM tasks_updates WHERE project_id = ? AND kind = 'status' ORDER BY created_at DESC LIMIT 1",
        (project_id,))
    return project


def query(status: str | None = None, archived: bool = False) -> list[dict]:
    """Projects in your order. status: one status, or "all" (default: everything that isn't archived)."""
    where, args = ["archived_at IS NOT NULL" if archived else "archived_at IS NULL"], []
    if status and status != "all":
        where.append("status = ?")
        args.append(store.one_of(status, vocab.PROJECT_STATUSES, "Status"))
    rows = db.query(f"SELECT * FROM tasks_projects WHERE {' AND '.join(where)} ORDER BY sort, created_at", args)
    return [_shaped(r) for r in rows]


def update(project_id: str, changes: dict) -> dict:
    row = _row(project_id)
    if row is None:
        raise KeyError(project_id)
    unknown = set(changes) - PROJECT_EDITABLE
    if unknown:
        raise ValueError(f"Can't change {', '.join(sorted(unknown))}")
    cols: dict = {}
    if "name" in changes:
        cols["name"] = store.text(changes["name"], "A project")
    if "summary" in changes:
        cols["summary"] = store.name_or_none(changes["summary"], "A summary")
    if "brief" in changes:
        cols["brief"] = store.words(changes["brief"], "A brief")
    if "status" in changes:
        cols["status"] = store.one_of(changes["status"], vocab.PROJECT_STATUSES, "Status")
    if "health" in changes:
        cols["health"] = _health(changes["health"])
    for key in ("start_on", "due_on"):
        if key in changes:
            cols[key] = store.day(changes[key])
    if "owner_ref" in changes:
        cols["owner_ref"] = store.ref(changes["owner_ref"], "An owner")
        cols.setdefault("owner_name", None)
    if "owner_name" in changes:
        cols["owner_name"] = store.name_or_none(changes["owner_name"], "An owner's name")
    if "tags" in changes:
        cols["tags"] = store.tags(changes["tags"])
    if "attributes" in changes:
        cols["attributes"] = store.attributes(changes["attributes"])
    if "archived" in changes:
        if not isinstance(changes["archived"], bool):
            raise ValueError("archived is true or false")
        cols["archived_at"] = (row["archived_at"] or db.now()) if changes["archived"] else None
    if cols:
        cols["updated_at"] = db.now()
        db.execute(f"UPDATE tasks_projects SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                   (*cols.values(), project_id))
    if "owner_ref" in cols:
        _link_owner(project_id, row["owner_ref"], cols["owner_ref"])
    fresh = _row(project_id)
    store.index("project", project_id, fresh["name"], "\n".join(filter(None, [fresh["summary"], fresh["brief"]])))
    store.changed(project_id)
    return get(project_id)


def move(project_id: str, after_id: str | None) -> dict:
    """Your order of projects: right after `after_id` (first when None)."""
    if _row(project_id) is None:
        raise KeyError(project_id)
    sort = store.sort_after("tasks_projects", "id <> ?", (project_id,), after_id)
    db.execute("UPDATE tasks_projects SET sort = ? WHERE id = ?", (sort, project_id))
    store.changed(project_id)
    return get(project_id)


def delete(project_id: str) -> bool:
    """Deletes a project, its milestones and its updates. Its items stay, in no project (archive to keep it whole)."""
    if _row(project_id) is None:
        return False
    db.execute("DELETE FROM tasks_projects WHERE id = ?", (project_id,))
    store.unindex(project_id)
    links.forget(_ref(project_id))
    events.publish(contracts.ITEM_DELETED, {"ref": _ref(project_id)})
    store.changed(project_id)
    return True


# ── Milestones ────────────────────────────────────────────────────────

def add_milestone(project_id: str, name: str, due_on=None) -> dict:
    if _row(project_id) is None:
        raise KeyError(project_id)
    milestone_id, now = db.new_id(), db.now()
    db.execute("INSERT INTO tasks_milestones (id, project_id, name, due_on, sort, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)",
               (milestone_id, project_id, store.text(name, "A milestone"), store.day(due_on),
                store.sort_last("tasks_milestones", "project_id = ?", (project_id,)), now, now))
    store.changed(project_id, milestone_id=milestone_id)
    return milestone(milestone_id)


def milestone(milestone_id: str) -> dict | None:
    row = db.one("SELECT * FROM tasks_milestones WHERE id = ?", (milestone_id,))
    if row is None:
        return None
    return {**dict(row), "done": row["done_at"] is not None, "rollup": _rollup("milestone_id = ?", (milestone_id,))}


def update_milestone(milestone_id: str, changes: dict) -> dict:
    row = db.one("SELECT * FROM tasks_milestones WHERE id = ?", (milestone_id,))
    if row is None:
        raise KeyError(milestone_id)
    unknown = set(changes) - {"name", "due_on", "done", "after_id"}
    if unknown:
        raise ValueError(f"Can't change {', '.join(sorted(unknown))}")
    cols: dict = {}
    if "name" in changes:
        cols["name"] = store.text(changes["name"], "A milestone")
    if "due_on" in changes:
        cols["due_on"] = store.day(changes["due_on"])
    if "done" in changes:
        if not isinstance(changes["done"], bool):
            raise ValueError("done is true or false")
        cols["done_at"] = (row["done_at"] or db.now()) if changes["done"] else None
    if "after_id" in changes:
        cols["sort"] = store.sort_after("tasks_milestones", "project_id = ? AND id <> ?", (row["project_id"], milestone_id),
                                        changes["after_id"])
    if cols:
        cols["updated_at"] = db.now()
        db.execute(f"UPDATE tasks_milestones SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                   (*cols.values(), milestone_id))
    store.changed(row["project_id"], milestone_id=milestone_id)
    return milestone(milestone_id)


def delete_milestone(milestone_id: str) -> bool:
    """Its items stay in the project, in no milestone."""
    row = db.one("SELECT project_id FROM tasks_milestones WHERE id = ?", (milestone_id,))
    if row is None:
        return False
    db.execute("DELETE FROM tasks_milestones WHERE id = ?", (milestone_id,))
    store.changed(row["project_id"], milestone_id=milestone_id)
    return True


# ── Updates ───────────────────────────────────────────────────────────

def add_update(*, project_id: str | None = None, item_id: str | None = None, kind: str = "comment", body: str,
               health: str | None = None, author_ref: str | None = "core:me", author_name: str | None = None,
               written_by: str | None = None, edited: bool = False) -> dict:
    """A comment, status update or summary on a project or an item. Written by AI: author_ref None, written_by
    names the provider (shown next to it). Drafted by AI and posted by you (drafts.py): author_ref "core:me",
    written_by the provider, and edited when you changed what it wrote."""
    if (project_id is None) == (item_id is None):
        raise ValueError("An update belongs to a project or to a task")
    store.one_of(kind, vocab.UPDATE_KINDS, "Kind")
    if project_id and _row(project_id) is None:
        raise KeyError(project_id)
    if item_id and items.get(item_id) is None:
        raise KeyError(item_id)
    health = _health(health)
    if health and (kind != "status" or not project_id):
        raise ValueError("Only a project's status update reports health")
    update_id = db.new_id()
    db.execute("INSERT INTO tasks_updates (id, project_id, item_id, kind, body, health, author_ref, author_name, "
               "written_by, edited, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (update_id, project_id, item_id, kind, store.text(body, "An update"), health,
                store.ref(author_ref, "An author"), store.name_or_none(author_name, "An author's name"), written_by,
                int(bool(edited and written_by)), db.now()))
    if health:
        db.execute("UPDATE tasks_projects SET health = ?, updated_at = ? WHERE id = ?", (health, db.now(), project_id))
    owner = project_id or (items.get(item_id) or {}).get("project_id")
    store.changed(owner, update_id=update_id)
    return dict(db.one("SELECT * FROM tasks_updates WHERE id = ?", (update_id,)))


def updates(project_id: str) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM tasks_updates WHERE project_id = ? ORDER BY created_at DESC",
                                      (project_id,))]
