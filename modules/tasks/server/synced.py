"""Tasks that are also kept somewhere else (a Plane work item…): the linked copy, and how it follows the other side.

This module never knows where "elsewhere" is. The module that talks to it publishes the shared contracts
(contracts.WORK_*) with values already named as tasks' own fields, and these handlers keep the copy:

- A linked task remembers, per field, the value both sides last agreed on (its "base", in tasks_synced).
- When the other side changes a field you haven't changed here, the task takes the new value.
- When you've changed it too, and to something else, the task keeps yours and the field is flagged ("Changed in
  Plane") with their value, until you choose: take theirs, or keep yours (which then differs from theirs on purpose,
  for a later push to send).
- When it's gone from there, the task stays, marked ("Removed in Plane"). Nothing here deletes a task.

A linked task is also a link "tasks:<id>" → ref (kind "synced") in core_links, so the other module can tell which of
its things have a copy here without reading this module's tables; a project is linked the same way.
"""
import json
import logging

from core.server import contracts, db, links

from . import items, projects, store, vocab

log = logging.getLogger("tasks.synced")

# The fields a linked task follows, in groups that change together (an assignee is a ref and a name).
GROUPS = {
    "text": ("text",),
    "notes": ("notes",),
    "status": ("status",),
    "priority": ("priority",),
    "start_on": ("start_on",),
    "due_on": ("due_on",),
    "assignee": ("assignee_ref", "assignee_name"),
}
LABELS = {"text": "Title", "notes": "Notes", "status": "Status", "priority": "Priority", "start_on": "Start",
          "due_on": "Due", "assignee": "Assignee"}


def _clean(fields: dict) -> dict:
    """The fields that make sense here, checked the way a task's own are. A value that doesn't fit is left out (and
    logged) rather than failing the whole item."""
    out = {}
    checks = {
        "text": lambda v: store.text(v),
        "notes": lambda v: store.words(v, "Notes"),
        "status": lambda v: store.one_of(v, vocab.ITEM_STATUSES, "Status"),
        "priority": store.priority,
        "start_on": store.day,
        "due_on": store.day,
        "assignee_ref": lambda v: store.ref(v, "An assignee"),
        "assignee_name": lambda v: store.name_or_none(v, "An assignee's name"),
    }
    for key in contracts.WORK_FIELDS:
        if key in (fields or {}):
            try:
                out[key] = checks[key](fields[key])
            except ValueError as e:
                log.warning("Left out %s from elsewhere: %s", key, e)
    return out


def _row(ref: str) -> dict | None:
    return db.one("SELECT * FROM tasks_synced WHERE ref = ?", (ref,))


def _local_project(project_ref: str | None) -> str | None:
    """The project here that's synced with project_ref, if there is one."""
    if not project_ref:
        return None
    for local in links.sources(project_ref, "synced"):
        if local.startswith("tasks:"):
            pid = local.split(":", 1)[1]
            if db.one("SELECT 1 FROM tasks_projects WHERE id = ?", (pid,)):
                return pid
    return None


# ── The contracts ─────────────────────────────────────────────────────

def project_arrived(payload: dict) -> None:
    """contracts.WORK_PROJECT_ARRIVED: a project elsewhere gets a project here, unless it has one already."""
    ref = payload["ref"]
    if _local_project(ref):
        return
    pid = projects.create(payload.get("name") or "Untitled project", summary=payload.get("summary") or None,
                          source="import")
    links.add(links.ref("tasks", pid), ref, "synced")


def arrived(payload: dict) -> None:
    """contracts.WORK_ARRIVED: a linked copy of something elsewhere. Already here: it's an update instead."""
    ref = payload["ref"]
    if _row(ref):
        updated(payload)
        return
    fields = _clean(payload.get("fields") or {})
    if "text" not in fields:
        log.warning("Not bringing in %s: it has no name", ref)
        return
    project_id = _local_project(payload.get("project_ref"))
    item_id = items.create(fields["text"], project_id=project_id, status=fields.get("status", "todo"),
                           notes=fields.get("notes", ""), priority=fields.get("priority", 0),
                           start_on=fields.get("start_on"), due_on=fields.get("due_on"),
                           assignee_ref=fields.get("assignee_ref"), assignee_name=fields.get("assignee_name"),
                           source="linked", quiet=True)
    now = db.now()
    created = items.get(item_id)
    base = {key: created[key] for key in contracts.WORK_FIELDS}
    db.execute("INSERT INTO tasks_synced (item_id, ref, source, url, base, conflicts, synced_at, created_at) "
               "VALUES (?, ?, ?, ?, ?, '{}', ?, ?)",
               (item_id, ref, payload.get("source") or ref.split(":", 1)[0], payload.get("url"), json.dumps(base), now, now))
    links.add(links.ref("tasks", item_id), ref, "synced")
    store.changed(project_id, item_id=item_id)


