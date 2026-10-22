"""Work items: the to-dos, grown up. An item belongs to at most one project and one milestone, may be a subtask of
another item, may wait on other items (blockers), and has a status, priority, dates and an assignee.

Rules (the Lodge blueprint §4): one function changes status and keeps done, completed_at and updated_at in step;
every write re-indexes the item for search and says tasks.changed; deleting an item says item.deleted and forgets
its links. An assignee is kept twice on purpose: the column answers "what's on Ana's plate?" here, and a link lets
Ana's profile in another module list her tasks without reading this module's tables.
"""
from datetime import date, timedelta

from core.server import contracts, db, events, links

from . import store, vocab

EDITABLE = {"text", "notes", "status", "priority", "start_on", "due_on", "assignee_ref", "assignee_name",
            "estimate_min", "tags", "attributes", "project_id", "milestone_id", "parent_id", "done"}


def today() -> date:
    """The local calendar day (tests replace it)."""
    return date.today()


# Yours: nobody's on it, or you are. Anything with someone else's ref or name is theirs.
# (IS, not =, so a task with a name but no ref is someone else's rather than unknown.)
MINE_SQL = "((assignee_ref IS NULL AND assignee_name IS NULL) OR assignee_ref IS 'core:me')"


def _assignee_sql(assignee: str | None) -> tuple[str | None, list]:
    """assignee: a ref, "mine" or "others"."""
    if not assignee:
        return None, []
    if assignee == "mine":
        return MINE_SQL, []
    if assignee == "others":
        return f"NOT {MINE_SQL}", []
    return "assignee_ref = ?", [assignee]


def _ref(item_id: str) -> str:
    return links.ref("tasks", item_id)


def _row(item_id: str) -> dict | None:
    return db.one("SELECT * FROM tasks_items WHERE id = ?", (item_id,))


def _place(project_id, milestone_id, parent_id, item_id: str | None = None) -> tuple:
    """Where an item may live. A subtask lives with its parent; a milestone decides its project."""
    if parent_id:
        parent = _row(parent_id)
        if parent is None:
            raise ValueError("That parent task doesn't exist")
        if item_id and (parent_id == item_id or item_id in _ancestors(parent_id)):
            raise ValueError("A task can't be inside itself")
        return parent["project_id"], parent["milestone_id"], parent_id
    if milestone_id:
        ms = db.one("SELECT project_id FROM tasks_milestones WHERE id = ?", (milestone_id,))
        if ms is None:
            raise ValueError("That milestone doesn't exist")
        if project_id and project_id != ms["project_id"]:
            raise ValueError("That milestone belongs to another project")
        project_id = ms["project_id"]
    if project_id and not db.one("SELECT 1 FROM tasks_projects WHERE id = ?", (project_id,)):
        raise ValueError("That project doesn't exist")
    return project_id, milestone_id, None


def _ancestors(item_id: str) -> list[str]:
    out, seen = [], set()
    row = _row(item_id)
    while row and row["parent_id"] and row["parent_id"] not in seen:
        seen.add(row["parent_id"])
        out.append(row["parent_id"])
        row = _row(row["parent_id"])
    return out


def _scope(project_id, milestone_id, parent_id) -> tuple[str, tuple]:
    """The list an item is ordered within: its parent's subtasks, or its project and milestone's top-level items."""
    if parent_id:
        return "parent_id = ?", (parent_id,)
    return ("parent_id IS NULL AND project_id IS ? AND milestone_id IS ?", (project_id, milestone_id))


def _link_person(item_id: str, old: str | None, new: str | None) -> None:
    if old == new:
        return
    if old and not old.startswith("core:"):
        links.remove(_ref(item_id), old, "assigned")
    if new and not new.startswith("core:"):                   # core:me has no profile to show it on
        links.add(_ref(item_id), new, "assigned")


def create(text: str, *, project_id=None, milestone_id=None, parent_id=None, status="todo", notes="", priority=0,
           start_on=None, due_on=None, assignee_ref=None, assignee_name=None, estimate_min=None, tags=None,
           attributes=None, source="manual", source_ref=None, quiet=False) -> str:
    text = store.text(text)
    status = store.one_of(status, vocab.ITEM_STATUSES, "Status")
    source = store.one_of(source, vocab.ITEM_SOURCES, "Source")
    project_id, milestone_id, parent_id = _place(project_id, milestone_id, parent_id)
    assignee_ref = store.ref(assignee_ref, "An assignee")
    item_id, now = db.new_id(), db.now()
    scope_sql, scope_args = _scope(project_id, milestone_id, parent_id)
    done = status == "done"
    db.execute(
        "INSERT INTO tasks_items (id, text, done, source_ref, created_at, project_id, milestone_id, parent_id, status, "
        "notes, priority, start_on, due_on, assignee_ref, assignee_name, estimate_min, sort, attributes, tags, source, "
        "completed_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, text, int(done), store.ref(source_ref, "A source"), now, project_id, milestone_id, parent_id, status,
         store.words(notes, "Notes"), store.priority(priority), store.day(start_on), store.day(due_on), assignee_ref,
         store.name_or_none(assignee_name, "An assignee's name"), store.minutes(estimate_min),
         store.sort_last("tasks_items", scope_sql, scope_args), store.attributes(attributes), store.tags(tags), source,
         now if done else None, now),
    )
    if source_ref:
        links.add(source_ref, _ref(item_id), "action-item")
    _link_person(item_id, None, assignee_ref)
    store.index("item", item_id, text, notes or "")
    if not quiet:
        store.changed(project_id, item_id=item_id)
    return item_id


def get(item_id: str) -> dict | None:
    """One item with what surrounds it: subtasks, blockers (and whether any is still open) and updates."""
    item = store.parsed(_row(item_id))
    if item is None:
        return None
    item["subtasks"] = [store.parsed(r) for r in db.query(
        "SELECT * FROM tasks_items WHERE parent_id = ? ORDER BY sort, created_at", (item_id,))]
    item["blocked_by"] = [dict(r) for r in db.query(
        "SELECT i.id, i.text, i.status FROM tasks_blockers b JOIN tasks_items i ON i.id = b.blocked_by "
        "WHERE b.item_id = ? ORDER BY b.created_at", (item_id,))]
    item["blocks"] = [dict(r) for r in db.query(
        "SELECT i.id, i.text, i.status FROM tasks_blockers b JOIN tasks_items i ON i.id = b.item_id "
        "WHERE b.blocked_by = ? ORDER BY b.created_at", (item_id,))]
    item["blocked"] = any(b["status"] in vocab.OPEN for b in item["blocked_by"])
    item["updates"] = [dict(r) for r in db.query(
        "SELECT * FROM tasks_updates WHERE item_id = ? ORDER BY created_at", (item_id,))]
    return item


def query(*, project: str | None = None, assignee: str | None = None, status: str | None = None,
          when: str | None = None, q: str | None = None, parent: str | None = "top") -> list[dict]:
    """Items, open first, then by due day (none last), priority and your order.
    project: an id, or "none" for items in no project. assignee: a ref, "mine" (nobody's, or yours) or "others".
    status: a status, several separated by commas, "open" or "all" (default: everything).
    when: "late", "today" (late or due today), "week" (due within seven days) or "waiting" (open and waiting, or
    someone else's). parent: "top" (default: no subtasks), "any", or an item's id for its subtasks."""
    where, args = [], []
    if project == "none":
        where.append("project_id IS NULL")
    elif project:
        where.append("project_id = ?")
        args.append(project)
    who, who_args = _assignee_sql(assignee)
    if who:
        where.append(who)
        args += who_args
    if status == "open":
        where.append(f"status IN ({','.join('?' * len(vocab.OPEN))})")
        args += list(vocab.OPEN)
    elif status and status != "all":
        wanted = [store.one_of(s.strip(), vocab.ITEM_STATUSES, "Status") for s in status.split(",") if s.strip()]
        where.append(f"status IN ({','.join('?' * len(wanted))})")
        args += wanted
    if when:
        t = today()
        open_sql = f"status IN ({','.join('?' * len(vocab.OPEN))})"
        if when == "late":
            where += [open_sql, "due_on < ?"]
            args += [*vocab.OPEN, t.isoformat()]
        elif when == "today":
            where += [open_sql, "due_on <= ?"]
            args += [*vocab.OPEN, t.isoformat()]
        elif when == "week":
            where += [open_sql, "due_on <= ?"]
            args += [*vocab.OPEN, (t + timedelta(days=7)).isoformat()]
        elif when == "waiting":
            where += [open_sql, f"(status = 'waiting' OR NOT {MINE_SQL})"]
            args += list(vocab.OPEN)
        else:
            raise ValueError("when must be late, today, week or waiting")
    if parent == "top":
        where.append("parent_id IS NULL")
    elif parent and parent != "any":
        where.append("parent_id = ?")
        args.append(parent)
    if q and q.strip():
        words = " ".join(f'"{w}"*' for w in q.replace('"', " ").split())
        where.append("id IN (SELECT id FROM tasks_fts WHERE kind = 'item' AND tasks_fts MATCH ?)")
        args.append(words)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"SELECT * FROM tasks_items {clause} ORDER BY CASE WHEN status IN ('done', 'dropped') THEN 1 ELSE 0 END, "
        "due_on IS NULL, due_on, priority DESC, sort, created_at", args)
    blocked = {r["item_id"] for r in db.query(
        "SELECT DISTINCT b.item_id FROM tasks_blockers b JOIN tasks_items i ON i.id = b.blocked_by "
        f"WHERE i.status IN ({','.join('?' * len(vocab.OPEN))})", vocab.OPEN)}
    subtasks = {r["parent_id"]: (r["n"], r["done"]) for r in db.query(
        "SELECT parent_id, count(*) AS n, sum(status = 'done') AS done FROM tasks_items "
        "WHERE parent_id IS NOT NULL AND status <> 'dropped' GROUP BY parent_id")}
    out = []
    for r in rows:
        item = store.parsed(r)
        item["blocked"] = r["id"] in blocked
        n, finished = subtasks.get(r["id"], (0, 0))
        item["subtask_count"], item["subtasks_done"] = n, finished
        out.append(item)
    return out