def updated(payload: dict) -> None:
    """contracts.WORK_UPDATED_ELSEWHERE: follow what changed there, field by field (see the module's docstring)."""
    row = _row(payload["ref"])
    if row is None:
        return
    item = db.one("SELECT * FROM tasks_items WHERE id = ?", (row["item_id"],))
    theirs = _clean(payload.get("fields") or {})
    base = json.loads(row["base"])
    conflicts = json.loads(row["conflicts"])
    take: dict = {}
    for group, cols in GROUPS.items():
        if not all(c in theirs for c in cols):
            continue
        there = tuple(theirs[c] for c in cols)
        agreed = tuple(base.get(c) for c in cols)
        here = tuple(item[c] for c in cols)
        if there == agreed:
            conflicts.pop(group, None)       # unchanged there (or changed back): any edit here is just yours
        elif here == agreed:
            take.update(zip(cols, there))    # changed only there: follow
            base.update(zip(cols, there))
            conflicts.pop(group, None)
        elif here == there:
            base.update(zip(cols, there))    # both made the same change
            conflicts.pop(group, None)
        else:
            conflicts[group] = dict(zip(cols, there))   # both changed it, differently: you choose
    before = (row["base"], row["conflicts"], row["removed_at"], row["url"])
    url = payload.get("url") or row["url"]
    db.execute("UPDATE tasks_synced SET base = ?, conflicts = ?, removed_at = NULL, url = ?, synced_at = ? WHERE item_id = ?",
               (json.dumps(base), json.dumps(conflicts), url, db.now(), row["item_id"]))
    if take:
        items.update(row["item_id"], take)   # says tasks.changed
    elif before != (json.dumps(base), json.dumps(conflicts), None, url):
        store.changed(item["project_id"], item_id=row["item_id"])


def removed(payload: dict) -> None:
    """contracts.WORK_REMOVED_ELSEWHERE: mark the copy; never delete it."""
    row = _row(payload["ref"])
    if row is None or row["removed_at"]:
        return
    db.execute("UPDATE tasks_synced SET removed_at = ?, synced_at = ? WHERE item_id = ?", (db.now(), db.now(), row["item_id"]))
    item = db.one("SELECT project_id FROM tasks_items WHERE id = ?", (row["item_id"],))
    store.changed(item["project_id"] if item else None, item_id=row["item_id"])


# ── Choosing, unlinking and showing ───────────────────────────────────

def resolve(item_id: str, field: str, keep: str) -> dict:
    """A flagged field: keep "theirs" (the task takes their value) or "mine" (theirs becomes the base, so yours is a
    change of your own, to send later)."""
    row = db.one("SELECT * FROM tasks_synced WHERE item_id = ?", (item_id,))
    if row is None:
        raise KeyError(item_id)
    store.one_of(keep, ("theirs", "mine"), "keep")
    conflicts = json.loads(row["conflicts"])
    if field not in conflicts:
        raise ValueError(f"{LABELS.get(field, field)} isn't waiting for a choice")
    theirs = conflicts.pop(field)
    base = {**json.loads(row["base"]), **theirs}
    db.execute("UPDATE tasks_synced SET base = ?, conflicts = ? WHERE item_id = ?",
               (json.dumps(base), json.dumps(conflicts), item_id))
    if keep == "theirs":
        return items.update(item_id, theirs)
    item = items.get(item_id)
    store.changed(item["project_id"], item_id=item_id)
    return item


def unlink(item_id: str) -> bool:
    """The task stops following (and stays, as a task of your own). The other side is left alone."""
    row = db.one("SELECT ref FROM tasks_synced WHERE item_id = ?", (item_id,))
    if row is None:
        return False
    db.execute("DELETE FROM tasks_synced WHERE item_id = ?", (item_id,))
    links.remove(links.ref("tasks", item_id), row["ref"], "synced")
    item = db.one("SELECT project_id FROM tasks_items WHERE id = ?", (item_id,))
    store.changed(item["project_id"] if item else None, item_id=item_id)
    return True


def about(item_ids: list[str]) -> dict[str, dict]:
    """What the screens show for linked tasks: {item_id: {ref, source, url, removed_at, synced_at, conflicts,
    edited}}. conflicts: [{field, label, theirs}]; edited: the fields you've changed since you last agreed."""
    if not item_ids:
        return {}
    out = {}
    for chunk in (item_ids[i:i + 500] for i in range(0, len(item_ids), 500)):
        marks = ",".join("?" * len(chunk))
        rows = db.query(f"SELECT s.*, i.text, i.notes, i.status, i.priority, i.start_on, i.due_on, i.assignee_ref, "
                        f"i.assignee_name FROM tasks_synced s JOIN tasks_items i ON i.id = s.item_id "
                        f"WHERE s.item_id IN ({marks})", chunk)
        for r in rows:
            base = json.loads(r["base"])
            conflicts = json.loads(r["conflicts"])
            out[r["item_id"]] = {
                "ref": r["ref"], "source": r["source"], "url": r["url"], "removed_at": r["removed_at"],
                "synced_at": r["synced_at"],
                "conflicts": [{"field": g, "label": LABELS[g], "theirs": conflicts[g]} for g in GROUPS if g in conflicts],
                "edited": [g for g, cols in GROUPS.items()
                           if g not in conflicts and any(r[c] != base.get(c) for c in cols)],
            }
    return out