def set_status(item_id: str, status: str, *, quiet: bool = False) -> dict:
    """The one place status changes: done, completed_at and updated_at follow it."""
    store.one_of(status, vocab.ITEM_STATUSES, "Status")
    row = _row(item_id)
    if row is None:
        raise KeyError(item_id)
    now = db.now()
    done = status == "done"
    completed = (row["completed_at"] or now) if done else None
    db.execute("UPDATE tasks_items SET status = ?, done = ?, completed_at = ?, updated_at = ? WHERE id = ?",
               (status, int(done), completed, now, item_id))
    if not quiet:
        store.changed(row["project_id"], item_id=item_id)
    return get(item_id)


def update(item_id: str, changes: dict) -> dict:
    """Changes any editable field. "done": true/false still works (it sets the status)."""
    row = _row(item_id)
    if row is None:
        raise KeyError(item_id)
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"Can't change {', '.join(sorted(unknown))}")
    changes = dict(changes)
    if "done" in changes:
        flag = changes.pop("done")
        if not isinstance(flag, bool):
            raise ValueError("done is true or false")
        changes.setdefault("status", "done" if flag else ("todo" if row["status"] in ("done", "dropped") else row["status"]))
    cols: dict = {}
    if "text" in changes:
        cols["text"] = store.text(changes["text"])
    if "notes" in changes:
        cols["notes"] = store.words(changes["notes"], "Notes")
    if "priority" in changes:
        cols["priority"] = store.priority(changes["priority"])
    for key in ("start_on", "due_on"):
        if key in changes:
            cols[key] = store.day(changes[key])
    if "assignee_ref" in changes:
        cols["assignee_ref"] = store.ref(changes["assignee_ref"], "An assignee")
        cols.setdefault("assignee_name", None)
    if "assignee_name" in changes:
        cols["assignee_name"] = store.name_or_none(changes["assignee_name"], "An assignee's name")
    if "estimate_min" in changes:
        cols["estimate_min"] = store.minutes(changes["estimate_min"])
    if "tags" in changes:
        cols["tags"] = store.tags(changes["tags"])
    if "attributes" in changes:
        cols["attributes"] = store.attributes(changes["attributes"])
    if {"project_id", "milestone_id", "parent_id"} & set(changes):
        project_id = changes.get("project_id", row["project_id"])
        milestone_id = changes.get("milestone_id", row["milestone_id"] if "project_id" not in changes else None)
        parent_id = changes.get("parent_id", row["parent_id"])
        project_id, milestone_id, parent_id = _place(project_id, milestone_id, parent_id, item_id)
        cols.update(project_id=project_id, milestone_id=milestone_id, parent_id=parent_id)
        if (project_id, milestone_id, parent_id) != (row["project_id"], row["milestone_id"], row["parent_id"]):
            cols["sort"] = store.sort_last("tasks_items", *_scope(project_id, milestone_id, parent_id))
            _move_subtasks(item_id, project_id, milestone_id)
    if cols:
        cols["updated_at"] = db.now()
        db.execute(f"UPDATE tasks_items SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), item_id))
    if "status" in changes and changes["status"] != row["status"]:
        set_status(item_id, changes["status"], quiet=True)
    if "assignee_ref" in cols:
        _link_person(item_id, row["assignee_ref"], cols["assignee_ref"])
    fresh = _row(item_id)
    store.index("item", item_id, fresh["text"], fresh["notes"])
    store.changed(fresh["project_id"], item_id=item_id)
    if fresh["project_id"] != row["project_id"]:
        store.changed(row["project_id"], item_id=item_id)
    return get(item_id)


def _move_subtasks(item_id: str, project_id, milestone_id) -> None:
    """Subtasks always live where their parent does."""
    for child in db.query("SELECT id FROM tasks_items WHERE parent_id = ?", (item_id,)):
        db.execute("UPDATE tasks_items SET project_id = ?, milestone_id = ? WHERE id = ?",
                   (project_id, milestone_id, child["id"]))
        _move_subtasks(child["id"], project_id, milestone_id)


def move(item_id: str, *, project_id=None, milestone_id=None, after_id: str | None = None, within: str = "milestone",
         status: str | None = None) -> dict:
    """Puts a top-level item into a project and milestone (or none), right after `after_id` (first when None).
    within: "milestone" orders it among its milestone's items (the list view); "project" among all the project's
    top-level items, whatever their milestone (the board, where a column mixes milestones). status, when given, is
    set too, so a card dropped in another column changes in one step."""
    row = _row(item_id)
    if row is None:
        raise KeyError(item_id)
    if row["parent_id"]:
        raise ValueError("A subtask moves with its parent")
    store.one_of(within, ("milestone", "project"), "within")
    project_id, milestone_id, _ = _place(project_id, milestone_id, None, item_id)
    if after_id == item_id:
        raise ValueError("A task can't go after itself")
    if within == "project":
        scope_sql, scope_args = "parent_id IS NULL AND project_id IS ?", (project_id,)
    else:
        scope_sql, scope_args = _scope(project_id, milestone_id, None)
    sort = store.sort_after("tasks_items", f"{scope_sql} AND id <> ?", (*scope_args, item_id), after_id)
    db.execute("UPDATE tasks_items SET project_id = ?, milestone_id = ?, sort = ?, updated_at = ? WHERE id = ?",
               (project_id, milestone_id, sort, db.now(), item_id))
    _move_subtasks(item_id, project_id, milestone_id)
    if status is not None and status != row["status"]:
        set_status(item_id, status, quiet=True)
    store.changed(project_id, item_id=item_id)
    if project_id != row["project_id"]:
        store.changed(row["project_id"], item_id=item_id)
    return get(item_id)


def delete(item_id: str) -> bool:
    """Deletes an item and its subtasks. Each says item.deleted, so other modules can let go of it."""
    row = _row(item_id)
    if row is None:
        return False
    gone = [item_id] + _descendants(item_id)
    db.execute("DELETE FROM tasks_items WHERE id = ?", (item_id,))   # subtasks, blockers and updates cascade
    for each in gone:
        store.unindex(each)
        links.forget(_ref(each))
        events.publish(contracts.ITEM_DELETED, {"ref": _ref(each)})
    store.changed(row["project_id"], item_id=item_id)
    return True


def _descendants(item_id: str) -> list[str]:
    out = []
    for child in db.query("SELECT id FROM tasks_items WHERE parent_id = ?", (item_id,)):
        out += [child["id"], *_descendants(child["id"])]
    return out


def block(item_id: str, blocked_by: str) -> dict:
    """item_id can't really start until blocked_by is done. Refuses a loop (A waits on B, which waits on A)."""
    if item_id == blocked_by:
        raise ValueError("A task can't wait on itself")
    if _row(item_id) is None or _row(blocked_by) is None:
        raise KeyError(item_id if _row(item_id) is None else blocked_by)
    if item_id in _waits_on(blocked_by):
        raise ValueError("That would make the two wait on each other")
    db.execute("INSERT OR IGNORE INTO tasks_blockers (item_id, blocked_by, created_at) VALUES (?, ?, ?)",
               (item_id, blocked_by, db.now()))
    store.changed(_row(item_id)["project_id"], item_id=item_id)
    return get(item_id)


def unblock(item_id: str, blocked_by: str) -> dict:
    db.execute("DELETE FROM tasks_blockers WHERE item_id = ? AND blocked_by = ?", (item_id, blocked_by))
    row = _row(item_id)
    if row is None:
        raise KeyError(item_id)
    store.changed(row["project_id"], item_id=item_id)
    return get(item_id)


def _waits_on(item_id: str) -> set[str]:
    """Everything item_id waits on, directly or through others."""
    seen: set[str] = set()
    todo = [item_id]
    while todo:
        for r in db.query("SELECT blocked_by FROM tasks_blockers WHERE item_id = ?", (todo.pop(),)):
            if r["blocked_by"] not in seen:
                seen.add(r["blocked_by"])
                todo.append(r["blocked_by"])
    return seen


def counts(assignee: str | None = None) -> dict:
    """For the sidebar badge: open items, those due today, and those late. assignee as in query()."""
    t = today().isoformat()
    open_sql = f"status IN ({','.join('?' * len(vocab.OPEN))})"
    who, args = _assignee_sql(assignee)
    extra = f"AND {who}" if who else ""
    row = db.one(
        f"SELECT count(*) AS open, sum(due_on = ?) AS due_today, sum(due_on < ?) AS late FROM tasks_items "
        f"WHERE {open_sql} {extra}", (t, t, *vocab.OPEN, *args))
    return {"open": row["open"], "due_today": row["due_today"] or 0, "late": row["late"] or 0}
